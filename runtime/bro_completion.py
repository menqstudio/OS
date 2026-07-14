from __future__ import annotations

import hashlib
import json
import os
import pathlib
import time
from typing import Any

from bro_authority import AuthorityError, validate_verifier_assignment
from bro_contracts import canonical_json_sha256
from bro_repository_state import resolve_state
from bro_security import SecurityError, verify_signed_document

ROOT = pathlib.Path(__file__).resolve().parents[1]
LEVELS = ["L1", "L2", "L3", "L4", "L5"]


class CompletionError(ValueError):
    pass


def _json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompletionError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CompletionError(f"{path} must contain an object")
    return value


def _signed_env(path_env: str, key_env: str) -> dict[str, Any]:
    raw = os.getenv(path_env)
    if not raw:
        raise CompletionError(f"missing {path_env}")
    try:
        return verify_signed_document(_json(pathlib.Path(raw)), key_env)
    except SecurityError as exc:
        raise CompletionError(str(exc)) from exc


def _evidence_dir() -> pathlib.Path:
    raw = os.getenv("BRO_EVIDENCE_STORE")
    if not raw:
        raise CompletionError("missing external BRO_EVIDENCE_STORE")
    path = pathlib.Path(raw).expanduser()
    if not path.is_absolute():
        raise CompletionError("BRO_EVIDENCE_STORE must be absolute")
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return resolved
    raise CompletionError("BRO_EVIDENCE_STORE must be outside the repository")


def validate_evidence_chain(task_id: str, event_ids: list[str]) -> str:
    if not event_ids or len(event_ids) != len(set(event_ids)):
        raise CompletionError("evidence event IDs must be non-empty and unique")
    previous = None
    for event_id in event_ids:
        path = _evidence_dir() / f"{event_id}.json"
        try:
            payload = verify_signed_document(_json(path), "BRO_EVIDENCE_KEY")
        except SecurityError as exc:
            raise CompletionError(str(exc)) from exc
        required = {"schema","event_id","previous_event_hash","task_id","event_type","agent_id","payload_hash","issued_at_epoch","key_id"}
        if set(payload) != required or payload.get("schema") != 1:
            raise CompletionError("invalid evidence event shape")
        if payload["event_id"] != event_id or payload["task_id"] != task_id:
            raise CompletionError("evidence event binding mismatch")
        if payload["previous_event_hash"] != previous:
            raise CompletionError("evidence chain linkage mismatch")
        previous = canonical_json_sha256(payload)
    return previous or ""


def validate_completion(task: dict[str, Any], agent_id: str, root: pathlib.Path = ROOT) -> tuple[dict, str]:
    manifest = _signed_env("BRO_COMPLETION_MANIFEST", "BRO_COMPLETION_KEY")
    required = {"schema","task_id","agent_id","task_contract_sha256","candidate_head","candidate_tree","done_criteria","tests","evidence_event_ids","open_risks","rollback_ready","issued_at_epoch"}
    if set(manifest) != required or manifest.get("schema") != 1:
        raise CompletionError("invalid completion manifest shape")
    task_hash = canonical_json_sha256(task)
    expected = {"task_id": task["task_id"], "agent_id": agent_id, "task_contract_sha256": task_hash}
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise CompletionError(f"completion manifest binding mismatch: {key}")
    state = resolve_state(root)
    if manifest["candidate_head"] != state.head_sha or manifest["candidate_tree"] != state.tree_identity:
        raise CompletionError("completion candidate does not match current repository state")
    criteria = manifest.get("done_criteria")
    if not isinstance(criteria, list) or [x.get("criterion") for x in criteria if isinstance(x, dict)] != task["done_criteria"]:
        raise CompletionError("completion done criteria do not exactly match task")
    if any(x.get("status") != "satisfied" or not x.get("evidence_event_ids") for x in criteria):
        raise CompletionError("completion criterion lacks satisfied evidence")
    tests = manifest.get("tests")
    if not isinstance(tests, list) or not tests or any(x.get("status") != "passed" for x in tests if isinstance(x, dict)):
        raise CompletionError("completion tests are not all passed")
    if manifest.get("open_risks") or manifest.get("rollback_ready") is not True:
        raise CompletionError("completion has open risks or rollback is not ready")
    validate_evidence_chain(task["task_id"], manifest["evidence_event_ids"])
    return manifest, task_hash


def validate_verifier_receipt(task: dict[str, Any], manifest: dict, task_hash: str, root: pathlib.Path = ROOT) -> dict:
    receipt = _signed_env("BRO_VERIFIER_RECEIPT", "BRO_VERIFIER_RECEIPT_KEY")
    required = {"schema","receipt_id","task_id","builder_agent_id","verifier_agent_id","verifier_role","independence_level","task_contract_sha256","completion_manifest_sha256","candidate_head","candidate_tree","evidence_event_ids","verdict","issued_at_epoch","expires_at_epoch"}
    if set(receipt) != required or receipt.get("schema") != 1 or receipt.get("verdict") != "GREEN":
        raise CompletionError("invalid verifier receipt shape or verdict")
    verification = task["verification"]
    expected = {
        "task_id": task["task_id"], "builder_agent_id": task["agent_id"],
        "verifier_agent_id": verification["verifier_agent_id"], "verifier_role": verification["verifier_role"],
        "task_contract_sha256": task_hash, "completion_manifest_sha256": canonical_json_sha256(manifest),
        "candidate_head": manifest["candidate_head"], "candidate_tree": manifest["candidate_tree"],
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise CompletionError(f"verifier receipt binding mismatch: {key}")
    now = int(time.time())
    if not isinstance(receipt["issued_at_epoch"], int) or not isinstance(receipt["expires_at_epoch"], int) or receipt["expires_at_epoch"] <= now:
        raise CompletionError("verifier receipt expired or invalid")
    try:
        validate_verifier_assignment(builder_agent_id=task["agent_id"], verifier_agent_id=receipt["verifier_agent_id"], verifier_role=receipt["verifier_role"], risk=task["risk"], root=root)
    except AuthorityError as exc:
        raise CompletionError(str(exc)) from exc
    policy = _json(root / "agents" / "authority-policy.json")
    minimum = policy["independence_minimum_by_risk"][task["risk"]]
    if receipt["independence_level"] not in LEVELS or LEVELS.index(receipt["independence_level"]) < LEVELS.index(minimum):
        raise CompletionError("verifier independence level is insufficient")
    validate_evidence_chain(task["task_id"], receipt["evidence_event_ids"])
    return receipt


def authorize_stop(task: dict[str, Any], agent_id: str, root: pathlib.Path = ROOT) -> tuple[bool, str]:
    try:
        manifest, task_hash = validate_completion(task, agent_id, root)
        if task["verification"]["required"]:
            validate_verifier_receipt(task, manifest, task_hash, root)
        return True, "completion and verification evidence GREEN"
    except CompletionError as exc:
        return False, f"completion gate RED: {exc}"
