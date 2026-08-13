"""``governed_output_streams`` — the durable half of §4.10(f), the ONLY egress.

Every other governed table in this tree guards INGRESS. §4.10(a0) decides which signed
challenge may open a turn, §2.4/§4.10(a)(b)(c) decide which bytes may enter the protected
store, §4.10(d) decides which turn may execute, §5 decides what may be accepted and
completed. This one guards the single path by which anything comes back out: the desktop
never reads the protected store (§4.6 authority rule), so the recorder's captured output
reaches the party that must render it through a chunked PULL served from a row in this
table, and through nothing else.

The token IS the row's identity
-------------------------------
``output_stream_id`` is 32 cryptographically-random bytes, base64url no-pad, exactly 43
characters (§4.10(f)). There is no second "capability token" column: the design defines one
value, and the §4.10(f) request carries one — splitting identity from secret would invent a
field no frame on either hop can supply.

§4.10(f) is honest about what those 256 bits buy, and so is this module. They stop blind
guessing and unrelated callers. They do NOT provide confidentiality against the sidecar,
which is the transport proxy for every turn and therefore necessarily observes every token
and every chunk. Output *authenticity* comes from the isolated signer's envelope digest,
checked by the desktop over the reassembled bytes; this row is not an authority over
content, and nothing here is offered as one.

Why there is no ``state`` column
--------------------------------
§4.10(f): the row is "INSERT-ONCE (immutable after commit; never UPDATEd; only the sweep
DELETEs). Logical state is DERIVED, not stored." The three phases are therefore computed on
every read from ``expires_at_ms`` and row-presence:

  * **Phase 1 — LIVE**: the row is present and ``now_ms <= expires_at_ms``. Serve.
  * **Phase 2 — tombstone**: present but ``now_ms > expires_at_ms`` ⇒ ``stream_expired``.
    No replacement token is ever minted; the same expired id keeps answering the same way.
  * **Phase 3 — swept**: absent (the sweep DELETEd it past ``retained_until_ms``, or the
    quota evicted it) ⇒ ``stream_unknown``.

Storing the phase instead would make the read verdict depend on whether the asynchronous
sweep had run yet, and §4.10(f) requires the opposite in as many words: the verdict is
"SYNCHRONOUS on every read, never dependent on the async sweep". The DDL enforces the
INSERT-ONCE rule with a trigger that aborts *every* UPDATE, so the two timestamps a read is
decided by cannot be moved after commit — a live capability can never be renewed and an
expired one can never be revived.

The boundary is inclusive, in one direction
--------------------------------------------
``now_ms == expires_at_ms`` is **LIVE**; ``expires_at_ms + 1`` is expired (§4.10(f):
"**inclusive boundary**, ``now_ms == expires_at_ms`` LIVE"). The physical sweep uses the
same shape one window later: a row is deletable when ``now_ms > retained_until_ms``.

Prior art, and what is imported rather than re-written
-------------------------------------------------------
``governed_supervisor_ledger`` already owns this database: the connection, the canonical DDL
loader, the ``BEGIN IMMEDIATE`` discipline and the typed error hierarchy. All of it is
imported. ``governed_turn_result`` already owns ``OUTPUT_STREAM_ID_LEN`` and
``MAX_OUTPUT_BYTES``, because §4.10(e) transports the same two facts; they are imported too,
so the capability's length has one definition across the frame that carries it and the table
that binds it.

There WAS a second implementation of this table — ``core/src/governed_output_stream.rs`` —
and it is deleted in the same change that adds this one rather than left beside it. Its
``CREATE TABLE IF NOT EXISTS governed_output_streams`` ran on the same rusqlite connection
one line *before* ``supervisor_ledger::create_schema`` in all four of its call sites, so
keeping it would have made the canonical DDL a silent no-op and its divergent shape the one
that actually existed.

Only the Python standard library is used. Every clock is an injected ``now_ms``.
"""

