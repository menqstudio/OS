"""§0/§2.3/§8 evidence-recorder RUNNER core — in-process (no sockets). The recorder now OWNS
execution: given the INPUT handles for a governed turn, it launches the contained executor via the
launcher, reads its output pipe directly, measures teardown, and mints a REAL signed bro_evidence
chain the signer's own validate_chain_detailed accepts under the evidence-recorder key. Malformed
requests fail closed BEFORE any execution. The execution path is POSIX (FD passing + process
groups), so those cases are Linux-gated; the full supervisor→recorder AF_UNIX E2E runs on Linux CI.
"""
from __future__ import annotations

import os
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
from brops_evidence_store import NamespacedEvidenceStore  # noqa: E402
from brops_governed_recorder import RecorderComponents, record_governed_turn  # noqa: E402


def _keypair(seed: str) -> dict:
    priv = Ed25519PrivateKey.from_private_bytes((seed.encode() + b"\x00" * 32)[:32])
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {
        "key_id": f"key-{seed}",
        "private_key": priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex(),
        "public_key": pub.hex(),
    }


class RecorderCoreTests(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.store = NamespacedEvidenceStore(self.root / "store")
        # supervisor-written inputs live in sup/; the recorder reads them by handle.
        self.system_handle = self.store.publish(b"{}")
        self.history_handle = self.store.publish(b"hello-history")
        self.config_handle = self.store.publish(b'{"model":"claude-sonnet-5"}')
        self.key = _keypair("ev")
        # a reference executor: reads history off FD 4, writes it back on FD 1.
        self.executor = self.root / "exec.py"
        self.executor.write_text(
            "import os\nhistory=os.read(4,1<<20)\nos.write(1,b'REC OK: '+history)\n",
            encoding="utf-8")
        self.now = 1_800_000_000_000
        self.components = RecorderComponents(
            store=self.store, evidence_recorder_key=self.key,
            executor_command=(sys.executable, str(self.executor)), clock_ms=lambda: self.now)

    def _request(self, **over) -> dict:
        base = {
            "protocol": "brops.governed-record-request.v1",
            "run_id": "run-1", "execution_attempt_id": "attempt-1", "lease_id": "lease-1",
            "receipt_id": "receipt-1", "task_id": "task-1", "agent_id": "Bro",
            "runner_id": "runner-1", "executor_id": "exec-1",
            "system_handle": self.system_handle, "history_handle": self.history_handle,
            "generation_config_handle": self.config_handle, "issued_at_epoch": 42,
        }
        base.update(over)
        return base

    # --- malformed requests fail closed BEFORE execution (cross-platform) --------------------------

    def test_malformed_request_is_refused(self):
        bad = self._request()
        del bad["lease_id"]
        r = record_governed_turn(bad, self.components)
        self.assertEqual(r["status"], "refused")
        self.assertTrue(r["reason"].startswith("malformed"))

    def test_non_integer_issued_at_epoch_refused(self):
        r = record_governed_turn(self._request(issued_at_epoch="42"), self.components)
        self.assertEqual(r["status"], "refused")
        self.assertTrue(r["reason"].startswith("malformed"))

    def test_wrong_protocol_refused(self):
        r = record_governed_turn(self._request(protocol="nope"), self.components)
        self.assertEqual(r["status"], "refused")

    # --- real execution + evidence chain (POSIX: FD passing + process groups) ----------------------

    @unittest.skipUnless(os.name == "posix", "recorder-owned execution uses POSIX FD passing")
    def test_records_turn_and_mints_verifiable_chain(self):
        r = record_governed_turn(self._request(), self.components)
        self.assertEqual(r["status"], "recorded", r)
        # the recorder ran the executor and captured ITS output (not supervisor-supplied bytes).
        self.assertEqual(self.store.read(r["output_handle"]), b"REC OK: hello-history")
        self.assertEqual(r["output_bytes"], len(b"REC OK: hello-history"))
        self.assertEqual(r["containment"]["contained"], True)
        self.assertEqual(r["containment"]["teardown_outcome"], "contained")
        self.store.read(r["containment_handle"])
        self.store.read(r["execution_receipt_handle"])
        # the signed bro_evidence chain the recorder wrote validates under the SIGNER's own path.
        ev_keys = {self.key["key_id"]: TrustedKey(
            key_id=self.key["key_id"], public_key=self.key["public_key"],
            authority_type="evidence-recorder",
            allowed_artifact_types=("evidence-event", "evidence-head"),
            not_before_epoch=0, not_after_epoch=(1 << 62), status=ACTIVE,
            issued_by="root", subject_agent_id="Bro")}
        evidence_dir = pathlib.Path(self.store.rec.root) / "evidence"
        detail = validate_chain_detailed(
            "task-1", [r["evidence_event_id"]], ev_keys, store=evidence_dir, now=42)
        self.assertEqual(detail["event_count"], 1)
        self.assertEqual(detail["final_event_hash"], r["evidence_final_event_hash"])

    @unittest.skipUnless(os.name == "posix", "recorder-owned execution uses POSIX FD passing")
    def test_chain_rejects_wrong_authority_key(self):
        r = record_governed_turn(self._request(), self.components)
        self.assertEqual(r["status"], "recorded", r)
        other = _keypair("intruder")
        wrong_keys = {self.key["key_id"]: TrustedKey(
            key_id=self.key["key_id"], public_key=other["public_key"],   # mismatched pubkey
            authority_type="evidence-recorder",
            allowed_artifact_types=("evidence-event", "evidence-head"),
            not_before_epoch=0, not_after_epoch=(1 << 62), status=ACTIVE,
            issued_by="root", subject_agent_id="Bro")}
        evidence_dir = pathlib.Path(self.store.rec.root) / "evidence"
        with self.assertRaises(Exception):
            validate_chain_detailed("task-1", [r["evidence_event_id"]], wrong_keys,
                                    store=evidence_dir, now=42)

    @unittest.skipUnless(os.name == "posix", "recorder-owned execution uses POSIX FD passing")
    def test_nonzero_exit_is_refused(self):
        self.executor.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
        r = record_governed_turn(self._request(), self.components)
        self.assertEqual(r["status"], "refused")
        self.assertEqual(r["reason"], "run_binding_invalid")


if __name__ == "__main__":
    unittest.main()
