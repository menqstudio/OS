from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from bro_contracts import (
    ContractError,
    load_contract_bundle_from_env,
    load_mode_grant_from_env,
    validate_release_grant_v2,
)
from bro_security import (
    READ_ONLY_GIT,
    SecurityError,
    analyze_command,
    enforce_scope,
    finalize_nonce,
    quarantine_nonce,
    release_nonce_reservation,
    reserve_nonce,
    validate_exact_push,
    verify_signed_document,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / ".bro" / "policy.json"
MANIFEST_PATH = ROOT / "config" / "canonical-read-manifest.json"
MUTATING_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}
SHELL_TOOLS = {"Bash", "PowerShell", "Shell"}


@dataclass(frozen=True)
class State:
    mode: str
    role: str
    session_id: str
    agent_id: str = ""


def load_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()


def tracked_files() -> list[str]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [path.decode() for path in raw.split(b"\0") if path]


def tree_identity() -> str:
    digest = hashlib.sha256()
    for rel in tracked_files():
        digest.update(
            rel.encode() + b"\0" + hashlib.sha256((ROOT / rel).read_bytes()).digest()
        )
    return digest.hexdigest()


def receipt_dir() -> pathlib.Path:
    path = (
        pathlib.Path(tempfile.gettempdir())
        / "bro-runtime"
        / hashlib.sha256(str(ROOT.resolve()).encode()).hexdigest()[:20]
        / "receipts"
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def receipt_path(session_id: str) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown")
    return receipt_dir() / f"{safe}.json"


def current_state(payload: dict) -> State:
    requested = os.getenv(
        "BRO_MODE", load_json(POLICY_PATH)["default_mode"]
    ).strip().lower()
    return State(
        requested,
        os.getenv("BRO_ROLE", "bro").strip().lower(),
        str(payload.get("session_id") or os.getenv("BRO_SESSION_ID") or "unknown"),
        os.getenv("BRO_AGENT_ID", "").strip().lower(),
    )


def read_all(session_id: str) -> dict:
    files = tracked_files()
    hashes = {
        rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() for rel in files
    }
    canonical = load_json(MANIFEST_PATH)["paths"]
    missing = [path for path in canonical if path not in hashes]
    if missing:
        raise RuntimeError(f"canonical files are missing or untracked: {missing}")
    receipt = {
        "schema": 1,
        "session_id": session_id,
        "commit": git("rev-parse", "HEAD"),
        "tree_identity": tree_identity(),
        "read_at_epoch": int(time.time()),
        "tracked_files": len(files),
        "tracked_bytes": sum((ROOT / rel).stat().st_size for rel in files),
        "canonical_paths": canonical,
        "hashes": hashes,
        "proof_boundary": "read-to-EOF and hashes",
    }
    receipt_path(session_id).write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def load_receipt(session_id: str) -> dict | None:
    try:
        return load_json(receipt_path(session_id))
    except Exception:
        return None


def receipt_fresh(session_id: str) -> tuple[bool, str]:
    receipt = load_receipt(session_id)
    if not receipt:
        return False, "missing full-read receipt"
    age = int(time.time()) - int(receipt.get("read_at_epoch", 0))
    if age > int(load_json(POLICY_PATH)["receipt_max_age_seconds"]):
        return False, f"full-read receipt is stale ({age}s)"
    if receipt.get("tree_identity") != tree_identity():
        return False, "repository tree changed after full-read receipt"
    return True, "fresh"


def canonical_context() -> str:
    return "BRO CANONICAL STARTUP CONTEXT\n" + "".join(
        f"\n===== {path} =====\n{(ROOT / path).read_text(encoding='utf-8')} "
        for path in load_json(MANIFEST_PATH)["paths"]
    )


def _direct_targets(tool_input: dict) -> list[str]:
    values: list[str] = []
    for key in ("file_path", "path", "notebook_path", "destination", "source"):
        value = tool_input.get(key)
        if isinstance(value, str):
            values.append(value)
    for key in ("files", "paths", "edits"):
        value = tool_input.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    values.append(item)
                elif isinstance(item, dict):
                    for nested_key in ("file_path", "path"):
                        nested = item.get(nested_key)
                        if isinstance(nested, str):
                            values.append(nested)
    return values


def _normalize_repo(value: object) -> str:
    normalized = str(value or "").strip().replace("\\", "/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    if normalized.startswith("git@") and ":" in normalized:
        normalized = normalized.split("@", 1)[1].replace(":", "/", 1)
    elif "://" in normalized:
        parsed = urlparse(normalized)
        normalized = (parsed.netloc + parsed.path).lstrip("/")
    return normalized.lower()


def _grant_bindings_ok(grant: dict, bundle) -> tuple[bool, str]:
    expected_repo = _normalize_repo(bundle.task["repository"]["full_name"])
    actual_repo = _normalize_repo(grant.get("repository"))
    if actual_repo != expected_repo:
        return False, "grant repository binding mismatch"
    if str(grant.get("branch")) != str(bundle.task["repository"]["branch"]):
        return False, "grant branch binding mismatch"
    return True, "bound"


def _signed_release_payload(*, validate: bool) -> dict:
    grant_path = os.getenv("BRO_RELEASE_GRANT")
    if not grant_path:
        raise ContractError("missing BRO_RELEASE_GRANT")
    try:
        payload = verify_signed_document(
            load_json(pathlib.Path(grant_path)), "BRO_RELEASE_GRANT_KEY"
        )
    except (OSError, json.JSONDecodeError, SecurityError) as exc:
        raise ContractError(str(exc)) from exc
    if validate:
        return validate_release_grant_v2(payload, ROOT)
    if (
        payload.get("schema") != 2
        or payload.get("approved_by") != "Gev"
        or payload.get("allowed_action") != "git-push"
    ):
        raise ContractError("invalid release grant payload")
    return payload


def _release_ledger_dir() -> pathlib.Path:
    raw = os.getenv("BRO_RELEASE_LEDGER")
    if not raw:
        raise ContractError("missing external BRO_RELEASE_LEDGER")
    path = pathlib.Path(raw).expanduser()
    if not path.is_absolute():
        raise ContractError("BRO_RELEASE_LEDGER must be an absolute external path")
    resolved = path.resolve(strict=False)
    root = ROOT.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return resolved
    raise ContractError("BRO_RELEASE_LEDGER must be outside the repository")


def _command_from(tool_input: dict) -> str:
    return str(tool_input.get("command") or tool_input.get("script") or "")


def _validate_release_bindings(release: dict, bundle, command: str) -> None:
    bound, reason = _grant_bindings_ok(release, bundle)
    if not bound:
        raise ContractError(reason)
    origin = _normalize_repo(git("config", "--get", "remote.origin.url"))
    if _normalize_repo(release.get("remote")) != origin:
        raise ContractError("release grant remote binding mismatch")
    validate_exact_push(command, str(bundle.task["repository"]["branch"]))


def authorize_tool(
    state: State,
    tool_name: str,
    tool_input: dict,
    tool_use_id: str = "",
) -> tuple[bool, str]:
    if state.mode not in {"review", "work", "release"}:
        return False, f"unknown BRO_MODE={state.mode!r}"

    infos = []
    command = ""
    if tool_name in SHELL_TOOLS:
        command = _command_from(tool_input)
        try:
            infos = analyze_command(command)
        except SecurityError as exc:
            return False, f"command parser RED: {exc}"

    mutation = tool_name in MUTATING_TOOLS or any(info.mutating for info in infos)
    push = any(info.push for info in infos)

    if state.mode == "review":
        for info in infos:
            if info.executable == "git" and (
                info.dangerous_config or info.subcommand not in READ_ONLY_GIT
            ):
                return False, "review mode denies ambiguous or non-read-only git command"
            if not info.recognized_read_only:
                return False, "review mode denies unrecognized shell execution"
        if mutation:
            return False, "review mode is technically read-only"
        return True, "allowed"

    if mutation and state.role == "bro":
        return (
            False,
            "Bro remains free and may not perform repository mutation; "
            "delegate to a governed specialist",
        )

    try:
        bundle = load_contract_bundle_from_env(ROOT)
    except ContractError as exc:
        return False, f"task/agent/skill gate RED: {exc}"

    if state.agent_id and state.agent_id != bundle.agent["agent_id"].lower():
        return False, "BRO_AGENT_ID does not match bound agent profile"

    try:
        mode_grant = load_mode_grant_from_env(
            bundle, state.session_id, state.role, ROOT
        )
    except ContractError as exc:
        return False, f"mode grant RED: {exc}"

    if mode_grant["mode"] != state.mode:
        return False, "mode grant does not authorize requested mode"

    bound, reason = _grant_bindings_ok(mode_grant, bundle)
    if not bound:
        return False, reason

    scoped_mutation = (
        tool_name in MUTATING_TOOLS
        or any(info.mutating and not info.push for info in infos)
    )
    if scoped_mutation:
        targets = _direct_targets(tool_input)
        for info in infos:
            if info.mutating and not info.push:
                targets.extend(info.targets)
        try:
            enforce_scope(
                ROOT,
                targets,
                bundle.task["scope"],
                bundle.task["prohibited_scope"],
            )
        except SecurityError as exc:
            return False, f"scope gate RED: {exc}"

    if push:
        if state.mode != "release" or state.role != "push-executor":
            return False, "push requires release mode and push-executor"
        if os.getenv("BRO_EXTERNAL_RELEASE_BOUNDARY") != "confirmed":
            return False, "external credential/permission boundary is not confirmed"
        if len(infos) != 1:
            return False, "release push must be the only shell segment"
        try:
            release = _signed_release_payload(validate=True)
            _validate_release_bindings(release, bundle, command)
            ledger = _release_ledger_dir()
            reserve_nonce(release, ledger, tool_use_id, command)
        except (ContractError, SecurityError) as exc:
            return False, f"release grant RED: {exc}"
        return True, "release push authorized; nonce reserved pending tool result"

    return True, "allowed"


def _remote_branch_head(branch: str) -> str:
    completed = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=20,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or f"git ls-remote failed ({completed.returncode})")
    line = completed.stdout.strip()
    return line.split()[0] if line else ""


def settle_release_tool(
    state: State,
    tool_name: str,
    tool_input: dict,
    tool_use_id: str,
    *,
    success: bool,
    error: str = "",
) -> tuple[bool, bool, str]:
    """Settle a reservation after a shell tool result.

    Returns (handled, green, message).
    """
    if tool_name not in SHELL_TOOLS:
        return False, True, ""

    command = _command_from(tool_input)
    try:
        infos = analyze_command(command)
    except SecurityError:
        return False, True, ""
    if not any(info.push for info in infos):
        return False, True, ""

    try:
        bundle = load_contract_bundle_from_env(ROOT)
        release = _signed_release_payload(validate=False)
        _validate_release_bindings(release, bundle, command)
        ledger = _release_ledger_dir()

        if success:
            finalize_nonce(release, ledger, tool_use_id, command)
            return True, True, "release nonce finalized after successful push"

        try:
            remote_head = _remote_branch_head(str(release["branch"]))
        except Exception as reconcile_error:
            quarantine_nonce(
                release,
                ledger,
                tool_use_id,
                command,
                f"push failed and remote reconciliation failed: {reconcile_error}",
            )
            return (
                True,
                False,
                "push failed; nonce quarantined because remote state could not be proven",
            )

        if remote_head == str(release["expected_head_sha"]):
            finalize_nonce(release, ledger, tool_use_id, command)
            return (
                True,
                True,
                "push tool reported failure, but remote exact HEAD is present; "
                "nonce finalized",
            )

        release_nonce_reservation(release, ledger, tool_use_id, command)
        return (
            True,
            True,
            "push failed and remote exact HEAD is absent; nonce reservation released",
        )
    except (ContractError, SecurityError, KeyError, OSError) as exc:
        return True, False, f"release nonce settlement RED: {exc}"
