from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import time
from dataclasses import dataclass
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]

# The two builder classes the supervisor may delegate. Kept as literals here rather
# than imported from bro_protected so this module — consumed inside the builder's
# process — stays free of any control-plane import cycle.
STANDARD_BUILDER = "standard-builder"
SECURITY_MAINTENANCE = "security-maintenance"

# The capabilities a supervised builder of each class may hold. protected_scope
# governs WHICH paths a security task may touch; the capability set itself is the
# same — a builder writes files, writes the repo, and runs code. A lease may grant a
# subset but never more than its class allows, so a signed lease cannot over-reach.
CLASS_CAPABILITIES = {
    STANDARD_BUILDER: frozenset({"EXECUTE_CODE", "WRITE_FILESYSTEM", "WRITE_REPOSITORY"}),
    SECURITY_MAINTENANCE: frozenset({"EXECUTE_CODE", "WRITE_FILESYSTEM", "WRITE_REPOSITORY"}),
}

_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class LeaseError(ValueError):
    pass


@dataclass(frozen=True)
class ExecutionLease:
    lease_id: str
    nonce: str
    task_id: str
    agent_id: str
    session_id: str
    repository: str
    branch: str
    worktree: str
    head_sha: str
    tree_identity: str
    allowed_capabilities: tuple[str, ...]
    issued_at_epoch: int
    expires_at_epoch: int
    max_tool_calls: int
    # Superset bindings carried in the issuer-signed lease. control_plane_digest and
    # workspace_id are enforced against the consumer's live workspace binding;
    # task_class and protected_scope carry the owner-approved delegation policy.
    task_class: str
    protected_scope: tuple[str, ...]
    control_plane_digest: str
    workspace_id: str


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LeaseError(f"missing execution lease: {path}") from exc
    except json.JSONDecodeError as exc:
        raise LeaseError(f"malformed execution lease JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise LeaseError("execution lease document must be an object")
    return value


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LeaseError(f"{field} must be a non-empty string")
    return value.strip()


def _ledger_dir() -> pathlib.Path:
    raw = os.getenv("BRO_EXECUTION_LEASE_LEDGER")
    if not raw:
        raise LeaseError("missing external BRO_EXECUTION_LEASE_LEDGER")
    path = pathlib.Path(raw).expanduser()
    if not path.is_absolute():
        raise LeaseError("BRO_EXECUTION_LEASE_LEDGER must be absolute")
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return resolved
    raise LeaseError("BRO_EXECUTION_LEASE_LEDGER must be outside the repository")


def validate_execution_lease(
    payload: dict[str, Any],
    *,
    task: dict[str, Any],
    agent_id: str,
    session_id: str,
    required_capabilities: tuple[str, ...],
    control_plane_digest: str | None = None,
    workspace_id: str | None = None,
    now: int | None = None,
) -> ExecutionLease:
    # control_plane_digest/workspace_id are enforced when the caller supplies the
    # live workspace values (the reserve/authorize gate does). Settlement re-loads
    # the lease with no bound workspace and passes neither — safe, because a lease
    # can only be settled after a reserve that already enforced them, and a protected
    # mutation may legitimately have changed the digest by settlement time.
    required = {
        "schema", "lease_id", "nonce", "task_id", "agent_id", "session_id",
        "repository", "branch", "worktree", "head_sha", "tree_identity",
        "allowed_capabilities", "issued_at_epoch", "expires_at_epoch", "max_tool_calls",
        "task_class", "protected_scope", "control_plane_digest", "workspace_id",
    }
    # artifact_type/key_id are injected by the Ed25519 signer (broctl) and echoed
    # back by verify_artifact; tolerate them without weakening the required set.
    if set(payload) - {"artifact_type", "key_id"} != required:
        raise LeaseError("execution lease has unexpected or missing keys")
    if payload.get("schema") != 1:
        raise LeaseError("unsupported execution lease schema")

    lease_id = _require_string(payload.get("lease_id"), "lease_id")
    nonce = _require_string(payload.get("nonce"), "nonce")
    if len(nonce) < 16 or len(nonce) > 128:
        raise LeaseError("execution lease nonce length invalid")

    issued = payload.get("issued_at_epoch")
    expires = payload.get("expires_at_epoch")
    max_calls = payload.get("max_tool_calls")
    if not isinstance(issued, int) or not isinstance(expires, int):
        raise LeaseError("execution lease timestamps must be integers")
    if not isinstance(max_calls, int) or max_calls < 1:
        raise LeaseError("execution lease max_tool_calls invalid")
    instant = int(time.time()) if now is None else now
    if issued > instant + 60 or expires <= instant or expires <= issued:
        raise LeaseError("execution lease expired or not yet valid")

    repository = task.get("repository")
    if not isinstance(repository, dict):
        raise LeaseError("task repository binding is missing")
    expected = {
        "task_id": task.get("task_id"),
        "agent_id": agent_id,
        "session_id": session_id,
        "repository": repository.get("full_name"),
        "branch": repository.get("branch"),
        "worktree": str(pathlib.Path(str(repository.get("worktree") or "")).expanduser().resolve()),
        "head_sha": repository.get("base_commit"),
        "tree_identity": repository.get("tree_identity"),
    }
    for key, expected_value in expected.items():
        actual = payload.get(key)
        if key == "worktree":
            actual = str(pathlib.Path(str(actual or "")).expanduser().resolve())
        if actual != expected_value:
            raise LeaseError(f"execution lease binding mismatch: {key}")

    capabilities = payload.get("allowed_capabilities")
    if not isinstance(capabilities, list) or not capabilities or not all(isinstance(x, str) for x in capabilities):
        raise LeaseError("execution lease allowed_capabilities invalid")
    allowed = tuple(sorted(set(capabilities)))
    missing = sorted(set(required_capabilities) - set(allowed))
    if missing:
        raise LeaseError(f"execution lease lacks capabilities: {missing}")

    task_class = payload.get("task_class")
    if task_class not in CLASS_CAPABILITIES:
        raise LeaseError("execution lease task_class invalid")
    over_grant = sorted(set(allowed) - CLASS_CAPABILITIES[task_class])
    if over_grant:
        raise LeaseError(f"execution lease grants capabilities beyond its class: {over_grant}")

    scope = payload.get("protected_scope")
    if not isinstance(scope, list) or any(not isinstance(p, str) or not p for p in scope):
        raise LeaseError("execution lease protected_scope must be a list of exact paths")
    if any(ch in p for p in scope for ch in "*?["):
        raise LeaseError("execution lease protected_scope must contain exact paths, not patterns")
    if task_class == STANDARD_BUILDER and scope:
        raise LeaseError("a standard-builder lease may not carry a protected scope")
    if task_class == SECURITY_MAINTENANCE and not scope:
        raise LeaseError("a security-maintenance lease must name its protected scope")

    digest = payload.get("control_plane_digest")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise LeaseError("execution lease control_plane_digest invalid")
    if control_plane_digest is not None and digest != control_plane_digest:
        raise LeaseError("execution lease binding mismatch: control_plane_digest")

    lease_workspace_id = _require_string(payload.get("workspace_id"), "workspace_id")
    if workspace_id is not None and lease_workspace_id != workspace_id:
        raise LeaseError("execution lease binding mismatch: workspace_id")

    return ExecutionLease(
        lease_id=lease_id,
        nonce=nonce,
        task_id=str(payload["task_id"]),
        agent_id=str(payload["agent_id"]),
        session_id=str(payload["session_id"]),
        repository=str(payload["repository"]),
        branch=str(payload["branch"]),
        worktree=str(pathlib.Path(str(payload["worktree"])).expanduser().resolve()),
        head_sha=str(payload["head_sha"]),
        tree_identity=str(payload["tree_identity"]),
        allowed_capabilities=allowed,
        issued_at_epoch=issued,
        expires_at_epoch=expires,
        max_tool_calls=max_calls,
        task_class=str(task_class),
        protected_scope=tuple(scope),
        control_plane_digest=digest,
        workspace_id=lease_workspace_id,
    )


def load_execution_lease_from_env(
    *,
    task: dict[str, Any],
    agent_id: str,
    session_id: str,
    required_capabilities: tuple[str, ...],
    control_plane_digest: str | None = None,
    workspace_id: str | None = None,
    now: int | None = None,
    root: pathlib.Path = ROOT,
) -> ExecutionLease:
    # Ed25519, not HMAC: the lease is consumed by the enforcement hook inside the
    # builder's process, so a symmetric key would let the builder mint its own
    # lease. verify_artifact checks it against the operator-signed trusted-key
    # registry, so only the offline issuer key can grant execution capabilities.
    from bro_signature import SignatureError, load_trusted_keys, verify_artifact
    raw = os.getenv("BRO_EXECUTION_LEASE")
    if not raw:
        raise LeaseError("missing BRO_EXECUTION_LEASE")
    try:
        payload = verify_artifact(
            _load_json(pathlib.Path(raw)), "execution-lease", load_trusted_keys(root), now=now
        )
    except SignatureError as exc:
        raise LeaseError(str(exc)) from exc
    return validate_execution_lease(
        payload,
        task=task,
        agent_id=agent_id,
        session_id=session_id,
        required_capabilities=required_capabilities,
        control_plane_digest=control_plane_digest,
        workspace_id=workspace_id,
        now=now,
    )


def _lease_digest(lease: ExecutionLease) -> str:
    return hashlib.sha256(f"{lease.lease_id}:{lease.nonce}".encode()).hexdigest()


def _lease_paths(lease: ExecutionLease) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    digest = _lease_digest(lease)
    ledger = _ledger_dir()
    return (
        ledger / f"{digest}.active",
        ledger / f"{digest}.used",
        ledger / f"{digest}.ambiguous",
    )


def _claim_call_slot(lease: ExecutionLease) -> None:
    """Atomically claim one of the lease's max_tool_calls slots, or refuse.

    max_tool_calls was validated and never counted — a field that promised a
    bound the ledger did not enforce. Each successful reservation now claims one
    numbered slot file via O_EXCL, the same check-is-the-write primitive as the
    active/used markers, so two concurrent reservations cannot share a slot and
    a lease can never be reserved more times than it declares. Today the
    single-use markers cap this at one reservation anyway; the counter makes the
    signed field enforced in its own right rather than true by accident.
    """
    digest = _lease_digest(lease)
    ledger = _ledger_dir()
    for slot in range(1, lease.max_tool_calls + 1):
        path = ledger / f"{digest}.call.{slot:08d}"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"schema": 1, "slot": slot,
                       "claimed_at_epoch": int(time.time())}, handle, sort_keys=True)
        return
    raise LeaseError("execution lease max_tool_calls exhausted")


