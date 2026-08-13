"""The §4.6 re-framing — `brops.governed-turn-result.v1` → `bridge.governed-turn-result.v1`.

§4.10(e) is the supervisor's word about a finished turn. §4.6 is the shape that word takes
when it crosses the sidecar boundary, and the sidecar is the party §2.4 declares
compromised. So the questions this file is organized around are not "does the frame have
the right keys" but "what could a hostile version of this hop achieve", and "which of the
things it must be unable to do are unable by CONSTRUCTION rather than by care".

  * **`ReFramingTests`** — the copy is field-for-field, in both arms, and the emitted key
    set is DERIVED from §4.10(e)'s rather than typed, so it cannot gain a member this
    process invented or lose one the supervisor sent.

  * **`OriginationTests`** — the two things a compromised sidecar CAN do (downgrade a
    success to a Block; corrupt an echo) both only ever end a turn, and the one thing it
    cannot do — forge a success — is unforgeable because a `signed` frame is worthless
    without two signatures under keys §2.3 puts out of its reach and a capability token
    the supervisor mints and binds. Proven here as far as this hop can prove it: the
    re-framer has no parameter through which a value of its own choosing can enter.

  * **`ClosedUnionTests`** — every one of the 29 `GOVERNED_REFUSAL_REASONS` members is
    reachable BY NAME through this hop, and nothing else is. The tuple is IMPORTED from the
    §4.10(e) module that owns it, so a member added there is a member this roll call
    immediately demands.

  * **`DisjointnessTests`** — §2.2's LOCKED compatibility rule, both directions, via the
    positive top-level `protocol` const and NOT via `envelope_jcs_b64` (which §4.6 warns is
    a REQUIRED key of `bridge.result.receipt` too). Checked against the real frozen
    `bridge/contracts/bridge-result.schema.json` with `jsonschema`, not against a
    paraphrase of it.

  * **`FrameArithmeticTests`** — the maximum frame is CONSTRUCTED and its byte count
    asserted, against every bound on its path. The conclusion is that none of them can
    fire, which is why this module ships no size check.

  * **`DesignGapTests`** — §4.6 names 28 `receipt` fields and this hop can source 11. The
    other 17 are a tuple in the module, and the union is asserted equal to §4.6's literal
    list, so the gap is machine-checked rather than prose. This test is what turns RED the
    day someone closes half of it silently.

No prerequisite here is optional. Everything is stdlib plus repo modules imported at module
scope, with no `try`/`except` and no `skipIf`, so a missing prerequisite is an unmissable
hard error rather than a green run with a quiet skip. (There is no
`BROPS_TEST_MISSING_PREREQUISITES` declaration anywhere in this tree, so nothing is declared
in it and nothing here may be softened.)
"""
from __future__ import annotations

import base64
import json
import pathlib
import sys
import unittest

import jsonschema

import governed_turn_result_bridge as gtb

_BRIDGE = pathlib.Path(gtb.__file__).resolve().parent
_ENGINE_RUNTIME = _BRIDGE.parent / "engine" / "runtime"
if str(_ENGINE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_ENGINE_RUNTIME))

import governed_turn_result as gtr  # noqa: E402

_BRIDGE_RESULT_SCHEMA = json.loads(
    (_BRIDGE / "contracts" / "bridge-result.schema.json").read_text("utf-8"))

#: §4.6's `receipt` object, EXACTLY as the design lists it — the 28 names, transcribed once,
#: here rather than in the module under test. Keeping the design's list in the TEST and the
#: implementable subset in the MODULE is what makes the gap between them a machine-checked
#: fact instead of two comments that might once have agreed.
DESIGN_RECEIPT_FIELDS = (
    "task_id", "status", "exit_code", "evidence",
    "envelope_jcs_b64", "signature_b64", "containment_evidence_b64",
    "attestation_evidence_jcs_b64", "attestation_signature_b64",
    "supervisor_attestation_key_id",
    "run_id", "execution_attempt_id", "lease_id",
    "challenge_accepted_at_ms", "challenge_handle", "challenge_key_id",
    "challenge_registry_handle", "challenge_registry_hash",
    "challenge_registry_epoch", "challenge_registry_root_key_id",
    "lease_handle", "execution_receipt_handle",
    "output_sha256", "output_bytes",
    "evidence_event_count", "evidence_last_sequence", "evidence_head_sequence",
    "evidence_final_event_hash",
)


