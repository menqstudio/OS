"""Offline tests for the supervisor→sidecar result frame — rev-30 §4.10(e)
(+ §2.2, §4.5's closed union, and §4.10(f)/§4.10(h) which are NOT IMPLEMENTED).

No socket, no key material, no database, no clock. §4.10(e) is a SHAPE — the single frame
in which a finished governed turn travels back to the compromised-in-scope sidecar — so
everything below is about what the shape can and cannot express.

The tests are organized as the design's own obligations:

  * every field of both arms is violated ONE AT A TIME against an otherwise-valid frame,
    and each failure is asserted BY THE FIELD NAME it names, so a check that has been
    deleted cannot hide behind a neighbour that fires first;
  * the closed ``GOVERNED_REFUSAL_REASONS`` union is complete, deduplicated, and its
    ratified half is compared VERBATIM against the frozen
    ``engine/contracts/brops-sign-result.v1.schema.json`` enum — the copy that already
    shipped — so the two cannot drift;
  * no member of that union is REACHABLE as a decision from anything in this tree, and
    ``TheClosedUnionIsNotDecidedHereTests`` says so in its name: every producing gate is a
    §5/§7 gate and §5 acceptance is **NOT IMPLEMENTED**. What IS proved is that all 29 are
    constructible by name, which is the whole of what §4.10(e) owns;
  * the frame cap is proved by CONSTRUCTING the literal maximum instance and printing the
    number into an assertion, which is why no frame-size check exists in the module;
  * ``NothingGovernedIsMintedTests`` reads the module's own import graph: with no clock, no
    entropy source and no database in it, §4.10(e) cannot mint an ``execution_attempt_id``,
    stamp an acceptance time or persist a verdict even by accident.

No prerequisite here is optional. Everything is stdlib plus repo modules, imported at
module scope with no ``try``/``except`` and no ``skipIf``, so a missing prerequisite is an
unmissable hard error rather than a green run with a quiet skip. (There is no
``BROPS_TEST_MISSING_PREREQUISITES`` declaration anywhere in this tree, so nothing is
declared in it and nothing here may be softened.)
"""

import ast
import base64
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import brops_protocol as bp  # noqa: E402
import governed_evidence_request as ger  # noqa: E402
import governed_staging_upload as gsu  # noqa: E402
import governed_supervisor_server as gss  # noqa: E402
import governed_turn_open as gto  # noqa: E402
import governed_turn_result as gtr  # noqa: E402
from governed_supervisor import SupervisorError  # noqa: E402

RUNTIME = ROOT / "runtime" / "governed_turn_result.py"
FROZEN_SIGN_RESULT_SCHEMA = ROOT / "contracts" / "brops-sign-result.v1.schema.json"
FROZEN_SUPERVISOR_SERVICE = ROOT / "tools" / "brops_supervisor_service.py"


def b64(n: int) -> str:
    """`n` bytes of 0xff as canonical base64url. `n` divisible by 3 gives an unpadded
    string of exactly `4n/3` chars, which is how the design's encoded-byte caps are
    expressed."""
    return base64.urlsafe_b64encode(b"\xff" * n).decode("ascii").rstrip("=")


#: A valid `signed` frame with every field comfortably inside its bound. Each shape test
#: below mutates EXACTLY ONE key of a copy of this, so a failure is attributable to that
#: key and to nothing that ran before it.
def signed_frame(**overrides):
    frame = gtr.turn_result_signed(
        receipt_id="rcpt-0001",
        output_stream_id=b64(32),
        output_bytes=4096,
        output_sha256="b" * 64,
        envelope_jcs_b64=b64(300),
        signature_b64=b64(64),
        key_id="isolated-signer-1",
        attestation_evidence_jcs_b64=b64(600),
        attestation_signature_b64=b64(64),
        supervisor_attestation_key_id="sup-attest-1",
        containment_evidence_b64=b64(120),
        run_id="run-0001",
        execution_attempt_id="attempt-0001",
        lease_id="lease-0001",
    )
    frame.update(overrides)
    return frame


def signed_frame_builder(**overrides):
    """The same fields, but handed to the BUILDER rather than patched into a frame it
    already validated. `signed_frame` mutates a built dict, which is right for testing the
    validator in isolation and wrong for testing that the builder validates at all."""
    kwargs = dict(
        receipt_id="rcpt-0001", output_stream_id=b64(32), output_bytes=4096,
        output_sha256="b" * 64, envelope_jcs_b64=b64(300), signature_b64=b64(64),
        key_id="isolated-signer-1", attestation_evidence_jcs_b64=b64(600),
        attestation_signature_b64=b64(64), supervisor_attestation_key_id="sup-attest-1",
        containment_evidence_b64=b64(120), run_id="run-0001",
        execution_attempt_id="attempt-0001", lease_id="lease-0001",
    )
    kwargs.update(overrides)
    return gtr.turn_result_signed(**kwargs)