def reserve_execution_lease(lease: ExecutionLease, tool_use_id: str) -> None:
    if not tool_use_id or len(tool_use_id) > 256:
        raise LeaseError("invalid tool_use_id for execution lease")
    active, used, ambiguous = _lease_paths(lease)
    active.parent.mkdir(parents=True, exist_ok=True)
    if used.exists():
        raise LeaseError("execution lease already consumed")
    if ambiguous.exists():
        raise LeaseError("execution lease is quarantined")
    record = {
        "schema": 1,
        "lease_id_sha256": hashlib.sha256(lease.lease_id.encode()).hexdigest(),
        "nonce_sha256": hashlib.sha256(lease.nonce.encode()).hexdigest(),
        "tool_use_id_sha256": hashlib.sha256(tool_use_id.encode()).hexdigest(),
        "task_id": lease.task_id,
        "agent_id": lease.agent_id,
        "session_id": lease.session_id,
        "reserved_at_epoch": int(time.time()),
    }
    try:
        fd = os.open(active, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise LeaseError("execution lease already active") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, sort_keys=True)
        # Claimed after the active marker so a lost race on `.active` does not
        # burn a slot; a claimed slot is never returned, even if the reservation
        # later fails — an ambiguous call still counts against the bound.
        _claim_call_slot(lease)
    except Exception:
        try:
            active.unlink()
        except OSError:
            pass
        raise


