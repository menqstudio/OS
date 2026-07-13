import os
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_policy import State, authorize_tool


class PolicyTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("BRO_EXTERNAL_RELEASE_BOUNDARY", None)

    def test_review_denies_write(self):
        ok, _ = authorize_tool(State("review", "bro", "s"), "Write", {"file_path": "x"})
        self.assertFalse(ok)

    def test_review_allows_read(self):
        ok, _ = authorize_tool(State("review", "bro", "s"), "Read", {"file_path": "x"})
        self.assertTrue(ok)

    def test_bro_cannot_mutate(self):
        ok, reason = authorize_tool(State("work", "bro", "s"), "Write", {"file_path": "x"})
        self.assertFalse(ok)
        self.assertIn("delegate", reason)

    @patch("bro_policy.load_contract_bundle_from_env")
    def test_specialist_mutation_requires_valid_bundle(self, bundle):
        bundle.return_value.agent = {"agent_id": "agent-1"}
        ok, _ = authorize_tool(State("work", "specialist", "s", "agent-1"), "Write", {"file_path": "x"})
        self.assertTrue(ok)

    def test_work_denies_push(self):
        ok, _ = authorize_tool(State("work", "specialist", "s"), "Bash", {"command": "git push origin x"})
        self.assertFalse(ok)

    @patch("bro_policy.load_contract_bundle_from_env")
    def test_release_denies_wrong_role(self, bundle):
        bundle.return_value.agent = {"agent_id": "agent-1"}
        os.environ["BRO_EXTERNAL_RELEASE_BOUNDARY"] = "confirmed"
        ok, _ = authorize_tool(State("release", "release-verifier", "s", "agent-1"), "Bash", {"command": "git push origin x"})
        self.assertFalse(ok)

    @patch("bro_policy.load_release_grant_from_env")
    @patch("bro_policy.load_contract_bundle_from_env")
    def test_release_push_executor_with_grant_and_boundary(self, bundle, grant):
        bundle.return_value.agent = {"agent_id": "push-1"}
        grant.return_value = {"grant_id": "grant-1"}
        os.environ["BRO_EXTERNAL_RELEASE_BOUNDARY"] = "confirmed"
        ok, _ = authorize_tool(State("release", "push-executor", "s", "push-1"), "Bash", {"command": "git push origin x"})
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
