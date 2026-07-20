from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_control_room_api import ControlRoomAPIError, ControlRoomAPIV1
from bro_orchestration_runtime_v1 import DurableOrchestrationRuntimeV1

AGENT = "agt-p01-r01"
BASE = "6bb29bd61b171757a6aaef016fbd46e8b970ada9"


def task_contract(task_id: str) -> dict:
    return {
        "schema": 1,
        "task_id": task_id,
        "title": f"Task {task_id}",
        "objective": "Exercise governed Control Room read models",
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
        "done_criteria": ["Read models are integrity-bound"],
        "verification": {"required": False, "verifier_agent_id": None, "verifier_role": None, "commands": []},
        "rollback": {"strategy": "Discard isolated runtime state", "commands": []},
        "repository": {
            "full_name": "menqstudio/Bro",
            "branch": "control-room-api-v1",
            "worktree": "C:/Bro/control-room-api-v1",
            "base_commit": BASE,
            "tree_identity": "1" * 64,
        },
    }


def cancel_command(task_id: str = "task-api-1") -> dict:
    return {
        "schema": 1,
        "command_id": "cmd-1",
        "command": "cancel",
        "task_id": task_id,
        "requested_by_type": "owner",
        "requested_by": "owner-gev",
        "requested_at_epoch": 101,
        "expires_at_epoch": 200,
        "expected_task_state": "queued",
        "scope": [f"task:{task_id}"],
        "reason": "Owner requested cancellation review",
        "evidence_refs": [],
    }


class ControlRoomAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = DurableOrchestrationRuntimeV1(self.temp.name, ROOT)
        self.runtime.create_task(task_contract("task-api-1"), now_epoch=100)
        self.api = ControlRoomAPIV1(self.runtime)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_mission_and_task_views_are_integrity_bound(self) -> None:
        mission = self.api.mission_overview(now_epoch=101)
        detail = self.api.task_detail("task-api-1", now_epoch=101)
        self.assertEqual(mission["task_count"], 1)
        self.assertEqual(detail["snapshot"]["state"], "queued")
        self.assertEqual(mission["source_integrity_sha256"], detail["source_integrity_sha256"])
        self.assertTrue(detail["drill_down"]["available"])
        self.assertEqual(detail["contract"]["repository"]["base_commit"], BASE)

    def test_empty_runtime_is_unknown_not_green(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            api = ControlRoomAPIV1(DurableOrchestrationRuntimeV1(directory, ROOT))
            mission = api.mission_overview(now_epoch=1)
        self.assertEqual(mission["health"], "unknown")
        self.assertEqual(mission["task_count"], 0)
        self.assertFalse(mission["drill_down"]["available"])

    def test_queue_and_agent_views_are_canonical(self) -> None:
        queue = self.api.queue_state(now_epoch=101)
        agent = self.api.agent_workload(now_epoch=101, agent_id=AGENT)
        self.assertEqual(queue["tasks"][0]["queue_class"], "standard")
        self.assertEqual(agent["agents"][0]["pack_id"], "ai-agent-builders")
        self.assertEqual(agent["agents"][0]["role"], "Agent Architect")
        self.assertEqual(agent["agents"][0]["task_count"], 1)

    def test_checkpoint_view_exposes_evidence_and_freshness(self) -> None:
        lease = self.runtime.claim_next(AGENT, now_epoch=101)["lease_id"]
        self.runtime.checkpoint("task-api-1", actor_id=AGENT, lease_id=lease, now_epoch=102, completed_criteria=["Read model built"], open_risks=["None"], next_action="Verify API", evidence_refs=["evidence/checkpoint.json"])
        view = self.api.checkpoint_status("task-api-1", now_epoch=103)
        self.assertEqual(view["last_checkpoint"]["evidence_refs"], ["evidence/checkpoint.json"])
        self.assertFalse(view["freshness"]["stale"])
        self.assertTrue(self.api.checkpoint_status("task-api-1", now_epoch=1003)["freshness"]["stale"])

    def test_budget_and_approval_views_fail_closed_without_inventing_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = DurableOrchestrationRuntimeV1(directory, ROOT)
            runtime.create_task(task_contract("task-budget"), now_epoch=100, budget_limits={"tool_calls": {"soft": 1, "hard": 3}})
            lease = runtime.claim_next(AGENT, now_epoch=101)["lease_id"]
            runtime.record_usage("task-budget", actor_id=AGENT, lease_id=lease, now_epoch=102, delta={"tool_calls": 2}, evidence_refs=["evidence/usage.json"])
            api = ControlRoomAPIV1(runtime)
            budget = api.budget_status("task-budget", now_epoch=103)
            approval = api.approval_inbox(now_epoch=103)
        tool_calls = next(item for item in budget["dimensions"] if item["dimension"] == "tool_calls")
        self.assertEqual(tool_calls["status"], "soft-exceeded")
        self.assertEqual(approval["approvals"][0]["state"], "waiting-approval")
        self.assertIsNone(approval["approvals"][0]["expires_at_epoch"])
        self.assertEqual(approval["approvals"][0]["expiry_status"], "not-modeled-by-runtime-v1")

    def test_recovery_view_exposes_proof_without_inventing_effect(self) -> None:
        self.runtime.claim_next(AGENT, now_epoch=101)
        self.runtime.cancel_task("task-api-1", actor_type="owner", actor_id="owner-gev", now_epoch=102, effect_in_flight=True, evidence_refs=["evidence/ambiguous-effect.json"])
        view = self.api.recovery_quarantine(now_epoch=103)
        self.assertEqual(view["items"][0]["state"], "recovery-required")
        self.assertEqual(view["items"][0]["proof_refs"], ["evidence/ambiguous-effect.json"])
        self.assertIsNone(view["items"][0]["observed_effect"])

    def test_audit_timeline_is_deterministic(self) -> None:
        first = self.api.audit_timeline("task-api-1", now_epoch=101)
        second = self.api.audit_timeline("task-api-1", now_epoch=101)
        self.assertEqual(first["timeline_sha256"], second["timeline_sha256"])
        self.assertEqual(first["record_count"], len(first["records"]))

    def test_command_intent_validates_without_execution(self) -> None:
        command = cancel_command()
        before = self.runtime.task_snapshot("task-api-1", 101)
        result = self.api.validate_command_intent(command, now_epoch=101)
        after = self.runtime.task_snapshot("task-api-1", 101)
        self.assertTrue(result["valid"])
        self.assertFalse(result["executed"])
        self.assertFalse(result["mutation_authorized"])
        self.assertEqual(before, after)

    def test_wrong_actor_stale_state_and_forbidden_scope_fail_closed(self) -> None:
        wrong_actor = cancel_command(); wrong_actor["requested_by"] = "not-owner"
        with self.assertRaises(ControlRoomAPIError): self.api.validate_command_intent(wrong_actor, now_epoch=101)
        stale = cancel_command(); stale["expected_task_state"] = "running"
        with self.assertRaises(ControlRoomAPIError): self.api.validate_command_intent(stale, now_epoch=101)
        forbidden = cancel_command(); forbidden["scope"] = ["repository:menqstudio/Bro"]
        with self.assertRaises(ControlRoomAPIError): self.api.validate_command_intent(forbidden, now_epoch=101)

    def test_noncanonical_command_shape_fails_closed(self) -> None:
        command = cancel_command(); command["requested_by_id"] = command.pop("requested_by")
        with self.assertRaises(ControlRoomAPIError): self.api.validate_command_intent(command, now_epoch=101)

    def test_unknown_task_and_agent_fail_closed(self) -> None:
        with self.assertRaises(ControlRoomAPIError): self.api.task_detail("task-missing", now_epoch=101)
        with self.assertRaises(ControlRoomAPIError): self.api.agent_workload(now_epoch=101, agent_id="agt-p99-r99")

    def test_tampered_runtime_is_denied_by_all_reads(self) -> None:
        record = pathlib.Path(self.temp.name) / "tasks" / "task-api-1" / "records" / "00000002.json"
        value = json.loads(record.read_text(encoding="utf-8")); value["payload"]["next_state"] = "completed"
        record.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(ControlRoomAPIError): self.api.mission_overview(now_epoch=101)
        with self.assertRaises(ControlRoomAPIError): self.api.task_detail("task-api-1", now_epoch=101)


if __name__ == "__main__":
    unittest.main()
