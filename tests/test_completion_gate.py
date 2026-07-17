import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_completion import (
    CompletionError,
    authorize_conductor_stop,
    authorize_stop,
    validate_completion,
    validate_verifier_receipt,
)
from bro_policy import CANONICAL_CONDUCTOR_ID, CONDUCTOR_ROLE, UNKNOWN_ROLE, State
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


class ConductorStopTests(unittest.TestCase):
    """Demanding a builder's completion manifest from the conductor is a category
    error: Bro delegates and never builds, so the artifact can never exist. The
    gate was not strict, it was unsatisfiable."""

    def setUp(self):
        self.state_dir = pathlib.Path(tempfile.mkdtemp(prefix="bro-stop-"))
        self.addCleanup(shutil.rmtree, self.state_dir, ignore_errors=True)
        self.env = {"BRO_SESSION_STATE_DIR": str(self.state_dir)}
        for key in ("BRO_TASK_CONTRACT",):
            self.env.pop(key, None)

    def conductor(self, session="s-1"):
        return State("review", CONDUCTOR_ROLE, session, CANONICAL_CONDUCTOR_ID)

    def authorize(self, state, **extra):
        env = {k: v for k, v in os.environ.items() if k != "BRO_TASK_CONTRACT"}
        env.update(self.env)
        env.update(extra)
        with patch.dict(os.environ, env, clear=True):
            return authorize_conductor_stop(state, ROOT)

    def test_conductor_without_a_contract_may_finish(self):
        allowed, reason = self.authorize(self.conductor())
        self.assertTrue(allowed, reason)
        self.assertIn("no builder evidence is owed", reason)

    def test_specialist_may_not_use_the_exemption(self):
        allowed, reason = self.authorize(State("work", "specialist", "s-1", "agt-p01-r01"))
        self.assertFalse(allowed)
        self.assertIn("canonical conductor", reason)

    def test_role_name_alone_may_not_use_the_exemption(self):
        allowed, _ = self.authorize(State("review", CONDUCTOR_ROLE, "s-1", "agt-p01-r01"))
        self.assertFalse(allowed)

    def test_canonical_id_without_the_role_may_not_use_the_exemption(self):
        allowed, _ = self.authorize(State("review", "specialist", "s-1", CANONICAL_CONDUCTOR_ID))
        self.assertFalse(allowed)

    def test_unauthenticated_may_not_use_the_exemption(self):
        allowed, _ = self.authorize(State("review", UNKNOWN_ROLE, "s-1", ""))
        self.assertFalse(allowed)

    def test_conductor_holding_a_contract_owes_the_full_gate(self):
        """A bound contract means Bro executed, and executed work owes evidence."""
        contract = self.state_dir / "task.json"
        contract.write_text(json.dumps(TASK), encoding="utf-8")
        allowed, reason = self.authorize(self.conductor(), BRO_TASK_CONTRACT=str(contract))
        self.assertFalse(allowed)
        self.assertIn("executor for this turn", reason)

    def test_frozen_session_must_terminate_not_finish(self):
        from bro_freeze import freeze_authority

        with patch.dict(os.environ, self.env):
            freeze_authority("s-frozen", "task-sec-1", "0" * 64)
        allowed, reason = self.authorize(self.conductor("s-frozen"))
        self.assertFalse(allowed)
        self.assertIn("frozen", reason)

    def test_unreadable_freeze_marker_fails_closed(self):
        (self.state_dir / "s-bad.freeze.json").write_text("{not json", encoding="utf-8")
        allowed, reason = self.authorize(self.conductor("s-bad"))
        self.assertFalse(allowed)
        self.assertIn("freeze state gate RED", reason)

    def test_specialist_stop_gate_is_unchanged(self):
        """The exemption must not soften the path it does not cover."""
        with patch("bro_completion._signed_env",
                   side_effect=CompletionError("missing BRO_COMPLETION_MANIFEST")):
            allowed, reason = authorize_stop(TASK, TASK["agent_id"], ROOT)
        self.assertFalse(allowed)
        self.assertIn("missing BRO_COMPLETION_MANIFEST", reason)


if __name__ == "__main__":
    unittest.main()
