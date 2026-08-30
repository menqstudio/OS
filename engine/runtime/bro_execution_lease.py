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

# The lease shape. Bumped 1 -> 2 when allowed_egress became a required field:
# `additionalProperties: false` plus an exact-set `required` makes a v1 and a v2
# lease mutually invalid, so this is a version change and not an addition. The
# same number is the `schema` const in contracts/execution-lease.schema.json and
# the `version` in contracts/index.json; tools/check_contracts_single_source.py
# binds those two to each other, and nothing binds either to this line.
LEASE_SCHEMA_VERSION = 2

# The destination axis (design SS3.1/SS3.2). `https://` + an exact lowercase FQDN +
# an optional port, and nothing else: no wildcard (an attacker-controlled
# subdomain is one registration away, and subset comparison must stay decidable),
# no IP literal (it cannot be re-checked against the NAME the grant stated), no
# `http://` (an unauthenticated destination grants whoever holds the wire), no
# path (the only layer that can enforce a destination sees CONNECT host:port and
# cannot see inside TLS). The final `[a-z]{2,63}` label is what rejects IPv4
# without a second matcher to keep in step.
_EGRESS_ENTRY_RE = re.compile(
    r"https://[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,63}(:[0-9]{1,5})?"
)
MAX_EGRESS_DESTINATIONS = 32


class LeaseError(ValueError):
    pass


def validate_egress_destinations(value: Any) -> tuple[str, ...]:
    """Judge the SHAPE of an `allowed_egress` list and return it normalised.

    Module-level and public so each refusal below can be reached by a test on
    its own terms. Reached only through `validate_execution_lease` in
    production, but a check that can only be exercised behind two earlier
    refusals is a check no test can bind to -- which is how four of these came
    back green under a mutation sweep before this function existed.
    """
    if not isinstance(value, list) or any(not isinstance(e, str) for e in value):
        raise LeaseError("execution lease allowed_egress must be a list of destinations")
    if len(value) > MAX_EGRESS_DESTINATIONS:
        raise LeaseError(
            f"execution lease names more than {MAX_EGRESS_DESTINATIONS} destinations"
        )
    if len(set(value)) != len(value):
        raise LeaseError("execution lease allowed_egress contains a duplicate destination")
    for entry in value:
        if not _EGRESS_ENTRY_RE.fullmatch(entry):
            raise LeaseError(f"execution lease egress destination not expressible: {entry!r}")
        port = entry.rpartition(":")[2]
        if port.isdigit() and not (1 <= int(port) <= 65535):
            raise LeaseError(f"execution lease egress destination port invalid: {entry!r}")
    return tuple(value)


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
    # The destination axis: which network authorities, orthogonal to tool, path
    # and risk. Empty means "no network" and is the only way to say it.
    allowed_egress: tuple[str, ...]
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
        "allowed_capabilities", "allowed_egress", "issued_at_epoch", "expires_at_epoch",
        "max_tool_calls", "task_class", "protected_scope", "control_plane_digest",
        "workspace_id",
    }
    # artifact_type/key_id are injected by the Ed25519 signer (broctl) and echoed
    # back by verify_artifact; tolerate them without weakening the required set.
    present = set(payload) - {"artifact_type", "key_id"}
    if present != required:
        # Name the fields. The single opaque string this replaced said only that
        # something was wrong with the shape, so an absent allowed_egress and a
        # typo'd key were the same message -- and `absent => LeaseError` is only a
        # control if the refusal tells the reader which field was absent.
        missing_keys = sorted(required - present)
        unexpected_keys = sorted(present - required)
        raise LeaseError(
            "execution lease has unexpected or missing keys "
            f"(missing={missing_keys}, unexpected={unexpected_keys})"
        )
    if payload.get("schema") != LEASE_SCHEMA_VERSION:
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

    # The destination axis (design SS3.1/SS3.2). REQUIRED and with no minimum:
    # `[]` is the only way to say "no network", and an absent field is a
    # LeaseError rather than a permissive default -- that single decision is the
    # whole difference between this axis and USE_NETWORK, which is
    # absent-by-default and therefore silently satisfiable wherever it is not
    # checked.
    #
    # The SHAPE is judged here, before the capability block, and the
    # authority COUPLING below. Judged the other way round, a malformed
    # destination in a lease that cannot hold USE_NETWORK reports "no
    # USE_NETWORK" -- a true sentence about the wrong field, and a refusal that
    # sends its reader to the wrong place. It also made four checks unreachable:
    # a mutation sweep deleted each of them and every test stayed green, because
    # a later refusal answered for them.
    egress = validate_egress_destinations(payload.get("allowed_egress"))

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

    # A lease may not name a destination it holds no capability to reach. No
    # class in CLASS_CAPABILITIES carries USE_NETWORK, so at this head every
    # valid lease carries `[]` -- the axis exists, is required, and states "no
    # network" for every class that exists. It becomes expressible the day a
    # class holds USE_NETWORK, and not one commit earlier.
    if egress and "USE_NETWORK" not in allowed:
        raise LeaseError(
            "execution lease names destinations without USE_NETWORK: a grant must not "
            "state an authority it cannot deliver"
        )

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
        allowed_egress=egress,
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