def b64url(n: int) -> str:
    """A CANONICAL base64url string of exactly `n` characters.

    Canonical matters: every b64 field on this frame is decoded through
    `brops_protocol.decode_base64url`, which re-encodes and compares, so a string padded to
    length with arbitrary alphabet characters would be refused for the right reason at the
    wrong time and quietly turn a size test into a canonicality test.
    """
    raw = n // 4 * 3 + {0: 0, 2: 1, 3: 2}[n % 4]
    return base64.urlsafe_b64encode(b"x" * raw).decode().rstrip("=")


def engine_signed(**overrides) -> dict:
    """A minimal, VALID §4.10(e) `signed` frame, built by the engine's own builder.

    Built rather than written out, so this file cannot drift from the frame it re-frames:
    if §4.10(e) gains or loses a field, the call below stops type-checking at import time
    rather than silently exercising a stale shape.
    """
    fields = dict(
        receipt_id="rcpt-1",
        output_stream_id=b64url(43),
        output_bytes=11,
        output_sha256="a" * 64,
        envelope_jcs_b64=b64url(120),
        signature_b64=b64url(86),
        key_id="signer-1",
        attestation_evidence_jcs_b64=b64url(200),
        attestation_signature_b64=b64url(86),
        supervisor_attestation_key_id="attest-1",
        containment_evidence_b64=b64url(40),
        run_id="run-1",
        execution_attempt_id="attempt-1",
        lease_id="lease-1",
    )
    fields.update(overrides)
    return gtr.turn_result_signed(**fields)


def engine_max_signed() -> dict:
    """The literal MAXIMUM §4.10(e) `signed` frame: every field at its §4.6 cap."""
    return engine_signed(
        receipt_id="r" * 128,
        output_bytes=gtr.MAX_OUTPUT_BYTES,
        output_sha256="f" * 64,
        envelope_jcs_b64=b64url(gtr.MAX_ENVELOPE_JCS_B64_LEN),
        key_id="k" * 128,
        attestation_evidence_jcs_b64=b64url(gtr.MAX_ATTESTATION_EVIDENCE_JCS_B64_LEN),
        supervisor_attestation_key_id="s" * 128,
        containment_evidence_b64=b64url(gtr.MAX_CONTAINMENT_EVIDENCE_B64_LEN),
        run_id="u" * 128,
        execution_attempt_id="a" * 128,
        lease_id="l" * 128,
    )


# =====================================================================================
# The re-framing itself
# =====================================================================================


