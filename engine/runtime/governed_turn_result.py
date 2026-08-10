"""``brops.governed-turn-result.v1`` — the §4.10(e) supervisor→sidecar result frame.

By the time this frame exists the turn is over. §4.10(a0) verified one signed challenge,
§4.10(a)(b)(c) carried three artifacts into the protected store, §4.10(d) proved the
staging row was ``INPUTS_READY`` and handed the turn to §5, and §5/§6.1 either produced a
signed receipt envelope or refused. §4.10(e) is the single shape in which that outcome
travels back to the sidecar — and the sidecar is the party §2.4 declares compromised, so
the interesting question is not what the frame says but what it is structurally unable to
say.

What this file is
-----------------
The COMPLETE §4.10(e) tagged union, as a builder and as a validator, and nothing else. It
is a shape, not a decision: it verifies no signature, reads no store, reads no clock,
touches no table, and mints no identifier. It cannot decide that a turn succeeded; it can
only refuse to express a success that is not fully formed.

Two arms, told apart by ``status``, both under ONE ``protocol`` const:

  * ``signed`` — sixteen fields, every one of them present, ``containment_evidence_b64``
    the only nullable member. §4.10(e): "A ``signed`` result REQUIRES ``envelope_jcs_b64``
    + ``signature_b64`` + ``output_stream_id``; anything else ⇒ Block." Here that clause
    is not a separate test but a consequence of the exhaustive required set: a frame
    missing any of the three is not a ``signed`` frame at all, so the predicate can never
    be *partly* satisfied.
  * ``refused`` — four fields, the reason drawn from the closed ``GOVERNED_REFUSAL_REASONS``
    union and ``receipt_id`` nullable (a turn refused before a receipt id was minted has
    none).

The output is NEVER in this frame
---------------------------------
§4.10(e) says so twice: "the output is NEVER inlined — the summary carries only
``output_bytes``/``output_sha256``/``output_stream_id``". That is enforced by the field set
rather than by a size check: there is no key an output could ride, so the frozen 3b-1A
``brops.governed-result.v1`` shape — which carries a top-level ``output`` string — is
rejected here on the unknown key as well as on the ``protocol`` const (§2.2's compatibility
rule, in both directions). The reason it matters is §4.6's arithmetic: a full-schema frame
with inline output provably overflows ``MAX_FRAME_BYTES``, and a protocol that overflows
only at full size is a protocol that works until the day it does not.

The frame cap is real but unreachable, and that is stated rather than checked
----------------------------------------------------------------------------
§4.10(e) fixes the frame at ``MAX_FRAME_BYTES = 262144``. The largest frame this shape can
express is **74472 bytes** — every string at its cap, ``output_bytes`` at 8388608,
``containment_evidence_b64`` at its full 65536 — which leaves 187672 bytes of headroom, so
a builder-side or handler-side frame check could never fire. Step 2 deleted such a check
after mutation testing showed removing it changed no test, and step 3 declined to write
one; this file does neither. What stands in its place is
``test_the_literal_maximum_signed_frame_fits``, which CONSTRUCTS the maximum instance and
asserts the number, so the claim is arithmetic in a test rather than arithmetic in a
comment. The transport's own ``encode_frame`` remains the only enforcement, and it is the
same bound.

Two lengths that are checked once, not twice
--------------------------------------------
``signature_b64`` is "b64url 86" and ``output_stream_id`` is a "43-char base64url
capability" (256 bits). Neither gets a second check on its DECODED length, because there
cannot be one: 86 canonical base64url characters decode to exactly 64 bytes and 43 to
exactly 32, so ``len == 86`` plus the canonicality round-trip in
``brops_protocol.decode_base64url`` already pins the byte count. A ``len(decoded) == 64``
line would read as protection while being unable to fail — the exact class step 2 deleted.
``test_the_length_checks_already_pin_the_decoded_byte_counts`` proves the implication
instead of asserting it.

What this file deliberately does NOT do
---------------------------------------
**It does not check the echoes against each other.** ``output_bytes`` and ``output_sha256``
could be mutually inconsistent (0 bytes carried with a non-empty digest) and this validator
will pass them. §4.10(e) says "All non-signature fields TRANSPORT-ONLY" and §4.6/§7.1 put
the binding where it belongs: the desktop's authority for the output is the *signed
envelope's* ``output_sha256``/``output_bytes``, applied to the §4.10(f)-reassembled bytes.
A consistency check here would compare a transport echo against a transport echo — it would
catch a supervisor typo and would catch nothing an adversary does, while implying an
authority this frame does not have.

**It does not mint, and it does not classify.** ``output_stream_id`` is minted by §4.10(f)
— ``governed_output_stream.mint_stream``, into the ``governed_output_streams`` table, from
``complete-run`` (landed 2026-08-10; the DESKTOP hop of that pull is still unbuilt) — and this
file only checks that the value it is handed has the shape a capability must have.
Classifying a received frame into a desktop Block is §4.10(h)
(**NOT IMPLEMENTED** — a later ordered piece); this file only says whether a frame IS a
§4.10(e) frame.

**A malformed frame is a FAULT, never a refusal.** §4.10(e) is a REPLY, and the supervisor
is its only producer. There is no reason literal for "the supervisor could not build its
own reply", and inventing one would put a verdict outside a closed set — so every shape
violation raises ``SupervisorError``. ``_Refuse`` is used inside as typed control flow
only; its ``reason`` never reaches a wire and is a sentinel, not a protocol value.

Where ``GOVERNED_REFUSAL_REASONS`` lives, and why here
-----------------------------------------------------
§4.5 DEFINES the closed union and §4.10(e) EMBEDS it: "the two metadata-result relay reason
enums … embed the **exact literal ``GOVERNED_REFUSAL_REASONS`` array VERBATIM** (a
``$ref``/copy of the single list above), **never** an inferred 'mirrors §4.5'". A second
Python copy would be exactly the drift that rule forbids, so there is ONE tuple and it is
below. §4.5's own frame — ``brops.governed-sign-result.v1`` — is **NOT IMPLEMENTED**: no
producer, no consumer, no schema file. When it is built it must IMPORT this tuple rather
than restate it, and so must §4.6's ``bridge.governed-turn-result.v1`` relay enum. The
twelve ratified members are additionally pinned against the frozen
``engine/contracts/brops-sign-result.v1.schema.json`` by a test, so the "ratified" half
cannot drift from the 3b-1A schema it was ratified in.

Only the Python standard library is used, and no clock is read anywhere in this file.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from brops_protocol import MAX_FRAME_BYTES, ProtocolError, decode_base64url
from governed_staging_upload import (
    _checked,
    _Refuse,
    _require_exact_request,
    _require_id,
    _require_int,
    _require_sha256,
)
from governed_supervisor import SupervisorError

# ---------------------------------------------------------------------------
# Wire constants (§4.10(e) / §2.2, LOCKED literals)
# ---------------------------------------------------------------------------

#: §2.2 names this constant by name: "3b-1B **ADDS in parallel** a new
#: ``GOVERNED_TURN_RESULT_PROTOCOL = "brops.governed-turn-result.v1"`` constant". It is a
#: NEW name beside the frozen 3b-1A ``GOVERNED_RESULT_PROTOCOL =
#: "brops.governed-result.v1"`` in ``engine/tools/brops_supervisor_service.py``, which stays
#: byte-for-byte unchanged: KEEP + ADD, never rename.
GOVERNED_TURN_RESULT_PROTOCOL = "brops.governed-turn-result.v1"

#: §4.10(e): "Frame ≤ ``MAX_FRAME_BYTES = 262144``". Unlike §4.10(a)/(c)/(d) — which each
#: fix their OWN 4 KiB bound and therefore spell it out — §4.10(e) names the shared
#: transport constant itself, so it is imported rather than restated: a future change to
#: the frame cap must move both together or neither.
MAX_TURN_RESULT_FRAME_BYTES = MAX_FRAME_BYTES

STATUS_SIGNED = "signed"
STATUS_REFUSED = "refused"

#: §4.10(f): "``output_stream_id`` = 32 cryptographically-random bytes, base64url no-pad,
#: EXACTLY 43 chars (256-bit)". §4.10(e) transports it; the minting, the
#: ``governed_output_streams`` binding and the supervisor half of the read loop are all
#: §4.10(f) and live in ``governed_output_stream`` / ``governed_output_read``, which import
#: this constant rather than restating 43.
OUTPUT_STREAM_ID_LEN = 43

#: §4.10(e)/§4.5: "<b64url 86>" — a detached Ed25519 signature.
SIGNATURE_B64_LEN = 86

#: §4.10(e): ``output_bytes`` is ``<int 0..8388608>`` — the §2.4 ``history`` ceiling, the
#: largest single artifact the governed family moves.
MAX_OUTPUT_BYTES = 8_388_608

#: §4.6's frozen ENCODED-byte caps, quoted there as machine-checked derivations:
#: ``envelope_jcs_b64 ≤ 2848`` (= ``4·⌈2135/3⌉``, the §4.9 payload at schema max) and
#: ``attestation_evidence_jcs_b64 ≤ 4664`` (= ``4·⌈3498/3⌉``, the §4.4 evidence at schema
#: max). They bound the base64url STRING, not the bytes it decodes to.
MAX_ENVELOPE_JCS_B64_LEN = 2848
MAX_ATTESTATION_EVIDENCE_JCS_B64_LEN = 4664
MAX_CONTAINMENT_EVIDENCE_B64_LEN = 65536

#: The exhaustive ``signed`` field set. Sixteen names and no others — most pointedly no
#: ``output`` and no ``result``: §4.10(e) says the output is NEVER inlined, and the frozen
#: 3b-1A ``brops.governed-result.v1`` carries exactly such a top-level ``output`` string, so
#: the two shapes reject each other on the field set as well as on the discriminator.
SIGNED_FIELDS: Tuple[str, ...] = (
    "protocol",
    "status",
    "receipt_id",
    "output_stream_id",
    "output_bytes",
    "output_sha256",
    "envelope_jcs_b64",
    "signature_b64",
    "key_id",
    "attestation_evidence_jcs_b64",
    "attestation_signature_b64",
    "supervisor_attestation_key_id",
    "containment_evidence_b64",
    "run_id",
    "execution_attempt_id",
    "lease_id",
)

#: The exhaustive ``refused`` field set. ``receipt_id`` is REQUIRED and NULLABLE, exactly as
#: in the frozen §4.5 sibling: a turn refused before an id was minted has none, and a key
#: that is simply absent would make "no receipt" and "the field was forgotten" the same
#: frame.
REFUSED_FIELDS: Tuple[str, ...] = ("protocol", "status", "receipt_id", "reason")

# ---------------------------------------------------------------------------
# The CLOSED governed refusal-reason union (§4.5, embedded verbatim per §4.10(e))
# ---------------------------------------------------------------------------

#: The ratified twelve, in the exact order of the frozen
#: ``engine/contracts/brops-sign-result.v1.schema.json`` enum. §4.5: this is the union's
#: first half, and the frozen ``brops.sign-result.v1`` enum it is quoted from is UNTOUCHED —
#: the governed union is a SEPARATE constant that happens to contain these twelve, not an
#: extension of that schema.
RATIFIED_REFUSAL_REASONS: Tuple[str, ...] = (
    "attestation_invalid",
    "not_completed",
    "run_binding_invalid",
    "nonce_mismatch",
    "handle_missing",
    "hash_mismatch",
    "policy_mismatch",
    "containment_missing",
    "identity_denied",
    "timestamp_invalid",
    "oversize",
    "malformed",
)

#: The seventeen governed additions (§4.5, P1-4). Every one of them is produced by a §5/§7
#: gate that is **NOT IMPLEMENTED** in this tree — §4.10(e) transports the verdict, it does
#: not decide it — so this tuple is the vocabulary, not the vocabulary's users.
GOVERNED_ADDED_REFUSAL_REASONS: Tuple[str, ...] = (
    "challenge_replay",
    "acceptance_conflict",
    "lease_not_ready",
    "output_oversize",
    "output_timeout",
    "evidence_fork",
    "stale_evidence",
    "lease_expired",
    "challenge_invalidated",
    "retry_conflict",
    "stream_unknown",
    "stream_expired",
    "stream_binding_mismatch",
    "seq_out_of_range",
    "model_profile_unknown",
    "tcb_integrity_violation",
    "platform_unsupported",
)

#: §4.5's single closed union — "the ratified 12 … + the governed additions". The one list
#: §4.10(e)'s ``refused`` arm embeds, and the one §4.6 and §4.5's own frame must import
#: rather than restate.
#:
#: It is NOT disjoint by VALUE from the internal producer codes of §4.10(a0)/(a)/(b)/(c)/(d)
#: and §2.1: ``malformed`` and ``retry_conflict`` are spelled the same in both. §4.10(h)
#: (**NOT IMPLEMENTED** — a later ordered piece) calls the internal set "a **disjoint**
#: namespace", and that is true of the NAMESPACE — classification is by the top-level
#: ``protocol`` — and false of the strings. Nothing here may depend on the stronger reading;
#: what separates a governed verdict from an internal refusal is that the verdict arrives
#: under ``brops.governed-turn-result.v1`` and the refusal under its own protocol const.
GOVERNED_REFUSAL_REASONS: Tuple[str, ...] = (
    RATIFIED_REFUSAL_REASONS + GOVERNED_ADDED_REFUSAL_REASONS
)

#: The ``_Refuse`` reason this module raises internally. It is deliberately NOT a member of
#: any closed set: it never reaches a wire, because §4.10(e) has no refusal for a REPLY the
#: supervisor could not build. Every ``_Refuse`` raised below is converted to
#: ``SupervisorError`` by :func:`validate_turn_result` before it can escape.
_FRAME_FAULT = "supervisor_frame_fault"


# ---------------------------------------------------------------------------
# Field validators
# ---------------------------------------------------------------------------


def _require_b64url(body: Mapping[str, Any], field: str, *,
                    max_len: Optional[int] = None,
                    exact_len: Optional[int] = None,
                    nullable: bool = False) -> Optional[str]:
    """A base64url field, bounded on its ENCODED length and required to be canonical.

    ``decode_base64url`` is reused rather than a regex being written here: it is the one
    implementation of "strict base64url" in this tree, and its second rule is the one that
    matters — it re-encodes and compares, so a string that merely *decodes* but is not the
    canonical encoding of what it decodes to is refused. Two spellings of the same bytes in
    a field an equality check will later be run against is precisely the ambiguity §4.10(a0)
    added its canonicality gate for.

    Length is checked BEFORE the decode: §4.6 freezes these caps as encoded-byte lengths, so
    an over-cap value is over-cap whether or not it decodes.
    """
    value = body[field]
    if value is None:
        if nullable:
            return None
        raise _Refuse(_FRAME_FAULT, "%s may not be null" % field)
    if not isinstance(value, str):
        raise _Refuse(_FRAME_FAULT, "%s must be a base64url string" % field)
    if exact_len is not None and len(value) != exact_len:
        raise _Refuse(_FRAME_FAULT, "%s must be exactly %d base64url chars, got %d"
                      % (field, exact_len, len(value)))
    if max_len is not None and not (0 < len(value) <= max_len):
        raise _Refuse(_FRAME_FAULT, "%s must be 1..%d base64url chars, got %d"
                      % (field, max_len, len(value)))
    try:
        decode_base64url(value)
    except ProtocolError as exc:
        raise _Refuse(_FRAME_FAULT, "%s is not canonical base64url: %s" % (field, exc))
    return value


def _require_nullable_id(body: Mapping[str, Any], field: str) -> Optional[str]:
    """``receipt_id`` on the ``refused`` arm: a 1..128 char string, or an explicit null.

    ``_require_id`` is reused for the non-null case rather than its bounds being restated,
    so "what an id is" has one definition across §4.10(a0), the three staging protocols,
    §4.10(d) and here.
    """
    if body[field] is None:
        return None
    return _require_id(body, field)


def _require_bounded_int(body: Mapping[str, Any], field: str,
                         low: int, high: int) -> int:
    value = _require_int(body, field)
    if not (low <= value <= high):
        raise _Refuse(_FRAME_FAULT, "%s must be %d..%d, got %d" % (field, low, high, value))
    return value


# ---------------------------------------------------------------------------
# The validator
# ---------------------------------------------------------------------------


def _validate(frame: Any) -> Mapping[str, Any]:
    """The shape check proper. Raises ``_Refuse`` (converted by the caller) or
    ``SupervisorError`` (from ``_checked``, which already says exactly the right thing about
    an off-contract reason)."""
    if not isinstance(frame, Mapping):
        raise _Refuse(_FRAME_FAULT, "the frame must be a JSON object")

    status = frame.get("status")
    if status not in (STATUS_SIGNED, STATUS_REFUSED):
        raise _Refuse(_FRAME_FAULT, "status must be %r or %r, got %r"
                      % (STATUS_SIGNED, STATUS_REFUSED, status))

    # `_require_exact_request` is the ONE implementation of "exactly these keys, and the
    # protocol const is this" — the same door §4.10(a0), the three staging protocols and
    # §4.10(d) close. The arm is selected first because the two arms have different key
    # sets; the protocol const is then checked exactly once, inside that helper.
    fields = SIGNED_FIELDS if status == STATUS_SIGNED else REFUSED_FIELDS
    body = _require_exact_request(frame, GOVERNED_TURN_RESULT_PROTOCOL, fields)

    if status == STATUS_REFUSED:
        _require_nullable_id(body, "receipt_id")
        # A reason outside the closed union is a supervisor-side fault and says so by name.
        # This is the SINGLE membership check: the builder does not run a second one, so
        # breaking this one cannot be masked by its twin.
        _checked(body["reason"], GOVERNED_REFUSAL_REASONS, GOVERNED_TURN_RESULT_PROTOCOL)
        return frame

    # ---- the `signed` arm -------------------------------------------------------
    # §4.10(e): "A `signed` result REQUIRES `envelope_jcs_b64` + `signature_b64` +
    # `output_stream_id`". That is not a separate clause here: all three are members of the
    # exhaustive required set above and are non-nullable below, so a frame that satisfies
    # this arm at all carries them.
    _require_id(body, "receipt_id")
    _require_b64url(body, "output_stream_id", exact_len=OUTPUT_STREAM_ID_LEN)
    _require_bounded_int(body, "output_bytes", 0, MAX_OUTPUT_BYTES)
    _require_sha256(body, "output_sha256")
    _require_b64url(body, "envelope_jcs_b64", max_len=MAX_ENVELOPE_JCS_B64_LEN)
    _require_b64url(body, "signature_b64", exact_len=SIGNATURE_B64_LEN)
    _require_id(body, "key_id")
    _require_b64url(body, "attestation_evidence_jcs_b64",
                    max_len=MAX_ATTESTATION_EVIDENCE_JCS_B64_LEN)
    _require_b64url(body, "attestation_signature_b64", exact_len=SIGNATURE_B64_LEN)
    _require_id(body, "supervisor_attestation_key_id")
    _require_b64url(body, "containment_evidence_b64",
                    max_len=MAX_CONTAINMENT_EVIDENCE_B64_LEN, nullable=True)
    _require_id(body, "run_id")
    _require_id(body, "execution_attempt_id")
    _require_id(body, "lease_id")
    return frame


def validate_turn_result(frame: Any) -> Mapping[str, Any]:
    """Is ``frame`` a well-formed §4.10(e) result? Returns it, or raises ``SupervisorError``.

    There is no refusal reply for a bad answer here and there must not be one: §4.10(e) is
    a REPLY, the supervisor is its only producer, and the closed union it embeds is the
    vocabulary of GOVERNED verdicts — a supervisor that cannot build its own frame has not
    reached a verdict at all. Raising keeps that distinction: the caller sees a fault, not
    a decision it might relay.
    """
    try:
        return _validate(frame)
    except _Refuse as bad:
        raise SupervisorError(
            "not a %s frame: %s" % (GOVERNED_TURN_RESULT_PROTOCOL, bad.detail or bad.reason)
        )


# ---------------------------------------------------------------------------
# The builders
# ---------------------------------------------------------------------------


def turn_result_signed(*, receipt_id: Any, output_stream_id: Any, output_bytes: Any,
                       output_sha256: Any, envelope_jcs_b64: Any, signature_b64: Any,
                       key_id: Any, attestation_evidence_jcs_b64: Any,
                       attestation_signature_b64: Any,
                       supervisor_attestation_key_id: Any,
                       containment_evidence_b64: Any, run_id: Any,
                       execution_attempt_id: Any, lease_id: Any) -> Dict[str, Any]:
    """Build the §4.10(e) ``signed`` verdict.

    Keyword-only, because fourteen positional values of which ten are strings is a protocol
    whose fields can be transposed silently. Every argument is REQUIRED — there is no
    default and no ``None`` fallback except ``containment_evidence_b64``, the one member
    §4.10(e) makes nullable — so a caller cannot build a partial verdict by omission.

    The built frame is run through :func:`validate_turn_result` before it is returned, so
    the builder and the validator cannot disagree: there is one definition of the shape and
    the producer is held to it. That matters more than it looks. §5's F-01 finding was a
    supervisor that signed whatever arrived on the wire; the discipline that replaced it is
    that no governed document leaves this tree without passing the same check its consumer
    would apply.
    """
    frame = {
        "protocol": GOVERNED_TURN_RESULT_PROTOCOL,
        "status": STATUS_SIGNED,
        "receipt_id": receipt_id,
        "output_stream_id": output_stream_id,
        "output_bytes": output_bytes,
        "output_sha256": output_sha256,
        "envelope_jcs_b64": envelope_jcs_b64,
        "signature_b64": signature_b64,
        "key_id": key_id,
        "attestation_evidence_jcs_b64": attestation_evidence_jcs_b64,
        "attestation_signature_b64": attestation_signature_b64,
        "supervisor_attestation_key_id": supervisor_attestation_key_id,
        "containment_evidence_b64": containment_evidence_b64,
        "run_id": run_id,
        "execution_attempt_id": execution_attempt_id,
        "lease_id": lease_id,
    }
    validate_turn_result(frame)
    return frame


def turn_result_refused(reason: Any, receipt_id: Any = None) -> Dict[str, Any]:
    """Build the §4.10(e) ``refused`` verdict — a GOVERNED verdict, not an internal refusal.

    ``receipt_id`` defaults to ``None`` because most of the closed union's members are
    decided before a receipt id exists (``lease_not_ready``, ``challenge_replay``,
    ``platform_unsupported``); the key is still emitted, explicitly null, so "no receipt"
    and "the field was forgotten" are different frames.

    A reason outside ``GOVERNED_REFUSAL_REASONS`` raises rather than shipping: the §4.10(h)
    routing table (**NOT IMPLEMENTED** — a later ordered piece) maps reasons to Blocks BY
    NAME, so an unmapped string would fall through to whatever the default happens to be.
    """
    frame = {
        "protocol": GOVERNED_TURN_RESULT_PROTOCOL,
        "status": STATUS_REFUSED,
        "receipt_id": receipt_id,
        "reason": reason,
    }
    validate_turn_result(frame)
    return frame


__all__ = [
    "GOVERNED_ADDED_REFUSAL_REASONS",
    "GOVERNED_REFUSAL_REASONS",
    "GOVERNED_TURN_RESULT_PROTOCOL",
    "MAX_ATTESTATION_EVIDENCE_JCS_B64_LEN",
    "MAX_CONTAINMENT_EVIDENCE_B64_LEN",
    "MAX_ENVELOPE_JCS_B64_LEN",
    "MAX_OUTPUT_BYTES",
    "MAX_TURN_RESULT_FRAME_BYTES",
    "OUTPUT_STREAM_ID_LEN",
    "RATIFIED_REFUSAL_REASONS",
    "REFUSED_FIELDS",
    "SIGNATURE_B64_LEN",
    "SIGNED_FIELDS",
    "STATUS_REFUSED",
    "STATUS_SIGNED",
    "turn_result_refused",
    "turn_result_signed",
    "validate_turn_result",
]
