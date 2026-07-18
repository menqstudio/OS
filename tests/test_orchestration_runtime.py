import json
import pathlib
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

from bro_evidence import event_hash
from bro_orchestration_runtime import DurableOrchestrationRuntime, OrchestrationRuntimeError
from bro_signature import load_trusted_keys
from broctl import build_registry, generate_key, sign_payload

AUTHORITIES = ["operator-root", "issuer", "evidence-recorder", "builder",
               "verifier", "release"]


def build_evidence(store: pathlib.Path, keys: dict, task_id: str, count: int) -> list[str]:
    """A real signed chain with a signed head.

    complete_task used to accept any non-empty strings, so the tests handed it
    "evidence/completed.json" and it believed them. Evidence has to resolve now,
    which means the tests have to produce some.
    """
    previous, ids, digest = None, [], ""
    for sequence in range(1, count + 1):
        event_id = f"{task_id}-e{sequence}"
        payload = {
            "artifact_type": "evidence-event",
            "key_id": keys["evidence-recorder"]["key_id"],
            "event_id": event_id, "sequence": sequence,
            "previous_event_hash": previous, "task_id": task_id,
            "event_type": "work-recorded", "agent_id": AGENT,
            "payload_hash": "a" * 64, "issued_at_epoch": 1,
        }
        (store / f"{event_id}.json").write_text(
            json.dumps(sign_payload(keys["evidence-recorder"]["private_key"], payload)),
            encoding="utf-8")
        digest = event_hash(payload)
        previous = digest
        ids.append(event_id)
    head = {
        "artifact_type": "evidence-head",
        "key_id": keys["evidence-recorder"]["key_id"],
        "task_id": task_id, "final_event_hash": digest,
        "event_count": count, "last_sequence": count, "issued_at_epoch": 1,
    }
    (store / f"{task_id}.head.json").write_text(
        json.dumps(sign_payload(keys["evidence-recorder"]["private_key"], head)),
        encoding="utf-8")
    return ids

AGENT = "agt-p01-r01"
OTHER_AGENT = "agt-p01-r02"


