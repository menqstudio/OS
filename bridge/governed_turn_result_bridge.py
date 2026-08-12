"""``bridge.governed-turn-result.v1`` — the §4.6 re-framing, on the SIDECAR hop.

§4.10(e) is how a finished governed turn reaches the sidecar. §4.6 is how the sidecar
hands that same outcome to the desktop, and §4.10(e) names the relationship in one
sentence: "The sidecar re-frames it into ``bridge.governed-turn-result.v1`` (§4.6)."
Re-frames. Not decides, not summarises, not augments.

That verb is the whole contract, because of who is speaking. §2.4 declares the sidecar compromised
and §4.10(h) (**NOT IMPLEMENTED**) says it "originates **no** governed verdict: it may neither mint
a ``GOVERNED_REFUSAL_REASONS`` reason nor emit a ``signed`` ``bridge.governed-turn-result.v1``". So
the only interesting question about this module is not what it copies but what a hostile version of
it could achieve by copying wrongly.

What a compromised sidecar CAN do here
--------------------------------------
Exactly two things, and both of them only ever end a turn:

* **Downgrade.** Turn a ``signed`` §4.10(e) reply into a ``refused`` §4.6 frame carrying
  any member of the closed union, or drop the frame entirely. The desktop Blocks. §4.10(f)
  already states the matching limit in writing — the sidecar is the transport proxy for
  every turn, so denial is inside its power by construction and 3b-1B does not claim
  otherwise.
* **Corrupt an echo.** Alter ``run_id``/``execution_attempt_id``/``output_bytes``/
  ``output_sha256``/``supervisor_attestation_key_id`` on the way past. §7.1 requires the
  desktop to equality-check every one of them against the VERIFIED envelope, so this also
  only ever produces a Block. It is caught on the desktop, by the party with the signature,
  and deliberately not here: a check performed by the compromised party over values it
  chose is worth nothing to the party that matters.

What it is structurally unable to do
------------------------------------
Forge a success. A ``signed`` §4.6 frame is only usable if it carries an
``envelope_jcs_b64`` that verifies under the pinned isolated-signer key (§4.9/§7.1) AND an
``attestation_evidence_jcs_b64`` that verifies under the pinned supervisor-attestation key
AND an attested record that is an account of *this* turn. The sidecar holds neither key and
is in neither group (§2.3: "``sidecar``, ``executor``, and ``desktop`` are in NEITHER
``brops-store`` nor any owner"). It cannot mint an ``output_stream_id`` either: the token is
generated server-side and bound in the supervisor's ``0700`` ``governed_output_streams``
row to ``(receipt_id, execution_attempt_id, …)``, so a token this process invented is
refused ``stream_binding_mismatch`` by the supervisor before a byte is served, and a token
lifted from another turn fails the same compare against the envelope-sourced ids
(§4.10(f) P1-3). The output bytes themselves are gated by the SIGNED envelope's
``output_bytes``/``output_sha256`` in ``governed_output_pull``, whose API has no parameter
for an expected digest precisely so this frame's echo of one can never become the
authority.

So the honest summary is: this hop can stop a turn, and cannot make one.

The §4.6 receipt object is SMALLER than §4.6 says, and this is the reason
-------------------------------------------------------------------------
**A DESIGN GAP, recorded here rather than papered over.** §4.6's ``receipt`` lists 28
fields. Its only producer is this re-framer, and its only input is the §4.10(e) ``signed``
arm — which carries 16 fields, 11 of which §4.6 names. The other **17** §4.6 names have no
source in the input at all, and seven of them have no source anywhere the sidecar can
reach:

* ``status``, ``exit_code``, ``evidence[]`` are the frozen ``bridge.result.receipt`` shape
  (``bridge/contracts/bridge-result.schema.json``, built from ``SupervisorResult``). The
  governed path has no ``SupervisorResult``: §4.10(e) is the reply to the §4.10(d)
  evidence-request and carries none of the three.
* ``challenge_registry_handle``/``_hash``/``_epoch``/``_root_key_id`` are resolved by the
  supervisor "**from its own supervisor state** — the registry is NEVER supplied by the
  sidecar" (§4.10(a0)). The supervisor never returns them: the §4.10(a0) reply is
  ``{protocol, status, challenge_handle}``.

The remaining ten (``task_id``, ``challenge_accepted_at_ms``, ``lease_handle``,
``execution_receipt_handle``, ``evidence_event_count``/``_last_sequence``/
``_head_sequence``/``_final_event_hash``, plus ``challenge_handle``/``challenge_key_id``)
*could* be produced — by decoding ``envelope_jcs_b64`` here, or by remembering the
§4.10(a0) reply. They are deliberately NOT, because a value this process copies out of the
envelope is a value the desktop decodes from the same bytes: §7.1's equality check over it
would compare a document against itself and could not fail for any input, which is the
defect class this repository keeps producing. An echo is only worth carrying when the
supervisor, not this proxy, is the one who wrote it.

Every one of the 17 is named in :data:`UNSOURCED_RECEIPT_FIELDS`, and a test asserts that
:data:`RECEIPT_FIELDS` plus that tuple is exactly §4.6's 28. The gap is therefore
machine-checked: when §4.10(g) or a widened §4.10(e) gives one of them a source, a name
moves between the two tuples and the test says so.

The arithmetic, done first
--------------------------
The largest §4.6 frame this shape can express is **74206 bytes** compact — every string at
its §4.6 encoded-byte cap, ``containment_evidence_b64`` at its full 65536, ``output_bytes``
at 8388608 — and **74236** as ``engine_sidecar.run`` actually writes it (``json.dumps``
with default separators, which costs 30 bytes of spacing on this shape). The largest
``ok:false`` frame is **296**. All three are constructed and asserted in
``bridge/tests/test_governed_turn_result_bridge.py``, not estimated here.

**No cap on its path can fire.** The frame is written to this process's stdout as one JSON
object and read by ``ai.rs::governed_sidecar_call`` under ``MAX_STDOUT_BYTES = 9437184``
(``ai.rs:44``): 74236 against 9437184 leaves **9362948** bytes of headroom, a factor of 127.
§4.6 also states ``MAX_FRAME_BYTES = 262144``, which this fits inside 3.5× over — but that
bound belongs to ``brops_protocol``'s socket framing and this frame never crosses a socket.
So no size check is written in this file, for the same reason none is written in the
§4.10(f) hop below it in ``engine_sidecar.py``: a check that cannot fire reads as protection
while protecting nothing.

One cap on this frame is known to be WRONG, and it is inherited rather than fixed here.
§4.6 freezes ``envelope_jcs_b64 ≤ 2848`` as a machine-checked derivation of the §4.9 payload
"at schema max", and for the payload this tree's signer actually builds that derivation is too
small: nine of its seventeen string fields are ids capped at 128, so at 125 characters each the
encoding is **2852** and at the cap **2888** — 40 over. Established 2026-08-10 by the §5
acceptance work, which refuses the over-cap case as a governed ``oversize`` verdict in
``engine/runtime/governed_acceptance.py`` rather than letting it fault a frame validator. That is
what makes the cap safe to enforce here with no escape hatch: a legitimate envelope over 2848
never reaches this hop, because §4.10(e) refuses to build a frame carrying one. The number is
still the design's and the design's number is still too small; that needs an Architect ruling,
not a local widening.

Two bounds that would NOT admit it are worth naming, because they are why this is a
subprocess-stdio hop at all: ``governed_supervisor_server.MAX_FRAME_BYTES`` (broker-facing)
and ``ipc_framing::MAX_FRAME_PAYLOAD_BYTES`` are both **8192** — 9.06× too small for a
maximum §4.6 frame, and 30× too small for a §4.10(f) chunk. A future attempt to "simplify"
either onto a framed-IPC path fails at the first large containment blob rather than in
production. The bound that DOES admit it, and only just, is the one this frame's own INPUT
crosses: the §4.10(e) reply is at most **74472** bytes over ``brops_socket`` under
``MAX_SIDECAR_FRAME_BYTES = 262144``. Re-framing SHRINKS the document by 266 bytes
(``receipt_id`` and ``key_id`` dropped, ``status`` collapsed into ``ok``, against the cost
of the nested ``receipt``/``error`` keys), so if the input fitted, the output does.

WIRED ON THIS SIDE — and the gap moved one hop out (2026-08-10)
--------------------------------------------------------------
:func:`reframe_turn_result` now has a caller: ``bridge/governed_turn_submit.py`` drives
§4.10(a0) → §4.10(a)(b)(c) → §4.10(d) inside one one-shot subprocess and re-frames the
§4.10(e) reply through this module, reached from the ``bridge.governed-turn-submit.v1``
branch in ``engine_sidecar._dispatch``. ``engine/tests/test_governed_turn_submit_e2e.py``
walks that ladder against the real supervisor services and comes back with a §4.6 frame
whose envelope verifies, so this hop is exercised end to end rather than in isolation.

One hop further out, on the trusted side, the WRITER now exists (2026-08-12):
``brops_core::governed_prepare.prepare_governed_turn_v1b`` and
``brops_core::governed_submit.governed_turn_submit_prepared``. It is still not on a live path —
the helper has no caller, its subprocess spawn is an injected seam no production code
implements, and the broker's one production ``GovernedExecutor``
(``broker/src/chain_executor.rs``) spawns the recorder rather than a sidecar. So the frame is
produced and consumed only from tests, and the §4.10(f) pull behind it stays unreachable.

Only the Python standard library is used, and no clock, socket, subprocess or file is
touched anywhere in this file.
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any, Dict, Mapping, Optional, Tuple

# The engine's runtime is on `sys.path` when this module is imported from
# `engine_sidecar` (see its header); adding it here as well makes the module importable
# on its own — by a test, or by a future §4.10(g) orchestrator — without depending on
# import order. Idempotent, and it adds nothing this process could not already reach.
_ENGINE_RUNTIME = pathlib.Path(__file__).resolve().parent.parent / "engine" / "runtime"
if _ENGINE_RUNTIME.is_dir() and str(_ENGINE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_ENGINE_RUNTIME))

from brops_protocol import ProtocolError, decode_base64url  # noqa: E402
from governed_staging_upload import (  # noqa: E402
    _require_exact_request,
    _require_id,
    _require_int,
    _require_sha256,
    _Refuse,
)
from governed_turn_result import (  # noqa: E402
    GOVERNED_REFUSAL_REASONS,
    MAX_ATTESTATION_EVIDENCE_JCS_B64_LEN,
    MAX_CONTAINMENT_EVIDENCE_B64_LEN,
    MAX_ENVELOPE_JCS_B64_LEN,
    MAX_OUTPUT_BYTES,
    OUTPUT_STREAM_ID_LEN,
    SIGNATURE_B64_LEN,
    SIGNED_FIELDS,
    STATUS_REFUSED,
    STATUS_SIGNED,
    validate_turn_result,
)

# ---------------------------------------------------------------------------
# Wire constants (§4.6 / §2.2, LOCKED literals)
# ---------------------------------------------------------------------------

#: §2.2 names the const and §4.6 makes it a REQUIRED top-level key: "it carries an explicit
#: top-level ``"protocol": "bridge.governed-turn-result.v1"`` const in its ``required`` set".
#: That is the ONE canonical discriminator in both directions — the frozen ``bridge.result``
#: is ``additionalProperties:false`` with no ``protocol`` key so it rejects this document,
#: and this shape requires the const so it rejects a ``bridge.result``. §4.6 says in as many
#: words that ``receipt.envelope_jcs_b64`` MUST NOT be used instead, because it is a REQUIRED
#: key of ``bridge.result.receipt`` too.
BRIDGE_TURN_RESULT_PROTOCOL = "bridge.governed-turn-result.v1"

#: The §4.10(e) ``signed`` members the §4.6 OUTER object consumes rather than nests:
#: ``protocol`` becomes this protocol const, ``status`` becomes the boolean ``ok``, and
#: ``output_stream_id`` is lifted to the top level where §4.6 puts it ("non-null iff
#: ok==true; drives the §4.10(f) pull").
CONSUMED_BY_THE_OUTER_OBJECT: Tuple[str, ...] = ("protocol", "status", "output_stream_id")

#: The §4.10(e) ``signed`` members §4.6 gives NO slot on the ``ok`` arm — and both omissions
#: are coherent rather than oversights, so they are honoured rather than "fixed":
#:
#: * ``receipt_id`` — §4.10(f) P1-3 is explicit that "the desktop sources
#:   ``receipt_id``/``execution_attempt_id`` from the **verified §4.9 signed envelope**
#:   (authenticated values, not transport claims)". Carrying a transport copy of the very
#:   value the design forbids the desktop to source from transport is an invitation, not a
#:   convenience. §4.6 keeps ``receipt_id`` only on the ``error`` arm, where no envelope
#:   exists to source it from and it is forensic.
#: * ``key_id`` — the isolated-signer key id, which §7.1 checks by comparing
#:   ``envelope.key_id`` against the PINNED manifest id. The envelope carries it under the
#:   signature; an unsigned copy beside it could only ever be redundant or wrong.
NOT_CARRIED_ON_THE_OK_ARM: Tuple[str, ...] = ("receipt_id", "key_id")

#: The ``receipt`` object this hop emits: DERIVED from §4.10(e)'s exhaustive ``signed`` field
#: set, never typed out, so it cannot fall out of step with the frame it re-frames. Eleven
#: names, every one of them also named by §4.6.
RECEIPT_FIELDS: Tuple[str, ...] = tuple(
    field for field in SIGNED_FIELDS
    if field not in CONSUMED_BY_THE_OUTER_OBJECT and field not in NOT_CARRIED_ON_THE_OK_ARM
)

#: The 17 §4.6 ``receipt`` names with no source in the §4.10(e) reply this hop re-frames.
#: See the module docstring for which are structurally unobtainable (the first seven) and
#: which are obtainable but deliberately not carried (the rest — a value copied out of
#: ``envelope_jcs_b64`` makes §7.1's equality check compare a document against itself).
#:
#: This tuple is not documentation, it is a fixture: ``RECEIPT_FIELDS + this`` is asserted
#: equal to §4.6's literal 28-name set, so the gap cannot be quietly widened or quietly
#: closed. Closing one means MOVING a name from here to :data:`RECEIPT_FIELDS`.
#: **`status` is a HOMONYM and the two meanings must not be confused.** §4.10(e)'s
#: top-level ``status`` is the arm discriminator (``"signed"``/``"refused"``) and IS
#: consumed — it becomes ``ok``. §4.6's ``receipt.status`` is a completely different field:
#: the RUN status of the frozen ``bridge.result.receipt`` shape (``"completed"``, from a
#: ``SupervisorResult``), which the governed path never produces. So the name appears in
#: both :data:`CONSUMED_BY_THE_OUTER_OBJECT` and below, and it is not the same field twice.
UNSOURCED_RECEIPT_FIELDS: Tuple[str, ...] = (
    # No source anywhere the sidecar can reach.
    "status",
    "exit_code",
    "evidence",
    "challenge_registry_handle",
    "challenge_registry_hash",
    "challenge_registry_epoch",
    "challenge_registry_root_key_id",
    # Obtainable, deliberately not carried (see the module docstring).
    "task_id",
    "challenge_accepted_at_ms",
    "challenge_handle",
    "challenge_key_id",
    "lease_handle",
    "execution_receipt_handle",
    "evidence_event_count",
    "evidence_last_sequence",
    "evidence_head_sequence",
    "evidence_final_event_hash",
)

#: The exhaustive top-level key set. Five names: §4.6's literal outer object.
FRAME_FIELDS: Tuple[str, ...] = ("protocol", "ok", "output_stream_id", "receipt", "error")

#: The ``error`` object on the ``ok:false`` arm. ``receipt_id`` is REQUIRED and NULLABLE,
#: exactly as on the §4.10(e) ``refused`` arm it relays: a turn refused before an id was
#: minted has none, and a key that is simply absent would make "no receipt" and "the field
#: was forgotten" the same frame.
ERROR_FIELDS: Tuple[str, ...] = ("reason", "receipt_id")


class BridgeFrameError(RuntimeError):
    """This process could not produce or could not read a well-formed §4.6 frame.

    Deliberately NOT ``governed_supervisor.SupervisorError``, which the §4.10(e) module
    raises for the same class of fault. That name would be a lie about who failed: the
    supervisor is a different principal on the other side of a socket, and a fault in this
    proxy's own framing says nothing whatever about it.

    Deliberately NOT a refusal either. §4.10(h) (**NOT IMPLEMENTED**): a LOCAL failure of the
    sidecar "is NOT one of these reasons and produces NO reply frame". ``engine_sidecar._dispatch``
    already turns an exception on a governed hop into the protocol-less ``bridge.op.v1`` document,
    which the desktop can only read as the out-of-band transport failure it is — so raising is what
    routes this correctly, and inventing a ``GOVERNED_REFUSAL_REASONS`` member to carry it would be
    this hop originating the one thing §4.10(h) (**NOT IMPLEMENTED**) forbids it to originate.
    """


# ---------------------------------------------------------------------------
# Field validators
# ---------------------------------------------------------------------------


def _require_b64url(body: Mapping[str, Any], field: str, *,
                    max_len: Optional[int] = None,
                    exact_len: Optional[int] = None,
                    nullable: bool = False) -> Optional[str]:
    """A base64url field, bounded on its ENCODED length and required to be canonical.

    Same shape and same reasoning as the §4.10(e) validator's helper, and reused for the
    same reason ``decode_base64url`` is: that function re-encodes and compares, so a string
    that merely *decodes* but is not the canonical encoding of what it decodes to is
    refused. Two spellings of the same bytes, in a field §7.1 will later run an equality
    check against, is precisely the ambiguity §4.10(a0)'s canonicality gate exists for.

    Length is checked BEFORE the decode: §4.6 freezes these caps as ENCODED-byte lengths,
    so an over-cap value is over-cap whether or not it decodes.
    """
    value = body[field]
    if value is None:
        if nullable:
            return None
        raise _Refuse("bridge_frame_fault", "%s may not be null" % field)
    if not isinstance(value, str):
        raise _Refuse("bridge_frame_fault", "%s must be a base64url string" % field)
    if exact_len is not None and len(value) != exact_len:
        raise _Refuse("bridge_frame_fault", "%s must be exactly %d base64url chars, got %d"
                      % (field, exact_len, len(value)))
    if max_len is not None and not (0 < len(value) <= max_len):
        raise _Refuse("bridge_frame_fault", "%s must be 1..%d base64url chars, got %d"
                      % (field, max_len, len(value)))
    try:
        decode_base64url(value)
    except ProtocolError as exc:
        raise _Refuse("bridge_frame_fault", "%s is not canonical base64url: %s" % (field, exc))
    return value


def _validate_receipt(receipt: Any) -> Mapping[str, Any]:
    """The ``ok:true`` ``receipt`` object: exactly eleven keys, each at its §4.6 cap."""
    if not isinstance(receipt, Mapping):
        raise _Refuse("bridge_frame_fault", "receipt must be a JSON object on the ok arm")
    keys = set(receipt.keys())
    extra = keys - set(RECEIPT_FIELDS)
    if extra:
        raise _Refuse("bridge_frame_fault", "receipt has unexpected field(s) %s" % sorted(extra))
    missing = set(RECEIPT_FIELDS) - keys
    if missing:
        raise _Refuse("bridge_frame_fault", "receipt is missing field(s) %s" % sorted(missing))

    _require_b64url(receipt, "envelope_jcs_b64", max_len=MAX_ENVELOPE_JCS_B64_LEN)
    _require_b64url(receipt, "signature_b64", exact_len=SIGNATURE_B64_LEN)
    _require_b64url(receipt, "attestation_evidence_jcs_b64",
                    max_len=MAX_ATTESTATION_EVIDENCE_JCS_B64_LEN)
    _require_b64url(receipt, "attestation_signature_b64", exact_len=SIGNATURE_B64_LEN)
    _require_b64url(receipt, "containment_evidence_b64",
                    max_len=MAX_CONTAINMENT_EVIDENCE_B64_LEN, nullable=True)
    _require_id(receipt, "supervisor_attestation_key_id")
    _require_id(receipt, "run_id")
    _require_id(receipt, "execution_attempt_id")
    _require_id(receipt, "lease_id")
    _require_sha256(receipt, "output_sha256")
    output_bytes = _require_int(receipt, "output_bytes")
    if not (0 <= output_bytes <= MAX_OUTPUT_BYTES):
        raise _Refuse("bridge_frame_fault",
                      "output_bytes must be 0..%d, got %d" % (MAX_OUTPUT_BYTES, output_bytes))
    return receipt


def _validate_error(error: Any) -> Mapping[str, Any]:
    """The ``ok:false`` ``error`` object: ``{reason, receipt_id}`` and nothing else."""
    if not isinstance(error, Mapping):
        raise _Refuse("bridge_frame_fault", "error must be a JSON object on the refused arm")
    if set(error.keys()) != set(ERROR_FIELDS):
        raise _Refuse("bridge_frame_fault",
                      "error must carry exactly %s, got %s"
                      % (sorted(ERROR_FIELDS), sorted(error.keys())))
    # The SINGLE membership check against the closed union. §4.6 embeds "the literal
    # GOVERNED_REFUSAL_REASONS array (§4.5)" — and §4.5's relay rule forbids a second copy, so the
    # tuple is IMPORTED from the §4.10(e) module that owns it rather than restated. A reason outside
    # it is a fault, not a new reason: §4.10(h) (**NOT IMPLEMENTED**) maps reasons to Blocks BY
    # NAME, so an unmapped string would fall through to whatever the default happens to be.
    if error["reason"] not in GOVERNED_REFUSAL_REASONS:
        raise _Refuse("bridge_frame_fault",
                      "reason %r is not a member of the closed GOVERNED_REFUSAL_REASONS union"
                      % (error["reason"],))
    if error["receipt_id"] is not None:
        _require_id(error, "receipt_id")
    return error


def _validate(frame: Any) -> Mapping[str, Any]:
    """The shape check proper. Raises ``_Refuse``, converted by the caller."""
    if not isinstance(frame, Mapping):
        raise _Refuse("bridge_frame_fault", "the frame must be a JSON object")

    # `_require_exact_request` is the ONE implementation of "exactly these keys, and the
    # protocol const is this" — the same door §4.10(a0), the three staging protocols,
    # §4.10(d) and §4.10(e) close. Unlike §4.10(e) the two arms share ONE key set here
    # (§4.6 nulls the unused member rather than omitting it), so the check runs before the
    # arm is selected instead of after.
    body = _require_exact_request(frame, BRIDGE_TURN_RESULT_PROTOCOL, FRAME_FIELDS)

    ok = body["ok"]
    if not isinstance(ok, bool):
        raise _Refuse("bridge_frame_fault", "ok must be a boolean, got %r" % (ok,))

    if ok:
        # §4.6: "``output_stream_id``: non-null iff ok==true", "``receipt`` non-null iff
        # ok==true", "``error`` non-null iff ok==false". Three biconditionals, and both
        # halves of each are checked — an `ok:true` frame carrying an `error` object is as
        # malformed as one missing its receipt, and only checking the presence half would
        # admit a frame that is simultaneously a success and a refusal.
        _require_b64url(body, "output_stream_id", exact_len=OUTPUT_STREAM_ID_LEN)
        _validate_receipt(body["receipt"])
        if body["error"] is not None:
            raise _Refuse("bridge_frame_fault", "an ok frame may not carry an error object")
    else:
        if body["output_stream_id"] is not None:
            raise _Refuse("bridge_frame_fault",
                          "a refused frame may not carry an output_stream_id")
        if body["receipt"] is not None:
            raise _Refuse("bridge_frame_fault", "a refused frame may not carry a receipt")
        _validate_error(body["error"])
    return frame


def validate_bridge_turn_result(frame: Any) -> Mapping[str, Any]:
    """Is ``frame`` a well-formed §4.6 frame? Returns it, or raises :class:`BridgeFrameError`.

    Used by the builder below on its own output, so the producer is held to exactly the check its
    consumer applies and the two cannot disagree. §5's F-01 finding was a supervisor that signed
    whatever arrived on the wire; the discipline that replaced it is that no governed document
    leaves this tree without passing the check its consumer would apply. That discipline is worth as
    much on the untrusted hop as on the trusted one — a malformed frame from here reaches the
    desktop as an unclassifiable document, and §4.10(h) (**NOT IMPLEMENTED**) item 4 turns it into
    ``governed_transport_failure`` rather than into anything a reader could act on.
    """
    try:
        return _validate(frame)
    except _Refuse as bad:
        raise BridgeFrameError(
            "not a %s frame: %s" % (BRIDGE_TURN_RESULT_PROTOCOL, bad.detail or bad.reason)
        )


# ---------------------------------------------------------------------------
# The re-framer
# ---------------------------------------------------------------------------


def reframe_turn_result(engine_frame: Any) -> Dict[str, Any]:
    """Re-frame ONE §4.10(e) supervisor reply into its §4.6 desktop form.

    The only entry point, and it takes the supervisor's frame — never loose fields. That is
    what makes "the sidecar originates nothing" checkable rather than aspirational: there is
    no parameter through which a value of this process's own choosing could enter the
    result, so every member of the emitted frame is traceable to a member of the input.

    The input is validated with the ENGINE's own ``validate_turn_result`` before anything is
    read off it, for two reasons. A supervisor reply that is not a §4.10(e) frame is not
    something to re-frame — it is evidence that the thing on the other end of the socket is
    not the supervisor's handler, which is a LOCAL failure (§4.10(f) P1-5's rule, applied to
    §4.10(e)'s hop). And validating with the definition rather than with a copy of it is
    what keeps this hop unable to admit a reply the supervisor can no longer produce, or to
    reject one it can.

    Raises :class:`BridgeFrameError` on any input that is not a §4.10(e) frame, and on any
    output that is not a §4.6 frame.
    """
    try:
        frame = validate_turn_result(engine_frame)
    except Exception as exc:  # noqa: BLE001 — SupervisorError, or anything a hostile shape raises
        raise BridgeFrameError(
            "the supervisor reply is not a brops.governed-turn-result.v1 frame: %s" % exc
        )

    if frame["status"] == STATUS_SIGNED:
        # Field-for-field. No literal, no default, no computed value: `RECEIPT_FIELDS` is
        # derived from §4.10(e)'s own field set, so this comprehension cannot silently gain
        # a member this process invented, and cannot silently lose one the supervisor sent.
        reframed: Dict[str, Any] = {
            "protocol": BRIDGE_TURN_RESULT_PROTOCOL,
            "ok": True,
            "output_stream_id": frame["output_stream_id"],
            "receipt": {field: frame[field] for field in RECEIPT_FIELDS},
            "error": None,
        }
    elif frame["status"] == STATUS_REFUSED:
        reframed = {
            "protocol": BRIDGE_TURN_RESULT_PROTOCOL,
            "ok": False,
            "output_stream_id": None,
            "receipt": None,
            # The verdict is RELAYED, exactly as the §4.10(f) hop relays its five literals:
            # every `GOVERNED_REFUSAL_REASONS` member a desktop ever sees under this
            # protocol was decided by the supervisor or the isolated signer, against their
            # own durable state. This hop can pick a different one — see the module
            # docstring — but it can only ever pick one that Blocks.
            "error": {"reason": frame["reason"], "receipt_id": frame["receipt_id"]},
        }
    else:  # pragma: no cover — `validate_turn_result` admits exactly two statuses
        raise BridgeFrameError("unreachable: §4.10(e) status %r" % (frame["status"],))

    validate_bridge_turn_result(reframed)
    return reframed


__all__ = [
    "BRIDGE_TURN_RESULT_PROTOCOL",
    "BridgeFrameError",
    "CONSUMED_BY_THE_OUTER_OBJECT",
    "ERROR_FIELDS",
    "FRAME_FIELDS",
    "NOT_CARRIED_ON_THE_OK_ARM",
    "RECEIPT_FIELDS",
    "UNSOURCED_RECEIPT_FIELDS",
    "reframe_turn_result",
    "validate_bridge_turn_result",
]
