"""The governed supervisor's DURABLE acceptance/lease/completion state (rev-30 §5).

This is the module the independent audit's **F-01 (P0)** demanded. Before it, the
supervisor held NO run state: ``accept_open`` minted a lease from ``uuid4()`` and
persisted nothing, ``launch_gate`` decided on a lease the caller handed back, and
``attest-run`` signed whatever ``facts`` arrived on the wire. The broker uid could
therefore mint an Ed25519-signed ``brops.governed-receipt-envelope.v1`` for a run that
never happened — no challenge, no lease, no executor, no model.

This module closes that by making the supervisor an authority over state **it owns**:

  * ``accept_prepare`` writes a durable acceptance row whose three ``UNIQUE``
    constraints ARE the CAS — one signed challenge mints exactly ONE execution
    attempt, forever. A replay is either byte-identically idempotent or REFUSED.
  * the row carries the request binding copied out of the *signature-verified*
    challenge payload, the lease window stamped from the supervisor's own clock, and
    a supervisor-minted per-turn ``receipt_id`` — so the attestation can later be
    rebuilt WITHOUT trusting anything the caller says.
  * ``gate_and_start`` runs the §5 step-8a budget gate against the supervisor's OWN
    persisted lease window, not a caller-supplied one.
  * ``record_completion`` accepts the run-produced facts exactly ONCE (the completion
    table's PRIMARY KEY is the write-once gate) and only for an attempt that already
    reached ``EXECUTING`` through the legal edges — and in the same transaction it
    drives the evidence-head anti-rollback/anti-fork floor.
  * ``load_attestation_state`` is the ONLY door the attestation builder reads from,
    and it returns a row only for an attempt in the terminal ``COMPLETED`` state.

**A fabricated run has no row, so it has no evidence and no attestation.**

The schema is NOT written here. It is loaded verbatim from
``supervisor_ledger.sql`` — the single normative source shared with the Rust
``brops-core::supervisor_ledger`` (byte-equality enforced by the fail-closed CI gate
``tools/check_ledger_ddl_parity.py``). The SQL *is* the enforcement: the UNIQUEs, the
closed ``state`` CHECK, the BEFORE-UPDATE transition trigger, the write-once PK, and
the floor's PK. Neither language can weaken it alone.

Only the Python standard library is used. Every clock is an injected ``now_ms``; every
multi-statement operation owns a ``BEGIN IMMEDIATE`` so a read-then-write cannot be
interleaved or half-applied.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

# ---------------------------------------------------------------------------
# Canonical schema — loaded from the shared DDL, never inlined here.
# ---------------------------------------------------------------------------

SCHEMA_PATH = pathlib.Path(__file__).resolve().parent / "supervisor_ledger.sql"

# ---------------------------------------------------------------------------
# The closed §5 acceptance lifecycle (mirrors the SQL CHECK domain exactly).
# ---------------------------------------------------------------------------

ACCEPTED_PREPARED = "ACCEPTED_PREPARED"
LEASE_READY = "LEASE_READY"
EXECUTION_STARTING = "EXECUTION_STARTING"
EXECUTING = "EXECUTING"
COMPLETED = "COMPLETED"
BLOCKED = "BLOCKED"
FAILED = "FAILED"
EXPIRED = "EXPIRED"
RECOVERY_REQUIRED = "RECOVERY_REQUIRED"

TERMINAL_STATES = frozenset({COMPLETED, BLOCKED, FAILED, EXPIRED, RECOVERY_REQUIRED})

#: The closed domain the ``state`` column may hold — identical to the SQL CHECK. A stored
#: value outside it means a corrupt/foreign DB and is refused, never interpreted.
ALL_STATES = frozenset({
    ACCEPTED_PREPARED, LEASE_READY, EXECUTION_STARTING, EXECUTING,
    COMPLETED, BLOCKED, FAILED, EXPIRED, RECOVERY_REQUIRED,
})

#: The legal predecessors of each edge — the same matrix the DDL trigger enforces.
#: Kept here so an illegal edge is refused by a ``WHERE state IN (...)`` guard that
#: matches zero rows (a typed error), with the trigger as the independent second wall.
LEGAL_PREDECESSORS: Dict[str, Tuple[str, ...]] = {
    LEASE_READY: (ACCEPTED_PREPARED,),
    EXECUTION_STARTING: (LEASE_READY,),
    EXECUTING: (EXECUTION_STARTING,),
    COMPLETED: (EXECUTING,),
    FAILED: (EXECUTING,),
    BLOCKED: (ACCEPTED_PREPARED, LEASE_READY),
    EXPIRED: (LEASE_READY,),
    RECOVERY_REQUIRED: (EXECUTION_STARTING, EXECUTING),
}

# §5 step-8a budget constants — mirror supervisor_ledger.rs / governed_supervisor.py.
MIN_LAUNCH_REMAINING_MS = 180_000
LEASE_DURATION_MS = 210_000


# ---------------------------------------------------------------------------
# Errors — a ledger fault is infrastructure/authority, never a renderer verdict.
# ---------------------------------------------------------------------------


class LedgerError(Exception):
    """Base class for every durable-ledger fault. Always fail-closed."""


class NotFound(LedgerError):
    """No acceptance row exists for the given key (e.g. a fabricated attempt id)."""


class IllegalTransition(LedgerError):
    """The requested edge is not legal from the row's current state (or it is terminal)."""

    def __init__(self, frm: str, to: str) -> None:
        super().__init__("illegal acceptance transition %s -> %s" % (frm, to))
        self.frm = frm
        self.to = to


