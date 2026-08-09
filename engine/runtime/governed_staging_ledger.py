"""Durable PRE-ACCEPT staging state — rev-30 §2.4, created by §4.10(a0).

What this is, and what it deliberately is NOT
---------------------------------------------
``governed_turn_staging`` records that a signed challenge was OPENED: the supervisor
verified it, published its exact bytes, and admitted the turn to upload its three declared
inputs. That is the entire grant. The row carries **no ``execution_attempt_id``, no lease,
no execution right** — §2.4 is explicit — and the table has no column for one, so the P1-5
defect (a requester minting the id the supervisor must mint) has nowhere to land even if
the wire shape were ever loosened.

It is a SEPARATE table from ``governed_turn_acceptance`` for a reason §2.4 states directly:
staging is gated by the verified signed challenge, **not** by an acceptance row — which at
open time does not, and must not, yet exist. Gating staging on acceptance would deadlock
(acceptance needs ``INPUTS_READY``, ``INPUTS_READY`` needs the uploads, the uploads need
staging); gating acceptance on staging is the correct direction and is §5's job, not this
module's.

Prior art, and why nothing here is a second copy of it
------------------------------------------------------
``governed_supervisor_ledger`` already owns this ledger: the connection, the shared DDL,
the ``BEGIN IMMEDIATE`` discipline, the UNIQUE-violation classification and the typed error
hierarchy. **All of that is imported, not re-written.** Both tables live in the ONE
supervisor-owned 0700 SQLite file described by
``engine/runtime/supervisor_ledger.sql`` — the file whose header calls itself "the single
normative source for the governed-supervisor's durable state" — so opening a ledger with
``governed_supervisor_ledger.open_ledger`` creates the staging table too, and there is no
second schema, second connection, or second CAS engine to keep in step.

What this module adds is the staging-specific CAS: create-if-absent keyed on the two §2.4
UNIQUEs, the idempotent re-open, and the §2.4 LIVE-row quota count. The rules that actually
FORBID things live in the SQL (the ``state`` CHECK, the insert-must-be-``VERIFYING``
trigger, the transition trigger, the immutable-binding trigger) — this module drives them
and never substitutes for them, so an illegal transition is refused by the database even if
a future caller bypasses these functions entirely.

Only the Python standard library is used. Every clock is an injected ``now_ms``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Optional, Tuple

# The ONE ledger implementation. Connection, schema, transaction discipline and error
# taxonomy are reused verbatim; re-implementing any of them here is precisely the
# duplication the repository's prior-art rule exists to stop.
from governed_supervisor_ledger import (  # noqa: F401  (re-exported deliberately)
    Conflict,
    Corrupt,
    LedgerError,
    NotFound,
    _is_lower_sha256_hex,
    _is_u64_ms,
    _is_unique_violation,
    _nonempty_str,
    _Tx,
    apply_schema,
    open_ledger,
)

# ---------------------------------------------------------------------------
# The closed §2.4 staging lifecycle (mirrors the SQL CHECK domain exactly).
# ---------------------------------------------------------------------------

#: Transient, and committed only inside §4.10(a0): the supervisor has verified the
#: challenge and is creating the row. It is a real stored value for the width of one
#: transaction so that UPLOADING is REACHED through the trigger-checked edge rather than
#: declared at INSERT.
VERIFYING = "VERIFYING"

#: The turn may upload its three declared inputs. This is the state §4.10(a0) leaves behind,
#: and it is where the turn STOPS today: the upload protocols §4.10(a) / §4.10(b) / §4.10(c)
#: are NOT IMPLEMENTED — separate ordered pieces, no code in this tree serves them.
UPLOADING = "UPLOADING"

#: All three inputs published and re-hashed against the challenge's committed digests. It is
#: reached only by §4.10(c), which is NOT IMPLEMENTED, so nothing in this tree currently sets
#: it — the state exists in the closed domain because the DB must be able to refuse an
#: illegal path INTO it long before anything is allowed to take the legal one.
INPUTS_READY = "INPUTS_READY"

#: The closed domain the ``state`` column may hold — identical to the SQL CHECK. A stored
#: value outside it means a corrupt or foreign DB and is refused, never interpreted.
ALL_STAGING_STATES = frozenset({VERIFYING, UPLOADING, INPUTS_READY})

# ---------------------------------------------------------------------------
# §2.4 quota constants (P1-3, LOCKED literals — not prose).
# ---------------------------------------------------------------------------

#: LIVE ``governed_turn_staging`` rows per install (matches the desktop's
#: ``MAX_CONCURRENT_GENERATIONS = 2``). A 3rd LIVE row on open ⇒ ``quota_turns``.
MAX_CONCURRENT_GOVERNED_TURNS = 2

# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------

CREATED = "created"
IDEMPOTENT = "idempotent"

#: A 3rd concurrent LIVE row for this install. Surfaced by §4.10(a0) as ``quota_turns``.
QUOTA_TURNS = "quota_turns"


class StagingQuotaExceeded(LedgerError):
    """The §2.4 per-install LIVE-row cap would be exceeded. A refusal, not an error: the
    supervisor records nothing and admits nothing."""


@dataclass(frozen=True)
class NewStaging:
    """The staging bindings, every one of them copied out of the SIGNATURE-VERIFIED §4.1
    challenge payload (or, for ``challenge_handle``, computed by the supervisor from the
    exact document bytes it decoded).

    There is no field here a caller chose. That is the point: the row is a statement about
    a document the supervisor authenticated, not a record of what a peer asked for.
    """

    install_id: str
    request_nonce: str
    challenge_handle: str
    run_id: str
    task_id: str
    workspace_id: str
    system_sha256: str
    history_sha256: str
    generation_config_sha256: str
    challenge_expires_at_ms: int

    def validate(self) -> None:
        for field in ("install_id", "request_nonce", "run_id", "task_id", "workspace_id"):
            if not _nonempty_str(getattr(self, field)):
                raise LedgerError("staging %s must be a non-empty string" % field)
        for field in ("challenge_handle", "system_sha256", "history_sha256",
                      "generation_config_sha256"):
            if not _is_lower_sha256_hex(getattr(self, field)):
                raise LedgerError("staging %s must be lowercase 64-hex" % field)
        if not _is_u64_ms(self.challenge_expires_at_ms):
            raise LedgerError("staging challenge_expires_at_ms must be an epoch-ms int")


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def load_staging(conn: sqlite3.Connection, install_id: str,
                 request_nonce: str) -> Optional[sqlite3.Row]:
    """The staging row for ``(install_id, request_nonce)``, or ``None``.

    A stored ``state`` outside the closed domain is :class:`Corrupt`, never coerced: a row
    the supervisor cannot interpret must not be treated as one of the states it happens to
    resemble.
    """
    row = conn.execute(
        "SELECT * FROM governed_turn_staging WHERE install_id = ? AND request_nonce = ?",
        (install_id, request_nonce),
    ).fetchone()
    if row is not None and row["state"] not in ALL_STAGING_STATES:
        raise Corrupt("staging row holds unknown state %r" % (row["state"],))
    return row


def load_staging_by_handle(conn: sqlite3.Connection,
                           challenge_handle: str) -> Optional[sqlite3.Row]:
    """The staging row for a ``challenge_handle``, or ``None`` (the second §2.4 UNIQUE)."""
    row = conn.execute(
        "SELECT * FROM governed_turn_staging WHERE challenge_handle = ?",
        (challenge_handle,),
    ).fetchone()
    if row is not None and row["state"] not in ALL_STAGING_STATES:
        raise Corrupt("staging row holds unknown state %r" % (row["state"],))
    return row


def count_live_turns(conn: sqlite3.Connection, install_id: str, now_ms: int) -> int:
    """The §2.4 LIVE-count rule, exactly: rows whose ``challenge_expires_at_ms >= now_ms``.

    An EXPIRED row is NOT counted "whether or not the sweep has unlinked it". That wording
    is load-bearing — counting rows the sweep has merely not reached yet would let an
    expired (or replayed-expired) challenge pin a concurrency slot for up to
    ``STAGING_CLEANUP_DEADLINE_MS``, which is the P1-3 vector this rule closes.
    """
    if not _is_u64_ms(now_ms):
        raise LedgerError("now_ms must be an epoch-ms int")
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM governed_turn_staging "
        "WHERE install_id = ? AND challenge_expires_at_ms >= ?",
        (install_id, now_ms),
    ).fetchone()
    return int(row["n"])


# ---------------------------------------------------------------------------
# The CAS: absent -> VERIFYING -> UPLOADING, in ONE transaction
# ---------------------------------------------------------------------------


def _matches(row: sqlite3.Row, s: NewStaging) -> bool:
    """Is this stored row the SAME turn as ``s``?

    Every identity column is compared, not just the handle. A row that agrees on the
    challenge handle but disagrees on, say, ``task_id`` is not an idempotent retry — it is
    two different turns claiming one slot, and the caller must hear ``retry_conflict``.
    """
    return (
        row["challenge_handle"] == s.challenge_handle
        and row["run_id"] == s.run_id
        and row["task_id"] == s.task_id
        and row["workspace_id"] == s.workspace_id
        and row["system_sha256"] == s.system_sha256
        and row["history_sha256"] == s.history_sha256
        and row["generation_config_sha256"] == s.generation_config_sha256
        and row["challenge_expires_at_ms"] == s.challenge_expires_at_ms
    )


def open_staging(conn: sqlite3.Connection, s: NewStaging,
                 now_ms: int) -> Tuple[str, sqlite3.Row]:
    """CAS the §4.10(a0) staging row into existence. Returns ``(outcome, row)``.

    ``outcome`` is :data:`CREATED` (this call made the row) or :data:`IDEMPOTENT` (it was
    already there for this exact turn — a lost reply, safely retried).

    The whole decision owns one ``BEGIN IMMEDIATE``, so the lookup, the quota count and the
    insert cannot be interleaved by a second supervisor process. Order inside the
    transaction is **idempotent-lookup BEFORE quota** (the §2.1.1 rule, applied here for the
    same reason): a retry of a turn that already holds a slot must not be refused for
    occupying the slot it already holds.

    Refusals:
      * :class:`Conflict` — a different challenge under this ``(install_id, request_nonce)``,
        or this challenge already staged under a different nonce/install. Both are the two
        §2.4 UNIQUEs speaking, and both surface as ``retry_conflict``.
      * :class:`StagingQuotaExceeded` — a 3rd LIVE row for the install.

    The row is INSERTed ``VERIFYING`` and advanced to ``UPLOADING`` in the same transaction.
    That is not ceremony: the DDL forbids creating a row in any other state, so ``UPLOADING``
    can only be REACHED across the trigger-checked edge. Nothing can declare its way past
    the lifecycle, here or anywhere else that ever writes this table.
    """
    if not isinstance(s, NewStaging):
        raise LedgerError("open_staging requires a NewStaging")
    s.validate()
    if not _is_u64_ms(now_ms):
        raise LedgerError("now_ms must be an epoch-ms int")

    with _Tx(conn) as tx:
        existing = load_staging(tx, s.install_id, s.request_nonce)
        if existing is not None:
            if not _matches(existing, s):
                raise Conflict(
                    "staging row for (install_id, request_nonce) is bound to a different challenge"
                )
            return IDEMPOTENT, existing

        # The same challenge document under a DIFFERENT nonce or install is a replay
        # wearing a new label. UNIQUE(challenge_handle) would catch it at INSERT anyway;
        # naming it here makes the verdict a typed conflict instead of a raw constraint.
        by_handle = load_staging_by_handle(tx, s.challenge_handle)
        if by_handle is not None:
            raise Conflict("challenge_handle is already staged under a different turn")

        if count_live_turns(tx, s.install_id, now_ms) >= MAX_CONCURRENT_GOVERNED_TURNS:
            raise StagingQuotaExceeded(
                "install already holds %d live staging rows"
                % MAX_CONCURRENT_GOVERNED_TURNS
            )

        try:
            tx.execute(
                "INSERT INTO governed_turn_staging ("
                " install_id, request_nonce, challenge_handle, run_id, task_id, workspace_id,"
                " system_sha256, history_sha256, generation_config_sha256,"
                " system_handle, history_handle, generation_config_handle,"
                " state, challenge_expires_at_ms, created_at_ms, updated_at_ms)"
                " VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,?,?,?,?)",
                (
                    s.install_id, s.request_nonce, s.challenge_handle, s.run_id, s.task_id,
                    s.workspace_id, s.system_sha256, s.history_sha256,
                    s.generation_config_sha256, VERIFYING, s.challenge_expires_at_ms,
                    now_ms, now_ms,
                ),
            )
        except sqlite3.IntegrityError as exc:
            if _is_unique_violation(exc):
                raise Conflict("staging CAS lost to a concurrent open: %s" % exc)
            raise

        # VERIFYING -> UPLOADING across the trigger-checked edge, same transaction. The
        # guard in the WHERE clause is the code-side half; the trigger is the DB-side half
        # that holds even for a writer that never calls this function.
        updated = tx.execute(
            "UPDATE governed_turn_staging SET state = ?, updated_at_ms = ?"
            " WHERE install_id = ? AND request_nonce = ? AND state = ?",
            (UPLOADING, now_ms, s.install_id, s.request_nonce, VERIFYING),
        ).rowcount
        if updated != 1:
            raise Corrupt("staging row vanished between insert and advance")

        row = load_staging(tx, s.install_id, s.request_nonce)
        if row is None:
            raise Corrupt("staging row vanished after advance")
        return CREATED, row


__all__ = [
    "ALL_STAGING_STATES",
    "CREATED",
    "IDEMPOTENT",
    "INPUTS_READY",
    "MAX_CONCURRENT_GOVERNED_TURNS",
    "NewStaging",
    "QUOTA_TURNS",
    "StagingQuotaExceeded",
    "UPLOADING",
    "VERIFYING",
    "apply_schema",
    "count_live_turns",
    "load_staging",
    "load_staging_by_handle",
    "open_ledger",
    "open_staging",
]