class ReFramingTests(unittest.TestCase):
    def test_the_signed_arm_becomes_the_five_field_outer_object(self) -> None:
        frame = gtb.reframe_turn_result(engine_signed())
        self.assertEqual(set(frame), set(gtb.FRAME_FIELDS))
        self.assertEqual(frame["protocol"], "bridge.governed-turn-result.v1")
        self.assertIs(frame["ok"], True)
        self.assertIsNone(frame["error"])
        self.assertIsInstance(frame["receipt"], dict)

    def test_the_capability_token_is_lifted_to_the_top_level_where_the_pull_reads_it(self) -> None:
        engine = engine_signed()
        frame = gtb.reframe_turn_result(engine)
        # §4.6: "output_stream_id … non-null iff ok==true; drives the §4.10(f) pull". It is
        # the ONE member of this frame the desktop cannot obtain from the signed envelope,
        # which is why §4.6 exists at all rather than the envelope travelling alone.
        self.assertEqual(frame["output_stream_id"], engine["output_stream_id"])
        self.assertNotIn("output_stream_id", frame["receipt"])

    def test_every_receipt_field_is_copied_byte_for_byte_from_the_supervisors_frame(self) -> None:
        engine = engine_signed()
        receipt = gtb.reframe_turn_result(engine)["receipt"]
        self.assertEqual(set(receipt), set(gtb.RECEIPT_FIELDS))
        for field in gtb.RECEIPT_FIELDS:
            self.assertEqual(receipt[field], engine[field], field)

    def test_the_receipt_key_set_is_derived_from_the_engines_not_typed_out(self) -> None:
        # If §4.10(e)'s `signed` arm changes, this hop changes with it — the tuple is a
        # comprehension over `SIGNED_FIELDS`, not a second list that could go stale. The
        # partition is exhaustive in both directions, which is the property that makes
        # "copies everything, invents nothing" checkable.
        self.assertEqual(
            set(gtr.SIGNED_FIELDS),
            set(gtb.RECEIPT_FIELDS)
            | set(gtb.CONSUMED_BY_THE_OUTER_OBJECT)
            | set(gtb.NOT_CARRIED_ON_THE_OK_ARM),
        )
        self.assertEqual(len(gtb.RECEIPT_FIELDS), 11)

    def test_a_null_containment_evidence_survives_as_an_explicit_null(self) -> None:
        engine = engine_signed(containment_evidence_b64=None)
        receipt = gtb.reframe_turn_result(engine)["receipt"]
        self.assertIn("containment_evidence_b64", receipt)
        self.assertIsNone(receipt["containment_evidence_b64"])

    def test_the_refused_arm_relays_the_reason_and_the_receipt_id(self) -> None:
        engine = gtr.turn_result_refused("lease_expired", "rcpt-9")
        frame = gtb.reframe_turn_result(engine)
        self.assertIs(frame["ok"], False)
        self.assertIsNone(frame["output_stream_id"])
        self.assertIsNone(frame["receipt"])
        self.assertEqual(frame["error"], {"reason": "lease_expired", "receipt_id": "rcpt-9"})

    def test_a_refusal_with_no_receipt_id_yet_carries_an_explicit_null(self) -> None:
        frame = gtb.reframe_turn_result(gtr.turn_result_refused("lease_not_ready"))
        # Present-and-null, never absent: "no receipt id was minted" and "the field was
        # forgotten" must not be the same document.
        self.assertIn("receipt_id", frame["error"])
        self.assertIsNone(frame["error"]["receipt_id"])

    def test_the_two_ids_the_pull_must_take_from_the_envelope_are_not_carried(self) -> None:
        # §4.10(f) P1-3: "The desktop sources receipt_id/execution_attempt_id from the
        # VERIFIED §4.9 signed envelope (authenticated values, not transport claims)."
        # `execution_attempt_id` IS carried (§4.6 names it, and §7.1 equality-checks it);
        # `receipt_id` is not, because §4.6 gives it no ok-arm slot and a transport copy of
        # a value the design forbids sourcing from transport is an invitation.
        receipt = gtb.reframe_turn_result(engine_signed())["receipt"]
        self.assertNotIn("receipt_id", receipt)
        self.assertNotIn("key_id", receipt)


# =====================================================================================
# What this hop can and cannot originate
# =====================================================================================