def refused_frame(**overrides):
    frame = gtr.turn_result_refused("lease_not_ready", receipt_id=None)
    frame.update(overrides)
    return frame


# ---------------------------------------------------------------------------
# The two arms, positively
# ---------------------------------------------------------------------------


class ArmsTests(unittest.TestCase):
    def test_the_signed_arm_carries_exactly_the_sixteen_design_fields(self):
        self.assertEqual(set(signed_frame()), set(gtr.SIGNED_FIELDS))
        self.assertEqual(len(gtr.SIGNED_FIELDS), 16)
        self.assertEqual(len(set(gtr.SIGNED_FIELDS)), 16)

    def test_the_refused_arm_carries_exactly_the_four_design_fields(self):
        self.assertEqual(set(refused_frame()), set(gtr.REFUSED_FIELDS))
        self.assertEqual(gtr.REFUSED_FIELDS,
                         ("protocol", "status", "receipt_id", "reason"))

    def test_both_arms_share_one_protocol_const_and_differ_only_by_status(self):
        self.assertEqual(signed_frame()["protocol"], gtr.GOVERNED_TURN_RESULT_PROTOCOL)
        self.assertEqual(refused_frame()["protocol"], gtr.GOVERNED_TURN_RESULT_PROTOCOL)
        self.assertEqual(signed_frame()["status"], "signed")
        self.assertEqual(refused_frame()["status"], "refused")

    def test_a_valid_frame_of_either_arm_validates(self):
        self.assertEqual(gtr.validate_turn_result(signed_frame()), signed_frame())
        self.assertEqual(gtr.validate_turn_result(refused_frame()), refused_frame())

    def test_a_refused_frame_may_name_a_receipt_or_explicitly_none(self):
        """§4.10(e): `"receipt_id": "<string ≤128>" | null`. Both are frames; a MISSING key
        is not, so "no receipt" and "the field was forgotten" stay distinguishable."""
        self.assertIsNone(refused_frame()["receipt_id"])
        named = gtr.turn_result_refused("hash_mismatch", receipt_id="rcpt-9")
        self.assertEqual(named["receipt_id"], "rcpt-9")
        with self.assertRaisesRegex(SupervisorError, "missing field"):
            gtr.validate_turn_result({"protocol": gtr.GOVERNED_TURN_RESULT_PROTOCOL,
                                      "status": "refused", "reason": "hash_mismatch"})

    def test_containment_evidence_is_the_one_nullable_member_of_the_signed_arm(self):
        """§4.10(e): `"containment_evidence_b64": "<b64url ≤ 65536 bytes>" | null`. Every
        other member is non-null, and this test walks all fifteen to prove it rather than
        asserting the one."""
        gtr.validate_turn_result(signed_frame(containment_evidence_b64=None))
        for field in gtr.SIGNED_FIELDS:
            if field == "containment_evidence_b64":
                continue
            with self.subTest(field=field):
                with self.assertRaises(SupervisorError):
                    gtr.validate_turn_result(signed_frame(**{field: None}))

    def test_the_signed_builder_will_not_build_an_invalid_frame(self):
        """The builder runs the validator over what it builds, so a supervisor cannot emit
        a frame its own consumer would reject. Each of these is a different check inside
        the validator, reached THROUGH the builder rather than around it."""
        for bad in ({"output_bytes": -1}, {"output_sha256": "Z" * 64},
                    {"signature_b64": "short"}, {"receipt_id": ""},
                    {"output_stream_id": "!" * 43}, {"envelope_jcs_b64": None}):
            with self.subTest(bad=bad):
                with self.assertRaises(SupervisorError):
                    signed_frame_builder(**bad)

    def test_the_builders_are_pure_and_return_independent_objects(self):
        first, second = signed_frame(), signed_frame()
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        first["receipt_id"] = "mutated"
        self.assertNotEqual(first, second)


# ---------------------------------------------------------------------------
# The exhaustive shape: one violation at a time, each named
# ---------------------------------------------------------------------------


