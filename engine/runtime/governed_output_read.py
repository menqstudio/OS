"""``brops.governed-turn-output-read.v1`` — the §4.10(f) supervisor hop of the output PULL.

This is the ONLY egress. §4.6 forbids the desktop from reading the protected store and
forbids the output from riding inline in the result frame (a full-schema inline frame
provably overflows ``MAX_FRAME_BYTES``), so the exact bytes the recorder captured reach the
party that must render them through this request/response loop and through nothing else.

The shape of the whole mechanism follows from one transport fact §4.10(f) states up front:
the real ``brops_socket`` is one-request/one-response and the supervisor is a pure
responder. There is no push. The desktop DRIVES a loop, one chunk per round trip, and every
read is idempotent — the same ``seq`` always returns the same byte range, so a lost reply is
retried rather than resumed, and no cursor is consumed.

What this module is, and the line it does not cross
----------------------------------------------------
It serves one read. It mints nothing, signs nothing, writes no row, reads no clock of its
own (``now_ms`` is injected by the front door, as everywhere else in this family), and takes
no decision about whether a turn succeeded — by the time a token exists the turn is over and
§5 has already recorded its verdict.

It is emphatically **not an authority over the bytes**. §4.6/§7.1 put that authority in the
isolated signer's envelope: the desktop asserts ``len(reassembled) == envelope.output_bytes``
**and** ``SHA256(reassembled) == envelope.output_sha256`` over the raw bytes before any
normalization, so a tampered, re-ordered, dropped, truncated or cross-turn chunk fails the
whole-output digest and Blocks. Everything below is therefore a *resource* gate — who may
ask, for which stream, in which window, for which range — and the module says so rather than
implying an integrity guarantee it does not provide.

The verdict order is the design's, and the order is observable
---------------------------------------------------------------
§4.10(f) LOCKS it: row **absent** ⇒ ``stream_unknown``; ``now_ms > expires_at_ms`` ⇒
``stream_expired``; the row's ``receipt_id`` OR ``execution_attempt_id`` ≠ the request's ⇒
``stream_binding_mismatch``; ``seq`` out of range ⇒ ``seq_out_of_range``; only on a full
3-tuple match does it serve.

Expiry is checked **before** binding, and that is a real choice with a visible consequence:
an expired stream presented with the WRONG ``receipt_id`` answers ``stream_expired``, not
``stream_binding_mismatch``. The design fixes this order in both places it states it, and
the reason it is the right way round is that the later answer is the more informative one —
a caller who learns "binding mismatch" learns that the token it holds is live and belongs to
somebody, which is precisely what an unauthorized holder would like to know.

``stream_binding_mismatch`` is the server-side half of the capability
----------------------------------------------------------------------
§4.10(f) P1-3: "the supervisor requires the client to present ``receipt_id`` +
``execution_attempt_id`` alongside the token and compares all three against the row before
serving — so a *valid* token from a different receipt/attempt is caught **server-side**, not
merely by the desktop's final digest." The desktop sources those two values from the
**verified signed envelope**, so they are authenticated values rather than transport claims;
a sidecar that swapped in another turn's token would have to also produce that turn's
envelope, which it cannot sign.

The 256-bit token buys unguessability and nothing more, and §4.10(f) says so in writing: it
does NOT provide confidentiality against the compromised sidecar, which — being the proxy
for every turn — necessarily observes every token and every chunk. End-to-end output
encryption is a separate future contract and is not in 3b-1B.

The arithmetic, done first, and the check it does and does not justify
------------------------------------------------------------------------
Unlike §4.10(a)/(c)/(d)/(e), whose largest legal frames are a few hundred bytes to 74 KiB
against a 262144 cap, a §4.10(f) **reply** is genuinely large: it carries a 184320-byte chunk
as 245760 base64url characters. The literal maximum is

    ``{"protocol":"brops.governed-turn-output-read-result.v1"``  55
    ``,"ok":true``                                               10
    ``,"output_stream_id":"<43>"``                               65
    ``,"seq":44``                                                 9   (two digits, 0..45)
    ``,"bytes_b64":"<245760>"``                              245775
    ``,"eof":false``                                             12   (the LONGER arm)
    ``,"error":null}``                                           13
                                                            --------
                                                              245939 + 1 (`{`) = **245940**

against ``MAX_FRAME_BYTES = 262144`` — **16204 bytes of headroom**, versus §4.10(e)'s 187672.
``test_the_literal_maximum_reply_frame_fits`` CONSTRUCTS that instance and asserts the number
rather than leaving it as a comment, and a second test shows that a 262144-byte chunk would
encode to ``4·⌈262144/3⌉ = 349528`` and overflow — the §2.4 regression, restated for the
egress direction because the two chunk sizes are separate clauses about separate protocols.

So where IS a size check load-bearing here? On the **chunk**, not on the frame. The served
range is ``output[seq·184320 : (seq+1)·184320]``, which is ≤ 184320 by construction, and the
builder re-asserts it — that assertion is what the frame arithmetic above rests on, so if the
chunk constant were ever raised the failure would be named here instead of surfacing as a
transport error three layers away. A *frame* check on the reply could never fire on a legal
instance, and a *request*-side frame cap could not fire either: §4.10(f) declares the request
frame at ``MAX_FRAME_BYTES``, which is exactly the transport read bound, so an entry in the
front door's cap table would be an entry that is never consulted. The largest request this
shape accepts is **421 bytes**. Both omissions follow the precedent set when a §4.10(a)/(c)
handler cap that could never fire was deleted rather than shipped.

**The one size fix that WAS load-bearing is not in this file.** The supervisor front door
wrote every reply through ``write_frame(conn, …)`` at its own 8192-byte default while the
sidecar's READ bound had been widened to 262144. Every sidecar reply until now was a few
hundred bytes, so nothing noticed; a 245940-byte chunk would have been refused by the
supervisor's own writer and degraded to ``{"ok":false,"error":"reply exceeded frame bound"}``
— not a §4.10(f) frame at all, and a pull that could never complete. ``handle_connection``
now writes with the same bound it reads with.

A malformed request is a REFUSAL here, not a fault
----------------------------------------------------
The mirror image of §4.10(e): that module is a REPLY the supervisor is the sole producer of,
so a bad shape there is a supervisor fault with no wire vocabulary. This is a REQUEST from
the party §2.4 declares compromised, and ``malformed`` is a published member of its closed
set — so every shape violation is answered, not raised. What *does* raise is a disagreement
between the durable row and the store behind it (the artifact is missing, or its length is
not the length the row recorded): §4.10(f) publishes no reason for that, and inventing one
would put a verdict outside a closed set. Those two paths are **reachable only from a faulty
store or tampered durable state**, and they are marked as such rather than left to look like
peer-reachable refusals.

Only the Python standard library is used, and no clock is read anywhere in this file.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

import governed_output_stream as streams
from brops_protocol import MAX_FRAME_BYTES
from governed_staging_upload import (
    _checked,
    _Refuse,
    _require_exact_request,
    _require_id,
    _require_int,
    REFUSE_MALFORMED,
)
from governed_supervisor import SupervisorError
from governed_supervisor_ledger import LedgerError
from governed_turn_open import peer_is_sidecar
from governed_turn_result import MAX_OUTPUT_BYTES, OUTPUT_STREAM_ID_LEN

# ---------------------------------------------------------------------------
# Wire constants (§4.10(f), LOCKED literals)
# ---------------------------------------------------------------------------

OUTPUT_READ_PROTOCOL = "brops.governed-turn-output-read.v1"
OUTPUT_READ_RESULT_PROTOCOL = "brops.governed-turn-output-read-result.v1"

#: §4.10(f): "Frame ≤ ``MAX_FRAME_BYTES = 262144``". Imported rather than restated, exactly
#: as §4.10(e) does and unlike §4.10(a)/(c)/(d) which fix their own 4 KiB bound: this section
#: names the shared transport constant itself, so a change to the frame cap must move both
#: together or neither.
MAX_OUTPUT_READ_FRAME_BYTES = MAX_FRAME_BYTES

#: §4.10(f): "Chunk size = **184320** decoded (= 245760 b64url + a small JSON envelope ≤
#: 262144)." Numerically the same as §2.4's ``MAX_STAGING_CHUNK_BYTES``, and deliberately NOT
#: imported from it: that constant is a bound on what a sender may push IN, chosen so a
#: request frame fits; this one is the exact stride of the ranges served OUT, and the two are
#: separate clauses about separate protocols. Sharing the symbol would mean a future change
#: to the ingress cap silently re-cut every stored output's chunk boundaries.
OUTPUT_CHUNK_BYTES = 184_320

#: ``4·⌈184320/3⌉``. 184320 is divisible by 3, so the encoding has no padding and the
#: base64url length is exact rather than an upper bound.
MAX_OUTPUT_CHUNK_B64_LEN = 4 * ((OUTPUT_CHUNK_BYTES + 2) // 3)

#: ``ceil(8388608 / 184320) = 46`` chunks for a maximum output, so ``seq`` runs 0..45 and the
#: last chunk is 94208 bytes. This is a consequence of the two constants above, computed
#: rather than typed, so it cannot fall out of step with them.
MAX_OUTPUT_CHUNKS = (MAX_OUTPUT_BYTES + OUTPUT_CHUNK_BYTES - 1) // OUTPUT_CHUNK_BYTES

#: The exhaustive request field set. Four values and a discriminator; nothing else, ever.
#: Most pointedly there is no length, no offset and no chunk size: the stride is fixed by the
#: protocol, so a caller cannot choose how much of the output one round trip returns.
OUTPUT_READ_REQUEST_FIELDS: Tuple[str, ...] = (
    "protocol",
    "output_stream_id",
    "receipt_id",
    "execution_attempt_id",
    "seq",
)

#: The exhaustive reply field set — ONE set for both arms, unlike §4.10(e)'s two. §4.10(f)
#: gives the refused arm ``"output_stream_id": "<same or null>"`` and ``"seq": "<int or
#: null>"``, i.e. the same seven keys with three of them nullable, so "which arm is this" is
#: answered by ``ok`` and never by which keys happen to be present.
OUTPUT_READ_REPLY_FIELDS: Tuple[str, ...] = (
    "protocol",
    "ok",
    "output_stream_id",
    "seq",
    "bytes_b64",
    "eof",
    "error",
)

# ---- The CLOSED §4.10(f) refusal set -------------------------------------------------
REFUSE_STREAM_UNKNOWN = "stream_unknown"
REFUSE_STREAM_EXPIRED = "stream_expired"
REFUSE_STREAM_BINDING_MISMATCH = "stream_binding_mismatch"
REFUSE_SEQ_OUT_OF_RANGE = "seq_out_of_range"

#: Exactly the five literals §4.10(f) publishes, on BOTH hops. The bridge reply's enum is
#: "IDENTICAL to the supervisor's (NOT a superset)" because the sidecar relays a supervisor
#: verdict verbatim and originates none of its own.
#:
#: All five are members of §4.5's ``GOVERNED_REFUSAL_REASONS``, and that containment is
#: intended rather than accidental: §4.10(h) (**NOT IMPLEMENTED** — a later ordered piece)
#: names "a ``brops.governed-turn-output-read-result.v1`` ``refused``" as a **genuine governed
#: verdict**, relayed verbatim, explicitly NOT one of the internal refusals its diagnostic
#: carrier exists for. So unlike
#: §4.10(a0)/(a)/(b)/(c)/(d) — whose sets overlap ``GOVERNED_REFUSAL_REASONS`` only by
#: accident of spelling, on ``{malformed, retry_conflict, oversize}`` — this set is a SUBSET
#: by design. What still separates a §4.10(f) refusal from a §4.10(e) verdict is the
#: top-level ``protocol`` const, which is what §4.10(h) (**NOT IMPLEMENTED**) classifies on.
OUTPUT_READ_REFUSAL_REASONS: Tuple[str, ...] = (
    REFUSE_STREAM_UNKNOWN,
    REFUSE_STREAM_EXPIRED,
    REFUSE_STREAM_BINDING_MISMATCH,
    REFUSE_SEQ_OUT_OF_RANGE,
    REFUSE_MALFORMED,
)

#: §4.10(f)'s closed set has no ``peer_denied``, so a peer this supervisor does not serve is
#: answered ``malformed`` — the same choice §4.10(b)/(c) make for the same reason. It is the
#: least informative published literal: a stranger learns that its frame was not accepted and
#: nothing about whether the stream it named exists.
_OUTPUT_READ_PEER_DENIED = REFUSE_MALFORMED


# ---------------------------------------------------------------------------
# Replies
# ---------------------------------------------------------------------------


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def output_read_ok(output_stream_id: str, seq: int, chunk: bytes, eof: bool) -> Dict[str, Any]:
    """Build the §4.10(f) ``ok`` reply for one immutable byte range.

    The chunk bound is re-asserted here rather than trusted from the slice that produced it.
    That is the ONE size check in this file that can fire, and the frame arithmetic in the
    module docstring rests on it: 184320 decoded bytes are 245760 base64url characters and
    the whole reply is 245940 against a 262144 cap. If ``OUTPUT_CHUNK_BYTES`` were ever
    raised, this raises with a sentence naming the cause instead of the transport raising a
    ``ProtocolError`` three layers away about a body it cannot explain.
    """
    if len(chunk) > OUTPUT_CHUNK_BYTES:
        raise SupervisorError(
            "served chunk is %d bytes, over the %s stride of %d — the §4.10(f) frame "
            "arithmetic depends on this bound" % (len(chunk), OUTPUT_READ_PROTOCOL,
                                                  OUTPUT_CHUNK_BYTES))
    return {
        "protocol": OUTPUT_READ_RESULT_PROTOCOL,
        "ok": True,
        "output_stream_id": output_stream_id,
        "seq": seq,
        "bytes_b64": _b64url(chunk),
        "eof": eof,
        "error": None,
    }


def output_read_refused(reason: str, *, output_stream_id: Optional[str] = None,
                        seq: Optional[int] = None) -> Dict[str, Any]:
    """Build the §4.10(f) ``refused`` reply.

    ``_checked`` is imported from ``governed_staging_upload`` rather than rewritten: it is the
    one implementation of "a refusal reason must be a member of the set its protocol
    published". Here it matters more than usual, because §4.10(h) (**NOT IMPLEMENTED** — a
    later ordered piece) treats this frame as a GOVERNED VERDICT relayed verbatim to the
    desktop, so an unpublished literal would one day travel all the way to a
    ``record_pre_verification_block`` reason string.

    ``output_stream_id`` and ``seq`` echo back what the request named when it named something
    usable, and are ``null`` when it did not (§4.10(f): "``<same or null>``"). They are echoes
    of a request, never of the row: a refusal must not disclose a stream's real binding to a
    caller that failed to present it.
    """
    return {
        "protocol": OUTPUT_READ_RESULT_PROTOCOL,
        "ok": False,
        "output_stream_id": output_stream_id,
        "seq": seq,
        "bytes_b64": None,
        "eof": None,
        "error": {"reason": _checked(reason, OUTPUT_READ_REFUSAL_REASONS,
                                     OUTPUT_READ_PROTOCOL)},
    }


# ---------------------------------------------------------------------------
# Range arithmetic
# ---------------------------------------------------------------------------


def n_chunks(output_bytes: int) -> int:
    """``ceil(output_bytes / OUTPUT_CHUNK_BYTES)``. Zero for a zero-byte output."""
    return (output_bytes + OUTPUT_CHUNK_BYTES - 1) // OUTPUT_CHUNK_BYTES


def last_seq(output_bytes: int) -> int:
    """The highest legal ``seq`` for an output of this size.

    ``max(0, n_chunks - 1)``, and the ``max`` is the §4.10(f) zero-byte contract, not a
    defensive habit: "when ``output_bytes == 0`` … a read with ``seq == 0`` returns
    ``ok:true, bytes_b64:"", eof:true``; any ``seq > 0`` ⇒ ``seq_out_of_range``". A zero-byte
    output has zero chunks but exactly one legal read, so that the desktop's loop is the same
    loop for every turn and the empty case is not a special path it might get wrong.
    """
    count = n_chunks(output_bytes)
    return count - 1 if count else 0


def chunk_range(seq: int) -> Tuple[int, int]:
    """The immutable half-open byte range ``seq`` names. Idempotent by construction: it is a
    pure function of ``seq``, so the same read always returns the same bytes and a lost reply
    is safely retried with no cursor to consume."""
    start = seq * OUTPUT_CHUNK_BYTES
    return start, start + OUTPUT_CHUNK_BYTES


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Request:
    output_stream_id: str
    receipt_id: str
    execution_attempt_id: str
    seq: int


def _parse(request: Any) -> _Request:
    body = _require_exact_request(request, OUTPUT_READ_PROTOCOL, OUTPUT_READ_REQUEST_FIELDS)
    output_stream_id = _require_id(body, "output_stream_id")
    if len(output_stream_id) != OUTPUT_STREAM_ID_LEN:
        # The capability has ONE length. A value of any other length cannot be a token this
        # supervisor minted, and saying `stream_unknown` about it would be answering a
        # question about the table for a string that never reached it.
        raise _Refuse(REFUSE_MALFORMED, "output_stream_id must be exactly %d chars"
                      % OUTPUT_STREAM_ID_LEN)
    receipt_id = _require_id(body, "receipt_id")
    execution_attempt_id = _require_id(body, "execution_attempt_id")
    seq = _require_int(body, "seq")
    if seq < 0:
        # §4.10(f) types the field `<int ≥0>`, so a negative is a SHAPE violation, not a
        # range one. `seq_out_of_range` is reserved for a value that could have been a seq
        # for some stream and is not one for this stream.
        raise _Refuse(REFUSE_MALFORMED, "seq must be >= 0")
    return _Request(output_stream_id, receipt_id, execution_attempt_id, seq)


def gate_output_read(
    request: Any,
    *,
    peer_uid: Any,
    allowed_sidecar_uid: Any,
    conn: Any,
    now_ms: int,
) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
    """Run the §4.10(f) verdict ladder. Returns ``(row, None)`` or ``(None, refusal_reply)``.

    The order is §4.10(f)'s own and is not rearrangeable without changing what a caller can
    learn: authenticate the peer, validate the exact five-field shape, then **absent →
    expired → binding → range**. Nothing touches the database until the caller has proved it
    is the sidecar and its message is the exact frame, so a hostile peer never reaches a
    query; and nothing about a row is disclosed until all three of the token, the receipt and
    the attempt agree.

    ``now_ms`` is the front door's clock, injected. §4.10(f) requires the phase verdict to be
    "SYNCHRONOUS on every read, never dependent on the async sweep", so it is computed here
    from the row's own ``expires_at_ms`` — a retention-expired row the sweep has not reached
    yet still answers ``stream_expired``, and only its physical absence answers
    ``stream_unknown``.
    """
    try:
        if not peer_is_sidecar(peer_uid, allowed_sidecar_uid):
            raise _Refuse(_OUTPUT_READ_PEER_DENIED, "peer is not the sidecar principal")
        parsed = _parse(request)
    except _Refuse as refusal:
        # Nothing usable was parsed, so nothing is echoed: `<same or null>` means the value
        # the request named, and a frame that failed the shape check named none.
        return None, output_read_refused(refusal.reason)

    if conn is None:
        raise SupervisorError("governed-turn-output-read requires a durable ledger connection")

    echo = {"output_stream_id": parsed.output_stream_id, "seq": parsed.seq}
    try:
        row = streams.load_stream(conn, parsed.output_stream_id)
    except LedgerError as exc:
        # A durable row the supervisor cannot interpret is a FAULT, not a peer's refusal:
        # answering `stream_unknown` would report a clean absence where the truth is that
        # the ledger holds something unreadable.
        raise SupervisorError("output stream ledger fault: %s" % exc)

    # Phase 3 — absent (swept, quota-evicted, or never minted). One answer for all three,
    # deliberately: distinguishing them would tell an unauthorized holder whether the token
    # it guessed ever existed.
    if row is None:
        return None, output_read_refused(REFUSE_STREAM_UNKNOWN, **echo)

    # Phase 2 — the tombstone. Checked BEFORE the binding compare, per §4.10(f)'s locked
    # order: a caller presenting an expired token with the wrong receipt learns only that it
    # is expired, never that it is otherwise valid.
    if streams.is_expired(row, now_ms):
        return None, output_read_refused(REFUSE_STREAM_EXPIRED, **echo)

    # The P1-3 server-side 3-tuple compare. The desktop sources these two from the VERIFIED
    # signed envelope, so they are authenticated values; a valid token replayed against a
    # different turn is caught here rather than three steps later by the output digest.
    if (row["receipt_id"] != parsed.receipt_id
            or row["execution_attempt_id"] != parsed.execution_attempt_id):
        return None, output_read_refused(REFUSE_STREAM_BINDING_MISMATCH, **echo)

    if parsed.seq > last_seq(row["output_bytes"]):
        return None, output_read_refused(REFUSE_SEQ_OUT_OF_RANGE, **echo)

    return (row, parsed), None


# ---------------------------------------------------------------------------
# The wire operation
# ---------------------------------------------------------------------------


def handle_output_read(
    request: Any,
    *,
    peer_uid: Any,
    allowed_sidecar_uid: Any,
    conn: Any,
    now_ms: int,
    read_output: Callable[[str], bytes],
) -> Dict[str, Any]:
    """Serve one ``brops.governed-turn-output-read.v1`` and return the §4.10(f) reply.

    ``read_output`` is the content-addressed store read, injected for the same reason
    §4.10(c)'s publish is: what this protocol owns is the decision about *whether* a range may
    be served, not the machinery that holds the bytes. It has a REAL production implementation
    available — ``brops_evidence_store.EvidenceStore.read``, which refuses unless
    ``sha256(bytes) == handle`` — so the supervisor never serves a byte it has not just
    re-hashed against the handle the terminal record named. (§4.10(d)'s ``drive_acceptance``
    seam gained its own production supplier on 2026-08-10,
    ``governed_acceptance.AcceptanceDriver``; the contrast this paragraph used to draw with it
    no longer holds.)

    Re-reading the whole artifact per chunk is deliberate and is a cost, not an oversight: an
    8 MiB output costs 46 reads of ≤8 MiB, and in exchange every single chunk is served out
    of freshly digest-verified bytes rather than out of a handle that was verified once at
    the start of a loop that then ran for a minute. A ranged reader could be injected later
    through this same seam without the protocol changing.

    Two disagreements between the durable row and the store raise instead of refusing —
    §4.10(f) publishes no literal for either, and inventing one would put a verdict outside a
    closed set. **Both are reachable only from a faulty store or tampered durable state**, not
    from anything a hostile peer can send, and are marked as such: a peer chooses which
    stream to name, never what the store holds behind it.
    """
    if not callable(read_output):
        raise SupervisorError("read_output must be callable")

    gated, refusal = gate_output_read(
        request, peer_uid=peer_uid, allowed_sidecar_uid=allowed_sidecar_uid,
        conn=conn, now_ms=now_ms,
    )
    if gated is None:
        return refusal or output_read_refused(REFUSE_MALFORMED)

    row, parsed = gated
    try:
        data = read_output(row["output_handle"])
    except Exception as exc:  # noqa: BLE001 — every store failure is one fail-closed fault
        # MARKED: unreachable from a hostile frame. The handle comes off the row, the row was
        # written by the supervisor from the recorder's own evidence chain, and the store
        # re-verifies the digest — so a failure here means the protected store lost or
        # corrupted an artifact a signed terminal record still pins.
        raise SupervisorError("output artifact unreadable for a live stream: %s" % exc)
    if not isinstance(data, (bytes, bytearray)):
        raise SupervisorError("read_output must return bytes")
    data = bytes(data)
    if len(data) != row["output_bytes"]:
        # MARKED: same class. The row's `output_bytes` was measured from these exact bytes at
        # mint time and the row is INSERT-ONCE, so a divergence means the store's contents
        # changed under a content address — which the store's own digest check should have
        # caught first. Refusing with `seq_out_of_range` would be a lie about the request.
        raise SupervisorError(
            "output artifact is %d bytes, the stream row records %d"
            % (len(data), row["output_bytes"]))

    start, end = chunk_range(parsed.seq)
    return output_read_ok(
        parsed.output_stream_id, parsed.seq, data[start:end],
        eof=parsed.seq == last_seq(row["output_bytes"]),
    )


@dataclass(frozen=True)
class OutputReadService:
    """The §4.10(f) binding: the sidecar UID this supervisor serves, and the store read.

    Like ``OpenService``, ``StagingService`` and ``EvidenceRequestService`` it is also the
    fail-closed switch, and here it governs BOTH halves of §4.10(f). A supervisor constructed
    without one serves no read **and mints no stream**, so there is no configuration in which
    rows exist that nothing can read, or reads are served against rows nothing created. That
    pairing is what keeps §4.10(f)'s "a completing turn's stream is **always** created" true
    of every supervisor that can answer a read at all.
    """

    allowed_sidecar_uid: int
    read_output: Callable[[str], bytes]

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_sidecar_uid, int) or isinstance(self.allowed_sidecar_uid, bool):
            raise SupervisorError("OutputReadService.allowed_sidecar_uid must be an int uid")
        if not callable(self.read_output):
            raise SupervisorError("OutputReadService.read_output must be callable")

    def handle(self, request: Any, *, peer_uid: Any, conn: Any,
               clock_ms: Callable[[], int]) -> Dict[str, Any]:
        """Serve one request. The clock is read ONCE, here, and passed down — §4.10(f)'s
        phase verdict must be a single instant, or a read could be judged live by the expiry
        check and expired by a later one inside the same reply."""
        protocol = request.get("protocol") if isinstance(request, Mapping) else None
        if protocol != OUTPUT_READ_PROTOCOL:
            raise SupervisorError("not the output-read protocol: %r" % (protocol,))
        return handle_output_read(
            request,
            peer_uid=peer_uid,
            allowed_sidecar_uid=self.allowed_sidecar_uid,
            conn=conn,
            now_ms=clock_ms(),
            read_output=self.read_output,
        )

    def mint_for_completion(self, conn: Any, new: streams.NewStream,
                            now_ms: int) -> Tuple[str, Any]:
        """Mint (or re-read) the stream for a completing turn — the §5/§6.1 step-13 half.

        §4.10(f): "The row is **durably committed BEFORE** the §4.10(e) result summary is
        returned." It lives on the service rather than beside the §5 completion handler so
        that the ability to CREATE a stream and the ability to SERVE one are the same
        configuration decision.
        """
        return streams.mint_stream(conn, new, now_ms)

    def measure_output(self, output_handle: str) -> int:
        """The output's length in bytes, read from the store and therefore digest-verified.

        §4.10(f) binds ``output_bytes`` into the row, and the §5 ``complete-run`` facts do not
        carry one — ``produced`` is ``{output_handle, containment_evidence_handle,
        completed_at_ms}`` and deliberately admits nothing else (audit F-01). So the length is
        MEASURED from the bytes the handle addresses rather than reported by the caller, which
        is the same direction every other completion value moved in when F-01 closed.
        """
        try:
            data = self.read_output(output_handle)
        except Exception as exc:  # noqa: BLE001 - one fail-closed fault for every store failure
            # A completion naming an output the store cannot return is a completion the
            # supervisor must refuse: §4.10(f) says a completing turn's stream is ALWAYS
            # created, so a supervisor that cannot create one has not completed the turn.
            raise SupervisorError("output artifact unreadable at completion: %s" % exc)
        if not isinstance(data, (bytes, bytearray)):
            raise SupervisorError("read_output must return bytes")
        # There is deliberately NO ceiling check here. ``mint_stream`` refuses anything
        # outside ``0..MAX_OUTPUT_BYTES`` on the way into the row, and ``complete-run``
        # relays that refusal — so a check on this line could change the wording of a
        # refusal and never its outcome. Mutation testing found it: deleting it killed no
        # test, which is the definition of a check that reads as protection while protecting
        # nothing (the class deleted in §4.10(a)/(c) rather than shipped).
        return len(data)


__all__ = [
    "MAX_OUTPUT_CHUNKS",
    "MAX_OUTPUT_CHUNK_B64_LEN",
    "MAX_OUTPUT_READ_FRAME_BYTES",
    "OUTPUT_CHUNK_BYTES",
    "OUTPUT_READ_PROTOCOL",
    "OUTPUT_READ_REFUSAL_REASONS",
    "OUTPUT_READ_REPLY_FIELDS",
    "OUTPUT_READ_REQUEST_FIELDS",
    "OUTPUT_READ_RESULT_PROTOCOL",
    "OutputReadService",
    "REFUSE_MALFORMED",
    "REFUSE_SEQ_OUT_OF_RANGE",
    "REFUSE_STREAM_BINDING_MISMATCH",
    "REFUSE_STREAM_EXPIRED",
    "REFUSE_STREAM_UNKNOWN",
    "chunk_range",
    "gate_output_read",
    "handle_output_read",
    "last_seq",
    "n_chunks",
    "output_read_ok",
    "output_read_refused",
]
