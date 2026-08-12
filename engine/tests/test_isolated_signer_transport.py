"""The signer's WIRE contract, pinned from both ends — the test this tree did not have.

Every existing test of `governed_acceptance.AcceptanceDriver` wires its `sign_result` seam
straight to `IsolatedSigner.sign_result`, IN-PROCESS. That is a reasonable fixture and it
proves the §5 ladder; what it cannot prove is the thing between the two halves, because
in-process there is nothing between them. And `isolated_signer_server` — the seam's ONLY
transport in this tree — does not carry the signer's reply. It carries the BROKER's op shape:

  * the request travels as `{"op": "sign-result", "sign_request": {...}}`, not as the bare
    `brops.sign-request.v1`, because `dispatch` routes on `op`;
  * the signed reply is FLATTENED — `signature` rather than `signature_b64`, `ok` rather than
    `status` — because `governed_verification.rs` decodes exactly those names.

So the driver's documented contract ("must return the isolated signer's own reply") and the
only transport that exists disagreed, and nothing in the suite could see it. It surfaced on
the first live §4.10(g) run, AFTER a real contained execution had already completed: the
supervisor raised `the isolated signer seam returned neither a §4.9 envelope nor a typed
refusal`, which reached the sidecar as an op-shaped reply whose only content was that the
protocol was `None`.

This file is that missing middle. It drives the REAL `dispatch` over a REAL `IsolatedSigner`
with real Ed25519 keys and a real content-addressed store, then decodes the wire reply with
the REAL client half, and requires the result to be BYTE-IDENTICAL to what the signer itself
returned. Both arms — signed and typed refusal — and the failure directions too, because a
decoder that cannot refuse is a decoder that will one day repair a peer denial into a receipt.

No AF_UNIX and no root: the mismatch lived entirely in the request and reply SHAPES, which is
exactly why a test that needed Linux would have been the wrong test to write.
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
_TESTS = pathlib.Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

import isolated_signer as isg  # noqa: E402
import isolated_signer_server as iss  # noqa: E402

from test_governed_acceptance import _Case  # noqa: E402


class _SignerCase(_Case):
    """`_Case` already builds four real keypairs, a real store and a real signer. Reused
    rather than rebuilt — a second copy of that fixture is the duplication the §5 file's own
    prior-art rule refuses."""

    def signed_request(self):
        """One `brops.sign-request.v1` the signer will actually sign.

        Produced by driving a REAL turn to `COMPLETED` and letting the driver build the
        attestation, rather than by hand: a hand-written sign-request would be a third
        author of the document, and the shapes under test are precisely the ones that drift
        when a document has more than one.
        """
        captured = []
        document, _handle = self.ready_turn()
        driver = self.driver(sign_result=lambda request: captured.append(request)
                             or self.signer().sign_result(request))
        reply = self.trigger(document, driver=driver)
        self.assertEqual(reply.get("status"), "signed", reply)
        self.assertEqual(len(captured), 1, "the driver must call the signer exactly once")
        return captured[0]


class TheWireCarriesTheSignersOwnReplyTests(_SignerCase):

    def test_a_signed_result_survives_the_round_trip_unchanged(self):
        """`dispatch` -> `sign_result_reply` == `IsolatedSigner.sign_result`.

        This is the whole contract in one assertion. It fails on the tree as it was, because
        the wire says `signature` and the signer says `signature_b64`.
        """
        request = self.signed_request()
        direct = self.signer().sign_result(request)
        wire = iss.dispatch(iss.sign_result_request(request), self.signer())
        self.assertEqual(iss.sign_result_reply(wire), direct)
        self.assertEqual(direct["status"], "signed")

    def test_a_typed_refusal_survives_the_round_trip_unchanged(self):
        """The other arm. A refusal is a DECISION the signer made, so it has to arrive as
        the signer's decision and not as a transport failure wearing one."""
        request = self.signed_request()
        # A signer that pins a different supervisor id refuses this attestation by name.
        signer = self.signer(allowed_supervisor_ids={"somebody-else"})
        direct = signer.sign_result(request)
        self.assertEqual(direct["status"], "refused", direct)
        wire = iss.dispatch(iss.sign_result_request(request), signer)
        self.assertEqual(iss.sign_result_reply(wire), direct)

    def test_the_bare_sign_request_is_not_a_wire_frame(self):
        """The request half, stated as its own failure. Sending the sign-request itself —
        which is what a caller reading only `AcceptanceDriver.sign_result`'s docstring would
        do, and what the first live ladder run did — is an unknown op."""
        request = self.signed_request()
        with self.assertRaises(iss.SignerServerError) as caught:
            iss.dispatch(request, self.signer())
        self.assertIn("unknown op", str(caught.exception))

    def test_the_request_travels_nested_and_untouched(self):
        """`dispatch` hands the NESTED object to the signer verbatim: the routing key is not
        merged in, because the signer refuses unknown top-level keys and because a merged
        frame would make the transport a second author of the signed document."""
        request = self.signed_request()
        frame = iss.sign_result_request(request)
        self.assertEqual(set(frame), {"op", "sign_request"})
        self.assertEqual(frame["op"], iss.OP_SIGN_RESULT)
        self.assertIs(frame["sign_request"], request)


class TheDecoderRefusesRatherThanRepairsTests(unittest.TestCase):
    """A decoder that cannot refuse will one day turn a peer denial into a receipt."""

    def refused(self, wire):
        with self.assertRaises(iss.SignerServerError):
            iss.sign_result_reply(wire)

    def test_a_peer_denial_is_a_fault_and_never_a_refusal(self):
        # `{"ok": false, "error": "peer not authorized"}` is what the signer's front door
        # writes BEFORE reading a frame. Translating it into a typed refusal would put a
        # verdict about the turn in the caller's own mouth; the signer decided nothing.
        self.refused({"ok": False, "error": "peer not authorized"})

    def test_the_fail_closed_internal_fault_is_a_fault(self):
        self.refused({"ok": False, "error": "internal signer fault"})

    def test_a_signed_arm_missing_its_signature_is_refused(self):
        self.refused({"ok": True, "artifact_type": isg.ENVELOPE_ARTIFACT_TYPE,
                      "payload": {"a": 1}})

    def test_a_signed_arm_missing_its_payload_is_refused(self):
        self.refused({"ok": True, "artifact_type": isg.ENVELOPE_ARTIFACT_TYPE,
                      "signature": "sig"})

    def test_an_envelope_arm_that_is_not_ok_is_refused(self):
        # `ok` and `artifact_type` disagreeing is a broken server, not a signed result.
        self.refused({"ok": False, "artifact_type": isg.ENVELOPE_ARTIFACT_TYPE,
                      "payload": {"a": 1}, "signature": "sig"})

    def test_a_refusal_with_no_reason_is_refused(self):
        self.refused({"ok": False, "artifact_type": isg.REFUSAL_ARTIFACT_TYPE})

    def test_a_non_object_reply_is_refused(self):
        self.refused("not an object")
        self.refused(None)

    def test_a_well_formed_refusal_decodes_to_the_signers_own_shape(self):
        decoded = iss.sign_result_reply({
            "ok": False, "op": iss.OP_SIGN_RESULT, "error": "signer refused",
            "reason": "hash_mismatch", "artifact_type": isg.REFUSAL_ARTIFACT_TYPE})
        self.assertEqual(decoded, {"artifact_type": isg.REFUSAL_ARTIFACT_TYPE,
                                   "status": "refused", "reason": "hash_mismatch"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