class SignedShapeTests(unittest.TestCase):
    def bad(self, pattern, **overrides):
        with self.assertRaisesRegex(SupervisorError, pattern):
            gtr.validate_turn_result(signed_frame(**overrides))

    def test_an_unknown_field_is_refused_before_anything_else(self):
        self.bad(r"unexpected field\(s\) \['output'\]", output="hello")
        self.bad(r"unexpected field\(s\)", execution_started_marker="x")

    def test_a_missing_field_is_refused_by_name(self):
        for field in gtr.SIGNED_FIELDS:
            if field in ("protocol", "status"):
                continue          # removing these changes which arm is even selected
            with self.subTest(field=field):
                frame = signed_frame()
                del frame[field]
                with self.assertRaisesRegex(SupervisorError,
                                            r"missing field\(s\) \['%s'\]" % field):
                    gtr.validate_turn_result(frame)

    def test_receipt_id_must_be_a_bounded_non_empty_string(self):
        self.bad("receipt_id must be a 1..128 char string", receipt_id="")
        self.bad("receipt_id must be a 1..128 char string", receipt_id="r" * 129)
        self.bad("receipt_id must be a 1..128 char string", receipt_id=7)
        gtr.validate_turn_result(signed_frame(receipt_id="r" * 128))

    def test_output_stream_id_must_be_exactly_the_43_char_capability(self):
        self.bad("output_stream_id must be exactly 43", output_stream_id=b64(30))
        self.bad("output_stream_id must be exactly 43", output_stream_id=b64(33))
        self.bad("output_stream_id must be exactly 43", output_stream_id="")
        self.bad("output_stream_id must be a base64url string", output_stream_id=32)

    def test_output_stream_id_must_be_canonical_base64url(self):
        """A 43-char string is not automatically a capability: `+`/`/` are not the URL
        alphabet, and a 43-char value whose final character carries bits the 32 bytes do
        not have is a SECOND spelling of the same capability. `decode_base64url`
        re-encodes and compares, so both are refused."""
        self.bad("output_stream_id is not canonical base64url",
                 output_stream_id="+" + b64(32)[1:])
        noncanonical = b64(32)[:-1] + "B"      # 43 chars, decodes, re-encodes differently
        self.assertNotEqual(noncanonical, b64(32))
        self.bad("output_stream_id is not canonical base64url",
                 output_stream_id=noncanonical)

    def test_output_bytes_is_an_integer_inside_the_design_range(self):
        self.bad("output_bytes must be an integer", output_bytes="4096")
        self.bad("output_bytes must be an integer", output_bytes=True)
        self.bad("output_bytes must be 0..8388608", output_bytes=-1)
        self.bad("output_bytes must be 0..8388608", output_bytes=8388609)
        for edge in (0, 8388608):
            with self.subTest(edge=edge):
                gtr.validate_turn_result(signed_frame(output_bytes=edge))

    def test_output_sha256_must_be_lowercase_64_hex(self):
        self.bad("output_sha256 must be lowercase 64-hex", output_sha256="B" * 64)
        self.bad("output_sha256 must be lowercase 64-hex", output_sha256="b" * 63)
        self.bad("output_sha256 must be lowercase 64-hex", output_sha256="b" * 65)

    def test_the_two_signatures_must_be_exactly_86_base64url_chars(self):
        for field in ("signature_b64", "attestation_signature_b64"):
            with self.subTest(field=field):
                self.bad("%s must be exactly 86" % field, **{field: b64(63)})
                self.bad("%s must be exactly 86" % field, **{field: b64(66)})
                self.bad("%s is not canonical base64url" % field,
                         **{field: "*" + b64(64)[1:]})

    def test_the_two_jcs_documents_are_bounded_on_their_ENCODED_length(self):
        """§4.6 freezes `envelope_jcs_b64 ≤ 2848` and `attestation_evidence_jcs_b64 ≤ 4664`
        as ENCODED-byte caps, so the boundary is on the string, not on what it decodes to.
        Both edges are walked."""
        for field, cap, raw in (("envelope_jcs_b64", 2848, 2136),
                                ("attestation_evidence_jcs_b64", 4664, 3498)):
            with self.subTest(field=field):
                self.assertEqual(len(b64(raw)), cap)
                gtr.validate_turn_result(signed_frame(**{field: b64(raw)}))
                self.bad("%s must be 1..%d" % (field, cap), **{field: b64(raw + 3)})
                self.bad("%s must be 1..%d" % (field, cap), **{field: ""})

    def test_containment_evidence_is_bounded_at_65536_encoded_chars(self):
        self.assertEqual(len(b64(49152)), 65536)
        gtr.validate_turn_result(signed_frame(containment_evidence_b64=b64(49152)))
        self.bad("containment_evidence_b64 must be 1..65536",
                 containment_evidence_b64=b64(49155))

    def test_an_empty_containment_report_is_not_a_report(self):
        """§4.10(e) offers a value OR null, and `""` is neither. §5's v2 amendment, clause
        (j), says the same thing from the other end: "a missing or empty report is a
        REFUSAL, not a fallback". A supervisor with nothing to say says `null`."""
        self.bad("containment_evidence_b64 must be 1..65536", containment_evidence_b64="")

    def test_the_four_identity_echoes_are_bounded_ids(self):
        for field in ("key_id", "supervisor_attestation_key_id", "run_id",
                      "execution_attempt_id", "lease_id"):
            with self.subTest(field=field):
                self.bad("%s must be a 1..128 char string" % field, **{field: ""})
                self.bad("%s must be a 1..128 char string" % field, **{field: "x" * 129})


