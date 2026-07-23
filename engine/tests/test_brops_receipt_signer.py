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

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import brops_canonical as bc
from brops_evidence_store import EvidenceStore, EvidenceStoreError
import brops_receipt_signer as signer
from brops_supervisor_attest import (
    RunState,
    attest,
    build_evidence,
    produce_sign_request,
)


def _keypair():
    priv = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization

    raw_priv = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    raw_pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return raw_priv.hex(), raw_pub.hex()


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


class SignerEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = EvidenceStore(self.dir)
        self.att_priv, self.att_pub = _keypair()
        self.sig_priv, self.sig_pub = _keypair()
        self.attestation_key = {"key_id": "sup-att-1", "private_key": self.att_priv}
        self.signing_key = {"key_id": "receipt-key-1", "private_key": self.sig_priv}

    def _sign(self, run_state):
        provider = _Provider(run_state)
        request = produce_sign_request(
            run_state.run_id,
            run_state.execution_attempt_id,
            run_state_provider=provider,
            store=self.store,
            attestation_key=self.attestation_key,
        )
        return request, signer.sign(
            request,
            store=self.store,
            signing_key=self.signing_key,
            supervisor_attestation_pubkey_hex=self.att_pub,
            supervisor_key_id="sup-att-1",
        )

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
        result = signer.sign(
            request,
            store=self.store,
            signing_key=self.signing_key,
            supervisor_attestation_pubkey_hex=self.att_pub,
            supervisor_key_id="sup-att-1",
        )
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "attestation_invalid")

    def test_wrong_supervisor_key_id_is_refused(self):
        state = _run_state()
        request, _ = self._sign(state)
        result = signer.sign(
            request,
            store=self.store,
            signing_key=self.signing_key,
            supervisor_attestation_pubkey_hex=self.att_pub,
            supervisor_key_id="sup-att-DIFFERENT",
        )
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
        result = signer.sign(
            request, store=self.store, signing_key=self.signing_key,
            supervisor_attestation_pubkey_hex=self.att_pub, supervisor_key_id="sup-att-1",
        )
        self.assertEqual(result["status"], "refused")
        self.assertIn(result["reason"], {"handle_missing", "containment_missing"})

    def test_non_completed_run_is_never_attested(self):
        from brops_supervisor_attest import AttestationError

        state = _run_state(decision="denied")
        with self.assertRaises(AttestationError):
            build_evidence(state, self.store)

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
        bad = signer.sign(
            {"protocol": "brops.sign-request.v1", "evidence": {}},
            store=self.store, signing_key=self.signing_key,
            supervisor_attestation_pubkey_hex=self.att_pub, supervisor_key_id="sup-att-1",
        )
        jsonschema.validate(bad, res_schema)

    def test_signer_never_signs_arbitrary_bytes(self):
        # A sign-request with no attestation is refused, not signed.
        result = signer.sign(
            {"protocol": "brops.sign-request.v1", "evidence": {}},
            store=self.store, signing_key=self.signing_key,
            supervisor_attestation_pubkey_hex=self.att_pub, supervisor_key_id="sup-att-1",
        )
        self.assertEqual(result["status"], "refused")


if __name__ == "__main__":
    unittest.main()