class OriginationTests(unittest.TestCase):
    def test_the_reframer_takes_the_supervisors_frame_and_nothing_else(self) -> None:
        # The structural half of "originates nothing": one parameter, and it is the
        # supervisor's document. There is no keyword through which a locally-chosen
        # `output_stream_id`, reason or signature could enter the result.
        import inspect

        sig = inspect.signature(gtb.reframe_turn_result)
        self.assertEqual(list(sig.parameters), ["engine_frame"])

    def test_a_reply_that_is_not_a_supervisor_frame_is_a_local_failure_not_a_verdict(self) -> None:
        # §4.10(f) P1-5's rule, applied to §4.10(e)'s hop: a peer that is not the
        # supervisor's handler has decided nothing, so this cannot become a `refused`
        # frame. It raises, and `engine_sidecar._dispatch` turns a raise on a governed hop
        # into the protocol-less `bridge.op.v1` document the desktop reads as out-of-band.
        for bad in (
            {},
            {"protocol": "brops.governed-result.v1", "status": "signed", "output": "hi"},
            {"protocol": "brops.governed-turn-result.v1", "status": "signed"},
            "not a document",
            None,
        ):
            with self.assertRaises(gtb.BridgeFrameError):
                gtb.reframe_turn_result(bad)

    def test_the_fault_is_not_a_supervisor_error_because_the_supervisor_did_not_fail(self) -> None:
        from governed_supervisor import SupervisorError

        self.assertFalse(issubclass(gtb.BridgeFrameError, SupervisorError))

    def test_the_builder_is_held_to_the_check_its_consumer_applies(self) -> None:
        # Every frame this module emits has already passed `validate_bridge_turn_result`,
        # so a producer bug surfaces here rather than as an unclassifiable document on the
        # desktop's stdin.
        frame = gtb.reframe_turn_result(engine_signed())
        self.assertIs(gtb.validate_bridge_turn_result(frame), frame)

    def test_a_producer_that_diverged_from_its_consumer_raises_rather_than_shipping(self) -> None:
        # The self-check inside `reframe_turn_result` exists for exactly ONE failure mode, and it
        # is not an input: a future edit that changes what the builder emits without changing what
        # the validator accepts. No document can reach it — every frame the builder produces is
        # well-formed by construction — so mutation testing found it unkillable by any fixture, and
        # this test CREATES the divergence instead of feeding one in. Without the self-check the
        # builder returns a frame its own consumer would reject, which is the drift the §4.10(e)
        # builder adopted the same discipline against.
        original = gtb.FRAME_FIELDS
        try:
            gtb.FRAME_FIELDS = original + ("result",)   # the consumer now demands a key
            with self.assertRaises(gtb.BridgeFrameError):
                gtb.reframe_turn_result(engine_signed())  # ...the producer does not emit
        finally:
            gtb.FRAME_FIELDS = original
        self.assertEqual(gtb.FRAME_FIELDS, original)
        gtb.reframe_turn_result(engine_signed())

    def test_a_frame_that_is_both_a_success_and_a_refusal_is_refused(self) -> None:
        frame = gtb.reframe_turn_result(engine_signed())
        frame["error"] = {"reason": "malformed", "receipt_id": None}
        with self.assertRaises(gtb.BridgeFrameError):
            gtb.validate_bridge_turn_result(frame)

    def test_a_refusal_may_not_smuggle_a_capability_token(self) -> None:
        # The token is the one member of this frame that grants the desktop an action. A
        # `refused` frame carrying one would be a Block that still invited a read.
        frame = gtb.reframe_turn_result(gtr.turn_result_refused("malformed"))
        frame["output_stream_id"] = b64url(43)
        with self.assertRaises(gtb.BridgeFrameError):
            gtb.validate_bridge_turn_result(frame)

    def test_a_refusal_may_not_smuggle_a_receipt(self) -> None:
        signed = gtb.reframe_turn_result(engine_signed())
        frame = gtb.reframe_turn_result(gtr.turn_result_refused("malformed"))
        frame["receipt"] = signed["receipt"]
        with self.assertRaises(gtb.BridgeFrameError):
            gtb.validate_bridge_turn_result(frame)

    def test_a_success_missing_any_of_the_three_signed_members_is_refused(self) -> None:
        # §4.10(e), quoted by §4.6: "A `signed` result REQUIRES `envelope_jcs_b64` +
        # `signature_b64` + `output_stream_id`; anything else ⇒ Block." Here that is a
        # consequence of the exhaustive key set rather than a separate clause, so the
        # predicate can never be PARTLY satisfied.
        for field in ("envelope_jcs_b64", "signature_b64"):
            frame = gtb.reframe_turn_result(engine_signed())
            del frame["receipt"][field]
            with self.assertRaises(gtb.BridgeFrameError):
                gtb.validate_bridge_turn_result(frame)
        frame = gtb.reframe_turn_result(engine_signed())
        frame["output_stream_id"] = None
        with self.assertRaises(gtb.BridgeFrameError):
            gtb.validate_bridge_turn_result(frame)

    def test_a_token_of_any_other_length_is_not_a_capability(self) -> None:
        for token in (b64url(40), b64url(44), ""):
            frame = gtb.reframe_turn_result(engine_signed())
            frame["output_stream_id"] = token
            with self.assertRaises(gtb.BridgeFrameError):
                gtb.validate_bridge_turn_result(frame)

    def test_a_non_canonical_base64url_field_is_refused_rather_than_re_encoded(self) -> None:
        # Two spellings of the same bytes in a field §7.1 later runs an equality check
        # against is exactly the ambiguity §4.10(a0)'s canonicality gate exists for.
        frame = gtb.reframe_turn_result(engine_signed())
        frame["receipt"]["envelope_jcs_b64"] = b64url(120)[:-1] + "="
        with self.assertRaises(gtb.BridgeFrameError):
            gtb.validate_bridge_turn_result(frame)

    def test_each_encoded_byte_cap_is_one_over_from_refusing(self) -> None:
        caps = {
            "envelope_jcs_b64": gtr.MAX_ENVELOPE_JCS_B64_LEN,
            "attestation_evidence_jcs_b64": gtr.MAX_ATTESTATION_EVIDENCE_JCS_B64_LEN,
            "containment_evidence_b64": gtr.MAX_CONTAINMENT_EVIDENCE_B64_LEN,
        }
        for field, cap in caps.items():
            frame = gtb.reframe_turn_result(engine_signed())
            frame["receipt"][field] = b64url(cap)
            gtb.validate_bridge_turn_result(frame)          # exactly at the cap: legal
            frame["receipt"][field] = b64url(cap + 4)
            with self.assertRaises(gtb.BridgeFrameError):    # over it: refused
                gtb.validate_bridge_turn_result(frame)

    def test_output_bytes_is_bounded_at_the_eight_mib_ceiling(self) -> None:
        frame = gtb.reframe_turn_result(engine_signed())
        frame["receipt"]["output_bytes"] = gtr.MAX_OUTPUT_BYTES
        gtb.validate_bridge_turn_result(frame)
        for bad in (gtr.MAX_OUTPUT_BYTES + 1, -1, True, "8"):
            frame["receipt"]["output_bytes"] = bad
            with self.assertRaises(gtb.BridgeFrameError):
                gtb.validate_bridge_turn_result(frame)

    def test_an_unknown_field_anywhere_is_refused(self) -> None:
        for mutate in (
            lambda f: f.__setitem__("result", "hello"),
            lambda f: f["receipt"].__setitem__("verified", True),
        ):
            frame = gtb.reframe_turn_result(engine_signed())
            mutate(frame)
            with self.assertRaises(gtb.BridgeFrameError):
                gtb.validate_bridge_turn_result(frame)
        frame = gtb.reframe_turn_result(gtr.turn_result_refused("malformed"))
        frame["error"]["stage"] = "staging-open"
        with self.assertRaises(gtb.BridgeFrameError):
            gtb.validate_bridge_turn_result(frame)

    def test_ok_must_be_a_boolean_not_a_truthy_value(self) -> None:
        for bad in (1, "true", None):
            frame = gtb.reframe_turn_result(engine_signed())
            frame["ok"] = bad
            with self.assertRaises(gtb.BridgeFrameError):
                gtb.validate_bridge_turn_result(frame)


