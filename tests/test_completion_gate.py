import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_completion import CompletionError, authorize_stop, validate_completion, validate_verifier_receipt
from bro_repository_state import RepositoryState


TASK = {
    "task_id": "task-complete-1",
    "agent_id": "agt-p01-r01",
    "risk": "critical",
    "done_criteria": ["tests green"],
    "verification": {
        "required": True,
        "verifier_agent_id": "agt-p01-r02",
        "verifier_role": "Independent Verifier",
    },
}


def manifest():
    from bro_contracts import canonical_json_sha256
    return {
        "schema": 1,
        "task_id": TASK["task_id"],
        "agent_id": TASK["agent_id"],
        "task_contract_sha256": canonical_json_sha256(TASK),
        "candidate_head": "a" * 40,
        "candidate_tree": "b" * 64,
        "done_criteria": [{"criterion": "tests green", "status": "satisfied", "evidence_event_ids": ["evt-1"]}],
        "tests": [{"command": "python -m unittest", "status": "passed", "evidence_event_id": "evt-1"}],
        "evidence_event_ids": ["evt-1"],
        "open_risks": [],
        "rollback_ready": True,
        "issued_at_epoch": 1000,
    }


class CompletionGateTests(unittest.TestCase):
    def test_missing_manifest_denies_stop(self):
        with patch("bro_completion._signed_env", side_effect=CompletionError("missing BRO_COMPLETION_MANIFEST")):
            allowed, reason = authorize_stop(TASK, TASK["agent_id"], ROOT)
        self.assertFalse(allowed)
        self.assertIn("missing BRO_COMPLETION_MANIFEST", reason)

    def test_dirty_repository_denies_completion(self):
        with (
            patch("bro_completion._signed_env", return_value=manifest()),
            patch("bro_completion.resolve_state", return_value=RepositoryState(ROOT, ROOT, "x", "a" * 40, "b" * 64)),
            patch("bro_completion.validate_evidence_chain"),
            patch("bro_completion._clean_repository", side_effect=CompletionError("repository is dirty")),
        ):
            with self.assertRaises(CompletionError):
                validate_completion(TASK, TASK["agent_id"], ROOT)

    def test_pending_or_ambiguous_lease_denies_completion(self):
        with (
            patch("bro_completion._signed_env", return_value=manifest()),
            patch("bro_completion.resolve_state", return_value=RepositoryState(ROOT, ROOT, "x", "a" * 40, "b" * 64)),
            patch("bro_completion.validate_evidence_chain"),
            patch("bro_completion._clean_repository"),
            patch("bro_completion._no_pending_execution", side_effect=CompletionError("pending or ambiguous execution lease exists")),
        ):
            with self.assertRaises(CompletionError):
                validate_completion(TASK, TASK["agent_id"], ROOT)

    def test_evidence_link_mismatch_denies_completion(self):
        with (
            patch("bro_completion._signed_env", return_value=manifest()),
            patch("bro_completion.resolve_state", return_value=RepositoryState(ROOT, ROOT, "x", "a" * 40, "b" * 64)),
            patch("bro_completion.validate_evidence_chain", side_effect=CompletionError("evidence chain linkage mismatch")),
        ):
            with self.assertRaises(CompletionError):
                validate_completion(TASK, TASK["agent_id"], ROOT)

    def test_bad_verifier_verdict_denied(self):
        receipt = {"schema": 1, "verdict": "RED"}
        with patch("bro_completion._signed_env", return_value=receipt):
            with self.assertRaises(CompletionError):
                validate_verifier_receipt(TASK, manifest(), manifest()["task_contract_sha256"], ROOT)

    def test_valid_manifest_and_verifier_allow_stop(self):
        with (
            patch("bro_completion.validate_completion", return_value=(manifest(), manifest()["task_contract_sha256"])),
            patch("bro_completion.validate_verifier_receipt", return_value={"verdict": "GREEN"}),
        ):
            allowed, reason = authorize_stop(TASK, TASK["agent_id"], ROOT)
        self.assertTrue(allowed)
        self.assertIn("GREEN", reason)


if __name__ == "__main__":
    unittest.main()