from __future__ import annotations

import base64
import secrets
import sqlite3
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from governed_supervisor_ledger import (
    Conflict,
    LedgerError,
    _is_lower_sha256_hex,
    _is_u64_ms,
    _Tx,
)
from governed_turn_result import MAX_OUTPUT_BYTES, OUTPUT_STREAM_ID_LEN

# ---------------------------------------------------------------------------
# §4.10(f) lifecycle constants (LOCKED literals)
# ---------------------------------------------------------------------------

#: Logical expiry. §4.10(f) proves it nests inside the desktop's own freshness window:
#: ``now_sup <= completed_at + max_age_ms(300000) + skew(60000) <= created_at + 360000``.
#: A stream that outlived that window could only ever serve bytes the desktop would refuse
#: as stale, so the two bounds are deliberately the same size.
OUTPUT_STREAM_TTL_MS = 360_000

#: The tombstone window: how long an EXPIRED row keeps answering ``stream_expired`` before
#: it is physically removed and starts answering ``stream_unknown``. The distinction is the
#: whole reason a tombstone exists — "your capability aged out" and "no such capability" are
#: different facts, and collapsing them would make a swept row indistinguishable from a
#: forged token.
OUTPUT_STREAM_RETENTION_MS = 360_000

#: How often the physical sweep runs. It is a SCHEDULE, not a correctness input: every read
#: verdict is computed from the row's own timestamps, so a sweep that never ran changes
#: nothing a peer can observe except how much disk is in use.
OUTPUT_STREAM_SWEEP_INTERVAL_MS = 60_000

#: Per-install quota (§4.10(f)). 64 rows and 536870912 bytes = 64 × the 8 MiB output
#: ceiling, so the byte limb binds only when the rows are large and the count limb only when
#: they are small; neither alone would bound the table.
MAX_OUTPUT_STREAMS_PER_INSTALL = 64
MAX_OUTPUT_STREAM_BYTES_PER_INSTALL = 536_870_912

#: Outcomes of :func:`mint_stream`, mirroring ``governed_staging_ledger``'s vocabulary.
CREATED = "created"
IDEMPOTENT = "idempotent"


class StreamConflict(Conflict):
    """A second, DIFFERENT stream for one attempt/receipt.

    Distinct from a plain :class:`Conflict` because the two UNIQUEs here are not a replay
    guard on a peer's message — nothing a peer sends ever reaches this table. A conflict
    means the supervisor tried to bind one attempt's egress to two different outputs, which
    is a supervisor-side fault about its own durable state.
    """


# ---------------------------------------------------------------------------
# The capability
# ---------------------------------------------------------------------------


def mint_output_stream_id() -> str:
    """32 cryptographically-random bytes as 43 base64url characters (§4.10(f)).

    ``secrets`` rather than ``random``: this is an unguessability requirement, and the
    difference between the two modules is exactly whether an observer who has seen previous
    values can predict the next one. 32 bytes encode to ``ceil(32/3)*4 = 44`` base64url
    characters of which the last is padding, so stripping ``=`` yields exactly 43 — the
    length the §4.10(e) frame and the DDL both pin, and the reason neither needs a second
    check on the decoded byte count.
    """
    token = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    if len(token) != OUTPUT_STREAM_ID_LEN:
        # Unreachable arithmetic, named rather than assumed: a minted id of the wrong length
        # would be refused by the DDL CHECK anyway, but it would be refused as a database
        # error rather than as the thing it is.
        raise LedgerError("minted output_stream_id is not %d chars" % OUTPUT_STREAM_ID_LEN)
    return token


