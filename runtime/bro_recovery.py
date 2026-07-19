from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
from contextlib import contextmanager
from typing import Any

from bro_contracts import canonical_json_sha256
from bro_repository_state import resolve_state
from bro_secrets import redact
from bro_security import SecurityError, verify_signed_document

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLOCKING = {"PREPARED", "RECOVERY_REQUIRED", "RECOVERY_STARTED", "QUARANTINED", "FAILED_WITH_IRREVERSIBLE_EFFECT"}
EFFECTS = {"REVERSIBLE", "COMPENSATABLE", "IRREVERSIBLE", "UNKNOWN"}


class RecoveryError(ValueError):
    pass


def _json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryError(f"cannot read recovery data: {exc}") from exc
    if not isinstance(value, dict):
        raise RecoveryError("recovery data must be an object")
    return value


def _store() -> pathlib.Path:
    raw = os.getenv("BRO_RECOVERY_STORE")
    if not raw:
        raise RecoveryError("missing external BRO_RECOVERY_STORE")
    path = pathlib.Path(raw).expanduser()
    if not path.is_absolute():
        raise RecoveryError("BRO_RECOVERY_STORE must be absolute")
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved
    raise RecoveryError("BRO_RECOVERY_STORE must be outside repository")


def _state_path(task_id: str) -> pathlib.Path:
    return _store() / f"{hashlib.sha256(task_id.encode()).hexdigest()}.state.json"


def _status_hash(root: pathlib.Path = ROOT) -> str:
    try:
        raw = subprocess.check_output(["git", "status", "--porcelain=v1", "-z"], cwd=root)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RecoveryError("cannot inspect git status") from exc
    return hashlib.sha256(raw).hexdigest()


def snapshot(root: pathlib.Path = ROOT) -> dict[str, str]:
    state = resolve_state(root)
    return {"head": state.head_sha, "tree": state.tree_identity, "status_hash": _status_hash(root)}


def _load_state_unlocked(task_id: str) -> dict[str, Any] | None:
    path = _state_path(task_id)
    return _json(path) if path.exists() else None


def _load_state(task_id: str) -> dict[str, Any] | None:
    return _load_state_unlocked(task_id)


@contextmanager
def _state_guard(task_id: str):
    lock = _state_path(task_id).with_suffix(".lock")
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RecoveryError("recovery state is busy or an interrupted transition requires reconciliation") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"task_id_sha256": hashlib.sha256(task_id.encode()).hexdigest()}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def assert_recovery_clear(task_id: str) -> None:
    state = _load_state(task_id)
    if state and state.get("phase") in BLOCKING:
        raise RecoveryError(f"task recovery state blocks mutation: {state.get('phase')}")