class RefusedShapeTests(unittest.TestCase):
    def bad(self, pattern, **overrides):
        with self.assertRaisesRegex(SupervisorError, pattern):
            gtr.validate_turn_result(refused_frame(**overrides))

    def test_an_unknown_field_is_refused(self):
        self.bad(r"unexpected field\(s\) \['output_stream_id'\]",
                 output_stream_id=b64(32))

    def test_the_signed_arms_fields_are_unknown_here(self):
        """The two arms are not a superset and a subset: a `refused` frame carrying the
        `signed` arm's evidence is refused, so a refusal can never be dressed up as a
        verdict by adding keys to it."""
        self.bad(r"unexpected field\(s\)", envelope_jcs_b64=b64(300),
                 signature_b64=b64(64))

    def test_a_reason_outside_the_closed_union_is_a_supervisor_fault(self):
        for bad in ("looks_plausible", "no_inputs_ready", "quota_turns", "peer_denied",
                    "session_corrupt", "noncanonical", "", None, 7):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(
                        SupervisorError, "is not in the brops.governed-turn-result.v1"):
                    gtr.validate_turn_result(refused_frame(reason=bad))

    def test_the_builder_refuses_an_off_contract_reason_before_it_can_ship(self):
        with self.assertRaises(SupervisorError):
            gtr.turn_result_refused("no_inputs_ready")

    def test_receipt_id_is_a_bounded_string_when_it_is_not_null(self):
        self.bad("receipt_id must be a 1..128 char string", receipt_id="")
        self.bad("receipt_id must be a 1..128 char string", receipt_id="r" * 129)
        self.bad("receipt_id must be a 1..128 char string", receipt_id=7)


class DiscriminatorTests(unittest.TestCase):
    def test_a_frame_that_is_not_an_object_is_refused(self):
        for bad in (None, "signed", 7, ["x"], b"{}"):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(SupervisorError, "must be a JSON object"):
                    gtr.validate_turn_result(bad)

    def test_an_unknown_status_selects_no_arm_at_all(self):
        for bad in ("SIGNED", "ok", "published", "opened", "ack", None, True):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(SupervisorError, "status must be"):
                    gtr.validate_turn_result(signed_frame(status=bad))

    def test_the_protocol_const_is_required_on_both_arms(self):
        for build in (signed_frame, refused_frame):
            for wrong in ("brops.governed-result.v1", "brops.governed-sign-result.v1",
                          "bridge.governed-turn-result.v1",
                          "brops.governed-evidence-request-result.v1", "", None):
                with self.subTest(build=build.__name__, wrong=wrong):
                    with self.assertRaisesRegex(SupervisorError, "unexpected protocol"):
                        gtr.validate_turn_result(build(protocol=wrong))


# ---------------------------------------------------------------------------
# The closed §4.5 union that §4.10(e) embeds
# ---------------------------------------------------------------------------


