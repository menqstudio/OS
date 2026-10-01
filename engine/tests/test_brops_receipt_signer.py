"""Wave 3b-1 — isolated receipt signer + supervisor attestation + evidence store.

Exercises the crux end-to-end (supervisor builds evidence from {run_id, attempt_id} ->
attests -> signer verifies + reads store by handle + constructs + signs the 21-field
receipt), the content-addressed store's atomic publish + integrity, and the fail-closed
negative matrix (design §1.3-1.5, §4.0-4.2).
"""

import base64
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))  # _brops_fixtures

import brops_canonical as bc
from brops_evidence_store import EvidenceStore, EvidenceStoreError
import brops_receipt_signer as signer
from brops_supervisor_attest import RunState, produce_sign_request

from _brops_fixtures import keypair as _keypair


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class _Provider:
    def __init__(self, run_state):
        self._state = run_state

    def terminal_run_state(self, run_id, execution_attempt_id):
        if (run_id, execution_attempt_id) == (
            self._state.run_id,
            self._state.execution_attempt_id,
        ):
            return self._state
        return None


def _run_state(**overrides) -> RunState:
    base = dict(
        run_id="run-1",
        execution_attempt_id="attempt-1",
        lease_id="lease-1",
        request_nonce="11111111-1111-4111-8111-111111111111",
        receipt_id="22222222-2222-4222-8222-222222222222",
        decision="completed",
        workspace_id="ws-1",
        install_id="install-1",
        supervisor_id="sup-1",
        executor_id="exec-1",
        builder_id="builder-1",
        policy_id="policy-1",
        policy_version="1",
        requested_at="1000",
        completed_at="2000",
        system="You are a governed assistant.",
        history=[{"role": "user", "content": "hi"}],
        output="hello",
        generation_config='{"model":"claude","temperature":0}',
        containment_evidence={"contained": True, "group": "pg-1"},
        policy_bundle=b"policy-bundle-bytes",
    )
    base.update(overrides)
    return RunState(**base)


class EvidenceStoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = EvidenceStore(self.dir)

    def test_publish_is_content_addressed_and_idempotent(self):
        h1 = self.store.publish(b"abc")
        h2 = self.store.publish(b"abc")
        self.assertEqual(h1, h2)
        self.assertEqual(h1, bc.sha256_hex(b"abc"))
        self.assertEqual(self.store.read(h1), b"abc")

    def test_read_rejects_bad_handle(self):
        with self.assertRaises(EvidenceStoreError):
            self.store.read("not-a-handle")
        with self.assertRaises(EvidenceStoreError):
            self.store.read("0" * 64)  # valid shape, absent

    def test_read_detects_corruption(self):
        h = self.store.publish(b"payload")
        (pathlib.Path(self.dir) / h).write_bytes(b"tampered")
        with self.assertRaises(EvidenceStoreError):
            self.store.read(h)

    def test_concurrent_publishers_of_same_bytes_do_not_race(self):
        # Two threads publish identical bytes simultaneously (P1-5): the atomic
        # create-if-absent means exactly one file exists, both get the same handle, and
        # neither overwrites the other or errors.
        import threading

        data = b"concurrent-artifact-bytes"
        barrier = threading.Barrier(8)
        results, errors = [], []

        def worker():
            try:
                barrier.wait()
                results.append(self.store.publish(data))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(set(results), {bc.sha256_hex(data)})
        # exactly one published file (plus no leftover temp files)
        names = [p.name for p in pathlib.Path(self.dir).iterdir()]
        self.assertEqual(names, [bc.sha256_hex(data)])
        self.assertEqual(self.store.read(bc.sha256_hex(data)), data)


class SignerEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = EvidenceStore(self.dir)
        self.att_priv, self.att_pub = _keypair()
        self.sig_priv, self.sig_pub = _keypair()
        self.attestation_key = {"key_id": "sup-att-1", "private_key": self.att_priv}
        self.signing_key = {"key_id": "receipt-key-1", "private_key": self.sig_priv}
        self.now_ms = 10_000
        # The signer's own authorization policy (P1-7), matching the _run_state() fixture.
        self.policy = signer.SignerAuthorizationPolicy(
            allowed_executor_ids=frozenset({"exec-1"}),
            allowed_builder_ids=frozenset({"builder-1"}),
            allowed_supervisor_ids=frozenset({"sup-1"}),
            expected_policy_id="policy-1",
            expected_policy_version="1",
            expected_policy_bundle_sha256=bc.policy_bundle_sha256(b"policy-bundle-bytes"),
        )

    def _sign_only(self, request, **overrides):
        kwargs = dict(
            store=self.store,
            signing_key=self.signing_key,
            supervisor_attestation_pubkey_hex=self.att_pub,
            supervisor_key_id="sup-att-1",
            policy=self.policy,
            now_ms=self.now_ms,
        )
        kwargs.update(overrides)
        return signer.sign(request, **kwargs)

    def _sign(self, run_state):
        provider = _Provider(run_state)
        request = produce_sign_request(
            run_state.run_id,
            run_state.execution_attempt_id,
            run_state_provider=provider,
            store=self.store,
            attestation_key=self.attestation_key,
        )
        return request, self._sign_only(request)

    def test_happy_path_signs_a_verifiable_21_field_receipt(self):
        state = _run_state()
        _, result = self._sign(state)
        self.assertEqual(result["status"], "signed")
        envelope = json.loads(_b64url_decode(result["envelope_jcs_b64"]))
        self.assertEqual(set(envelope), set(bc.RECEIPT_FIELDS))
        self.assertEqual(envelope["protocol"], bc.RECEIPT_PROTOCOL)
        # The receipt's hashes equal the §4.0a formulas over the run's exact inputs.
        self.assertEqual(envelope["system_sha256"], bc.system_sha256(state.system))
        self.assertEqual(envelope["history_sha256"], bc.history_sha256(state.history))
        self.assertEqual(envelope["output_sha256"], bc.output_sha256(state.output))
        self.assertEqual(
            envelope["generation_config_sha256"],
            bc.generation_config_sha256(state.generation_config),
        )
        self.assertEqual(
            envelope["containment_evidence_sha256"],
            bc.containment_evidence_sha256(state.containment_evidence),
        )
        self.assertEqual(envelope["policy_bundle_sha256"], bc.policy_bundle_sha256(state.policy_bundle))
        self.assertEqual(
            envelope["request_sha256"],
            bc.request_sha256(
                workspace_id=state.workspace_id,
                install_id=state.install_id,
                request_nonce=state.request_nonce,
                system_sha256=bc.system_sha256(state.system),
                history_sha256=bc.history_sha256(state.history),
                generation_config_sha256=bc.generation_config_sha256(state.generation_config),
                requested_at=state.requested_at,
            ),
        )
        # The signature verifies over the exact canonical envelope bytes.
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.sig_pub))
        pub.verify(_b64url_decode(result["signature_b64"]), _b64url_decode(result["envelope_jcs_b64"]))
        # Forensic record present (design §4.2).
        for f in ("attestation_evidence_jcs_b64", "attestation_signature_b64", "run_id", "lease_id"):
            self.assertTrue(result[f])

    def test_tampered_attestation_is_refused(self):
        state = _run_state()
        request, _ = self._sign(state)
        request["evidence"]["output_handle"] = bc.sha256_hex(b"forged")  # break the signed set
        result = self._sign_only(request)
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "attestation_invalid")

    def test_a_non_canonical_spelling_of_a_valid_attestation_signature_is_refused(self):
        """The lenient stdlib decode skipped characters outside the alphabet, so one valid
        signature had any number of accepted spellings. Each of these decoded to the same 64
        bytes and VERIFIED."""
        state = _run_state()
        request, signed = self._sign(state)
        self.assertEqual(signed["status"], "signed")          # the control: as sent, it verifies
        good = request["attestation"]["sig"]
        for name, spelling in (("padded", good + "=="), ("newline", good[:10] + "\n" + good[10:]),
                               ("junk", good[:10] + "!" + good[10:]), ("space", " " + good)):
            with self.subTest(spelling=name):
                request["attestation"]["sig"] = spelling
                result = self._sign_only(request)
                self.assertEqual(result["status"], "refused", name)
                self.assertEqual(result["reason"], "attestation_invalid")
        request["attestation"]["sig"] = good
        self.assertEqual(self._sign_only(request)["status"], "signed")

    def test_wrong_supervisor_key_id_is_refused(self):
        state = _run_state()
        request, _ = self._sign(state)
        result = self._sign_only(request, supervisor_key_id="sup-att-DIFFERENT")
        self.assertEqual(result["reason"], "attestation_invalid")

    def test_missing_store_handle_is_refused(self):
        state = _run_state()
        # Build+attest evidence but publish to a DIFFERENT store, so the signer's store lacks it.
        provider = _Provider(state)
        other = EvidenceStore(tempfile.mkdtemp())
        request = produce_sign_request(
            state.run_id, state.execution_attempt_id,
            run_state_provider=provider, store=other, attestation_key=self.attestation_key,
        )
        result = self._sign_only(request)
        self.assertEqual(result["status"], "refused")
        self.assertIn(result["reason"], {"handle_missing", "containment_missing"})

    def test_non_completed_run_is_never_attested(self):
        # The supervisor refuses to attest a non-completed run — reachable ONLY through
        # produce_sign_request (there is no public build_evidence/attest seam, P0-2).
        from brops_supervisor_attest import AttestationError

        state = _run_state(decision="denied")
        with self.assertRaises(AttestationError):
            produce_sign_request(
                state.run_id, state.execution_attempt_id,
                run_state_provider=_Provider(state), store=self.store,
                attestation_key=self.attestation_key,
            )

    def test_no_public_attest_or_build_evidence_oracle(self):
        # P0-2: the caller-evidence signing seam must not exist as a public callable.
        import brops_supervisor_attest as mod

        self.assertFalse(hasattr(mod, "attest"))
        self.assertFalse(hasattr(mod, "build_evidence"))

    def test_reversed_timestamps_are_refused(self):
        state = _run_state(requested_at="5000", completed_at="1000")
        _, result = self._sign(state)
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "timestamp_invalid")

    def test_sign_request_and_result_conform_to_ipc_schemas(self):
        try:
            import jsonschema
        except Exception:  # pragma: no cover
            self.skipTest("jsonschema not available")
        contracts = ROOT / "contracts"
        req_schema = json.loads((contracts / "brops-sign-request.v1.schema.json").read_text("utf-8"))
        res_schema = json.loads((contracts / "brops-sign-result.v1.schema.json").read_text("utf-8"))
        request, result = self._sign(_run_state())
        jsonschema.validate(request, req_schema)
        jsonschema.validate(result, res_schema)
        # A refusal also conforms to the union.
        bad = self._sign_only({"protocol": "brops.sign-request.v1", "evidence": {}})
        jsonschema.validate(bad, res_schema)

    def test_identity_not_in_allow_set_is_refused(self):
        state = _run_state(executor_id="rogue-exec")
        _, result = self._sign(state)
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "identity_denied")

    def test_policy_not_in_force_is_refused(self):
        state = _run_state(policy_version="99")
        _, result = self._sign(state)
        self.assertEqual(result["reason"], "policy_mismatch")

    def test_wrong_policy_bundle_digest_is_refused(self):
        state = _run_state(policy_bundle=b"an-unauthorized-bundle")
        _, result = self._sign(state)
        self.assertEqual(result["reason"], "policy_mismatch")

    def test_future_timestamp_beyond_skew_is_refused(self):
        state = _run_state(requested_at="1000", completed_at="999999999999")
        _, result = self._sign(state)
        self.assertEqual(result["reason"], "timestamp_invalid")

    def test_signer_never_signs_arbitrary_bytes(self):
        # A sign-request with no attestation is refused, not signed.
        result = self._sign_only(
            {"protocol": "brops.sign-request.v1", "evidence": {}},
        )
        self.assertEqual(result["status"], "refused")