@dataclass(frozen=True)
class NewStream:
    """Everything §4.10(f) binds a token to. Every field is SUPERVISOR-DERIVED.

    ``receipt_id`` and ``execution_attempt_id`` come from the acceptance row the supervisor
    minted; ``output_handle`` is the digest the recorder's own evidence chain committed to;
    ``output_bytes`` is the length of the bytes read back out of the content-addressed store
    (which re-verifies ``sha256(bytes) == handle`` as it reads). Nothing here is a value a
    caller sent, which is why there is no validation of a peer's claim anywhere below —
    there is no peer at mint time.

    There is no ``output_sha256`` field: Appendix B's handle matrix says a raw-artifact
    handle IS its digest, so carrying both would be carrying one fact twice and inviting
    them to disagree. The column exists (the design names it) and is written from
    ``output_handle``; the DDL refuses any row where the two differ.
    """

    install_id: str
    receipt_id: str
    execution_attempt_id: str
    output_handle: str
    output_bytes: int


def _validate(new: NewStream) -> None:
    if not isinstance(new, NewStream):
        raise LedgerError("mint_stream requires a NewStream")
    for field in ("install_id", "receipt_id", "execution_attempt_id"):
        value = getattr(new, field)
        if not isinstance(value, str) or not value:
            raise LedgerError("%s must be a non-empty string" % field)
    if not _is_lower_sha256_hex(new.output_handle):
        raise LedgerError("output_handle must be 64 lowercase hex chars")
    if (not isinstance(new.output_bytes, int) or isinstance(new.output_bytes, bool)
            or not (0 <= new.output_bytes <= MAX_OUTPUT_BYTES)):
        raise LedgerError("output_bytes must be an int 0..%d" % MAX_OUTPUT_BYTES)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def load_stream(conn: sqlite3.Connection, output_stream_id: Any) -> Optional[sqlite3.Row]:
    """The row for a token, or ``None``.

    There is deliberately NO type guard on ``output_stream_id``. One was written and then
    deleted: the §4.10(f) protocol layer refuses a non-string as ``malformed`` before this is
    ever reached, so for every value a caller can actually supply the guard returned exactly
    what the query returns anyway. Mutation testing confirmed it — deleting it killed no test
    — which is the definition of a check that reads as protection while protecting nothing.
    """
    return conn.execute(
        "SELECT * FROM governed_output_streams WHERE output_stream_id = ?",
        (output_stream_id,),
    ).fetchone()


def load_stream_for_attempt(conn: sqlite3.Connection,
                            execution_attempt_id: str) -> Optional[sqlite3.Row]:
    """The stream a COMPLETED turn already has, if any — the "re-read, never re-mint" read."""
    return conn.execute(
        "SELECT * FROM governed_output_streams WHERE execution_attempt_id = ?",
        (execution_attempt_id,),
    ).fetchone()


def is_expired(row: Any, now_ms: int) -> bool:
    """Phase 2 test. ``now_ms == expires_at_ms`` is LIVE; ``+1`` is expired (§4.10(f)
    inclusive boundary). Written as ONE function so the read path and the tests cannot
    disagree about which side of the instant the boundary falls on."""
    return now_ms > row["expires_at_ms"]


# ---------------------------------------------------------------------------
# The mint
# ---------------------------------------------------------------------------


def _install_totals(tx: sqlite3.Connection, install_id: str) -> Tuple[int, int]:
    row = tx.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(output_bytes), 0) AS b"
        " FROM governed_output_streams WHERE install_id = ?",
        (install_id,),
    ).fetchone()
    return int(row["n"]), int(row["b"])


def _sweep_install(tx: sqlite3.Connection, install_id: str, now_ms: int) -> int:
    """Delete this install's rows past their retention deadline. §4.10(f) runs this BEFORE
    the quota is counted, so a live turn is never evicted to make room that was already
    free."""
    return tx.execute(
        "DELETE FROM governed_output_streams"
        " WHERE install_id = ? AND ? > retained_until_ms",
        (install_id, now_ms),
    ).rowcount