# =====================================================================================
# The closed union
# =====================================================================================


class ClosedUnionTests(unittest.TestCase):
    def test_every_member_of_the_closed_union_is_reachable_by_name_through_this_hop(self) -> None:
        # The roll call. A member added to §4.5's union in the §4.10(e) module is a member
        # this test immediately demands a working relay for.
        for reason in gtr.GOVERNED_REFUSAL_REASONS:
            frame = gtb.reframe_turn_result(gtr.turn_result_refused(reason))
            self.assertEqual(frame["error"]["reason"], reason)
        self.assertEqual(len(gtr.GOVERNED_REFUSAL_REASONS), 29)

    def test_the_union_is_imported_not_restated(self) -> None:
        # §4.5's relay rule: the two metadata-result relay enums embed the exact literal
        # array, "never an inferred 'mirrors §4.5'". A second Python copy is the drift that
        # rule forbids, so the module's source must not contain one.
        source = pathlib.Path(gtb.__file__).read_text("utf-8")
        for reason in gtr.GOVERNED_REFUSAL_REASONS:
            self.assertNotIn('"%s"' % reason, source, reason)

    def test_a_reason_outside_the_union_never_reaches_the_desktop(self) -> None:
        # Internal producer codes (§4.10(a0)/(a)/(b)/(c)/(d), §2.1) are a DISJOINT namespace carried
        # by §4.10(h) (**NOT IMPLEMENTED**)'s diagnostic — NOT by this frame. `no_staging_row` under
        # this protocol would be a §4.10(h) internal refusal wearing a governed verdict's clothes,
        # and §4.10(h) classifies by the top-level discriminator.
        frame = gtb.reframe_turn_result(gtr.turn_result_refused("malformed"))
        for outside in ("no_staging_row", "peer_denied", "challenge_expired", "", None):
            frame["error"]["reason"] = outside
            with self.assertRaises(gtb.BridgeFrameError):
                gtb.validate_bridge_turn_result(frame)

    def test_two_reasons_spelled_the_same_in_both_namespaces_are_still_admitted(self) -> None:
        # `malformed` and `retry_conflict` are members of BOTH the closed governed union and the
        # internal producer sets. §4.10(h) (**NOT IMPLEMENTED**) calls the internal set disjoint,
        # and that is true of the NAMESPACE and false of the strings. Nothing here may depend on the
        # stronger reading: what separates them is the protocol const they arrive under.
        for shared in ("malformed", "retry_conflict"):
            frame = gtb.reframe_turn_result(gtr.turn_result_refused(shared))
            self.assertEqual(frame["error"]["reason"], shared)