class ClosedUnionTests(unittest.TestCase):
    def test_the_union_is_twenty_nine_members_with_no_duplicates(self):
        self.assertEqual(len(gtr.GOVERNED_REFUSAL_REASONS), 29)
        self.assertEqual(len(set(gtr.GOVERNED_REFUSAL_REASONS)), 29)
        self.assertEqual(len(gtr.RATIFIED_REFUSAL_REASONS), 12)
        self.assertEqual(len(gtr.GOVERNED_ADDED_REFUSAL_REASONS), 17)
        self.assertEqual(
            gtr.GOVERNED_REFUSAL_REASONS,
            gtr.RATIFIED_REFUSAL_REASONS + gtr.GOVERNED_ADDED_REFUSAL_REASONS)

    def test_the_ratified_twelve_are_the_FROZEN_schema_enum_verbatim(self):
        """§4.5 builds its union from "the ratified 12" of `brops.sign-result.v1`, and §2.2
        freezes that schema byte-for-byte. So the twelve are not re-typed from the design
        prose here — they are compared against the shipped schema file, in order. If either
        moves, this fails, which is the only way "verbatim" means anything."""
        schema = json.loads(FROZEN_SIGN_RESULT_SCHEMA.read_text(encoding="utf-8"))
        frozen = None
        for clause in schema["allOf"]:
            then = clause.get("then", {})
            reason = then.get("properties", {}).get("reason")
            if reason is not None:
                frozen = tuple(reason["enum"])
        self.assertIsNotNone(frozen, "the frozen schema no longer declares a reason enum")
        self.assertEqual(gtr.RATIFIED_REFUSAL_REASONS, frozen)

    def test_the_governed_additions_are_disjoint_from_the_ratified_twelve(self):
        self.assertEqual(
            set(gtr.RATIFIED_REFUSAL_REASONS) & set(gtr.GOVERNED_ADDED_REFUSAL_REASONS),
            set())

    def test_every_member_is_constructible_by_name(self):
        for reason in gtr.GOVERNED_REFUSAL_REASONS:
            with self.subTest(reason=reason):
                frame = gtr.turn_result_refused(reason)
                self.assertEqual(frame["reason"], reason)
                self.assertEqual(frame["protocol"], gtr.GOVERNED_TURN_RESULT_PROTOCOL)

    def test_the_union_is_NOT_disjoint_by_value_from_the_internal_codes(self):
        """§4.10(h) (NOT IMPLEMENTED) calls the §4.10(a0/a/b/c/d) internal producer codes "a
        **disjoint** namespace from `GOVERNED_REFUSAL_REASONS`". Read as a claim about the
        STRINGS that is FALSE, and this pins exactly how false across every internal set in
        the tree. Nothing in §4.10(e) may depend on the stronger reading."""
        internal = (set(ger.EVIDENCE_REQUEST_REFUSAL_REASONS)
                    | set(gsu.STAGING_OPEN_REFUSAL_REASONS)
                    | set(gsu.STAGING_CHUNK_REFUSAL_REASONS)
                    | set(gsu.STAGING_FINAL_REFUSAL_REASONS)
                    | set(gto.OPEN_REFUSAL_REASONS))
        self.assertEqual(internal & set(gtr.GOVERNED_REFUSAL_REASONS),
                         {"malformed", "retry_conflict", "oversize"})

    def test_the_discriminator_is_what_actually_separates_them(self):
        """So the separation is structural. The same string under two protocol consts is
        two different verdicts, and only the const says which."""
        governed = gtr.turn_result_refused("retry_conflict")
        internal = ger.evidence_request_refused("retry_conflict")
        self.assertEqual(governed["reason"], internal["reason"])
        self.assertNotEqual(governed["protocol"], internal["protocol"])


class TheClosedUnionIsNotDecidedHereTests(unittest.TestCase):
    """MARKED, in the manner step 2 marked three of its 29 reasons and step 3 marked one.

    Not one member of ``GOVERNED_REFUSAL_REASONS`` is REACHABLE as a decision from a frame
    a hostile sidecar could send — not because the sidecar is trusted, but because §4.10(e)
    decides nothing. Every producing gate named in §4.5 is a §5 acceptance or §7
    verification gate (`challenge_replay` at the §5 CAS, `lease_not_ready` at the execute
    trigger, `stale_evidence` at §7 case A, and so on), and §5 acceptance is **NOT
    IMPLEMENTED** — its continuation is still an injected seam with no production supplier.

    What §4.10(e) owns is the VOCABULARY, and that is what the tests above cover: all 29
    constructible by name, none producible by this module. Reading a green suite here as
    "the governed refusals work" would be reading it wrong, so it is written down.
    """

    def test_this_module_decides_nothing_it_only_expresses(self):
        source = RUNTIME.read_text(encoding="utf-8")
        tree = ast.parse(source)
        produced = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in gtr.GOVERNED_REFUSAL_REASONS:
                    produced.add(node.value)
        # The literals appear ONLY inside the two closed tuples — never as an argument to
        # a builder, never in a branch. A `turn_result_refused("...")` call anywhere in the
        # runtime module would be this module deciding, and there is none.
        self.assertNotIn("turn_result_refused(\"", source)
        self.assertEqual(produced, set(gtr.GOVERNED_REFUSAL_REASONS))

    def test_the_sidecar_may_not_send_this_protocol_at_all(self):
        """§4.10(h) (**NOT IMPLEMENTED** — a later ordered piece): "The sidecar originates
        **no** governed verdict". That half of it holds here already, for a structural
        reason: the front door's grant is a closed tuple of five REQUEST protocols, and
        §4.10(e) is a REPLY, so a sidecar presenting one is refused as an unauthorized
        frame before any handler sees it."""
        self.assertNotIn(gtr.GOVERNED_TURN_RESULT_PROTOCOL, gss.SIDECAR_PROTOCOLS)
        self.assertEqual(len(gss.SIDECAR_PROTOCOLS), 5)


# ---------------------------------------------------------------------------
# Arithmetic, done first and asserted rather than commented
# ---------------------------------------------------------------------------