def _evict_oldest(tx: sqlite3.Connection, install_id: str) -> bool:
    """FIFO-evict one row: the oldest by ``created_at_ms``. False if nothing was left.

    Eviction DELETEs rather than tombstones. §4.10(f) is explicit that an evicted stream
    reads ``stream_unknown`` — "evicted ⇒ ``stream_unknown`` early — never a correctness
    loss, bytes remain" — and a tombstone would say ``stream_expired``, which would be a
    false statement about time.
    """
    return tx.execute(
        "DELETE FROM governed_output_streams WHERE output_stream_id = ("
        "  SELECT output_stream_id FROM governed_output_streams"
        "   WHERE install_id = ? ORDER BY created_at_ms ASC, output_stream_id ASC LIMIT 1)",
        (install_id,),
    ).rowcount > 0


def mint_stream(conn: sqlite3.Connection, new: NewStream, now_ms: int,
                *, mint_id: Any = mint_output_stream_id) -> Tuple[str, sqlite3.Row]:
    """Create this attempt's output stream exactly once. Returns ``(outcome, row)``.

    §4.10(f): "``output_stream_id`` is minted **exactly once** (create-if-absent on
    ``UNIQUE(receipt_id)``/``UNIQUE(execution_attempt_id)``) … and a ``COMPLETED`` retry
    **re-reads, never re-mints** it." So the create-if-absent key is the ATTEMPT, not the
    token: the token is server-generated from 256 bits of entropy and could never collide,
    so a uniqueness rule on it would be a rule about nothing. A retry of the same completion
    finds the existing row and gets :data:`IDEMPOTENT` with the SAME token; a retry naming a
    different output for the same attempt is :class:`StreamConflict`, never a second
    capability over one turn.

    **The quota is enforced by eviction, never by refusal.** §4.10(f): "a completing turn's
    stream is **always** created". A refusal here would mean a genuinely completed, genuinely
    signed turn whose output the desktop could not fetch — a result lost to a resource limit.
    So the order is: sweep this install's retention-expired rows, then FIFO-evict the oldest
    until both limbs of the quota hold, then insert. Evicting someone else's finished stream
    costs at worst a re-run; refusing this one costs the run that just happened.

    ``mint_id`` is injected so a test can pin a token; production takes the default. It is
    NOT a way to choose an id from outside — every caller in this tree uses the default, and
    a supplied id is still bound by the DDL's 43-character CHECK.
    """
    _validate(new)
    if not _is_u64_ms(now_ms):
        raise LedgerError("now_ms must be a u64 epoch-ms int")
    if not callable(mint_id):
        raise LedgerError("mint_id must be callable")

    with _Tx(conn) as tx:
        existing = load_stream_for_attempt(tx, new.execution_attempt_id)
        if existing is not None:
            # The re-read. Every bound value must agree; a completion that reported a
            # different output for an attempt that already has one is not a retry.
            if (existing["install_id"] != new.install_id
                    or existing["receipt_id"] != new.receipt_id
                    or existing["output_handle"] != new.output_handle
                    or existing["output_bytes"] != new.output_bytes):
                raise StreamConflict("output_stream_rebinding")
            return IDEMPOTENT, existing

        _sweep_install(tx, new.install_id, now_ms)
        count, total = _install_totals(tx, new.install_id)
        # THE BYTE LIMB CANNOT BIND FIRST, and that is arithmetic, not an accident.
        # `MAX_OUTPUT_STREAM_BYTES_PER_INSTALL = 536870912 = 64 x MAX_OUTPUT_BYTES`, and the
        # DDL caps every row at `MAX_OUTPUT_BYTES`. So while the count limb is satisfied
        # (`count <= 63`) the sum is at most `63 x 8388608 = 528482304` and `total + new` is
        # at most exactly the cap — never over it. The byte limb is therefore UNREACHABLE
        # while the count limb holds, and it is kept anyway because §4.10(f) states both
        # constants and a supervisor that dropped one would stop matching the design the day
        # either number changed. `test_the_byte_limb_cannot_bind_before_the_count_limb`
        # proves the implication rather than pretending the branch is exercised; two mutants
        # of this line survive for exactly this reason and are reported, not hidden.
        while (count >= MAX_OUTPUT_STREAMS_PER_INSTALL
               or total + new.output_bytes > MAX_OUTPUT_STREAM_BYTES_PER_INSTALL):
            if not _evict_oldest(tx, new.install_id):
                break  # nothing left to evict; one row alone always fits both limbs
            count, total = _install_totals(tx, new.install_id)

        output_stream_id = mint_id()
        try:
            tx.execute(
                "INSERT INTO governed_output_streams ("
                " output_stream_id, install_id, receipt_id, execution_attempt_id,"
                " output_handle, output_bytes, output_sha256, created_at_ms,"
                " expires_at_ms, retained_until_ms) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    output_stream_id, new.install_id, new.receipt_id,
                    new.execution_attempt_id, new.output_handle, new.output_bytes,
                    # Appendix B: a raw-artifact handle IS its digest. Written from the
                    # handle rather than taken as a second argument, so the two can never be
                    # given different values; the DDL refuses the row if they ever are.
                    new.output_handle,
                    now_ms,
                    now_ms + OUTPUT_STREAM_TTL_MS,
                    now_ms + OUTPUT_STREAM_TTL_MS + OUTPUT_STREAM_RETENTION_MS,
                ),
            )
        except sqlite3.IntegrityError as exc:
            # `receipt_id` collided (the attempt did not, or the branch above would have
            # returned), or the FOREIGN KEY refused an attempt this supervisor never
            # accepted. Both are supervisor-state faults; neither may produce a token.
            raise StreamConflict(str(exc))
        row = load_stream_for_attempt(tx, new.execution_attempt_id)
        if row is None:  # pragma: no cover - the INSERT above put it there
            raise LedgerError("output stream vanished immediately after insert")
        return CREATED, row