def finalize_execution_lease(lease: ExecutionLease, tool_use_id: str) -> None:
    active, used, ambiguous = _lease_paths(lease)
    if ambiguous.exists():
        raise LeaseError("execution lease is quarantined")
    if used.exists():
        raise LeaseError("execution lease already consumed")
    try:
        record = json.loads(active.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LeaseError("execution lease active reservation missing") from exc
    expected = hashlib.sha256(tool_use_id.encode()).hexdigest()
    if record.get("tool_use_id_sha256") != expected:
        raise LeaseError("execution lease tool_use_id binding mismatch")
    record["finalized_at_epoch"] = int(time.time())
    try:
        fd = os.open(used, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise LeaseError("execution lease already consumed") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(record, handle, sort_keys=True)
    active.unlink()


def quarantine_execution_lease(lease: ExecutionLease, tool_use_id: str, reason: str) -> None:
    active, used, ambiguous = _lease_paths(lease)
    if used.exists():
        raise LeaseError("execution lease already consumed")
    try:
        record = json.loads(active.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LeaseError("execution lease active reservation missing") from exc
    expected = hashlib.sha256(tool_use_id.encode()).hexdigest()
    if record.get("tool_use_id_sha256") != expected:
        raise LeaseError("execution lease tool_use_id binding mismatch")
    record["quarantined_at_epoch"] = int(time.time())
    record["reason"] = str(reason)
    try:
        fd = os.open(ambiguous, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise LeaseError("execution lease already quarantined") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(record, handle, sort_keys=True)
    active.unlink()