class Conflict(LedgerError):
    """A CAS/uniqueness conflict: a reused nonce/challenge/attempt/receipt bound to a
    DIFFERENT turn, or a second completion whose facts differ from the recorded ones."""

    def __init__(self, which: str) -> None:
        super().__init__("acceptance ledger conflict: %s" % which)
        self.which = which


class InvalidHead(LedgerError):
    """A malformed evidence head (bad hex, non-positive counts, last_sequence != count)."""


class StaleEvidence(LedgerError):
    """The evidence head presents a strictly LOWER head_sequence than the durable floor."""


class EvidenceFork(LedgerError):
    """Equal head_sequence with differing content — a same-head fork."""


class Corrupt(LedgerError):
    """A stored row carried a value outside its closed domain (a corrupt/foreign DB)."""


# ---------------------------------------------------------------------------
# Small validators (byte-compatible with governed_supervisor / isolated_signer).
# ---------------------------------------------------------------------------


def _is_lower_sha256_hex(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(c in "0123456789abcdef" for c in value)


def _is_u64_ms(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 2 ** 64


def _is_pos_i63(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value < 2 ** 63


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    """The same deterministic JCS-ish encoding the supervisor signs with — used here
    only to content-address the completion facts so a retry is byte-comparable."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Connection.
# ---------------------------------------------------------------------------


def open_ledger(db_path: str) -> sqlite3.Connection:
    """Open (creating if absent) the supervisor's durable ledger and apply the shared DDL.

    The file is created 0600 and the containing directory is expected to belong to the
    supervisor principal — this state is the supervisor's authority, so no other uid may
    write it. ``isolation_level=None`` puts the connection in explicit-transaction mode so
    every multi-statement operation below can own its ``BEGIN IMMEDIATE``.
    """
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, mode=0o700, exist_ok=True)
    fresh = not os.path.exists(db_path)
    conn = sqlite3.connect(db_path, isolation_level=None)
    if fresh:
        try:
            os.chmod(db_path, 0o600)
        except OSError:
            pass  # a platform without POSIX modes; the directory ACL is the real control
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    apply_schema(conn)
    return conn


def apply_schema(conn: sqlite3.Connection) -> None:
    """Apply the CANONICAL shared DDL (idempotent). Fails closed if the file is missing —
    a supervisor with no durable schema must refuse to serve, not run stateless."""
    try:
        ddl = SCHEMA_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise LedgerError("canonical ledger DDL unreadable at %s: %s" % (SCHEMA_PATH, exc))
    conn.executescript(ddl)
    conn.execute("PRAGMA foreign_keys = ON")


def _errname(exc: sqlite3.Error) -> str:
    # Python 3.11+ exposes the extended result code by name; fall back to the message so
    # the classification never silently degrades into "unknown integrity error".
    name = getattr(exc, "sqlite_errorname", "") or ""
    if name:
        return name
    text = str(exc).upper()
    if "UNIQUE CONSTRAINT FAILED" in text:
        return "SQLITE_CONSTRAINT_UNIQUE"
    if "FOREIGN KEY CONSTRAINT FAILED" in text:
        return "SQLITE_CONSTRAINT_FOREIGNKEY"
    return "SQLITE_CONSTRAINT"


def _is_unique_violation(exc: sqlite3.Error) -> bool:
    return _errname(exc) in ("SQLITE_CONSTRAINT_UNIQUE", "SQLITE_CONSTRAINT_PRIMARYKEY")


class _Tx:
    """An owned ``BEGIN IMMEDIATE`` — the write lock is taken up front so a read-then-write
    decision (a CAS, a floor comparison) cannot be interleaved by a second supervisor."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        if self._conn.in_transaction:
            raise LedgerError("ledger operation must own its BEGIN IMMEDIATE")
        self._conn.execute("BEGIN IMMEDIATE")
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self._conn.execute("COMMIT")
        else:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        return False


# ---------------------------------------------------------------------------
# Acceptance — the CAS that makes one signed challenge worth exactly one attempt.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NewAcceptance:
    """The authoritative bindings persisted at ``ACCEPTED_PREPARED`` (§5 step 4).

    Every field is SUPERVISOR-derived: the identity/binding values are copied out of the
    challenge payload *after* its signature verified, the lease window is the supervisor's
    own clock, and ``receipt_id`` is minted by the supervisor. None of it is a raw caller
    input, which is exactly what lets the later attestation mean something.
    """

    install_id: str
    request_nonce: str
    challenge_handle: str
    run_id: str
    task_id: str
    workspace_id: str
    execution_attempt_id: str
    challenge_accepted_at_ms: int
    challenge_registry_handle: str
    challenge_registry_hash: str
    challenge_registry_epoch: int
    challenge_registry_root_key_id: str
    lease_payload_bytes: bytes
    lease_id: str
    lease_issued_at_ms: int
    lease_expires_at_ms: int
    receipt_id: str
    supervisor_id: str
    requested_at_ms: int
    request_sha256: str
    system_handle: str
    history_handle: str
    generation_config_handle: str


#: Every bound field compared when deciding idempotent-retry vs hard conflict.
_BOUND_FIELDS: Tuple[str, ...] = (
    "challenge_handle",
    "run_id",
    "task_id",
    "workspace_id",
    "execution_attempt_id",
    "lease_id",
    "lease_issued_at_ms",
    "lease_expires_at_ms",
    "receipt_id",
    "supervisor_id",
    "requested_at_ms",
    "request_sha256",
    "system_handle",
    "history_handle",
    "generation_config_handle",
)

CREATED = "created"
IDEMPOTENT = "idempotent"


def accept_prepare(conn: sqlite3.Connection, a: NewAcceptance, now_ms: int) -> str:
    """CAS insert ``absent → ACCEPTED_PREPARED`` (§5 step 4).

    The three ``UNIQUE`` constraints ARE the CAS: a reused ``(install_id, request_nonce)``,
    ``challenge_handle``, ``execution_attempt_id`` — or a reused ``receipt_id`` — collides.
    On collision the existing row is loaded and compared field-by-field: byte-identical is a
    genuine retry (:data:`IDEMPOTENT`, still ONE attempt); ANY divergence raises
    :class:`Conflict` and creates no second attempt.

    This is what stops a replayed signed challenge from minting unlimited leases.
    """
    with _Tx(conn) as tx:
        return _prepare_locked(tx, a, now_ms)


def _prepare_locked(tx: sqlite3.Connection, a: NewAcceptance, now_ms: int) -> str:
    """The CAS body. Caller already holds the ``BEGIN IMMEDIATE``."""
    lease_payload_sha256 = _sha256_hex(bytes(a.lease_payload_bytes))
    try:
        tx.execute(
            "INSERT INTO governed_turn_acceptance ("
            " install_id, request_nonce, challenge_handle, run_id, task_id, workspace_id,"
            " execution_attempt_id, challenge_accepted_at_ms, challenge_registry_handle,"
            " challenge_registry_hash, challenge_registry_epoch, challenge_registry_root_key_id,"
            " lease_payload_sha256, lease_payload_bytes,"
            " lease_id, lease_issued_at_ms, lease_expires_at_ms, receipt_id, supervisor_id,"
            " requested_at_ms, request_sha256, system_handle, history_handle,"
            " generation_config_handle,"
            " state, created_at_ms, updated_at_ms)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
            "         'ACCEPTED_PREPARED',?,?)",
            (
                a.install_id, a.request_nonce, a.challenge_handle, a.run_id, a.task_id,
                a.workspace_id, a.execution_attempt_id, a.challenge_accepted_at_ms,
                a.challenge_registry_handle, a.challenge_registry_hash,
                a.challenge_registry_epoch, a.challenge_registry_root_key_id,
                lease_payload_sha256, sqlite3.Binary(bytes(a.lease_payload_bytes)),
                a.lease_id, a.lease_issued_at_ms, a.lease_expires_at_ms, a.receipt_id,
                a.supervisor_id, a.requested_at_ms, a.request_sha256, a.system_handle,
                a.history_handle, a.generation_config_handle,
                now_ms, now_ms,
            ),
        )
        return CREATED
    except sqlite3.IntegrityError as exc:
        if not _is_unique_violation(exc):
            raise LedgerError("acceptance insert failed: %s" % exc)
        row = tx.execute(
            "SELECT * FROM governed_turn_acceptance"
            " WHERE install_id = ? AND request_nonce = ?",
            (a.install_id, a.request_nonce),
        ).fetchone()
        if row is None:
            # The nonce is unused, so the collision was on challenge_handle /
            # execution_attempt_id / receipt_id reused under a DIFFERENT nonce.
            raise Conflict("challenge_or_attempt_reused")
        if row["lease_payload_sha256"] != lease_payload_sha256:
            raise Conflict("nonce_rebound_to_different_turn")
        for field in _BOUND_FIELDS:
            if row[field] != getattr(a, field):
                raise Conflict("nonce_rebound_to_different_turn")
        return IDEMPOTENT


def reuse_or_prepare(conn: sqlite3.Connection, a: NewAcceptance,
                     now_ms: int) -> Tuple[str, sqlite3.Row]:
    """Accept a challenge ONCE, tolerating an honest retry — the operation the front door uses.

    ``accept_prepare`` alone cannot serve a retry, because the supervisor mints fresh
    ``lease_id`` / ``execution_attempt_id`` / ``receipt_id`` on every call, so a resubmitted
    challenge would look like a rebinding and be refused. Here the *challenge* is the key:
    inside one ``BEGIN IMMEDIATE`` this looks the challenge up by its content address and

      * if that exact signed challenge was already accepted, returns the ORIGINAL row — the
        caller gets back the SAME lease and the SAME attempt, so a replay still buys zero
        additional executions (and a challenge somehow re-bound to a different install/nonce
        is a hard :class:`Conflict`);
      * otherwise inserts the new acceptance under the three ``UNIQUE`` CAS constraints.

    Returns ``(CREATED|IDEMPOTENT, row)``.
    """
    with _Tx(conn) as tx:
        row = tx.execute(
            "SELECT * FROM governed_turn_acceptance WHERE challenge_handle = ?",
            (a.challenge_handle,),
        ).fetchone()
        if row is not None:
            if row["install_id"] != a.install_id or row["request_nonce"] != a.request_nonce:
                raise Conflict("challenge_rebound_to_different_turn")
            return IDEMPOTENT, row
        _prepare_locked(tx, a, now_ms)
        fresh = tx.execute(
            "SELECT * FROM governed_turn_acceptance WHERE execution_attempt_id = ?",
            (a.execution_attempt_id,),
        ).fetchone()
        if fresh is None:  # pragma: no cover - the insert above just succeeded
            raise LedgerError("acceptance row vanished after insert")
        return CREATED, fresh


def _current_state(conn: sqlite3.Connection, execution_attempt_id: str) -> Optional[str]:
    row = conn.execute(
        "SELECT state FROM governed_turn_acceptance WHERE execution_attempt_id = ?",
        (execution_attempt_id,),
    ).fetchone()
    if row is None:
        return None
    state = row["state"]
    if state not in ALL_STATES:
        raise Corrupt("acceptance.state")
    return state


def _advance(
    conn: sqlite3.Connection,
    execution_attempt_id: str,
    target: str,
    now_ms: int,
    extra_sql: str = "",
    extra_params: Tuple[Any, ...] = (),
) -> str:
    """Apply one §5 edge under a ``WHERE state IN (<legal predecessors>)`` guard.

    An illegal jump matches zero rows and raises :class:`IllegalTransition` — never a
    silent overwrite; a missing attempt raises :class:`NotFound`. The DDL's BEFORE-UPDATE
    trigger is the independent second wall against any illegal edge or any move out of a
    terminal state. Caller must already hold the transaction.
    """
    preds = LEGAL_PREDECESSORS.get(target)
    if preds is None:
        raise LedgerError("unknown acceptance target state %r" % (target,))
    placeholders = ",".join("?" for _ in preds)
    cur = conn.execute(
        "UPDATE governed_turn_acceptance SET state = ?, updated_at_ms = ?%s"
        " WHERE execution_attempt_id = ? AND state IN (%s)" % (extra_sql, placeholders),
        (target, now_ms) + tuple(extra_params) + (execution_attempt_id,) + tuple(preds),
    )
    if cur.rowcount == 1:
        return target
    state = _current_state(conn, execution_attempt_id)
    if state is None:
        raise NotFound("no acceptance row for attempt %r" % (execution_attempt_id,))
    raise IllegalTransition(state, target)


def advance(conn: sqlite3.Connection, execution_attempt_id: str, target: str, now_ms: int,
            *, failure_reason: Optional[str] = None) -> str:
    """Public single-edge transition for the refusal/terminal edges (BLOCKED / FAILED /
    EXPIRED / RECOVERY_REQUIRED) and LEASE_READY-less bookkeeping."""
    with _Tx(conn) as tx:
        if failure_reason is not None:
            return _advance(tx, execution_attempt_id, target, now_ms,
                            ", failure_reason = ?", (failure_reason,))
        return _advance(tx, execution_attempt_id, target, now_ms)


def mark_lease_ready(conn: sqlite3.Connection, execution_attempt_id: str,
                     lease_handle: str, now_ms: int) -> str:
    """``ACCEPTED_PREPARED → LEASE_READY`` — the lease is published and re-verified (§5 step 7)."""
    with _Tx(conn) as tx:
        return _advance(tx, execution_attempt_id, LEASE_READY, now_ms,
                        ", lease_handle = ?", (lease_handle,))


def mark_executing(conn: sqlite3.Connection, execution_attempt_id: str, *,
                   process_group_id: str, cgroup_id: str,
                   execution_started_marker: Optional[str], now_ms: int) -> str:
    """``EXECUTION_STARTING → EXECUTING`` — the child is confirmed running AND its process
    metadata is durably persisted (§5: the single event that flips STARTING→EXECUTING)."""
    return _guarded(conn, execution_attempt_id, EXECUTING, now_ms,
                    ", process_group_id = ?, cgroup_id = ?, execution_started_marker = ?",
                    (process_group_id, cgroup_id, execution_started_marker))


def _guarded(conn: sqlite3.Connection, attempt: str, target: str, now_ms: int,
             extra_sql: str, extra_params: Tuple[Any, ...]) -> str:
    with _Tx(conn) as tx:
        return _advance(tx, attempt, target, now_ms, extra_sql, extra_params)


# ---------------------------------------------------------------------------
# The §5 step-8a launch gate — over the supervisor's OWN persisted lease window.
# ---------------------------------------------------------------------------


def lease_launch_gate(now_ms: int, lease_issued_at_ms: int, lease_expires_at_ms: int) -> Optional[str]:
    """Pure §5 step-8a gate. Returns ``None`` to proceed, else the deterministic EXPIRED
    cause. Boundary: remaining exactly ``180000`` proceeds, ``179999`` refuses (identical to
    ``supervisor_ledger.rs::lease_launch_gate``)."""
    if now_ms < lease_issued_at_ms:
        return "lease_not_yet_valid"
    if now_ms > lease_expires_at_ms:
        return "lease_expired"
    if lease_expires_at_ms - now_ms < MIN_LAUNCH_REMAINING_MS:
        return "insufficient_remaining_budget"
    return None


def gate_and_start(conn: sqlite3.Connection, execution_attempt_id: str, now_ms: int) -> str:
    """Run the step-8a gate against the lease window THIS supervisor persisted, then CAS
    ``LEASE_READY`` to its deterministic next state: proceed ⇒ ``EXECUTION_STARTING``
    (the launcher may spawn exactly once), failure ⇒ ``EXPIRED`` with the gate reason.

    The caller supplies ONLY the attempt id. It cannot present a lease, so it can no longer
    choose the expiry it is judged against — the fix for the decorative-lease half of F-01
    (and audit F-23). This is the ONE place a ``LEASE_READY`` row is driven forward, so the
    gate cannot be smuggled past.
    """
    with _Tx(conn) as tx:
        row = tx.execute(
            "SELECT lease_issued_at_ms, lease_expires_at_ms FROM governed_turn_acceptance"
            " WHERE execution_attempt_id = ?",
            (execution_attempt_id,),
        ).fetchone()
        if row is None:
            raise NotFound("no acceptance row for attempt %r" % (execution_attempt_id,))
        reason = lease_launch_gate(now_ms, row["lease_issued_at_ms"], row["lease_expires_at_ms"])
        if reason is None:
            return _advance(tx, execution_attempt_id, EXECUTION_STARTING, now_ms)
        return _advance(tx, execution_attempt_id, EXPIRED, now_ms,
                        ", failure_reason = ?", (reason,))


# ---------------------------------------------------------------------------
# Completion — the WRITE-ONCE record of what the run produced (+ the evidence floor).
# ---------------------------------------------------------------------------

#: The only §4.9 evidence values the supervisor cannot derive itself, so the executing
#: chain reports them — ONCE, for an attempt the supervisor already authorized. Every
#: OTHER evidence field comes from the acceptance row or the supervisor's own config.
COMPLETION_HANDLE_FIELDS: Tuple[str, ...] = (
    "output_handle",
    "containment_evidence_handle",
)

#: Handles the SUPERVISOR derives from its own state and publishes to the protected store —
#: they are NOT part of `produced` and cannot be supplied by a caller (audit **F-02**).
#:
#: `lease_handle` is the content address of the exact canonical lease bytes persisted at
#: acceptance; `record_handle` and `execution_receipt_handle` address documents the supervisor
#: builds from the acceptance + completion rows. Before this, all three were deployment-static
#: constants the broker copied out of a world-readable config, so the signer's "deep protected-
#: chain verification" only proved that someone had written those same constant bytes once.
DERIVED_HANDLE_FIELDS: Tuple[str, ...] = (
    "record_handle",
    "lease_handle",
    "execution_receipt_handle",
)
COMPLETION_DIGEST_FIELDS: Tuple[str, ...] = ("evidence_final_event_hash",)
COMPLETION_TS_FIELDS: Tuple[str, ...] = ("completed_at_ms",)
COMPLETION_COUNT_FIELDS: Tuple[str, ...] = (
    "evidence_event_count",
    "evidence_last_sequence",
    "evidence_head_sequence",
)
COMPLETION_FIELDS: Tuple[str, ...] = (
    COMPLETION_HANDLE_FIELDS
    + COMPLETION_DIGEST_FIELDS
    + COMPLETION_TS_FIELDS
    + COMPLETION_COUNT_FIELDS
)


def validate_completion_facts(produced: Any) -> Dict[str, Any]:
    """Strict-parse the run-produced facts against the fixed :data:`COMPLETION_FIELDS`
    shape. An extra key (a smuggled id, nonce, timestamp, or identity the supervisor
    already owns), a missing key, or a wrong-typed value raises :class:`InvalidHead`-free
    :class:`LedgerError` — there is no partial acceptance.

    Note what is DELIBERATELY absent: ``run_id``, ``task_id``, ``request_nonce``,
    ``receipt_id``, ``workspace_id``, ``install_id``, ``supervisor_id``, ``executor_id``,
    ``builder_id``, ``policy_*``, ``requested_at``, ``challenge_accepted_at_ms``. Those are
    supervisor state or supervisor config; accepting them here would re-open F-01. Also absent
    (audit **F-02**): ``record_handle``, ``lease_handle`` and ``execution_receipt_handle`` — the
    supervisor derives those from its own rows and publishes them itself.
    """
    if not isinstance(produced, Mapping):
        raise LedgerError("completion facts must be a mapping")
    keys = set(produced.keys())
    allowed = set(COMPLETION_FIELDS)
    extra = keys - allowed
    if extra:
        raise LedgerError("unexpected completion field(s) %s" % sorted(extra))
    missing = allowed - keys
    if missing:
        raise LedgerError("missing completion field(s) %s" % sorted(missing))
    for field in COMPLETION_HANDLE_FIELDS + COMPLETION_DIGEST_FIELDS:
        if not _is_lower_sha256_hex(produced[field]):
            raise LedgerError("%s must be 64 lowercase hex chars" % field)
    for field in COMPLETION_TS_FIELDS:
        if not _is_u64_ms(produced[field]):
            raise LedgerError("%s must be a u64 epoch-ms int" % field)
    for field in COMPLETION_COUNT_FIELDS:
        if not _is_pos_i63(produced[field]):
            raise LedgerError("%s must be a positive int (>= 1)" % field)
    if produced["evidence_last_sequence"] != produced["evidence_event_count"]:
        raise InvalidHead("last_sequence != event_count")
    return {field: produced[field] for field in COMPLETION_FIELDS}


def _evidence_floor_cas(conn: sqlite3.Connection, install_id: str, task_id: str,
                        facts: Mapping[str, Any], now_ms: int) -> str:
    """The durable evidence-head anti-rollback/anti-fork floor (§5 step 11 / §7 P1-7),
    run INSIDE the completion transaction so a refused head writes no completion at all.

    (The Rust twin owns its own ``BEGIN IMMEDIATE`` and refuses nesting; here the floor is
    deliberately folded into the completion's single transaction — same atomicity, one
    fewer lock acquisition, and a refused floor cannot leave a completion behind.)
    """
    head_sequence = facts["evidence_head_sequence"]
    event_count = facts["evidence_event_count"]
    last_sequence = facts["evidence_last_sequence"]
    final_event_hash = facts["evidence_final_event_hash"]

    row = conn.execute(
        "SELECT highest_head_sequence, event_count, last_sequence, final_event_hash"
        " FROM governed_evidence_head_floor WHERE install_id = ? AND task_id = ?",
        (install_id, task_id),
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO governed_evidence_head_floor (install_id, task_id,"
            " highest_head_sequence, event_count, last_sequence, final_event_hash, updated_at_ms)"
            " VALUES (?,?,?,?,?,?,?)",
            (install_id, task_id, head_sequence, event_count, last_sequence,
             final_event_hash, now_ms),
        )
        return "bootstrapped"

    highest = row["highest_head_sequence"]
    if (highest < 1 or row["event_count"] < 1 or row["last_sequence"] < 1
            or row["last_sequence"] != row["event_count"]
            or len(row["final_event_hash"]) != 64):
        raise Corrupt("evidence_head_floor")

    if head_sequence < highest:
        raise StaleEvidence("head_sequence %d below durable floor %d" % (head_sequence, highest))
    if head_sequence == highest:
        identical = (event_count == row["event_count"]
                     and last_sequence == row["last_sequence"]
                     and final_event_hash == row["final_event_hash"])
        if identical:
            return "idempotent"
        raise EvidenceFork("equal head_sequence with divergent chain content")
    conn.execute(
        "UPDATE governed_evidence_head_floor SET highest_head_sequence = ?, event_count = ?,"
        " last_sequence = ?, final_event_hash = ?, updated_at_ms = ?"
        " WHERE install_id = ? AND task_id = ?",
        (head_sequence, event_count, last_sequence, final_event_hash, now_ms,
         install_id, task_id),
    )
    return "advanced"


def load_acceptance(conn: sqlite3.Connection, execution_attempt_id: str) -> Optional[sqlite3.Row]:
    """The full acceptance row for an attempt — the state the supervisor builds its own
    terminal artifacts from (audit F-02). ``None`` if the attempt was never accepted."""
    return conn.execute(
        "SELECT * FROM governed_turn_acceptance WHERE execution_attempt_id = ?",
        (execution_attempt_id,),
    ).fetchone()


def record_completion(conn: sqlite3.Connection, execution_attempt_id: str,
                      produced: Any, now_ms: int,
                      *, derived: Mapping[str, str]) -> str:
    """Record the run-produced facts EXACTLY ONCE and move ``EXECUTING → COMPLETED``.

    In one ``BEGIN IMMEDIATE``:

      1. strict-validate the fixed completion shape (:func:`validate_completion_facts`);
      2. drive the evidence-head floor — a stale or forked head refuses the whole
         completion, so no attestation can ever be built over rolled-back evidence;
      3. INSERT the completion row. Its PRIMARY KEY is the write-once gate: a retry with
         byte-identical facts is :data:`IDEMPOTENT`; ANY divergence is :class:`Conflict`;
      4. CAS the acceptance row ``EXECUTING → COMPLETED``. An attempt that never legally
         reached ``EXECUTING`` raises :class:`IllegalTransition` and nothing is written.

    Step 4 is why a fabricated attempt cannot buy an attestation: there is no row to
    advance, and the ``FOREIGN KEY`` on the completion table refuses the insert outright.
    """
    facts = validate_completion_facts(produced)
    # The three supervisor-derived handles (F-02) join the record here, never through `produced`.
    for field in DERIVED_HANDLE_FIELDS:
        value = derived.get(field)
        if not _is_lower_sha256_hex(value):
            raise LedgerError("derived %s must be 64 lowercase hex chars" % field)
        facts[field] = value
    if set(derived) - set(DERIVED_HANDLE_FIELDS):
        raise LedgerError(
            "unexpected derived handle(s) %s" % sorted(set(derived) - set(DERIVED_HANDLE_FIELDS))
        )
    facts_sha256 = _sha256_hex(canonical_bytes(facts))

    with _Tx(conn) as tx:
        acceptance = tx.execute(
            "SELECT install_id, task_id, state FROM governed_turn_acceptance"
            " WHERE execution_attempt_id = ?",
            (execution_attempt_id,),
        ).fetchone()
        if acceptance is None:
            raise NotFound("no acceptance row for attempt %r" % (execution_attempt_id,))

        inserted = True
        try:
            tx.execute(
                "INSERT INTO governed_turn_completion ("
                " execution_attempt_id, output_handle, containment_evidence_handle,"
                " record_handle, lease_handle, execution_receipt_handle, completed_at_ms,"
                " evidence_final_event_hash, evidence_event_count, evidence_last_sequence,"
                " evidence_head_sequence, facts_sha256, created_at_ms)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    execution_attempt_id, facts["output_handle"],
                    facts["containment_evidence_handle"], facts["record_handle"],
                    facts["lease_handle"], facts["execution_receipt_handle"],
                    facts["completed_at_ms"], facts["evidence_final_event_hash"],
                    facts["evidence_event_count"], facts["evidence_last_sequence"],
                    facts["evidence_head_sequence"], facts_sha256, now_ms,
                ),
            )
        except sqlite3.IntegrityError as exc:
            if not _is_unique_violation(exc):
                # A FOREIGN KEY violation lands here: a completion for an attempt that was
                # never accepted. Fail closed rather than record an orphan fact.
                raise Conflict("completion_not_accepted")
            existing = tx.execute(
                "SELECT facts_sha256 FROM governed_turn_completion WHERE execution_attempt_id = ?",
                (execution_attempt_id,),
            ).fetchone()
            if existing is None or existing["facts_sha256"] != facts_sha256:
                raise Conflict("completion_facts_differ")
            inserted = False

        # Only a genuinely NEW completion touches the floor; an idempotent retry must not
        # re-run the CAS (its head is by definition the one already accepted). Kept OUTSIDE
        # the try above so a floor refusal is never mistaken for a uniqueness collision —
        # StaleEvidence / EvidenceFork propagate and roll the whole completion back.
        if inserted:
            _evidence_floor_cas(tx, acceptance["install_id"], acceptance["task_id"],
                                facts, now_ms)
        outcome = CREATED if inserted else IDEMPOTENT

        if acceptance["state"] != COMPLETED:
            _advance(tx, execution_attempt_id, COMPLETED, now_ms,
                     ", terminal_record_handle = ?", (facts["record_handle"],))
        return outcome


# ---------------------------------------------------------------------------
# The ONLY read the attestation builder is allowed.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttestationState:
    """The supervisor's OWN terminal run state for one attempt — everything the §4.9
    evidence needs except the deployment identities, which come from supervisor config.

    Returned only for an attempt whose acceptance row is in the terminal ``COMPLETED``
    state with a matching ``run_id``. There is no other way to obtain one.
    """

    run_id: str
    execution_attempt_id: str
    task_id: str
    request_nonce: str
    receipt_id: str
    workspace_id: str
    install_id: str
    supervisor_id: str
    requested_at_ms: int
    challenge_accepted_at_ms: int
    completed_at_ms: int
    system_handle: str
    history_handle: str
    generation_config_handle: str
    output_handle: str
    containment_evidence_handle: str
    record_handle: str
    lease_handle: str
    execution_receipt_handle: str
    evidence_final_event_hash: str
    evidence_event_count: int
    evidence_last_sequence: int
    evidence_head_sequence: int


def load_attestation_state(conn: sqlite3.Connection, run_id: str,
                           execution_attempt_id: str) -> Optional[AttestationState]:
    """Load the supervisor's terminal run state for ``{run_id, execution_attempt_id}``.

    Returns ``None`` when there is no such attempt, when its ``run_id`` does not match,
    when it is not ``COMPLETED``, or when no completion row exists — i.e. for every
    fabricated or half-finished run. The caller turns ``None`` into a refusal; it has no
    way to supply the missing facts itself.
    """
    if not _nonempty_str(run_id) or not _nonempty_str(execution_attempt_id):
        return None
    row = conn.execute(
        "SELECT a.run_id AS run_id, a.execution_attempt_id AS execution_attempt_id,"
        "       a.task_id AS task_id, a.request_nonce AS request_nonce,"
        "       a.receipt_id AS receipt_id, a.workspace_id AS workspace_id,"
        "       a.install_id AS install_id, a.supervisor_id AS supervisor_id,"
        "       a.requested_at_ms AS requested_at_ms,"
        "       a.challenge_accepted_at_ms AS challenge_accepted_at_ms,"
        "       a.system_handle AS system_handle, a.history_handle AS history_handle,"
        "       a.generation_config_handle AS generation_config_handle,"
        "       a.state AS state,"
        "       c.output_handle AS output_handle,"
        "       c.containment_evidence_handle AS containment_evidence_handle,"
        "       c.record_handle AS record_handle, c.lease_handle AS lease_handle,"
        "       c.execution_receipt_handle AS execution_receipt_handle,"
        "       c.completed_at_ms AS completed_at_ms,"
        "       c.evidence_final_event_hash AS evidence_final_event_hash,"
        "       c.evidence_event_count AS evidence_event_count,"
        "       c.evidence_last_sequence AS evidence_last_sequence,"
        "       c.evidence_head_sequence AS evidence_head_sequence"
        "  FROM governed_turn_acceptance a"
        "  JOIN governed_turn_completion c"
        "    ON c.execution_attempt_id = a.execution_attempt_id"
        " WHERE a.execution_attempt_id = ?",
        (execution_attempt_id,),
    ).fetchone()
    if row is None:
        return None
    if row["run_id"] != run_id:
        return None
    if row["state"] != COMPLETED:
        return None
    return AttestationState(
        run_id=row["run_id"],
        execution_attempt_id=row["execution_attempt_id"],
        task_id=row["task_id"],
        request_nonce=row["request_nonce"],
        receipt_id=row["receipt_id"],
        workspace_id=row["workspace_id"],
        install_id=row["install_id"],
        supervisor_id=row["supervisor_id"],
        requested_at_ms=row["requested_at_ms"],
        challenge_accepted_at_ms=row["challenge_accepted_at_ms"],
        completed_at_ms=row["completed_at_ms"],
        system_handle=row["system_handle"],
        history_handle=row["history_handle"],
        generation_config_handle=row["generation_config_handle"],
        output_handle=row["output_handle"],
        containment_evidence_handle=row["containment_evidence_handle"],
        record_handle=row["record_handle"],
        lease_handle=row["lease_handle"],
        execution_receipt_handle=row["execution_receipt_handle"],
        evidence_final_event_hash=row["evidence_final_event_hash"],
        evidence_event_count=row["evidence_event_count"],
        evidence_last_sequence=row["evidence_last_sequence"],
        evidence_head_sequence=row["evidence_head_sequence"],
    )


def load_lease(conn: sqlite3.Connection, execution_attempt_id: str) -> Optional[sqlite3.Row]:
    """The durable lease bindings for an attempt (used to re-return the SAME lease on an
    idempotent ``accept-open`` retry rather than minting a second one)."""
    return conn.execute(
        "SELECT lease_id, execution_attempt_id, lease_issued_at_ms, lease_expires_at_ms, state"
        " FROM governed_turn_acceptance WHERE execution_attempt_id = ?",
        (execution_attempt_id,),
    ).fetchone()


def load_lease_by_nonce(conn: sqlite3.Connection, install_id: str,
                        request_nonce: str) -> Optional[sqlite3.Row]:
    """The durable lease bindings keyed by the accepted ``(install_id, request_nonce)`` —
    the key an idempotent retry collides on."""
    return conn.execute(
        "SELECT lease_id, execution_attempt_id, lease_issued_at_ms, lease_expires_at_ms, state"
        " FROM governed_turn_acceptance WHERE install_id = ? AND request_nonce = ?",
        (install_id, request_nonce),
    ).fetchone()


__all__ = [
    "ACCEPTED_PREPARED", "LEASE_READY", "EXECUTION_STARTING", "EXECUTING", "COMPLETED",
    "BLOCKED", "FAILED", "EXPIRED", "RECOVERY_REQUIRED", "TERMINAL_STATES",
    "LEASE_DURATION_MS", "MIN_LAUNCH_REMAINING_MS",
    "CREATED", "IDEMPOTENT",
    "COMPLETION_FIELDS", "DERIVED_HANDLE_FIELDS", "load_acceptance",
    "AttestationState", "NewAcceptance",
    "Conflict", "Corrupt", "EvidenceFork", "IllegalTransition", "InvalidHead",
    "LedgerError", "NotFound", "StaleEvidence",
    "accept_prepare", "advance", "apply_schema", "canonical_bytes", "gate_and_start",
    "lease_launch_gate", "load_attestation_state", "load_lease", "load_lease_by_nonce",
    "mark_executing", "mark_lease_ready", "open_ledger", "record_completion",
    "reuse_or_prepare", "validate_completion_facts",
]
