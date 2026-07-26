"""§2.3 / §8 evidence-recorder RUNNER core — in-process (no sockets). Proves that the dedicated
recorder principal's `record_governed_turn`, given a well-formed governed-record request, writes
the output/containment/execution-receipt into store/rec/ and mints a REAL signed bro_evidence
chain that the signer's own `validate_chain_detailed` accepts under the evidence-recorder key.
Malformed requests fail closed. The full supervisor->recorder AF_UNIX E2E runs on Linux CI.
"""
from __future__ import annotations

import base64
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

from bro_signature import ACTIVE, TrustedKey  # noqa: E402
from bro_evidence import validate_chain_detailed  # noqa: E402
from brops_evidence_store import EvidenceStore  # noqa: E402
from brops_governed_recorder import RecorderComponents, record_governed_turn  # noqa: E402


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _keypair(seed: str) -> dict:
    priv = Ed25519PrivateKey.from_private_bytes((seed.encode() + b"\x00" * 32)[:32])
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {
        "key_id": f"key-{seed}",
        "private_key": priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex(),
        "public_key": pub.hex(),
    }


def _request(**over) -> dict:
    base = {
        "protocol": "brops.governed-record-request.v1",
        "output_b64": _b64url(b"executor output bytes"),
        "run_id": "run-1", "execution_attempt_id": "attempt-1", "lease_id": "lease-1",
        "receipt_id": "receipt-1", "task_id": "task-1", "agent_id": "Bro",
        "runner_id": "runner-1", "executor_id": "exec-1",
        "started_at_ms": 1000, "finished_at_ms": 2000, "issued_at_epoch": 42,
    }
    base.update(over)
    return base


class RecorderCoreTests(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.rec_store = EvidenceStore(self.root / "rec")
        self.key = _keypair("ev")
        self.components = RecorderComponents(rec_store=self.rec_store, evidence_recorder_key=self.key)

    def test_records_turn_and_mints_verifiable_chain(self):
        r = record_governed_turn(_request(), self.components)
        self.assertEqual(r["status"], "recorded")
        # every returned handle resolves in store/rec/ and content-addresses to itself.
        self.assertEqual(self.rec_store.read(r["output_handle"]), b"executor output bytes")
        self.assertEqual(r["output_bytes"], len(b"executor output bytes"))
        self.rec_store.read(r["containment_handle"])
        self.rec_store.read(r["execution_receipt_handle"])
        # the signed bro_evidence chain the recorder wrote validates under the SIGNER's own path.
        ev_keys = {self.key["key_id"]: TrustedKey(
            key_id=self.key["key_id"], public_key=self.key["public_key"],
            authority_type="evidence-recorder",
            allowed_artifact_types=("evidence-event", "evidence-head"),
            not_before_epoch=0, not_after_epoch=(1 << 62), status=ACTIVE,
            issued_by="root", subject_agent_id="Bro")}
        evidence_dir = pathlib.Path(self.rec_store.root) / "evidence"
        detail = validate_chain_detailed(
            "task-1", [r["evidence_event_id"]], ev_keys, store=evidence_dir, now=42)
        self.assertEqual(detail["event_count"], 1)
        self.assertEqual(detail["last_sequence"], 1)
        self.assertEqual(detail["final_event_hash"], r["evidence_final_event_hash"])

    def test_chain_rejects_wrong_authority_key(self):
        r = record_governed_turn(_request(), self.components)
        other = _keypair("intruder")
        wrong_keys = {self.key["key_id"]: TrustedKey(
            key_id=self.key["key_id"], public_key=other["public_key"],   # mismatched pubkey
            authority_type="evidence-recorder",
            allowed_artifact_types=("evidence-event", "evidence-head"),
            not_before_epoch=0, not_after_epoch=(1 << 62), status=ACTIVE,
            issued_by="root", subject_agent_id="Bro")}
        evidence_dir = pathlib.Path(self.rec_store.root) / "evidence"
        with self.assertRaises(Exception):
            validate_chain_detailed("task-1", [r["evidence_event_id"]], wrong_keys,
                                    store=evidence_dir, now=42)

    def test_malformed_request_is_refused(self):
        bad = _request()
        del bad["lease_id"]
        r = record_governed_turn(bad, self.components)
        self.assertEqual(r["status"], "refused")
        self.assertTrue(r["reason"].startswith("malformed"))

    def test_non_integer_timestamp_refused(self):
        r = record_governed_turn(_request(started_at_ms="1000"), self.components)
        self.assertEqual(r["status"], "refused")


if __name__ == "__main__":
    unittest.main()