class StdinEntrypointTests(unittest.TestCase):
    """`main` documents "Always exits 0", with a refusal frame as the verdict."""

    def run_main(self, env):
        import io
        import os
        from unittest import mock

        import brops_protocol
        reader, writer = io.BytesIO(b""), io.BytesIO()
        with mock.patch.dict(os.environ, env, clear=False):
            rc = signer.main(reader, writer)
        writer.seek(0)
        return rc, brops_protocol.read_frame(writer)

    def test_an_unprovisioned_signer_answers_with_a_refusal_frame(self):
        """A key directory with no key file in it: `FileNotFoundError`, which the `except` did
        not name, so the caller got a traceback and EOF instead of a frame."""
        import os
        store = tempfile.mkdtemp()
        keydir = tempfile.mkdtemp()
        os.chmod(store, 0o700)
        os.chmod(keydir, 0o700)
        rc, frame = self.run_main({
            "BROPS_EVIDENCE_STORE_DIR": store,
            "BROPS_RECEIPT_SIGNER_KEYDIR": keydir,
            "BROPS_SUPERVISOR_ATTESTATION_PUBKEY": "00" * 32,
            "BROPS_SUPERVISOR_ATTESTATION_KEY_ID": "sup-att-1",
            "BROPS_EXPECTED_POLICY_ID": "policy-1",
            "BROPS_EXPECTED_POLICY_VERSION": "1",
            "BROPS_EXPECTED_POLICY_BUNDLE_SHA256": "0" * 64,
        })
        self.assertEqual(rc, 0)
        self.assertEqual((frame["status"], frame["reason"]), ("refused", "malformed"))
        self.assertEqual(frame["protocol"], signer.SIGN_RESULT_PROTOCOL)


class TheTwoKeyLoadersAreOneFunctionTests(unittest.TestCase):
    """`load_receipt_signing_key` and `brops_supervisor_attest.load_attestation_key` are the
    same body twice, for two principals' keys. They are kept separate and held EQUAL, so a
    hardening of the custody check cannot land in one and be forgotten in the other."""

    @staticmethod
    def body(function, filename_constant, noun):
        import ast
        import inspect
        import textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
        definition = tree.body[0]
        statements = definition.body[1:]            # drop the docstring
        text = "\n".join(ast.unparse(node) for node in statements)
        return text.replace(filename_constant, "KEY_FILENAME").replace(noun, "NOUN")

    def test_the_bodies_differ_only_in_the_filename_and_the_noun(self):
        import brops_supervisor_attest as attest
        mine = self.body(signer.load_receipt_signing_key,
                         "RECEIPT_SIGNER_KEY_FILENAME", "receipt-signer")
        theirs = self.body(attest.load_attestation_key,
                           "SUPERVISOR_ATTESTATION_KEY_FILENAME", "attestation")
        self.assertEqual(mine, theirs)
        self.assertIn("S_IRWXG", mine, "the fixture must be comparing the custody check itself")


if __name__ == "__main__":
    unittest.main()