# ---------------------------------------------------------------------------
# The physical sweep
# ---------------------------------------------------------------------------


def sweep_streams(conn: sqlite3.Connection, now_ms: int) -> int:
    """Phase 2 → Phase 3: DELETE every row past ``retained_until_ms``. Returns the count.

    **It MUST NOT unlink the content-addressed output** (§2.3/§4.10(f)). The bytes at
    ``store/rec/<output_handle>`` are pinned by the terminal governed-turn record and by the
    execution receipt that name that handle, and are collected only by the store's own
    content-addressed GC once nothing references them — so output OUTLIVES its stream row.
    This function touches no filesystem at all, which is the strongest form that promise can
    take: it is not that the sweep declines to unlink, it is that it cannot.

    The sweep is a schedule, not a correctness input. A read of a retention-expired row the
    sweep has not reached yet still answers ``stream_expired`` (Phase 2), because the read
    verdict is derived from ``expires_at_ms`` and not from whether this ran.
    """
    if not _is_u64_ms(now_ms):
        raise LedgerError("now_ms must be a u64 epoch-ms int")
    with _Tx(conn) as tx:
        return tx.execute(
            "DELETE FROM governed_output_streams WHERE ? > retained_until_ms",
            (now_ms,),
        ).rowcount


__all__ = [
    "CREATED",
    "IDEMPOTENT",
    "MAX_OUTPUT_STREAMS_PER_INSTALL",
    "MAX_OUTPUT_STREAM_BYTES_PER_INSTALL",
    "NewStream",
    "OUTPUT_STREAM_RETENTION_MS",
    "OUTPUT_STREAM_SWEEP_INTERVAL_MS",
    "OUTPUT_STREAM_TTL_MS",
    "StreamConflict",
    "is_expired",
    "load_stream",
    "load_stream_for_attempt",
    "mint_output_stream_id",
    "mint_stream",
    "sweep_streams",
]
