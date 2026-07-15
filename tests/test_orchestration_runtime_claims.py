import pathlib
import sys
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_orchestration_runtime import OrchestrationRuntimeError
from bro_orchestration_runtime_v1 import DurableOrchestrationRuntimeV1

AGENT = "agt-p01-r01"


def task_contract(task_id: str) -> dict:
    return {
        "schema": 1,
        "task_id": task_id,
        "title": f"Task {task_id}",
        "objective": "Exercise atomic orchestration claim leases",
        "mode": "work",
        "risk": "low",
        "pack_id": "ai-agent-builders",
        "agent_id": AGENT,
        "assignee_role": "Agent Architect",
        "scope": ["runtime"],
        "prohibited_scope": ["release"],
        "inputs": ["orchestration/registry.json"],
        "core_skills": ["ai-agent-engineering"],
        "additional_skills": [],
        "reference_skills": [],
        "done_criteria": ["Claim is serialized and evidence-backed"],
        "verification": {
            "required": False,
            "verifier_agent_id": None,
            "verifier_role": None,
            "commands": [],
        },
        "rollback": {"strategy": "Discard isolated runtime state", "commands": []},
        "repository": {
            "full_name": "menqstudio/Bro",
            "branch": "orchestration-runtime-v1",
            "worktree": "C:/Bro/runtime-v1",
            "base_commit": "b5d1a343a8777738d4113e3e28cf27527f04020a",
            "tree_identity": "1" * 64,
        },
    }


class ClaimLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.state_dir = pathlib.Path(self.temporary.name)
        self.runtime = DurableOrchestrationRuntimeV1(self.state_dir, ROOT)

    def tearDown(self):
        self.temporary.cleanup()

    def test_parallel_claim_returns_task_once(self):
        self.runtime.create_task(task_contract("task-parallel"), now_epoch=100)
        results = []
        errors = []

        def claim():
            try:
                results.append(DurableOrchestrationRuntimeV1(self.state_dir, ROOT).claim_next(AGENT, now_epoch=101))
            except Exception as exc:
                errors.append(exc)

        workers = [threading.Thread(target=claim) for _ in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        self.assertFalse(errors)
        claimed = [item for item in results if item is not None]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["task_id"], "task-parallel")
        self.assertRegex(claimed[0]["lease_id"], r"^lease-[0-9a-f]{32}$")

    def test_active_lease_blocks_second_claim(self):
        self.runtime.create_task(task_contract("task-one"), now_epoch=100)
        first = self.runtime.claim_next(AGENT, now_epoch=101, lease_seconds=10)
        self.assertIsNotNone(first)
        self.runtime.create_task(task_contract("task-two"), now_epoch=102)
        second = self.runtime.claim_next(AGENT, now_epoch=103)
        self.assertEqual(second["task_id"], "task-two")

    def test_renew_requires_exact_lease_and_agent(self):
        self.runtime.create_task(task_contract("task-renew"), now_epoch=100)
        claimed = self.runtime.claim_next(AGENT, now_epoch=101, lease_seconds=10)
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.renew_claim(
                "task-renew", agent_id=AGENT, lease_id="lease-wrong",
                now_epoch=102, lease_seconds=10,
            )
        renewed = self.runtime.renew_claim(
            "task-renew", agent_id=AGENT, lease_id=claimed["lease_id"],
            now_epoch=102, lease_seconds=20,
        )
        self.assertNotEqual(renewed["lease_id"], claimed["lease_id"])
        self.assertEqual(renewed["expires_at_epoch"], 122)

    def test_release_requires_evidence(self):
        self.runtime.create_task(task_contract("task-release"), now_epoch=100)
        claimed = self.runtime.claim_next(AGENT, now_epoch=101)
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.release_claim(
                "task-release", agent_id=AGENT, lease_id=claimed["lease_id"],
                now_epoch=102, evidence_refs=[],
            )
        snapshot = self.runtime.release_claim(
            "task-release", agent_id=AGENT, lease_id=claimed["lease_id"],
            now_epoch=102, evidence_refs=["evidence/release.json"],
        )
        self.assertEqual(snapshot["state"], "running")

    def test_expired_queued_lease_is_recovered(self):
        self.runtime.create_task(task_contract("task-expired"), now_epoch=100)
        self.runtime._append(
            "task-expired", "claim-lease", 101,
            {
                "lease_id": "lease-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "agent_id": AGENT,
                "issued_at_epoch": 101,
                "expires_at_epoch": 102,
            },
        )
        claimed = self.runtime.claim_next(AGENT, now_epoch=103)
        self.assertEqual(claimed["task_id"], "task-expired")
        kinds = [item["kind"] for item in self.runtime._records("task-expired")]
        self.assertIn("claim-expired", kinds)

    def test_invalid_lease_duration_fails_closed(self):
        self.runtime.create_task(task_contract("task-duration"), now_epoch=100)
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.claim_next(AGENT, now_epoch=101, lease_seconds=0)


if __name__ == "__main__":
    unittest.main()