# =====================================================================================
# §2.2 compatibility — the positive discriminator, both directions
# =====================================================================================


class DisjointnessTests(unittest.TestCase):
    def _bridge_result_valid(self, doc) -> bool:
        return jsonschema.Draft7Validator(_BRIDGE_RESULT_SCHEMA).is_valid(doc)

    def test_the_frozen_schema_rejects_a_governed_frame_on_the_unknown_protocol_key(self) -> None:
        # §2.2 test (5), first half. `bridge.result` is `additionalProperties:false` with no
        # `protocol` key, so it rejects this document on the top-level key alone.
        self.assertFalse(self._bridge_result_valid(gtb.reframe_turn_result(engine_signed())))

    def test_the_governed_validator_rejects_a_frozen_bridge_result(self) -> None:
        # §2.2 test (5), second half — and note WHAT it is rejected on. The frozen document
        # below carries `receipt.envelope_jcs_b64`, so a discriminator built on that key
        # would have admitted it. §4.6: "The earlier claim that `receipt.envelope_jcs_b64`
        # is 'absent from bridge.result' was FALSE — it is a REQUIRED key … and MUST NOT be
        # used to discriminate."
        frozen = {
            "ok": True,
            "result": "hello",
            "receipt": {
                "task_id": "t", "status": "completed", "exit_code": 0,
                "evidence": ["evidence:1"],
                "envelope_jcs_b64": b64url(120), "signature_b64": b64url(86),
            },
            "error": None,
        }
        self.assertTrue(self._bridge_result_valid(frozen))
        with self.assertRaises(gtb.BridgeFrameError):
            gtb.validate_bridge_turn_result(frozen)

    def test_the_discrimination_is_not_via_envelope_jcs_b64(self) -> None:
        governed = gtb.reframe_turn_result(engine_signed())
        self.assertIn("envelope_jcs_b64", governed["receipt"])
        self.assertIn("envelope_jcs_b64",
                      _BRIDGE_RESULT_SCHEMA["properties"]["receipt"]["properties"])
        # The key is present in BOTH, so it separates nothing. What separates them is the
        # top-level const, which is required here and forbidden there.
        self.assertNotIn("protocol", _BRIDGE_RESULT_SCHEMA["properties"])
        self.assertIs(_BRIDGE_RESULT_SCHEMA["additionalProperties"], False)
        self.assertIn("protocol", gtb.FRAME_FIELDS)

    def test_a_governed_frame_under_the_wrong_protocol_const_is_refused(self) -> None:
        for other in ("brops.governed-turn-result.v1", "bridge.governed-turn-diagnostic.v1",
                      "bridge.governed-turn-output-read-result.v1", ""):
            frame = gtb.reframe_turn_result(engine_signed())
            frame["protocol"] = other
            with self.assertRaises(gtb.BridgeFrameError):
                gtb.validate_bridge_turn_result(frame)

    def test_the_two_protocol_consts_differ_only_by_their_family_prefix(self) -> None:
        self.assertEqual(gtb.BRIDGE_TURN_RESULT_PROTOCOL,
                         "bridge." + gtr.GOVERNED_TURN_RESULT_PROTOCOL.split("brops.", 1)[1])

    def test_the_diagnostic_shape_can_never_satisfy_this_frame(self) -> None:
        # §4.10(h) (**NOT IMPLEMENTED**) requires its diagnostic to be unable to satisfy the
        # `signed` predicate. Pinned from this side too, so the day §4.10(h) lands the two shapes
        # are already proven non-confusable.
        diagnostic = {"protocol": "bridge.governed-turn-diagnostic.v1",
                      "stage": "staging-open", "upstream_reason": "no_staging_row"}
        with self.assertRaises(gtb.BridgeFrameError):
            gtb.validate_bridge_turn_result(diagnostic)


# =====================================================================================
# The arithmetic — constructed, never estimated
# =====================================================================================


