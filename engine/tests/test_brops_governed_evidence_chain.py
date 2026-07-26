"""§7 real evidence chain — in-process (no sockets). Proves the signer's chain-verification path:
a genuine bro_evidence event + signed head (evidence-recorder authority, {payload,signature}
format) is loaded and validated via validate_chain_detailed with the exact TrustedKey the signer
builds, and the head scalars are DERIVED from the validated chain; a tampered event or a head
signed by an untrusted key is rejected. The full accept->sign E2E runs on Linux CI.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
for sub in ("runtime", "tools"):
    sys.path.insert(0, str(ROOT / sub))

from bro_evidence import EvidenceError, event_hash, validate_chain_detailed  # noqa: E402
from bro_signature import ACTIVE, TrustedKey  # noqa: E402
from brops_evidence_store import NamespacedEvidenceStore  # noqa: E402
from broctl import sign_payload  # noqa: E402


class NamespacedStoreTests(unittest.TestCase):
    """§2.3 app split: sup/ and rec/ are physically separate content-addressed namespaces;
    publish defaults to sup, publish_rec writes rec, and read resolves from whichever holds it."""

    def test_publish_and_read_across_namespaces(self):
        d = pathlib.Path(tempfile.mkdtemp())
        store = NamespacedEvidenceStore(d)
        h_sup = store.publish(b"supervisor-artifact")
        h_rec = store.publish_rec(b"recorder-artifact")
        self.assertEqual(store.read(h_sup), b"supervisor-artifact")   # resolved from sup/
        self.assertEqual(store.read(h_rec), b"recorder-artifact")     # resolved from rec/
        self.assertTrue((d / "sup" / h_sup).exists())
        self.assertTrue((d / "rec" / h_rec).exists())
        self.assertFalse((d / "sup" / h_rec).exists())               # rec artifact NOT in sup/
        self.assertFalse((d / "rec" / h_sup).exists())               # sup artifact NOT in rec/


def _keypair():
    priv = Ed25519PrivateKey.generate()
    return (priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex(),
            priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex())


class EvidenceChainVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.priv, self.pub = _keypair()
        # exactly the TrustedKey the signer constructs for the evidence-recorder.
        self.keys = {"ev-k1": TrustedKey(
            key_id="ev-k1", public_key=self.pub, authority_type="evidence-recorder",
            allowed_artifact_types=("evidence-event", "evidence-head"),
            not_before_epoch=0, not_after_epoch=(1 << 62), status=ACTIVE,
            issued_by="brops-governed-evidence-recorder", subject_agent_id=None)}

    def tearDown(self):
        self.tmp.cleanup()

    def _write_chain(self, *, task_id="t", key_id="ev-k1", sign_priv=None):
        sign_priv = sign_priv or self.priv
        eid = "evt-1"
        event = {"artifact_type": "evidence-event", "key_id": key_id, "event_id": eid,
                 "sequence": 1, "previous_event_hash": None, "task_id": task_id,
                 "event_type": "governed-turn-completed", "agent_id": "Bro",
                 "payload_hash": "h" * 64, "issued_at_epoch": 1000}
        final = event_hash(event)
        head = {"artifact_type": "evidence-head", "key_id": key_id, "task_id": task_id,
                "final_event_hash": final, "event_count": 1, "last_sequence": 1,
                "head_sequence": 1, "issued_at_epoch": 1000}
        (self.dir / f"{eid}.json").write_text(json.dumps(sign_payload(sign_priv, event)), encoding="utf-8")
        (self.dir / f"{task_id}.head.json").write_text(json.dumps(sign_payload(sign_priv, head)), encoding="utf-8")
        return eid, final

    def test_valid_chain_derives_scalars_from_the_validated_head(self):
        eid, final = self._write_chain()
        v = validate_chain_detailed("t", [eid], self.keys, store=self.dir, now=2000)
        self.assertEqual(v["event_count"], 1)
        self.assertEqual(v["last_sequence"], 1)
        self.assertEqual(v["head_sequence"], 1)
        self.assertEqual(v["final_event_hash"], final)
        self.assertEqual(v["event_hashes"], [final])

    def test_tampered_event_is_rejected(self):
        eid, _ = self._write_chain()
        p = self.dir / f"{eid}.json"
        doc = json.loads(p.read_text())
        doc["payload"]["payload_hash"] = "T" * 64        # break the signature + head reproduction
        p.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaises(EvidenceError):
            validate_chain_detailed("t", [eid], self.keys, store=self.dir, now=2000)

    def test_head_signed_by_untrusted_key_is_rejected(self):
        other_priv, _ = _keypair()                       # a key NOT in the trusted set
        eid, _ = self._write_chain(sign_priv=other_priv)
        with self.assertRaises(EvidenceError):
            validate_chain_detailed("t", [eid], self.keys, store=self.dir, now=2000)

    def test_missing_head_is_rejected(self):
        eid, _ = self._write_chain()
        (self.dir / "t.head.json").unlink()              # a chain with no anchor is not a chain
        with self.assertRaises(EvidenceError):
            validate_chain_detailed("t", [eid], self.keys, store=self.dir, now=2000)


if __name__ == "__main__":
    unittest.main()
