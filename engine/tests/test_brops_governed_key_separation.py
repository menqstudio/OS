"""§8 authority-separation: the execution receipt (evidence-recorder key) and the terminal
record (governed-turn-recorder key) are signed by DISTINCT authorities. A document signed by the
wrong authority — whether by a mismatched key_id or by a signature that does not verify under the
pinned pubkey — must be refused. Pure crypto; no sockets; cross-platform (Windows-runnable).
"""
from __future__ import annotations

import pathlib
import sys
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
for sub in ("runtime", "tools"):
    sys.path.insert(0, str(ROOT / sub))

from brops_governed_supervisor import _sign_document  # noqa: E402
from brops_governed_signer import _signed_payload, GovernedSignRefused  # noqa: E402

RECORD = "brops.governed-turn-record.v1"
RECEIPT = "brops.governed-turn-execution-receipt.v1"


def _keypair(key_id: str):
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return (
        {"key_id": key_id, "private_key": priv.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex()},
        pub.hex(),
    )


class KeySeparationTests(unittest.TestCase):
    def setUp(self):
        self.ev_key, self.ev_pub = _keypair("evidence-recorder-k1")          # evidence-recorder
        self.gt_key, self.gt_pub = _keypair("governed-turn-recorder-k1")     # governed-turn-recorder

    def _doc(self, artifact_type, key_id, key):
        return _sign_document({"artifact_type": artifact_type, "key_id": key_id, "x": "1"}, key)

    def test_record_with_evidence_recorder_key_id_is_refused(self):
        # The terminal record is signed by the evidence-recorder authority (wrong): its key_id does
        # not match the governed-turn-recorder pin → refused.
        doc = self._doc(RECORD, "evidence-recorder-k1", self.ev_key)
        with self.assertRaises(GovernedSignRefused):
            _signed_payload(doc, artifact_type=RECORD,
                            key_id="governed-turn-recorder-k1", pubkey_hex=self.gt_pub)

    def test_record_forged_with_evidence_key_fails_signature(self):
        # Stronger: the forger CLAIMS the governed-turn-recorder key_id but signs with the
        # evidence-recorder private key → the signature does not verify under the pinned
        # governed-turn-recorder pubkey → refused.
        doc = self._doc(RECORD, "governed-turn-recorder-k1", self.ev_key)
        with self.assertRaises(GovernedSignRefused):
            _signed_payload(doc, artifact_type=RECORD,
                            key_id="governed-turn-recorder-k1", pubkey_hex=self.gt_pub)

    def test_receipt_signed_by_governed_turn_recorder_is_refused(self):
        doc = self._doc(RECEIPT, "governed-turn-recorder-k1", self.gt_key)
        with self.assertRaises(GovernedSignRefused):
            _signed_payload(doc, artifact_type=RECEIPT,
                            key_id="evidence-recorder-k1", pubkey_hex=self.ev_pub)

    def test_each_authority_verifies_under_its_own_key(self):
        # Positive control: record under governed-turn-recorder, receipt under evidence-recorder.
        rec = self._doc(RECORD, "governed-turn-recorder-k1", self.gt_key)
        _signed_payload(rec, artifact_type=RECORD,
                        key_id="governed-turn-recorder-k1", pubkey_hex=self.gt_pub)  # no raise
        rcpt = self._doc(RECEIPT, "evidence-recorder-k1", self.ev_key)
        _signed_payload(rcpt, artifact_type=RECEIPT,
                        key_id="evidence-recorder-k1", pubkey_hex=self.ev_pub)  # no raise


if __name__ == "__main__":
    unittest.main()