class FrameArithmeticTests(unittest.TestCase):
    """Every bound on this frame's path, measured against the literal maximum instance.

    The conclusion is the reason this module ships no size check: nothing on the path can
    fire. Three pieces in this wave have declined to write a check the numbers proved
    unreachable; what stands in its place is these assertions, which fail if the numbers
    ever stop being true.
    """

    def setUp(self) -> None:
        self.engine_max = engine_max_signed()
        self.bridge_max = gtb.reframe_turn_result(self.engine_max)

    def test_the_literal_maximum_frame_is_the_number_this_module_publishes(self) -> None:
        compact = json.dumps(self.bridge_max, separators=(",", ":")).encode("utf-8")
        self.assertEqual(len(compact), 74_206)
        # ...and as `engine_sidecar.run` actually writes it: `json.dumps(reply)` with
        # DEFAULT separators, which costs 30 bytes of spacing on this shape. The number
        # that matters for a cap is the one that goes on the pipe, not the tidy one.
        as_written = json.dumps(self.bridge_max).encode("utf-8")
        self.assertEqual(len(as_written), 74_236)

    def test_the_desktop_stdout_bound_admits_it_with_a_factor_of_127_to_spare(self) -> None:
        # `ai.rs:44` — `const MAX_STDOUT_BYTES: u64 = 9 * 1024 * 1024;`
        max_stdout = 9 * 1024 * 1024
        self.assertEqual(max_stdout, 9_437_184)
        as_written = len(json.dumps(self.bridge_max).encode("utf-8"))
        self.assertLess(as_written, max_stdout)
        self.assertEqual(max_stdout - as_written, 9_362_948)
        self.assertGreater(max_stdout, as_written * 127)

    def test_re_framing_shrinks_the_document_so_a_fitting_input_always_fits_out(self) -> None:
        # The §4.10(e) reply crosses `brops_socket` under MAX_SIDECAR_FRAME_BYTES; the §4.6
        # frame crosses stdout. They are different bounds, but the ordering is what makes a
        # separate output check unnecessary: `receipt_id` and `key_id` are dropped and
        # `status` collapses into `ok`, against the cost of the nested `receipt`/`error`
        # keys, and the net is negative.
        engine_len = len(json.dumps(self.engine_max, separators=(",", ":")).encode("utf-8"))
        bridge_len = len(json.dumps(self.bridge_max, separators=(",", ":")).encode("utf-8"))
        self.assertEqual(engine_len, 74_472)
        self.assertEqual(engine_len - bridge_len, 266)

    def test_the_maximum_input_fits_the_socket_that_carries_it_here(self) -> None:
        import governed_staging_upload as gsu

        self.assertEqual(gsu.MAX_SIDECAR_FRAME_BYTES, 262_144)
        engine_len = len(json.dumps(self.engine_max, separators=(",", ":")).encode("utf-8"))
        self.assertLess(engine_len, gsu.MAX_SIDECAR_FRAME_BYTES)

    def test_neither_framed_ipc_bound_could_ever_carry_this_frame(self) -> None:
        # The bounds that do NOT admit it, and the reason this is a subprocess-stdio hop.
        # The supervisor's broker-facing frame bound and the desktop's own framed IPC
        # payload cap are both 8192 — 9.06x too small. A future "simplification" onto
        # either fails here rather than at the first large containment blob in production.
        import governed_supervisor_server as gss

        ipc_framing = (pathlib.Path(gtb.__file__).resolve().parents[1]
                       / "apps" / "desktop" / "src-tauri" / "core" / "src" / "ipc_framing.rs")
        self.assertIn("pub const MAX_FRAME_PAYLOAD_BYTES: usize = 8192;",
                      ipc_framing.read_text("utf-8"))
        self.assertEqual(gss.MAX_FRAME_BYTES, 8192)
        as_written = len(json.dumps(self.bridge_max).encode("utf-8"))
        self.assertGreater(as_written, gss.MAX_FRAME_BYTES * 9)

    def test_the_largest_refusal_is_under_three_hundred_bytes(self) -> None:
        # Two members tie at 23 characters (`stream_binding_mismatch`, `tcb_integrity_violation`), so
        # the longest is pinned by NAME and by length rather than by `max`, whose tie-break differs
        # from Rust's `max_by_key` and would have made the two hops assert different reasons.
        self.assertEqual(max(len(r) for r in gtr.GOVERNED_REFUSAL_REASONS), 23)
        self.assertEqual(len("stream_binding_mismatch"), 23)
        frame = gtb.reframe_turn_result(
            gtr.turn_result_refused("stream_binding_mismatch", "r" * 128))
        # 296 as `engine_sidecar.run` writes it; 284 compact, which is the number the Rust hop
        # asserts over the same instance.
        self.assertEqual(len(json.dumps(frame).encode("utf-8")), 296)
        self.assertEqual(len(json.dumps(frame, separators=(",", ":")).encode("utf-8")), 284)

    def test_the_module_ships_no_size_check_because_none_could_fire(self) -> None:
        source = pathlib.Path(gtb.__file__).read_text("utf-8")
        self.assertNotIn("MAX_FRAME_BYTES", source.split('"""', 2)[-1])
        self.assertNotIn("encode_frame", source)