def task_contract(task_id: str, agent_id: str = AGENT) -> dict:
    role = "Agent Architect" if agent_id == AGENT else "Agent Builder"
    return {
        "schema": 1,
        "task_id": task_id,
        "title": f"Task {task_id}",
        "objective": "Exercise durable orchestration runtime",
        "mode": "work",
        "risk": "low",
        "pack_id": "ai-agent-builders",
        "agent_id": agent_id,
        "assignee_role": role,
        "scope": ["runtime"],
        "prohibited_scope": ["release"],
        "inputs": ["orchestration/registry.json"],
        "core_skills": ["ai-agent-engineering"],
        "additional_skills": [],
        "reference_skills": [],
        "done_criteria": ["Runtime behavior is evidence-backed"],
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


class DurableRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.temporary.name)
        self.store = base / "evidence"
        self.store.mkdir()
        self.keys = {a: generate_key(a, f"dev-{a}", False) for a in AUTHORITIES}
        registry_root = base / "registry"
        (registry_root / "config").mkdir(parents=True)
        now = int(time.time())
        (registry_root / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(self.keys.values()), now - 60, 86400)),
            encoding="utf-8")
        self.trusted = load_trusted_keys(registry_root)
        self.runtime = DurableOrchestrationRuntime(
            base / "state", ROOT, evidence_keys=self.trusted, evidence_store=self.store)

    def tearDown(self):
        self.temporary.cleanup()

    def test_priority_queue_and_exact_agent_claim(self):
        self.runtime.create_task(task_contract("task-background"), queue_class="background", now_epoch=100)
        self.runtime.create_task(task_contract("task-recovery"), queue_class="recovery", now_epoch=101)
        self.assertIsNone(self.runtime.claim_next(OTHER_AGENT, now_epoch=102))
        self.assertEqual(self.runtime.claim_next(AGENT, now_epoch=102)["task_id"], "task-recovery")
        self.assertEqual(self.runtime.claim_next(AGENT, now_epoch=103)["task_id"], "task-background")

    def test_duplicate_task_and_unknown_queue_fail_closed(self):
        self.runtime.create_task(task_contract("task-duplicate"), now_epoch=100)
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.create_task(task_contract("task-duplicate"), now_epoch=101)
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.create_task(task_contract("task-invalid"), queue_class="magic", now_epoch=100)

    def test_checkpoint_requires_evidence_and_becomes_stale(self):
        self.runtime.create_task(task_contract("task-checkpoint"), now_epoch=100)
        self.runtime.claim_next(AGENT, now_epoch=101)
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.checkpoint(
                "task-checkpoint", actor_id=AGENT, now_epoch=110,
                completed_criteria=["claimed"], open_risks=["none"],
                next_action="Continue", evidence_refs=[]
            )
        snapshot = self.runtime.checkpoint(
            "task-checkpoint", actor_id=AGENT, now_epoch=110,
            completed_criteria=["claimed"], open_risks=["none"],
            next_action="Continue", evidence_refs=["evidence/checkpoint.json"]
        )
        self.assertFalse(snapshot["stale"])
        self.assertTrue(self.runtime.task_snapshot("task-checkpoint", 1011)["stale"])

    def test_soft_and_hard_budget_gates(self):
        limits = {"tool_calls": {"soft": 2, "hard": 4}}
        self.runtime.create_task(task_contract("task-soft"), now_epoch=100, budget_limits=limits)
        self.runtime.claim_next(AGENT, now_epoch=101)
        soft = self.runtime.record_usage(
            "task-soft", actor_id=AGENT, now_epoch=102,
            delta={"tool_calls": 3}, evidence_refs=["evidence/soft.json"]
        )
        self.assertEqual(soft["state"], "waiting-approval")

        self.runtime.create_task(task_contract("task-hard"), now_epoch=103, budget_limits=limits)
        self.runtime.claim_next(AGENT, now_epoch=104)
        hard = self.runtime.record_usage(
            "task-hard", actor_id=AGENT, now_epoch=105,
            delta={"tool_calls": 5}, evidence_refs=["evidence/hard.json"]
        )
        self.assertEqual(hard["state"], "blocked")

    def test_owner_retry_and_terminal_immutability(self):
        limits = {"tool_calls": {"soft": None, "hard": 1}}
        self.runtime.create_task(task_contract("task-retry"), now_epoch=100, budget_limits=limits)
        self.runtime.claim_next(AGENT, now_epoch=101)
        self.runtime.record_usage(
            "task-retry", actor_id=AGENT, now_epoch=102,
            delta={"tool_calls": 2}, evidence_refs=["evidence/hard.json"]
        )
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.retry_blocked(
                "task-retry", owner_id="owner-fake", now_epoch=103,
                evidence_refs=["evidence/retry.json"]
            )
        self.assertEqual(self.runtime.retry_blocked(
            "task-retry", owner_id="owner-gev", now_epoch=103,
            evidence_refs=["evidence/retry.json"]
        )["state"], "queued")
        self.runtime.claim_next(AGENT, now_epoch=104)
        refs = build_evidence(self.store, self.keys, "task-retry", 2)
        self.assertEqual(self.runtime.complete_task(
            "task-retry", actor_id=AGENT, now_epoch=105, evidence_refs=refs
        )["state"], "completed")
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.cancel_task(
                "task-retry", actor_type="owner", actor_id="owner-gev",
                now_epoch=106, effect_in_flight=False, evidence_refs=[]
            )

    def test_inflight_cancel_requires_recovery_proof(self):
        self.runtime.create_task(task_contract("task-recovery"), now_epoch=100)
        self.runtime.claim_next(AGENT, now_epoch=101)
        state = self.runtime.cancel_task(
            "task-recovery", actor_type="owner", actor_id="owner-gev",
            now_epoch=102, effect_in_flight=True,
            evidence_refs=["evidence/ambiguous.json"]
        )
        self.assertEqual(state["state"], "recovery-required")
        recovered = self.runtime.recover_task(
            "task-recovery", owner_id="owner-gev", now_epoch=103,
            evidence_refs=["evidence/recovery.json"]
        )
        self.assertEqual(recovered["state"], "running")
        cancelled = self.runtime.cancel_task(
            "task-recovery", actor_type="bro", actor_id="bro-000",
            now_epoch=104, effect_in_flight=False, evidence_refs=[]
        )
        self.assertEqual(cancelled["state"], "cancelled")

    def test_hash_chain_tamper_is_denied(self):
        self.runtime.create_task(task_contract("task-tamper"), now_epoch=100)
        record = self.runtime.state_dir / "tasks" / "task-tamper" / "records" / "00000002.json"
        value = json.loads(record.read_text())
        value["payload"]["next_state"] = "completed"
        record.write_text(json.dumps(value))
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.integrity_report()

    def test_control_room_projection_is_derived_from_records(self):
        self.runtime.create_task(task_contract("task-projection"), now_epoch=100)
        self.runtime.claim_next(AGENT, now_epoch=101)
        projection = self.runtime.control_room_snapshot(now_epoch=102)
        self.assertEqual(projection["health"], "healthy")
        self.assertEqual(projection["state_counts"]["running"], 1)
        self.assertRegex(projection["source_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
