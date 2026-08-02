"""§4.9 conformance: the isolated signer emits the FLAT
``brops.governed-receipt-envelope.v1`` payload the desktop broker
(``governed_verification.rs``) reconstructs and Ed25519-verifies.

This is the regression guard for the confirmed P1: the signer must sign the
EXACT 23-key flat envelope (``key_id`` and the execution binding INSIDE the
signature), JCS-encoded as
``json.dumps(payload, sort_keys=True, separators=(",",":"), ensure_ascii=False)
.encode("utf-8")`` — the byte-for-byte encoding the Rust ``payload_jcs``
reconstructs — and the signature MUST be Ed25519 over those bytes, base64url
(no padding) as the broker's ``URL_SAFE_NO_PAD`` decoder expects.

Uses a REAL Ed25519 key (``cryptography``) as the injected ``sign_fn`` so the
test proves the produced signature verifies under the signer's public key.
"""

import base64
import hashlib
import json
import pathlib
import sys
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from isolated_signer import (  # noqa: E402
    ATTESTATION_PROTOCOL,
    ENVELOPE_ARTIFACT_TYPE,
    ENVELOPE_INTEGER_KEYS,
    ENVELOPE_STRING_KEYS,
    REQUEST_PROTOCOL,
    SIGN_REQUEST_PROTOCOL,
    ArtifactStore,
    IsolatedSigner,
    SignerConfig,
)

RECEIPT_KEY_ID = "iso-signer-2026-07"
SUP_KEY_ID = "sup-attest-2026-07"
NOW_MS = 1_700_000_000_000
OUTPUT = b"the exact governed reply bytes"

