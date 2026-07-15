import copy
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_orchestration import (
    OrchestrationError,
    build_control_room_projection,
    validate_control_room_command,
    validate_orchestration_registry,
    validate_transition,
)


class OrchestrationTests(unittest.TestCase):
    def test_registry_is_canonical_and_complete(self):
        result = validate_orchestration_registry(ROOT)
        self.assertEqual(result["states"], 13)
        self.assertEqual(result["commands"], 6)
        self.assertEqual(result["surfaces"], 6)
        self.assertEqual(result["queues"], 5)

    def test_first_state_must_be_draft(self):
        validate_transition(None, "draft", ROOT)
        with self.assertRaises(OrchestrationError):
            validate_transition(None, "running", ROOT)

    def test_impossible_and_terminal_transitions_are_denied(self):
        validate_transition("queued", "routing", ROOT)
        with self.assertRaises(OrchestrationError):
            validate_transition("queued", "completed", ROOT)
        with self.assertRaises(OrchestrationError):
            validate_transition("completed", "running", ROOT)

    def test_projection_is_evidence_backed_and_fail_closed(self):
        events = [
            {
                "event_id": "evt-1",
                "task_id": "task-1",
                "sequence": 1,
                "previous_state": None,
                "next_state": "draft",
                "observed_at_epoch": 100,
                "evidence_refs": [],
            },
            {
                "event_id": "evt-2",
                "task_id": "task-1",
                "sequence": 2,
                "previous_state": "draft",
                "next_state": "queued",
                "observed_at_epoch": 110,
                "evidence_refs": ["evidence/task-1/queue.json"],
            },
            {
                "event_id": "evt-3",
                "task_id": "task-2",
                "sequence": 1,
                "previous_state": None,
                "next_state": "draft",
                "observed_at_epoch": 100,
                "evidence_refs": [],
            },
            {
                "event_id": "evt-4",
                "task_id": "task-2",
                "sequence": 2,
                "previous_state": "draft",
                "next_state": "queued",
                "observed_at_epoch": 101,
                "evidence_refs": ["evidence/task-2/queue.json"],
            },
            {
                "event_id": "evt-5",
                "task_id": "task-2",
                "sequence": 3,
                "previous_state": "queued",
                "next_state": "routing",
                "observed_at_epoch": 102,
                "evidence_refs": ["evidence/task-2/routing.json"],
            },
            {
                "event_id": "evt-6",
                "task_id": "task-2",
                "sequence": 4,
                "previous_state": "routing",
                "next_state": "running",
                "observed_at_epoch": 103,
                "evidence_refs": ["evidence/task-2/start.json"],
            },
            {
                "event_id": "evt-7",
                "task_id": "task-2",
                "sequence": 5,
                "previous_state": "running",
                "next_state": "quarantined",
                "observed_at_epoch": 120,
                "evidence_refs": ["evidence/task-2/ambiguity.json"],
            },
        ]
        projection = build_control_room_projection(events, 200, ROOT)
        self.assertEqual(projection["health"], "critical")
        self.assertEqual(projection["state_counts"]["queued"], 1)
        self.assertEqual(projection["state_counts"]["quarantined"], 1)
        self.assertTrue(next(item for item in projection["tasks"] if item["task_id"] == "task-2")["recovery_open"])

        duplicate = copy.deepcopy(events)
        duplicate[-1]["event_id"] = "evt-1"
        with self.assertRaises(OrchestrationError):
            build_control_room_projection(duplicate, 200, ROOT)

    def test_control_room_commands_are_state_actor_and_expiry_bound(self):
        command = {
            "schema": 1,
            "command_id": "cmd-1",
            "task_id": "task-1",
            "command": "approve",
            "requested_by_type": "owner",
            "requested_by": "owner-gev",
            "requested_at_epoch": 100,
            "expires_at_epoch": 200,
            "expected_task_state": "waiting-approval",
            "scope": ["task-1"],
            "reason": "Approve exact task continuation",
            "evidence_refs": ["evidence/task-1/approval.json"],
        }
        validate_control_room_command(command, "waiting-approval", 150, ROOT)

        stale = copy.deepcopy(command)
        stale["expected_task_state"] = "running"
        with self.assertRaises(OrchestrationError):
            validate_control_room_command(stale, "waiting-approval", 150, ROOT)

        expired = copy.deepcopy(command)
        expired["expires_at_epoch"] = 120
        with self.assertRaises(OrchestrationError):
            validate_control_room_command(expired, "waiting-approval", 150, ROOT)

        bro_approval = copy.deepcopy(command)
        bro_approval["requested_by_type"] = "bro"
        bro_approval["requested_by"] = "bro-000"
        with self.assertRaises(OrchestrationError):
            validate_control_room_command(bro_approval, "waiting-approval", 150, ROOT)


if __name__ == "__main__":
    unittest.main()
