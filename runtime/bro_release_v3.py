from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time
from typing import Any
from urllib.parse import urlparse

from bro_completion import validate_completion, validate_verifier_receipt
from bro_contracts import canonical_json_sha256, load_json, validate_task_contract
from bro_identity import expected_agent_id
from bro_repository_state import resolve_state
from bro_security import (
    SecurityError,
    finalize_nonce,
    quarantine_nonce,
    release_nonce_reservation,
    reserve_nonce,
    validate_exact_push,
    verify_signed_document,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ReleaseV3Error(ValueError):
    pass


def _normalize_repo(value: object) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if text.endswith(".git"):
        text = text[:-4]
    if text.startswith("git@") and ":" in text:
        text = text.split("@", 1)[1].replace(":", "/", 1)
    elif "://" in text:
        parsed = urlparse(text)
        text = (parsed.netloc + parsed.path).lstrip("/")
    return text.lower()


def _signed(path_env: str, key_env: str) -> dict[str, Any]:
    raw = os.getenv(path_env)
    if not raw:
        raise ReleaseV3Error(f"missing {path_env}")
    try:
        return verify_signed_document(load_json(pathlib.Path(raw)), key_env)
    except (OSError, json.JSONDecodeError, SecurityError) as exc:
        raise ReleaseV3Error(str(exc)) from exc


def _ledger() -> pathlib.Path:
    raw = os.getenv("BRO_RELEASE_LEDGER")
    if not raw:
        raise ReleaseV3Error("missing external BRO_RELEASE_LEDGER")
    path = pathlib.Path(raw).expanduser()
    if not path.is_absolute():
        raise ReleaseV3Error("BRO_RELEASE_LEDGER must be absolute")
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return resolved
    raise ReleaseV3Error("BRO_RELEASE_LEDGER must be outside repository")


def _task() -> dict[str, Any]:
    raw = os.getenv("BRO_TASK_CONTRACT")
    if not raw:
        raise ReleaseV3Error("missing BRO_TASK_CONTRACT")
    try:
        return validate_task_contract(load_json(pathlib.Path(raw)), ROOT)
    except Exception as exc:
        raise ReleaseV3Error(str(exc)) from exc


def _origin() -> str:
    try:
        return subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseV3Error("cannot resolve origin remote") from exc


def validate_release_grant_v3(
    payload: dict[str, Any],
    *,
    task: dict[str, Any],
    manifest: dict[str, Any],
    receipt: dict[str, Any],
    now: int | None = None,
) -> dict[str, Any]:
    required = {
        "schema", "grant_id", "nonce", "principal_id", "task_id",
        "task_contract_sha256", "completion_manifest_sha256",
        "verifier_receipt_sha256", "repository", "remote", "branch",
        "expected_head_sha", "expected_tree_identity", "allowed_action",
        "issued_at_epoch", "expires_at_epoch",
    }
    if set(payload) != required or payload.get("schema") != 3:
        raise ReleaseV3Error("invalid Release Grant V3 shape")
    if payload.get("principal_id") != "owner-gev" or payload.get("allowed_action") != "git-push":
        raise ReleaseV3Error("release grant lacks exact owner/action authority")
    instant = int(time.time()) if now is None else now
    if not isinstance(payload.get("issued_at_epoch"), int) or not isinstance(payload.get("expires_at_epoch"), int):
        raise ReleaseV3Error("release grant timestamps invalid")
    if payload["issued_at_epoch"] > instant + 60 or payload["expires_at_epoch"] <= instant:
        raise ReleaseV3Error("release grant expired or not yet valid")
    state = resolve_state(ROOT)
    expected = {
        "task_id": task["task_id"],
        "task_contract_sha256": canonical_json_sha256(task),
        "completion_manifest_sha256": canonical_json_sha256(manifest),
        "verifier_receipt_sha256": canonical_json_sha256(receipt),
        "repository": task["repository"]["full_name"],
        "branch": task["repository"]["branch"],
        "expected_head_sha": state.head_sha,
        "expected_tree_identity": state.tree_identity,
    }
    for key, value in expected.items():
        actual = payload.get(key)
        if key == "repository":
            actual, value = _normalize_repo(actual), _normalize_repo(value)
        if actual != value:
            raise ReleaseV3Error(f"release grant binding mismatch: {key}")
    if _normalize_repo(payload.get("remote")) != _normalize_repo(_origin()):
        raise ReleaseV3Error("release grant remote binding mismatch")
    return payload


def _validate_executor_state(state_agent_id: str, state_mode: str, state_role: str) -> None:
    if state_mode != "release" or state_role != "push-executor":
        raise ReleaseV3Error("push requires release mode and push-executor")
    canonical = expected_agent_id("git-release-control", "Push Executor", ROOT)
    if state_agent_id != canonical:
        raise ReleaseV3Error("BRO_AGENT_ID is not canonical Push Executor")


def authorize_release_push(
    *,
    state_agent_id: str,
    state_mode: str,
    state_role: str,
    command: str,
    tool_use_id: str,
) -> tuple[dict[str, Any], pathlib.Path]:
    _validate_executor_state(state_agent_id, state_mode, state_role)
    if os.getenv("BRO_EXTERNAL_RELEASE_BOUNDARY") != "confirmed":
        raise ReleaseV3Error("external credential/permission boundary is not confirmed")
    task = _task()
    manifest, task_hash = validate_completion(task, task["agent_id"], ROOT)
    receipt = validate_verifier_receipt(task, manifest, task_hash, ROOT)
    grant = validate_release_grant_v3(
        _signed("BRO_RELEASE_GRANT", "BRO_RELEASE_GRANT_KEY"),
        task=task,
        manifest=manifest,
        receipt=receipt,
    )
    validate_exact_push(command, str(task["repository"]["branch"]))
    ledger = _ledger()
    reserve_nonce(grant, ledger, tool_use_id, command)
    return grant, ledger


def _remote_head(branch: str) -> str:
    run = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=20,
        check=False,
    )
    if run.returncode != 0:
        raise ReleaseV3Error(run.stderr.strip() or "remote reconciliation failed")
    line = run.stdout.strip()
    return line.split()[0] if line else ""


def settle_release_push(
    *,
    state_agent_id: str,
    state_mode: str,
    state_role: str,
    command: str,
    tool_use_id: str,
    success: bool,
    error: str = "",
) -> tuple[bool, str]:
    _validate_executor_state(state_agent_id, state_mode, state_role)
    task = _task()
    validate_exact_push(command, str(task["repository"]["branch"]))
    manifest, task_hash = validate_completion(task, task["agent_id"], ROOT)
    receipt = validate_verifier_receipt(task, manifest, task_hash, ROOT)
    grant = validate_release_grant_v3(
        _signed("BRO_RELEASE_GRANT", "BRO_RELEASE_GRANT_KEY"),
        task=task,
        manifest=manifest,
        receipt=receipt,
    )
    ledger = _ledger()
    if success:
        finalize_nonce(grant, ledger, tool_use_id, command)
        return True, "Release Grant V3 nonce finalized"
    try:
        remote = _remote_head(str(grant["branch"]))
    except Exception as exc:
        quarantine_nonce(grant, ledger, tool_use_id, command, f"{error}; {exc}")
        return False, "release quarantined because remote state is ambiguous"
    if remote == str(grant["expected_head_sha"]):
        finalize_nonce(grant, ledger, tool_use_id, command)
        return True, "remote exact HEAD exists; Release Grant V3 finalized"
    release_nonce_reservation(grant, ledger, tool_use_id, command)
    return True, "remote exact HEAD absent; release reservation safely released"