# The 23 §4.9 keys, split by JSON type (must match the Rust ReceiptEnvelope).
EXPECTED_STRING_KEYS = {
    "artifact_type",
    "key_id",
    "receipt_id",
    "run_id",
    "execution_attempt_id",
    "task_id",
    "workspace_id",
    "install_id",
    "request_nonce",
    "request_sha256",
    "record_handle",
    "lease_handle",
    "execution_receipt_handle",
    "output_sha256",
    "evidence_final_event_hash",
    "supervisor_attestation_key_id",
    "attestation_evidence_sha256",
}
EXPECTED_INTEGER_KEYS = {
    "output_bytes",
    "challenge_accepted_at_ms",
    "completed_at_ms",
    "evidence_event_count",
    "evidence_last_sequence",
    "evidence_head_sequence",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _b64url_nopad(raw: bytes) -> str:
    """Base64url without padding — the exact variant the Rust broker's
    ``URL_SAFE_NO_PAD`` decoder accepts."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _build_store():
    artifacts = {
        "policy_bundle_handle": b"policy-bundle-bytes",
        "generation_config_handle": b'{"temperature":0,"top_p":1}',
        "system_handle": b"you are Bro, a governed conductor",
        "history_handle": b'[{"role":"user","content":"hello"}]',
        "output_handle": OUTPUT,
        "containment_evidence_handle": b'{"containment":"verified"}',
        "record_handle": b'{"terminal_record":"COMPLETED"}',
        "lease_handle": b'{"lease":"signed-lease"}',
        "execution_receipt_handle": b'{"execution_receipt":"ok"}',
    }
    store = ArtifactStore()
    handles = {f: store.put(d) for f, d in artifacts.items()}
    return store, handles


def _evidence(handles):
    return {
        "run_id": "run-9",
        "execution_attempt_id": "attempt-2",
        "task_id": "task-42",
        "request_nonce": "nonce-abc-123",
        "receipt_id": "receipt-xyz",
        "decision": "completed",
        "workspace_id": "ws-7",
        "install_id": "install-7",
        "supervisor_id": "sup-1",
        "executor_id": "exec-1",
        "builder_id": "builder-1",
        "policy_id": "policy-9",
        "policy_version": "2.1.0",
        "policy_bundle_handle": handles["policy_bundle_handle"],
        "generation_config_handle": handles["generation_config_handle"],
        "system_handle": handles["system_handle"],
        "history_handle": handles["history_handle"],
        "output_handle": handles["output_handle"],
        "containment_evidence_handle": handles["containment_evidence_handle"],
        "record_handle": handles["record_handle"],
        "lease_handle": handles["lease_handle"],
        "execution_receipt_handle": handles["execution_receipt_handle"],
        "evidence_final_event_hash": "d" * 64,
        "requested_at": NOW_MS - 8_000,
        "challenge_accepted_at_ms": NOW_MS - 6_000,
        "completed_at": NOW_MS - 2_000,
        "evidence_event_count": 5,
        "evidence_last_sequence": 17,
        "evidence_head_sequence": 2,
    }


class EnvelopeV49ConformanceTest(unittest.TestCase):
    def setUp(self):
        self.priv = Ed25519PrivateKey.generate()
        self.pub = self.priv.public_key()
        # Injected sign_fn: real Ed25519, base64url-nopad (broker convention).
        self._signed = []

        def sign_fn(private_key_handle, message_bytes):
            self.assertIs(private_key_handle, self.priv)  # opaque handle == key
            self._signed.append(message_bytes)
            return _b64url_nopad(self.priv.sign(message_bytes))

        store, handles = _build_store()
        self.store = store
        self.handles = handles
        config = SignerConfig(
            receipt_key_id=RECEIPT_KEY_ID,
            receipt_private_key_handle=self.priv,  # opaque to the signer
            supervisor_attestation_key_id=SUP_KEY_ID,
            supervisor_attestation_key_handle=object(),
            allowed_executor_ids={"exec-1"},
            allowed_builder_ids={"builder-1"},
            allowed_supervisor_ids={"sup-1"},
        )
        self.signer = IsolatedSigner(
            config=config,
            store=store,
            sign_fn=sign_fn,
            verify_attestation=lambda h, m, s: s == "GOOD-SIG",
            clock_ms=lambda: NOW_MS,
        )

    def _request(self):
        return {
            "protocol": SIGN_REQUEST_PROTOCOL,
            "attestation": {
                "attestation_protocol": ATTESTATION_PROTOCOL,
                "supervisor_key_id": SUP_KEY_ID,
                "sig": "GOOD-SIG",
            },
            "evidence": _evidence(self.handles),
        }

    def test_module_key_sets_match_the_23_field_spec(self):
        self.assertEqual(set(ENVELOPE_STRING_KEYS), EXPECTED_STRING_KEYS)
        self.assertEqual(set(ENVELOPE_INTEGER_KEYS), EXPECTED_INTEGER_KEYS)
        self.assertEqual(len(EXPECTED_STRING_KEYS) + len(EXPECTED_INTEGER_KEYS), 23)

    def test_payload_is_exactly_the_23_key_flat_envelope(self):
        result = self.signer.sign_result(self._request())
        self.assertEqual(result["status"], "signed")
        payload = result["payload"]

        # EXACTLY 23 keys, the right split of string vs integer.
        self.assertEqual(len(payload), 23)
        self.assertEqual(set(payload.keys()), EXPECTED_STRING_KEYS | EXPECTED_INTEGER_KEYS)
        self.assertEqual(payload["artifact_type"], "brops.governed-receipt-envelope.v1")
        self.assertEqual(payload["artifact_type"], ENVELOPE_ARTIFACT_TYPE)

        # 17 string-valued.
        for key in EXPECTED_STRING_KEYS:
            self.assertIsInstance(payload[key], str, key)
        # 6 integer-valued — bare ints, never bool, never quoted.
        for key in EXPECTED_INTEGER_KEYS:
            self.assertIsInstance(payload[key], int, key)
            self.assertNotIsInstance(payload[key], bool, key)

        # key_id and the execution binding are INSIDE the signed payload.
        self.assertEqual(payload["key_id"], RECEIPT_KEY_ID)
        self.assertEqual(payload["supervisor_attestation_key_id"], SUP_KEY_ID)
        self.assertEqual(payload["output_sha256"], _sha(OUTPUT))
        self.assertEqual(payload["output_bytes"], len(OUTPUT))
        self.assertEqual(payload["completed_at_ms"], NOW_MS - 2_000)

    def test_request_sha256_matches_the_receipt_rs_formula(self):
        result = self.signer.sign_result(self._request())
        expected = _sha(
            json.dumps(
                {
                    "protocol": REQUEST_PROTOCOL,
                    "workspace_id": "ws-7",
                    "install_id": "install-7",
                    "request_nonce": "nonce-abc-123",
                    "system_sha256": _sha(b"you are Bro, a governed conductor"),
                    "history_sha256": _sha(b'[{"role":"user","content":"hello"}]'),
                    "generation_config_sha256": _sha(b'{"temperature":0,"top_p":1}'),
                    "requested_at": str(NOW_MS - 8_000),
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )
        self.assertEqual(result["payload"]["request_sha256"], expected)

    def test_signature_verifies_over_the_jcs_the_broker_reconstructs(self):
        result = self.signer.sign_result(self._request())
        payload = result["payload"]

        # The exact JCS bytes the Rust broker rebuilds from the envelope fields.
        jcs = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

        # (a) the signer signed EXACTLY these bytes (recompute-then-sign).
        self.assertEqual(self._signed, [jcs])

        # (b) the returned signature is base64url-nopad and Ed25519-verifies
        #     over JCS(payload) under the signer's public key.
        sig_b64 = result["signature_b64"]
        pad = "=" * (-len(sig_b64) % 4)
        raw = base64.urlsafe_b64decode(sig_b64 + pad)
        self.assertEqual(len(raw), 64)  # Ed25519 signature size
        self.pub.verify(raw, jcs)  # raises InvalidSignature on failure

        # (c) tampering ANY signed field breaks verification (defence proof).
        tampered = dict(payload)
        tampered["completed_at_ms"] = payload["completed_at_ms"] + 1
        tampered_jcs = json.dumps(
            tampered, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        with self.assertRaises(InvalidSignature):
            self.pub.verify(raw, tampered_jcs)

    def test_jcs_has_bare_integers_and_no_whitespace(self):
        result = self.signer.sign_result(self._request())
        jcs = json.dumps(
            result["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        self.assertTrue(jcs.startswith('{"artifact_type":'))
        self.assertIn('"output_bytes":%d' % len(OUTPUT), jcs)
        self.assertNotIn('"output_bytes":"', jcs)  # never quoted
        self.assertNotIn(", ", jcs)
        self.assertNotIn(": ", jcs)


if __name__ == "__main__":
    unittest.main()
