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
UNIQUEs, the idempotent re-open, the §2.4 LIVE-row quota count, and — added with
§4.10(a)(b)(c) — the per-artifact upload session, its chunk cursor and its final publish.
The rules that actually FORBID things live in the SQL (the ``state`` CHECKs, the
insert-must-be-empty triggers, the transition triggers, the immutable-binding triggers, the
cursor rule that ties ``byte_count`` to the recorded chunks, and the handle rule that ties a
published input to the challenge's committed digest) — this module drives them and never
substitutes for them, so an illegal transition is refused by the database even if a future
caller bypasses these functions entirely.

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
    IllegalTransition,
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

#: The turn may upload its three declared inputs. This is the state §4.10(a0) leaves behind
#: and the state §4.10(a) requires before it will open a session.
UPLOADING = "UPLOADING"

#: All three inputs published and re-hashed against the challenge's committed digests.
#: Reached only by §4.10(c), and only through the DDL: a trigger refuses the state unless
#: all three handles are set, and another refuses any handle that is not the digest the
#: signed challenge committed to. So the reading §4.10(d) will place on this state is a
#: property of the row rather than a claim about it. §4.10(d) — the message that consumes
#: it — reads exactly that property in ``governed_evidence_request``; it re-derives nothing.
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

#: §2.4 P1-3, LOCKED: "an expired staging row/`session_dir` (now past
#: `challenge_expires_at_ms`) has ZERO retention: it is eligible for unlink the instant it
#: expires, never preserved". Staging holds no post-expiry value and the sweep does not
#: consume the challenge nonce, so nothing is lost by reclaiming it immediately.
EXPIRED_SESSION_RETENTION_MS = 0

#: §2.4 P1-3, LOCKED: the background sweep cadence (plus a startup pass).
STAGING_SWEEP_INTERVAL_MS = 60_000

#: §2.4 P1-3, LOCKED: "fully unlinked (row + `session_dir` + temps) within
#: `2 x STAGING_SWEEP_INTERVAL_MS` of its expiry (one missed-sweep tolerance)". DERIVED from
#: the interval, because the design derives it: a deployment that slows the sweep down and
#: leaves a hand-written deadline behind would be promising an SLA it no longer meets.
STAGING_CLEANUP_DEADLINE_MS = 2 * STAGING_SWEEP_INTERVAL_MS

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


#: The ONE §2.4 liveness predicate, as SQL, with ``?`` bound to ``now_ms``. Both halves of
#: the rule read it: the live count that enforces ``MAX_CONCURRENT_GOVERNED_TURNS``, and —
#: as its exact complement below — the sweep that reclaims what is no longer live. Written
#: once so the two cannot drift into a row that is neither counted nor collected, or one
#: that is both counted and collected.
LIVE_STAGING_PREDICATE_SQL = "challenge_expires_at_ms >= ?"

#: The complement, offset by the LOCKED zero retention: a row is sweepable exactly when it
#: is not live. ``EXPIRED_SESSION_RETENTION_MS`` appears in the SQL rather than being folded
#: away at 0, so a future non-zero retention changes the collected set and NOT the counted
#: one — which is the direction that stays fail-closed.
SWEEPABLE_STAGING_PREDICATE_SQL = (
    "challenge_expires_at_ms + %d < ?" % EXPIRED_SESSION_RETENTION_MS
)


def count_live_turns(conn: sqlite3.Connection, install_id: str, now_ms: int) -> int:
    """The §2.4 LIVE-count rule, exactly: rows whose ``challenge_expires_at_ms >= now_ms``.

    An EXPIRED row is NOT counted "whether or not the sweep has unlinked it". That wording
    is load-bearing — counting rows the sweep has merely not reached yet would let an
    expired (or replayed-expired) challenge pin a concurrency slot for up to
    ``STAGING_CLEANUP_DEADLINE_MS``, which is the P1-3 vector this rule closes.

    §2.4 grants that tolerance to THIS cap and to no other. The session and byte caps count
    what is still on disk (see :func:`count_install_sessions`), and the sweep — not a
    predicate — is what returns their quota.
    """
    if not _is_u64_ms(now_ms):
        raise LedgerError("now_ms must be an epoch-ms int")
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM governed_turn_staging "
        "WHERE install_id = ? AND " + LIVE_STAGING_PREDICATE_SQL,
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


# ---------------------------------------------------------------------------
# §2.4 / §4.10(a)(b)(c) — the per-artifact chunked upload session.
#
# Everything below drives the DDL in `supervisor_ledger.sql` section 6. It is worth
# being explicit about the division, because it is the reason this half is small:
#
#   the DATABASE forbids  — creating a session that is not empty and UPLOADING;
#                           advancing the cursor by anything other than exactly one
#                           recorded chunk; recording a chunk anywhere but AT the
#                           cursor; re-describing a recorded chunk; rebinding a
#                           session's declared contract or its published handle;
#                           recording an input handle that is not the challenge's
#                           committed digest; reaching INPUTS_READY without all three.
#
#   this MODULE does      — take the write lock, read the row, decide, and drive
#                           those edges. It NEVER re-implements them, so a future
#                           writer that skips these functions is refused anyway.
# ---------------------------------------------------------------------------

#: The session is accepting chunks. Created here, and the only state a session may be
#: born in (the DDL insert trigger enforces it, cursor and handle included).
SESSION_UPLOADING = "UPLOADING"

#: The artifact assembled, re-hashed from byte zero and published; `published_handle`
#: is set. Terminal: an identical §4.10(c) retry re-returns the recorded handle.
ARTIFACT_READY = "ARTIFACT_READY"

#: §2.4 P1-4, terminal and fail-closed: a durable chunk file is missing, unreadable, or
#: no longer hashes to its recorded digest. Every later open/chunk/final for this session
#: refuses `session_corrupt`; the supervisor never finalizes, publishes, or advances the
#: turn. Recovery is sweep-only (`sweep_expired_staging`), and the sweep does NOT consume
#: the challenge nonce — so a corrupt session costs the desktop a re-issue, never the turn.
#:
#: What the sweep does NOT do is delete a corrupt session out from under a turn whose
#: challenge is still live, and that is a REFUSAL to choose rather than an omission. §2.4
#: says both "EVERY later `governed-staging-open` (reopen), `-chunk`, and `-final` for that
#: `staging_session_id` ... returns `session_corrupt`" (LOCKED) and, of the recovery, that
#: the sweep "deletes the row ... the desktop then re-issues a fresh staging session against
#: the still-valid signed challenge". A deleted row cannot answer `session_corrupt` — it
#: answers `session_unknown` — so those two sentences cannot both hold for a live challenge.
#: The expiry-driven sweep satisfies the second without breaking the first (an expired
#: challenge has no later messages to answer), and the design owes the difference an answer
#: before anything here reclaims more.
SESSION_CORRUPT = "SESSION_CORRUPT"

#: The closed domain the session `state` column may hold — identical to the SQL CHECK.
ALL_SESSION_STATES = frozenset({SESSION_UPLOADING, ARTIFACT_READY, SESSION_CORRUPT})

#: The three artifacts a sidecar may upload (§2.4). `policy_bundle` is absent by design,
#: not by omission: policy is a supervisor authority, the signed challenge carries no
#: `policy_bundle_sha256` to bind an uploaded one against, and the SQL CHECK holds the
#: same closed set so the refusal survives a caller that never reaches this module.
STAGING_ARTIFACTS = ("system", "history", "generation_config")

#: artifact -> the `governed_turn_staging` column carrying the digest the SIGNED challenge
#: committed to, and the column that records the handle actually published for it.
ARTIFACT_DIGEST_COLUMN = {a: "%s_sha256" % a for a in STAGING_ARTIFACTS}
ARTIFACT_HANDLE_COLUMN = {a: "%s_handle" % a for a in STAGING_ARTIFACTS}

#: §2.4 P1-3/P1-4, LOCKED: 46 = ceil(8 MiB / 184320), the worst case being the
#: `history <= 8 MiB` ceiling. Mirrors the `next_seq <= 46` / `seq <= 45` SQL CHECKs.
MAX_STAGING_CHUNKS = 46

#: §2.4 P1-3: concurrent `governed_turn_staging_session` rows per install, written by the
#: design as "(= 2 turns x 3 artifacts)" and DERIVED from those two here rather than
#: restated as a literal 6. The arithmetic is the rule: one turn may hold one session per
#: artifact (the DDL's `UNIQUE (challenge_handle, artifact)` makes that a database fact),
#: and an install may hold MAX_CONCURRENT_GOVERNED_TURNS turns. A future edit that raises
#: the turn cap or adds a fourth uploadable artifact moves this with it; an edit that moves
#: this alone has to say so in the arithmetic. Over ⇒ `quota_sessions`.
#:
#: It counts EVERY session row of the install, live parent or not — deliberately, and see
#: `sweep_expired_staging`. §2.4 gives the LIVE-count rule to `MAX_CONCURRENT_GOVERNED_TURNS`
#: alone; the session and byte caps are the ones it says the cleanup SLA exists for ("so the
#: per-install byte/file quotas can rely on expired rows being GONE"). They bound DISK, and a
#: session the sweep has not reached still owns its `session_dir`.
MAX_STAGING_SESSIONS_PER_INSTALL = MAX_CONCURRENT_GOVERNED_TURNS * len(STAGING_ARTIFACTS)

#: §2.4 P1-3: total decoded staging bytes per install, 17 MiB = 2 x the 8.5 MiB per-turn
#: request ceiling. Over ⇒ `quota_bytes`.
MAX_STAGING_BYTES_PER_INSTALL = 17825792

#: §2.4 P1-3, derived and asserted rather than separately counted: with the deterministic
#: chunk length, `n_chunks = ceil(declared_len / 184320)`, so the per-artifact ceilings
#: already bound a turn at history 46 + system 2 + generation_config 1 = 49 immutable
#: `<seq>.chunk` files, and an install at 2 x 49 = 98. A separate runtime file count would
#: be a second, weaker statement of the same arithmetic.
MAX_STAGING_FILES_PER_TURN = 49
MAX_STAGING_FILES_PER_INSTALL = 98

#: Refusal reasons this module's quota exception carries, matching §4.10(a)'s closed set.
QUOTA_SESSIONS = "quota_sessions"
QUOTA_BYTES = "quota_bytes"


class SessionQuotaExceeded(LedgerError):
    """A §2.4 per-install session/byte cap would be exceeded.

    Carries the §4.10(a) reason so the protocol layer relays the supervisor's actual
    verdict instead of guessing which cap was hit from a message string.
    """

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


class SessionCorrupt(LedgerError):
    """The session is (or has just become) ``SESSION_CORRUPT`` — §2.4 P1-4, terminal."""


@dataclass(frozen=True)
class NewSession:
    """The §4.10(a) staging-open bindings.

    ``declared_sha256`` is NOT a caller's free choice by the time it reaches here: the
    protocol layer has already required it to equal the digest the signature-verified
    challenge committed to for this artifact. What the caller genuinely chooses is
    ``declared_len``, and that is bounded by the artifact's ceiling before it arrives.
    """

    staging_session_id: str
    challenge_handle: str
    artifact: str
    declared_len: int
    declared_sha256: str
    session_dir: str

    def validate(self) -> None:
        if not _nonempty_str(self.staging_session_id) or len(self.staging_session_id) > 128:
            raise LedgerError("staging_session_id must be a 1..128 char string")
        if not _is_lower_sha256_hex(self.challenge_handle):
            raise LedgerError("session challenge_handle must be lowercase 64-hex")
        if self.artifact not in STAGING_ARTIFACTS:
            raise LedgerError("session artifact %r is not a staging artifact" % (self.artifact,))
        if (not isinstance(self.declared_len, int) or isinstance(self.declared_len, bool)
                or not 0 <= self.declared_len <= 8388608):
            raise LedgerError("declared_len must be an int in 0..8388608")
        if not _is_lower_sha256_hex(self.declared_sha256):
            raise LedgerError("declared_sha256 must be lowercase 64-hex")
        if not _nonempty_str(self.session_dir):
            raise LedgerError("session_dir must be a non-empty string")


# ---------------------------------------------------------------------------
# Session reads
# ---------------------------------------------------------------------------


def load_session(conn: sqlite3.Connection,
                 staging_session_id: str) -> Optional[sqlite3.Row]:
    """The session row, or ``None``. A stored state outside the closed domain is
    :class:`Corrupt` — a row the supervisor cannot interpret is never coerced into the
    state it happens to resemble."""
    row = conn.execute(
        "SELECT * FROM governed_turn_staging_session WHERE staging_session_id = ?",
        (staging_session_id,),
    ).fetchone()
    if row is not None and row["state"] not in ALL_SESSION_STATES:
        raise Corrupt("staging session holds unknown state %r" % (row["state"],))
    return row


def load_session_for_artifact(conn: sqlite3.Connection, challenge_handle: str,
                              artifact: str) -> Optional[sqlite3.Row]:
    """The one session for ``(challenge_handle, artifact)`` — the §2.4 UNIQUE that makes
    "one in-flight session per (tuple, artifact)" a database fact."""
    row = conn.execute(
        "SELECT * FROM governed_turn_staging_session"
        " WHERE challenge_handle = ? AND artifact = ?",
        (challenge_handle, artifact),
    ).fetchone()
    if row is not None and row["state"] not in ALL_SESSION_STATES:
        raise Corrupt("staging session holds unknown state %r" % (row["state"],))
    return row


def count_install_sessions(conn: sqlite3.Connection, install_id: str) -> int:
    """Concurrent sessions for an install, counted THROUGH the parent staging row.

    The session table carries no ``install_id`` of its own — deliberately. §2.4's table
    binds a session to a ``challenge_handle``, and ``challenge_handle`` is UNIQUE on
    ``governed_turn_staging``, so the install is derived from the turn rather than
    re-declared beside it. A second copy of the install id would be a second thing that
    could disagree with the first.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM governed_turn_staging_session s"
        " JOIN governed_turn_staging t ON t.challenge_handle = s.challenge_handle"
        " WHERE t.install_id = ?",
        (install_id,),
    ).fetchone()
    return int(row["n"])


def sum_install_declared_bytes(conn: sqlite3.Connection, install_id: str) -> int:
    """Staging bytes RESERVED by an install's live sessions (§2.4 ``quota_bytes``).

    It sums ``declared_len``, not ``byte_count``. That is the fail-closed reading: a
    compromised sidecar that could open sessions declaring 8 MiB each and be charged only
    for what it had uploaded so far would be able to reserve unbounded disk and then fill
    it. Charging the declaration at open means the cap binds before the bytes arrive.
    """
    row = conn.execute(
        "SELECT COALESCE(SUM(s.declared_len), 0) AS n FROM governed_turn_staging_session s"
        " JOIN governed_turn_staging t ON t.challenge_handle = s.challenge_handle"
        " WHERE t.install_id = ?",
        (install_id,),
    ).fetchone()
    return int(row["n"])


def _session_matches(row: sqlite3.Row, s: NewSession) -> bool:
    """Is this the SAME declared upload? §4.10(a): an identical re-open is idempotent, any
    differing ``declared_len``/``declared_sha256`` is ``retry_conflict``. ``session_dir``
    is excluded on purpose — it is derived from the session id the supervisor minted, so
    it can never differ for a row that matched on everything else."""
    return (
        row["declared_len"] == s.declared_len
        and row["declared_sha256"] == s.declared_sha256
    )


def open_session(conn: sqlite3.Connection, s: NewSession) -> Tuple[str, sqlite3.Row]:
    """CAS the §4.10(a) session row into existence. Returns ``(outcome, row)``.

    ``outcome`` is :data:`CREATED` or :data:`IDEMPOTENT`. On :data:`IDEMPOTENT` the caller
    MUST return the stored ``staging_session_id`` and ``next_seq``, not the ones it just
    minted — a lost reply is retried, and the retry has to reach the same session.

    Order inside the one ``BEGIN IMMEDIATE`` is idempotent-lookup BEFORE quota, the same
    rule §4.10(a0) follows: a retry of a session that already holds a slot must not be
    refused for occupying the slot it already holds.

    Refusals: :class:`SessionCorrupt` (§2.4 P1-4 — a corrupt session is never silently
    re-created or reused), :class:`Conflict` (a differing declaration for the same
    ``(challenge_handle, artifact)``), :class:`SessionQuotaExceeded`.
    """
    if not isinstance(s, NewSession):
        raise LedgerError("open_session requires a NewSession")
    s.validate()

    with _Tx(conn) as tx:
        parent = load_staging_by_handle(tx, s.challenge_handle)
        if parent is None:
            raise NotFound("no staging row for challenge_handle")

        existing = load_session_for_artifact(tx, s.challenge_handle, s.artifact)
        if existing is not None:
            if existing["state"] == SESSION_CORRUPT:
                raise SessionCorrupt("staging session is SESSION_CORRUPT")
            if not _session_matches(existing, s):
                raise Conflict("session for this artifact declares different bytes")
            return IDEMPOTENT, existing

        install_id = parent["install_id"]
        if count_install_sessions(tx, install_id) >= MAX_STAGING_SESSIONS_PER_INSTALL:
            raise SessionQuotaExceeded(
                QUOTA_SESSIONS,
                "install already holds %d staging sessions" % MAX_STAGING_SESSIONS_PER_INSTALL,
            )
        if (sum_install_declared_bytes(tx, install_id) + s.declared_len
                > MAX_STAGING_BYTES_PER_INSTALL):
            raise SessionQuotaExceeded(
                QUOTA_BYTES,
                "install staging bytes would exceed %d" % MAX_STAGING_BYTES_PER_INSTALL,
            )

        try:
            tx.execute(
                "INSERT INTO governed_turn_staging_session ("
                " staging_session_id, challenge_handle, artifact, declared_len,"
                " declared_sha256, next_seq, byte_count, session_dir, state, published_handle)"
                " VALUES (?,?,?,?,?,0,0,?,?,NULL)",
                (s.staging_session_id, s.challenge_handle, s.artifact, s.declared_len,
                 s.declared_sha256, s.session_dir, SESSION_UPLOADING),
            )
        except sqlite3.IntegrityError as exc:
            if _is_unique_violation(exc):
                raise Conflict("staging session CAS lost to a concurrent open: %s" % exc)
            raise

        row = load_session(tx, s.staging_session_id)
        if row is None:
            raise Corrupt("staging session vanished after insert")
        return CREATED, row


# ---------------------------------------------------------------------------
# Chunks
# ---------------------------------------------------------------------------


def load_chunk(conn: sqlite3.Connection, staging_session_id: str,
               seq: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM governed_turn_staging_chunk"
        " WHERE staging_session_id = ? AND seq = ?",
        (staging_session_id, seq),
    ).fetchone()


def record_chunk(conn: sqlite3.Connection, staging_session_id: str, seq: int,
                 chunk_sha256: str, chunk_len: int) -> sqlite3.Row:
    """§2.4 steps 7-11: take the write lock, RE-CHECK the cursor, record the chunk, advance.

    The re-check inside the transaction is the point. Steps 1-6 (validate, hash, write the
    temp, fsync, link the immutable ``<seq>.chunk``, fsync the dir) run outside any lock,
    so a second connection could have advanced the cursor in the meantime. Committing on a
    cursor read before that work would let two senders both believe they filled ``seq``.

    The DDL is the floor under all of it: the INSERT is refused unless ``seq`` IS the
    cursor, and the UPDATE is refused unless it advances by exactly one seq and exactly
    this chunk's recorded length. So even a caller that skipped this function cannot
    produce a cursor that outruns the bytes on disk.
    """
    if not _is_lower_sha256_hex(chunk_sha256):
        raise LedgerError("chunk_sha256 must be lowercase 64-hex")
    if not isinstance(chunk_len, int) or isinstance(chunk_len, bool) or chunk_len < 1:
        raise LedgerError("chunk_len must be a positive int")

    with _Tx(conn) as tx:
        row = load_session(tx, staging_session_id)
        if row is None:
            raise NotFound("no such staging session")
        if row["state"] == SESSION_CORRUPT:
            raise SessionCorrupt("staging session is SESSION_CORRUPT")
        if row["state"] != SESSION_UPLOADING:
            raise IllegalTransition(row["state"], SESSION_UPLOADING)
        if row["next_seq"] != seq:
            raise Conflict("cursor moved to %d under seq %d" % (row["next_seq"], seq))

        try:
            tx.execute(
                "INSERT INTO governed_turn_staging_chunk"
                " (staging_session_id, seq, chunk_sha256, chunk_len) VALUES (?,?,?,?)",
                (staging_session_id, seq, chunk_sha256, chunk_len),
            )
        except sqlite3.IntegrityError as exc:
            # The cursor re-check above should have caught every reachable case; if the DDL
            # still refuses, the two disagree and the ledger is not in a state this code
            # understands. Typed as Corrupt rather than left as a raw `sqlite3.IntegrityError`
            # because nothing above this layer catches that type — it would escape the front
            # door entirely instead of becoming a fail-closed reply.
            raise Corrupt("ledger refused a chunk the cursor check admitted: %s" % exc)
        updated = tx.execute(
            "UPDATE governed_turn_staging_session"
            " SET next_seq = ?, byte_count = ?"
            " WHERE staging_session_id = ? AND next_seq = ?",
            (seq + 1, row["byte_count"] + chunk_len, staging_session_id, seq),
        ).rowcount
        if updated != 1:
            raise Corrupt("staging session vanished between chunk insert and advance")

        advanced = load_session(tx, staging_session_id)
        if advanced is None:
            raise Corrupt("staging session vanished after advance")
        return advanced


def mark_session_corrupt(conn: sqlite3.Connection, staging_session_id: str) -> None:
    """Drive UPLOADING -> SESSION_CORRUPT (§2.4 recovery rule b). Terminal and idempotent:
    a session already corrupt stays corrupt, and the DDL refuses any edge back out."""
    with _Tx(conn) as tx:
        row = load_session(tx, staging_session_id)
        if row is None:
            raise NotFound("no such staging session")
        if row["state"] == SESSION_CORRUPT:
            return
        tx.execute(
            "UPDATE governed_turn_staging_session SET state = ?"
            " WHERE staging_session_id = ?",
            (SESSION_CORRUPT, staging_session_id),
        )


# ---------------------------------------------------------------------------
# Final publish
# ---------------------------------------------------------------------------


def finalize_session(conn: sqlite3.Connection, staging_session_id: str, handle: str,
                     now_ms: int) -> Tuple[sqlite3.Row, bool]:
    """§4.10(c): record the published handle on the session AND on the turn, in ONE
    transaction, and advance the turn to ``INPUTS_READY`` when all three are in.

    Returns ``(session_row, inputs_ready)``.

    Two DDL rules do the load-bearing work and are relied on rather than restated: the
    handle written onto the staging row must EQUAL the digest the signed challenge
    committed to for that artifact, and ``INPUTS_READY`` cannot be reached until all three
    handles are set. So the state §4.10(d) reads as "every declared input exists and
    re-hashes to the challenge's committed digest" is true of the row by construction, not
    because this function was careful.
    """
    if not _is_lower_sha256_hex(handle):
        raise LedgerError("published handle must be lowercase 64-hex")
    if not _is_u64_ms(now_ms):
        raise LedgerError("now_ms must be an epoch-ms int")

    with _Tx(conn) as tx:
        row = load_session(tx, staging_session_id)
        if row is None:
            raise NotFound("no such staging session")
        if row["state"] == SESSION_CORRUPT:
            raise SessionCorrupt("staging session is SESSION_CORRUPT")
        if row["state"] != SESSION_UPLOADING:
            raise IllegalTransition(row["state"], SESSION_UPLOADING)

        artifact = row["artifact"]
        handle_column = ARTIFACT_HANDLE_COLUMN[artifact]

        tx.execute(
            "UPDATE governed_turn_staging_session"
            " SET published_handle = ?, state = ?"
            " WHERE staging_session_id = ? AND state = ?",
            (handle, ARTIFACT_READY, staging_session_id, SESSION_UPLOADING),
        )
        # The column name comes from a fixed dict keyed by the CHECK-constrained
        # `artifact` value, never from anything a caller wrote.
        tx.execute(
            "UPDATE governed_turn_staging SET %s = ?, updated_at_ms = ?"
            " WHERE challenge_handle = ?" % handle_column,
            (handle, now_ms, row["challenge_handle"]),
        )

        turn = load_staging_by_handle(tx, row["challenge_handle"])
        if turn is None:
            raise Corrupt("staging row vanished under its own session")
        inputs_ready = all(
            turn[ARTIFACT_HANDLE_COLUMN[a]] is not None for a in STAGING_ARTIFACTS
        )
        if inputs_ready and turn["state"] == UPLOADING:
            tx.execute(
                "UPDATE governed_turn_staging SET state = ?, updated_at_ms = ?"
                " WHERE challenge_handle = ? AND state = ?",
                (INPUTS_READY, now_ms, row["challenge_handle"], UPLOADING),
            )

        final = load_session(tx, staging_session_id)
        if final is None:
            raise Corrupt("staging session vanished after finalize")
        return final, inputs_ready


# ---------------------------------------------------------------------------
# The §2.4 sweep — the ONLY DELETE in this module
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SweptStaging:
    """What one sweep pass removed from the ledger, and what the caller must now unlink.

    ``session_dirs`` is the whole point of returning anything: the rows are gone by the time
    this is handed back, so the directories they named would be unreachable if they were not
    carried out of the transaction.
    """

    turns: Tuple[str, ...]
    sessions: Tuple[str, ...]
    session_dirs: Tuple[str, ...]

    @property
    def rows_deleted(self) -> int:
        return len(self.turns)


def sweep_expired_staging(conn: sqlite3.Connection, now_ms: int) -> SweptStaging:
    """§2.4's sweep, ledger half: DELETE every staging row past its challenge's expiry.

    §2.4 specifies this sweep and names everything about it — the trigger ("a
    ``STAGING_SWEEP_INTERVAL_MS = 60000`` background sweep (plus a startup pass)"), the
    subject ("orphan ``.tmp-*.part`` + the whole ``session_dir``", "deletes expired/abandoned
    staging rows"), the retention (``EXPIRED_SESSION_RETENTION_MS = 0``), the completion SLA
    (``STAGING_CLEANUP_DEADLINE_MS``), and the one thing it may NOT do: it reclaims
    "**WITHOUT consuming the challenge nonce** — the desktop may re-issue against the same
    signed challenge until the challenge itself expires (this denies the sidecar a
    nonce-burning DoS)".

    That last promise is kept structurally rather than carefully. The challenge nonce lives
    in the challenge authority's own protected store, behind its own principal and its own
    channel; this module has no handle on it, imports nothing that does, and could not
    consume one if it tried. What the DELETE frees here is the ``UNIQUE (install_id,
    request_nonce)`` slot in the SUPERVISOR's staging table — which is what "may re-issue"
    means for this table.

    Nor does it touch the published bytes. Every artifact an ``ARTIFACT_READY`` session
    published is in the content-addressed store under a handle the challenge committed to,
    and a turn that reached ``INPUTS_READY`` has been read by §4.10(d) into an acceptance row
    that outlives staging entirely. This function performs no filesystem operation at all —
    the same shape ``governed_output_stream.sweep_streams`` takes, for the same reason: it is
    not that the sweep declines to unlink the store, it is that it cannot.

    **What may be deleted, exactly:** rows matching
    :data:`SWEEPABLE_STAGING_PREDICATE_SQL`, the complement of the live predicate the
    concurrency cap reads. A LIVE turn is never swept, however long it has sat there, and a
    caller that wants something else gone cannot ask for it — the predicate is in the SQL,
    not in an argument. Sessions and chunks follow through the DDL's ``ON DELETE CASCADE``;
    deleting them with separate statements would be a second statement of the same rule, and
    one that could disagree with the first.

    **Order, and what a crash between the halves leaves:** the rows commit here FIRST and the
    directories are unlinked afterwards by the filesystem half, so an interrupted sweep leaves
    a ``session_dir`` with no row — an orphan the next pass collects. The other order would
    leave a ROW whose immutable chunks are missing, which the §2.4 restart-recovery rule (b)
    must read as ``SESSION_CORRUPT``: a fail-closed state, but a worse one to manufacture on
    purpose.

    Returns what was removed. A pass that removed nothing returns empty tuples rather than
    ``None``: "nothing was expired" and "the sweep did not run" must not look alike.
    """
    if not _is_u64_ms(now_ms):
        raise LedgerError("now_ms must be an epoch-ms int")

    # The cascade is this sweep's entire mechanism for sessions and chunks, and SQLite
    # enforces foreign keys only when the pragma is on — `apply_schema` sets it, but it is
    # per-CONNECTION, so a caller that opened the ledger some other way would silently orphan
    # every session it swept. Checked before the transaction and refused rather than worked
    # around: an orphan session keeps its directory AND drops out of `count_install_sessions`
    # (which counts THROUGH the parent), and that is this fail-closed cap failing open.
    enabled = conn.execute("PRAGMA foreign_keys").fetchone()
    if not enabled or not int(enabled[0]):
        raise Corrupt(
            "staging sweep requires PRAGMA foreign_keys = ON: without the cascade it would "
            "orphan sessions instead of collecting them"
        )

    with _Tx(conn) as tx:
        doomed = tx.execute(
            "SELECT challenge_handle FROM governed_turn_staging WHERE "
            + SWEEPABLE_STAGING_PREDICATE_SQL,
            (now_ms,),
        ).fetchall()
        sessions = tx.execute(
            "SELECT s.staging_session_id AS id, s.session_dir AS dir"
            " FROM governed_turn_staging_session s"
            " JOIN governed_turn_staging t ON t.challenge_handle = s.challenge_handle"
            " WHERE t." + SWEEPABLE_STAGING_PREDICATE_SQL,
            (now_ms,),
        ).fetchall()
        deleted = tx.execute(
            "DELETE FROM governed_turn_staging WHERE " + SWEEPABLE_STAGING_PREDICATE_SQL,
            (now_ms,),
        ).rowcount
        if deleted != len(doomed):
            raise Corrupt(
                "staging sweep deleted %d rows for the %d it selected" % (deleted, len(doomed))
            )
        orphans = tx.execute(
            "SELECT COUNT(*) AS n FROM governed_turn_staging_session s"
            " LEFT JOIN governed_turn_staging t ON t.challenge_handle = s.challenge_handle"
            " WHERE t.challenge_handle IS NULL"
        ).fetchone()
        if int(orphans["n"]):
            # Unreachable while the FK and its cascade are in the DDL, and asserted anyway:
            # this is the exact state in which the quota count would report less than the
            # disk actually holds.
            raise Corrupt(
                "staging sweep left %d parentless session rows behind" % int(orphans["n"])
            )

    return SweptStaging(
        turns=tuple(row["challenge_handle"] for row in doomed),
        sessions=tuple(row["id"] for row in sessions),
        session_dirs=tuple(row["dir"] for row in sessions),
    )


__all__ = [
    "ALL_SESSION_STATES",
    "ALL_STAGING_STATES",
    "ARTIFACT_DIGEST_COLUMN",
    "ARTIFACT_HANDLE_COLUMN",
    "ARTIFACT_READY",
    "CREATED",
    "EXPIRED_SESSION_RETENTION_MS",
    "IDEMPOTENT",
    "INPUTS_READY",
    "LIVE_STAGING_PREDICATE_SQL",
    "MAX_CONCURRENT_GOVERNED_TURNS",
    "MAX_STAGING_BYTES_PER_INSTALL",
    "MAX_STAGING_CHUNKS",
    "MAX_STAGING_FILES_PER_INSTALL",
    "MAX_STAGING_FILES_PER_TURN",
    "MAX_STAGING_SESSIONS_PER_INSTALL",
    "NewSession",
    "NewStaging",
    "QUOTA_BYTES",
    "QUOTA_SESSIONS",
    "QUOTA_TURNS",
    "SESSION_CORRUPT",
    "SESSION_UPLOADING",
    "STAGING_ARTIFACTS",
    "STAGING_CLEANUP_DEADLINE_MS",
    "STAGING_SWEEP_INTERVAL_MS",
    "SWEEPABLE_STAGING_PREDICATE_SQL",
    "SessionCorrupt",
    "SessionQuotaExceeded",
    "StagingQuotaExceeded",
    "SweptStaging",
    "UPLOADING",
    "VERIFYING",
    "apply_schema",
    "count_install_sessions",
    "count_live_turns",
    "finalize_session",
    "load_chunk",
    "load_session",
    "load_session_for_artifact",
    "load_staging",
    "load_staging_by_handle",
    "mark_session_corrupt",
    "open_ledger",
    "open_session",
    "open_staging",
    "record_chunk",
    "sum_install_declared_bytes",
    "sweep_expired_staging",
]