def _write_cas(task_id: str, expected_version: int, value: dict[str, Any]) -> None:
    path = _state_path(task_id)
    with _state_guard(task_id):
        current = _load_state_unlocked(task_id)
        actual = int(current.get("state_version", 0)) if current else 0
        if actual != expected_version:
            raise RecoveryError(f"stale recovery state version: expected {expected_version}, actual {actual}")
        next_value = dict(value)
        next_value["state_version"] = expected_version + 1
        temp = path.with_suffix(f".{os.getpid()}.tmp")
        try:
            with temp.open("w", encoding="utf-8") as handle:
                json.dump(next_value, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass


def _signed_record(root: pathlib.Path = ROOT, now: int | None = None) -> dict[str, Any]:
    # Ed25519, not HMAC: the prepared recovery record is verified in the builder's
    # process at the mutation gate, so a symmetric key would let the builder forge
    # its own before-state journal. verify_artifact checks it against the operator-
    # signed registry; a recovery record is signed by the issuer authority — the
    # same per-action authorizer that issues the execution lease at this boundary.
    from bro_signature import SignatureError, load_trusted_keys, verify_artifact
    raw = os.getenv("BRO_RECOVERY_RECORD")
    if not raw:
        raise RecoveryError("missing signed BRO_RECOVERY_RECORD")
    try:
        return verify_artifact(_json(pathlib.Path(raw)), "recovery-record", load_trusted_keys(root), now=now)
    except SignatureError as exc:
        raise RecoveryError(str(exc)) from exc


def validate_prepared_record(*, task: dict[str, Any], agent_id: str, session_id: str, tool_use_id: str, action: dict[str, Any], before: dict[str, str]) -> dict[str, Any]:
    record = _signed_record()
    required = {"schema","record_id","task_id","agent_id","session_id","tool_use_id","phase","effect_class","action_hash","capabilities","targets","before_head","before_tree","after_head","after_tree","before_status_hash","after_status_hash","recovery_proof_hash","irreversible_effects","state_version","previous_record_hash","issued_at_epoch"}
    # artifact_type/key_id are injected by the Ed25519 signer (broctl) and echoed
    # back by verify_artifact; tolerate them without weakening the required set.
    if set(record) - {"artifact_type", "key_id"} != required or record.get("schema") != 1 or record.get("phase") != "PREPARED":
        raise RecoveryError("invalid prepared recovery record shape")
    if record.get("effect_class") not in EFFECTS:
        raise RecoveryError("invalid recovery effect class")
    expected = {"task_id":task["task_id"],"agent_id":agent_id,"session_id":session_id,"tool_use_id":tool_use_id,"action_hash":canonical_json_sha256(action),"before_head":before["head"],"before_tree":before["tree"],"before_status_hash":before["status_hash"]}
    for key, value in expected.items():
        if record.get(key) != value:
            raise RecoveryError(f"prepared recovery binding mismatch: {key}")
    if any(record.get(key) is not None for key in ("after_head", "after_tree", "after_status_hash")):
        raise RecoveryError("prepared recovery record already contains after-state")
    return record


def prepare_mutation(*, task: dict[str, Any], agent_id: str, session_id: str, tool_use_id: str, capabilities: tuple[str, ...], targets: tuple[str, ...], tool: str, action_name: str) -> dict[str, Any]:
    assert_recovery_clear(task["task_id"])
    before = snapshot(ROOT)
    action = {"tool":tool,"action":action_name,"capabilities":list(capabilities),"targets":list(targets)}
    record = validate_prepared_record(task=task, agent_id=agent_id, session_id=session_id, tool_use_id=tool_use_id, action=action, before=before)
    if record.get("capabilities") != list(capabilities) or record.get("targets") != list(targets):
        raise RecoveryError("prepared recovery capability/target mismatch")
    _write_cas(task["task_id"], int(record["state_version"]), record)
    return record


def cancel_prepared(task_id: str, tool_use_id: str) -> None:
    with _state_guard(task_id):
        state = _load_state_unlocked(task_id)
        if not state or state.get("phase") != "PREPARED" or state.get("tool_use_id") != tool_use_id:
            raise RecoveryError("matching prepared recovery record is missing")
        try:
            _state_path(task_id).unlink()
        except OSError as exc:
            raise RecoveryError("failed to cancel unexecuted recovery journal") from exc


def settle_mutation(task_id: str, tool_use_id: str, *, success: bool, error: str = "") -> tuple[bool, str]:
    state = _load_state(task_id)
    if not state or state.get("phase") != "PREPARED" or state.get("tool_use_id") != tool_use_id:
        raise RecoveryError("matching prepared recovery record is missing")
    after = snapshot(ROOT)
    next_state = dict(state)
    next_state.update({"after_head":after["head"],"after_tree":after["tree"],"after_status_hash":after["status_hash"]})
    if success:
        next_state["phase"] = "MUTATION_RECORDED"
        _write_cas(task_id, int(state["state_version"]), next_state)
        return True, "mutation journal settled"
    effect = state.get("effect_class")
    if effect == "IRREVERSIBLE":
        next_state["phase"] = "FAILED_WITH_IRREVERSIBLE_EFFECT"
        next_state["irreversible_effects"] = [redact(error) or "irreversible mutation failed or was interrupted"]
    elif effect == "UNKNOWN":
        next_state["phase"] = "QUARANTINED"
    else:
        next_state["phase"] = "RECOVERY_REQUIRED"
    _write_cas(task_id, int(state["state_version"]), next_state)
    return False, f"mutation requires recovery: {next_state['phase']}"


def _verify_recovery_proof(document: Any, root: pathlib.Path, now: int | None) -> dict[str, Any]:
    """Verify an owner-signed recovery-proof artifact.

    The proof is Ed25519-signed by the owner-held RECOVERY authority (verified against
    the externally-pinned trusted-key registry), so a policed builder process cannot
    mint it. verify_artifact refuses any other authority."""
    from bro_signature import SignatureError, load_trusted_keys, verify_artifact
    if not isinstance(document, dict):
        raise RecoveryError("recovery proof document is required")
    try:
        return verify_artifact(document, "recovery-proof", load_trusted_keys(root), now=now)
    except SignatureError as exc:
        raise RecoveryError(str(exc)) from exc


def prove_recovery(task_id: str, proof_document: dict[str, Any], root: pathlib.Path = ROOT,
                   now: int | None = None) -> str:
    """Clear a recovery-required task on a real owner-signed proof, not a hex token.

    The previous implementation accepted any 64-hex string, so the builder that
    interrupted the mutation could clear its own quarantine. The proof is now an
    owner-signed recovery-proof artifact bound to THIS task, recovery record,
    restored state, effect class and state version, so it cannot be forged or replayed
    onto a different recovery. The whole signed document is persisted alongside its
    hash so a later audit can re-verify it from the record alone."""
    state = _load_state(task_id)
    if not state or state.get("phase") not in {"RECOVERY_REQUIRED", "RECOVERY_STARTED"}:
        raise RecoveryError("task is not recoverable from current phase")
    if state.get("effect_class") not in {"REVERSIBLE", "COMPENSATABLE"}:
        raise RecoveryError("unknown or irreversible effect cannot be marked recovered")
    current = snapshot(ROOT)
    if (current["head"], current["tree"], current["status_hash"]) != (state["before_head"], state["before_tree"], state["before_status_hash"]):
        raise RecoveryError("original repository state has not been restored")
    payload = _verify_recovery_proof(proof_document, root, now)
    required = {"schema", "task_id", "record_id", "before_head", "before_tree",
                "before_status_hash", "effect_class", "state_version", "issued_at_epoch"}
    if set(payload) - {"artifact_type", "key_id"} != required or payload.get("schema") != 1:
        raise RecoveryError("invalid recovery proof shape")
    expected = {"task_id": task_id, "record_id": state["record_id"],
                "before_head": state["before_head"], "before_tree": state["before_tree"],
                "before_status_hash": state["before_status_hash"],
                "effect_class": state["effect_class"], "state_version": state["state_version"]}
    for key, value in expected.items():
        if payload.get(key) != value:
            raise RecoveryError(f"recovery proof binding mismatch: {key}")
    next_state = dict(state)
    next_state.update({
        "phase": "REWORK_REQUIRED",
        "recovery_proof_hash": canonical_json_sha256(proof_document),
        "recovery_proof_document": proof_document,
    })
    _write_cas(task_id, int(state["state_version"]), next_state)
    return "recovery proven; task requires rework"