class FrameFitTests(unittest.TestCase):
    #: Every string field at its exact cap, `output_bytes` at 8388608, containment at its
    #: full 65536. There is no larger legal §4.10(e) frame than this one.
    @staticmethod
    def maximum():
        return gtr.turn_result_signed(
            receipt_id="r" * 128,
            output_stream_id=b64(32),
            output_bytes=gtr.MAX_OUTPUT_BYTES,
            output_sha256="f" * 64,
            envelope_jcs_b64=b64(2136),
            signature_b64=b64(64),
            key_id="k" * 128,
            attestation_evidence_jcs_b64=b64(3498),
            attestation_signature_b64=b64(64),
            supervisor_attestation_key_id="s" * 128,
            containment_evidence_b64=b64(49152),
            run_id="u" * 128,
            execution_attempt_id="e" * 128,
            lease_id="l" * 128,
        )

    def test_the_literal_maximum_signed_frame_fits(self):
        """§4.10(e): "Frame ≤ `MAX_FRAME_BYTES = 262144`". No approximate proof: the
        maximum instance is constructed and measured. 74472 ≤ 262144, with 187672 bytes to
        spare — which is WHY this module carries no frame-size check. A check that cannot
        fire reads as protection while protecting nothing (step 2 deleted one; step 3
        declined to write one), so the bound is asserted here and enforced only where it
        can actually bind: the transport's own `encode_frame`."""
        body = json.dumps(self.maximum(), separators=(",", ":"),
                          ensure_ascii=False).encode("utf-8")
        self.assertEqual(len(body), 74472)
        self.assertEqual(gtr.MAX_TURN_RESULT_FRAME_BYTES, 262144)
        self.assertLessEqual(len(body), gtr.MAX_TURN_RESULT_FRAME_BYTES)
        self.assertEqual(gtr.MAX_TURN_RESULT_FRAME_BYTES - len(body), 187672)

    def test_the_maximum_frame_survives_the_real_transport_encoder(self):
        framed = bp.encode_frame(self.maximum())
        self.assertEqual(len(framed), 74472 + 4)      # 4-byte big-endian length prefix
        self.assertEqual(bp.strict_loads(framed[4:]), self.maximum())

    def test_the_cap_is_the_shared_transport_constant_not_a_private_copy(self):
        """§4.10(e) names `MAX_FRAME_BYTES` itself, unlike §4.10(a)/(c)/(d) which each fix
        their own 4 KiB. So it is imported: the two cannot drift apart."""
        self.assertIs(gtr.MAX_TURN_RESULT_FRAME_BYTES, bp.MAX_FRAME_BYTES)

    def test_an_inline_output_could_not_have_fitted(self):
        """§4.6's reason for the pull: a full-schema frame carrying the output inline
        "provably OVERFLOWS 262144". Only the 8 MiB ceiling is needed to see it — the
        base64url of a maximum output alone is 11184812 bytes, 42x the whole frame cap."""
        inline = 4 * ((gtr.MAX_OUTPUT_BYTES + 2) // 3)
        self.assertEqual(inline, 11184812)
        self.assertGreater(inline, gtr.MAX_TURN_RESULT_FRAME_BYTES)


class DecodedLengthTests(unittest.TestCase):
    def test_the_length_checks_already_pin_the_decoded_byte_counts(self):
        """Why there is no `len(decoded) == 64` line in the module: there could not be one
        that fires. 86 canonical base64url chars decode to exactly 64 bytes and 43 to
        exactly 32 — the canonicality round-trip in `decode_base64url` removes the only
        freedom the trailing bits would otherwise have. This walks every canonical string
        of each length that the encoder can produce for a neighbouring byte count, and
        shows none has the right length."""
        for chars, raw in ((gtr.SIGNATURE_B64_LEN, 64), (gtr.OUTPUT_STREAM_ID_LEN, 32)):
            with self.subTest(chars=chars):
                self.assertEqual(len(b64(raw)), chars)
                self.assertEqual(len(bp.decode_base64url(b64(raw))), raw)
                for neighbour in (raw - 2, raw - 1, raw + 1, raw + 2):
                    self.assertNotEqual(len(b64(neighbour)), chars)


# ---------------------------------------------------------------------------
# §2.2 — the frozen 3b-1A family and the new governed family reject each other
# ---------------------------------------------------------------------------


class FrozenProtocolCoexistenceTests(unittest.TestCase):
    #: The exact shipped 3b-1A `signed` document, quoted from §2.2: "{protocol, status,
    #: output (top-level string), receipt:{...}}". It is written out here — not imported —
    #: because importing it would couple the frozen path to the new one, which is the
    #: coupling §2.2 forbids.
    FROZEN_SIGNED = {
        "protocol": "brops.governed-result.v1",
        "status": "signed",
        "output": "hello",
        "receipt": {"envelope_jcs_b64": "AAAA", "signature_b64": "BBBB"},
    }
    FROZEN_REFUSED = {
        "protocol": "brops.governed-result.v1",
        "status": "refused",
        "reason": "malformed",
    }

    def test_the_new_name_is_not_the_frozen_name(self):
        self.assertEqual(gtr.GOVERNED_TURN_RESULT_PROTOCOL,
                         "brops.governed-turn-result.v1")
        self.assertNotEqual(gtr.GOVERNED_TURN_RESULT_PROTOCOL,
                            "brops.governed-result.v1")

    def test_the_frozen_constant_and_emitter_are_still_where_they_were(self):
        """§2.2 "KEEP + ADD, never rename": the shipped `GOVERNED_RESULT_PROTOCOL` constant
        and its emitter stay byte-for-byte. This reads the frozen file rather than importing
        it, so the assertion holds without pulling that module's environment into this
        test."""
        text = FROZEN_SUPERVISOR_SERVICE.read_text(encoding="utf-8")
        self.assertIn('GOVERNED_RESULT_PROTOCOL = "brops.governed-result.v1"', text)
        self.assertNotIn(gtr.GOVERNED_TURN_RESULT_PROTOCOL, text)

    def test_a_frozen_document_fed_to_the_new_validator_is_refused(self):
        """§2.2 compatibility rule, one direction: "the new governed path accepts ONLY
        new-governed documents and refuses any frozen document"."""
        for doc in (self.FROZEN_SIGNED, self.FROZEN_REFUSED):
            with self.subTest(status=doc["status"]):
                with self.assertRaises(SupervisorError):
                    gtr.validate_turn_result(doc)

    def test_the_frozen_document_is_refused_on_TWO_independent_grounds(self):
        """Not only the discriminator. The frozen `signed` shape carries a top-level
        `output` and a nested `receipt`, neither of which is a §4.10(e) field, so even a
        frozen document relabelled with the new protocol const is refused — which is the
        property that keeps output out of this frame."""
        relabelled = dict(self.FROZEN_SIGNED,
                          protocol=gtr.GOVERNED_TURN_RESULT_PROTOCOL)
        with self.assertRaisesRegex(SupervisorError, r"unexpected field\(s\)"):
            gtr.validate_turn_result(relabelled)

    def test_a_new_document_is_not_a_frozen_document(self):
        """The other direction, as far as this piece can prove it. The frozen CONSUMER is
        `bridge/engine_sidecar.py`'s `_GovernedOutcome` and its new branch is §4.10(g)
        (**NOT IMPLEMENTED** — a later ordered piece), so what is proved here is the
        structural half: a §4.10(e) frame has neither of the two keys that consumer reads,
        so it can carry no output and no receipt into it."""
        frame = signed_frame()
        self.assertNotIn("output", frame)
        self.assertNotIn("receipt", frame)


# ---------------------------------------------------------------------------
# Nothing governed is minted here
# ---------------------------------------------------------------------------


class NothingGovernedIsMintedTests(unittest.TestCase):
    """§4.10(e) transports a verdict §5 reached. It must not be able to CREATE one.

    §5 mints `execution_attempt_id`, stamps `challenge_accepted_at_ms` from the one
    acceptance clock read, consumes the challenge nonce and persists the acceptance row.
    §4.10(e) names none of those as its own: every identifier in a `signed` frame is an
    ECHO the caller supplies. This class proves that structurally, from the module's own
    import graph, rather than by inspection.
    """

    #: Exactly what the module may import. A clock, an entropy source, a database driver or
    #: a filesystem module appearing here would mean §4.10(e) had acquired the ability to
    #: mint, stamp or persist — so the set is asserted equal, not merely checked for
    #: absence of a list somebody thought of.
    ALLOWED = {
        "__future__", "typing", "brops_protocol", "governed_staging_upload",
        "governed_supervisor",
    }

    def imported(self):
        tree = ast.parse(RUNTIME.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        return names

    def test_the_module_imports_no_clock_no_entropy_and_no_database(self):
        self.assertEqual(self.imported(), self.ALLOWED)
        for forbidden in ("time", "datetime", "secrets", "random", "uuid", "sqlite3",
                          "os", "pathlib", "hashlib"):
            self.assertNotIn(forbidden, self.imported())

    def test_the_signed_builder_supplies_no_identifier_of_its_own(self):
        """Every one of the fourteen is REQUIRED and keyword-only: there is no default, so
        a caller cannot obtain a frame in which this module chose a value. Omitting any one
        is a TypeError, not a frame with a blank in it."""
        full = dict(
            receipt_id="r", output_stream_id=b64(32), output_bytes=0,
            output_sha256="a" * 64, envelope_jcs_b64=b64(30), signature_b64=b64(64),
            key_id="k", attestation_evidence_jcs_b64=b64(30),
            attestation_signature_b64=b64(64), supervisor_attestation_key_id="s",
            containment_evidence_b64=None, run_id="u", execution_attempt_id="e",
            lease_id="l",
        )
        self.assertEqual(len(full), 14)
        gtr.turn_result_signed(**full)
        for field in full:
            with self.subTest(field=field):
                partial = {k: v for k, v in full.items() if k != field}
                with self.assertRaises(TypeError):
                    gtr.turn_result_signed(**partial)

    def test_the_signed_builder_positions_nothing(self):
        """Keyword-only, and proved by a call that would otherwise SUCCEED: all fourteen
        values are supplied positionally in the declared order, so the TypeError can only
        come from the keyword-only marker. A shorter call would raise for a missing
        argument instead and would pass even if `*` were deleted — which is exactly what
        mutation testing found the first version of this test doing."""
        positional = (
            "r", b64(32), 0, "a" * 64, b64(30), b64(64), "k", b64(30), b64(64), "s",
            None, "u", "e", "l",
        )
        self.assertEqual(len(positional), 14)
        gtr.turn_result_signed(**dict(zip(
            ("receipt_id", "output_stream_id", "output_bytes", "output_sha256",
             "envelope_jcs_b64", "signature_b64", "key_id",
             "attestation_evidence_jcs_b64", "attestation_signature_b64",
             "supervisor_attestation_key_id", "containment_evidence_b64", "run_id",
             "execution_attempt_id", "lease_id"), positional)))
        with self.assertRaises(TypeError):
            gtr.turn_result_signed(*positional)

    def test_the_frame_carries_no_acceptance_state(self):
        """A §5 acceptance row's own columns — the acceptance clock, the nonce, the staging
        handles, the acceptance state — are absent from both arms. §4.10(e) reports that a
        turn finished; it does not restate the turn."""
        for field in ("challenge_accepted_at_ms", "request_nonce", "challenge_handle",
                      "install_id", "state", "system_handle", "history_handle",
                      "generation_config_handle", "lease_payload_bytes",
                      "record_handle", "execution_receipt_handle", "lease_handle"):
            with self.subTest(field=field):
                self.assertNotIn(field, gtr.SIGNED_FIELDS)
                self.assertNotIn(field, gtr.REFUSED_FIELDS)


# ---------------------------------------------------------------------------
# The one place this frame is enforced today: §4.10(d)'s continuation
# ---------------------------------------------------------------------------


class EvidenceRequestContinuationTests(unittest.TestCase):
    """§4.10(d): "once a row exists, the acceptance/signer verdict is
    `brops.governed-turn-result.v1`".

    Until this piece landed that sentence was unenforced — §4.10(d) relayed whatever its §5
    continuation returned, guarding only against an answer in its OWN pre-acceptance
    namespace. Now the continuation must return a §4.10(e) frame, and this is where the
    module is REACHED from production code rather than only from its own tests. The §5
    continuation itself still has **no production supplier** (`drive_acceptance` remains an
    injected seam); what changed is that whatever supplies it is now held to this shape.
    """

    def test_a_denied_peer_never_reaches_the_continuation_at_all(self):
        """The ordering §4.10(d) fixes, restated here because everything below depends on
        it: the peer check runs before the shape, the ledger and the continuation, so a
        stranger's frame never causes a §4.10(e) frame to be built OR validated."""
        reached = []
        reply = ger.handle_evidence_request(
            {"protocol": ger.EVIDENCE_REQUEST_PROTOCOL, "install_id": "i",
             "challenge_handle": "a" * 64, "request_nonce": "n"},
            peer_uid=1, allowed_sidecar_uid=2, conn=None,
            drive_acceptance=lambda gated: reached.append(gated) or signed_frame(),
        )
        self.assertEqual(reply["protocol"], ger.EVIDENCE_REQUEST_RESULT_PROTOCOL)
        self.assertEqual(reply["reason"], "peer_denied")
        self.assertEqual(reached, [])

    def test_the_evidence_request_module_enforces_this_frame(self):
        """The wiring itself. The BEHAVIOURAL tests — a valid §4.10(e) verdict relayed, a
        non-§4.10(e) reply refused as a fault, the pre-acceptance namespace keeping its own
        message — live in `test_governed_evidence_request`, because reaching the
        continuation needs a real `INPUTS_READY` row and that harness already exists there.
        Rebuilding it here would be a second copy of the staging walk."""
        source = (ROOT / "runtime" / "governed_evidence_request.py").read_text("utf-8")
        self.assertIn("from governed_turn_result import validate_turn_result", source)
        self.assertIn("validate_turn_result(result)", source)


if __name__ == "__main__":
    unittest.main()
