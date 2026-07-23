"""Wave 3b-1 — authoritative LiveRunStateProvider (design §1.3; audit P0-3).

Proves the provider yields a RunState ONLY when the run's SIGNED artifacts validate:
execution lease (authentic + bound + unexpired), passing execution receipt (signed,
exit 0), evidence-chain head + chain, and containment. Every failure is fail-closed.
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
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # tests/ for _operator_pin

from bro_evidence import event_hash
from bro_receipt import catalog_sha256
from bro_signature import load_trusted_keys
from broctl import build_registry, generate_key, sign_payload
from _operator_pin import use_operator_pin

from brops_live_runstate import LiveRunStateProvider, RunStateValidationError

NOW = 1000
AGENT = "agt-p01-r01"
AUTHORITIES = ("operator-root", "issuer", "evidence-recorder", "builder")
CAND_HEAD = "a" * 40
CAND_TREE = "b" * 64


def _sign(keys, authority, payload):
    return sign_payload(keys[authority]["private_key"], payload)


def _build_evidence_chain(store, keys, task_id, count=2):
    previous, ids, digest = None, [], ""
    for sequence in range(1, count + 1):
        event_id = f"{task_id}-e{sequence}"
        payload = {
            "artifact_type": "evidence-event", "key_id": keys["evidence-recorder"]["key_id"],
            "event_id": event_id, "sequence": sequence, "previous_event_hash": previous,
            "task_id": task_id, "event_type": "work-recorded", "agent_id": AGENT,
            "payload_hash": "a" * 64, "issued_at_epoch": 1,
        }
        (store / f"{event_id}.json").write_text(json.dumps(_sign(keys, "evidence-recorder", payload)))
        digest = event_hash(payload)
        previous = digest
        ids.append(event_id)
    head = {
        "artifact_type": "evidence-head", "key_id": keys["evidence-recorder"]["key_id"],
        "task_id": task_id, "final_event_hash": digest, "event_count": count,
        "last_sequence": count, "head_sequence": 1, "issued_at_epoch": 1,
    }
    (store / f"{task_id}.head.json").write_text(json.dumps(_sign(keys, "evidence-recorder", head)))
    return ids


class LiveRunStateProviderTests(unittest.TestCase):
    def setUp(self):
        self.base = pathlib.Path(tempfile.mkdtemp())
        self.store = self.base / "evidence"
        self.store.mkdir()
        self.state_dir = self.base / "state"
        self.state_dir.mkdir()
        self.worktree = str(self.base / "wt")
        (self.base / "wt").mkdir()

        self.keys = {a: generate_key(a, f"dev-{a}", False) for a in AUTHORITIES}
        use_operator_pin(self, self.keys["operator-root"]["public_key"])
        (self.base / "config").mkdir()
        (self.base / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(self.keys.values()), NOW - 60, 86400)), encoding="utf-8"
        )
        self.trusted = load_trusted_keys(self.base)
        self.task_id = "task-1"
        self.event_ids = _build_evidence_chain(self.store, self.keys, self.task_id, 2)

        self.provider = LiveRunStateProvider(
            state_dir=self.state_dir, trusted_keys=self.trusted, evidence_store=self.store,
            now_epoch=NOW, required_capabilities=("EXECUTE_CODE",),
        )

    def _lease_payload(self, **over):
        p = {
            "artifact_type": "execution-lease", "key_id": self.keys["issuer"]["key_id"],
            "schema": 1, "lease_id": "lease-1", "nonce": "nonce-000000000001", "task_id": self.task_id,
            "agent_id": AGENT, "session_id": "session-1", "repository": "menqstudio/Bro",
            "branch": self.task_id, "worktree": self.worktree, "head_sha": CAND_HEAD,
            "tree_identity": CAND_TREE, "allowed_capabilities": ["EXECUTE_CODE", "WRITE_REPOSITORY"],
            "issued_at_epoch": NOW - 10, "expires_at_epoch": NOW + 100, "max_tool_calls": 1,
            "task_class": "standard-builder", "protected_scope": [],
            "control_plane_digest": "e" * 64, "workspace_id": "ws-1",
        }
        p.update(over)
        return p

    def _receipt_payload(self, **over):
        p = {
            "artifact_type": "evidence-event", "key_id": self.keys["evidence-recorder"]["key_id"],
            "receipt_id": "receipt-1", "task_id": self.task_id, "command": ["pytest", "-q"],
            "working_directory": self.worktree, "candidate_head": CAND_HEAD,
            "candidate_tree": CAND_TREE, "exit_code": 0, "stdout_sha256": "c" * 64,
            "stderr_sha256": "d" * 64, "runner_id": "runner-1", "runner_platform": "linux",
            "started_at_epoch": NOW - 5, "finished_at_epoch": NOW - 1,
            "test_catalog_sha256": catalog_sha256(ROOT), "issued_at_epoch": NOW - 1,
        }
        p.update(over)
        return p

    def _task(self):
        return {
            "task_id": self.task_id,
            "repository": {
                "full_name": "menqstudio/Bro", "branch": self.task_id,
                "worktree": self.worktree, "base_commit": CAND_HEAD, "tree_identity": CAND_TREE,
            },
        }

    def _write_record(self, *, lease=None, receipt=None, **over):
        record = {
            "run_id": "run-1", "execution_attempt_id": "attempt-1", "decision": "completed",
            "contained": True, "task": self._task(), "agent_id": AGENT, "session_id": "session-1",
            "control_plane_digest": "e" * 64,
            "lease_document": _sign(self.keys, "issuer", lease or self._lease_payload()),
            "receipt_document": _sign(self.keys, "evidence-recorder", receipt or self._receipt_payload()),
            "candidate_head": CAND_HEAD, "candidate_tree": CAND_TREE,
            "evidence_event_ids": self.event_ids,
            "lease_id": "lease-1", "request_nonce": "nonce-1", "receipt_id": "receipt-1",
            "workspace_id": "ws-1", "install_id": "install-1", "supervisor_id": "sup-1",
            "executor_id": "exec-1", "builder_id": "builder-1", "policy_id": "policy-1",
            "policy_version": "1", "requested_at": "1000", "completed_at": "2000",
            "system": "sys", "history": [{"role": "user", "content": "hi"}], "output": "out",
            "generation_config": "{}", "containment_evidence": {"contained": True},
            "policy_bundle_b64": base64.urlsafe_b64encode(b"pb").rstrip(b"=").decode(),
        }
        record.update(over)
        (self.state_dir / "run-1__attempt-1.json").write_text(json.dumps(record), encoding="utf-8")

    def test_fully_validated_run_yields_a_runstate(self):
        self._write_record()
        state = self.provider.terminal_run_state("run-1", "attempt-1")
        self.assertIsNotNone(state)
        self.assertEqual(state.lease_id, "lease-1")
        self.assertEqual(state.decision, "completed")
        self.assertEqual(state.policy_bundle, b"pb")

    def test_missing_record_is_not_terminal(self):
        self.assertIsNone(self.provider.terminal_run_state("ghost", "attempt-x"))

    def test_tampered_lease_signature_is_refused(self):
        self._write_record()
        path = self.state_dir / "run-1__attempt-1.json"
        rec = json.loads(path.read_text())
        rec["lease_document"]["signature"] = "00" * 64  # break the lease signature
        path.write_text(json.dumps(rec))
        with self.assertRaises(RunStateValidationError):
            self.provider.terminal_run_state("run-1", "attempt-1")

    def test_expired_lease_is_refused(self):
        self._write_record(lease=self._lease_payload(expires_at_epoch=NOW - 1))
        with self.assertRaises(RunStateValidationError):
            self.provider.terminal_run_state("run-1", "attempt-1")

    def test_lease_bound_to_a_different_agent_is_refused(self):
        self._write_record(lease=self._lease_payload(agent_id="agt-p01-r99"))
        with self.assertRaises(RunStateValidationError):
            self.provider.terminal_run_state("run-1", "attempt-1")

    def test_failing_receipt_is_refused(self):
        self._write_record(receipt=self._receipt_payload(exit_code=1))
        with self.assertRaises(RunStateValidationError):
            self.provider.terminal_run_state("run-1", "attempt-1")

    def test_receipt_for_a_different_head_is_refused(self):
        self._write_record(receipt=self._receipt_payload(candidate_head="f" * 40))
        with self.assertRaises(RunStateValidationError):
            self.provider.terminal_run_state("run-1", "attempt-1")

    def test_uncontained_run_is_refused(self):
        self._write_record(contained=False)
        with self.assertRaises(RunStateValidationError):
            self.provider.terminal_run_state("run-1", "attempt-1")

    def test_non_completed_run_is_refused(self):
        self._write_record(decision="failed")
        with self.assertRaises(RunStateValidationError):
            self.provider.terminal_run_state("run-1", "attempt-1")

    def test_record_lease_id_not_matching_signed_lease_is_refused(self):
        # The record claims a lease_id the SIGNED lease does not carry (P0-3 cross-bind).
        self._write_record(lease_id="lease-DIFFERENT")
        with self.assertRaises(RunStateValidationError):
            self.provider.terminal_run_state("run-1", "attempt-1")

    def test_record_receipt_id_not_matching_signed_receipt_is_refused(self):
        self._write_record(receipt_id="receipt-DIFFERENT")
        with self.assertRaises(RunStateValidationError):
            self.provider.terminal_run_state("run-1", "attempt-1")

    def test_missing_evidence_chain_is_refused(self):
        self._write_record(evidence_event_ids=["task-1-e1", "task-1-eMISSING"])
        with self.assertRaises(RunStateValidationError):
            self.provider.terminal_run_state("run-1", "attempt-1")


if __name__ == "__main__":
    unittest.main()