# =====================================================================================
# The design gap, machine-checked
# =====================================================================================


class DesignGapTests(unittest.TestCase):
    def test_the_carried_and_uncarried_receipt_fields_are_exactly_the_designs_28(self) -> None:
        self.assertEqual(len(DESIGN_RECEIPT_FIELDS), 28)
        self.assertEqual(
            set(gtb.RECEIPT_FIELDS) | set(gtb.UNSOURCED_RECEIPT_FIELDS),
            set(DESIGN_RECEIPT_FIELDS),
        )
        # Disjoint: a name is either carried or declared unsourced, never both.
        self.assertEqual(set(gtb.RECEIPT_FIELDS) & set(gtb.UNSOURCED_RECEIPT_FIELDS), set())
        self.assertEqual(len(gtb.UNSOURCED_RECEIPT_FIELDS), 17)

    def test_every_carried_field_is_a_field_the_design_names(self) -> None:
        # The rule this hop follows: emit the INTERSECTION of §4.6's receipt keys with
        # §4.10(e)'s `signed` arm. Nothing invented, nothing renamed.
        self.assertTrue(set(gtb.RECEIPT_FIELDS) <= set(DESIGN_RECEIPT_FIELDS))
        self.assertTrue(set(gtb.RECEIPT_FIELDS) <= set(gtr.SIGNED_FIELDS))

    def test_the_seven_structurally_unobtainable_fields_are_named(self) -> None:
        # Three come from the frozen `bridge.result` shape (built from a `SupervisorResult`
        # the governed path never produces); four are resolved by the supervisor "from its
        # own supervisor state" (§4.10(a0)) and never returned on any reply the sidecar
        # receives — the §4.10(a0) reply is `{protocol, status, challenge_handle}`.
        for field in ("status", "exit_code", "evidence",
                      "challenge_registry_handle", "challenge_registry_hash",
                      "challenge_registry_epoch", "challenge_registry_root_key_id"):
            self.assertIn(field, gtb.UNSOURCED_RECEIPT_FIELDS, field)

    def test_status_is_a_homonym_and_the_two_meanings_are_kept_apart(self) -> None:
        # The one name that appears on both sides for two different reasons, and the trap
        # a reader would otherwise fall into. §4.10(e)'s top-level `status` is the ARM
        # DISCRIMINATOR and is consumed — it becomes `ok`. §4.6's `receipt.status` is the
        # frozen `bridge.result` RUN status ("completed"), which the governed path never
        # produces. Carrying the first into the second would put the literal "signed" in a
        # field a reader would take as the run's outcome.
        self.assertIn("status", gtr.SIGNED_FIELDS)
        self.assertIn("status", gtb.CONSUMED_BY_THE_OUTER_OBJECT)
        self.assertIn("status", gtb.UNSOURCED_RECEIPT_FIELDS)
        self.assertIn("status", _BRIDGE_RESULT_SCHEMA["properties"]["receipt"]["properties"])
        engine = engine_signed()
        self.assertEqual(engine["status"], "signed")
        frame = gtb.reframe_turn_result(engine)
        self.assertNotIn("status", frame)
        self.assertNotIn("status", frame["receipt"])

    def test_the_six_uncarried_fields_that_ARE_obtainable_are_in_the_signed_envelope(self) -> None:
        # The other half of the gap, and the reason it is not closed. These six sit inside
        # `envelope_jcs_b64`, which this frame already carries whole. Copying them out here
        # would give §7.1 an equality check that compares a document against itself — it
        # could not fail for any input, hostile or otherwise, which is the class this
        # repository keeps producing. They stay declared-unsourced rather than faked.
        for field in ("task_id", "challenge_accepted_at_ms", "lease_handle",
                      "execution_receipt_handle", "evidence_event_count",
                      "evidence_final_event_hash"):
            self.assertIn(field, gtb.UNSOURCED_RECEIPT_FIELDS, field)
            self.assertNotIn(field, gtb.RECEIPT_FIELDS, field)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
