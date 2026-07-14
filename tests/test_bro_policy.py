import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_authorization import classify_tool_action
from bro_policy import State, authorize_classified_action


def bundle(agent_id="agent-1"):
    return SimpleNamespace(
        agent={"agent_id": agent_id},
        task={
            "scope": ["runtime/"],
            "prohibited_scope": ["runtime/secret/"],
            "repository": {
                "full_name": "menqstudio/Bro",
                "branch": "bro-execution-control-plane-v2",
            },
        },
    )


class PolicyTests(unittest.TestCase):
    def classified(self, tool, value):
        return classify_tool_action(tool, value, ROOT)

    def test_review_denies_canonical_write(self):
        classification = self.classified("Write", {"file_path": "runtime/x.py"})
        self.assertFalse(authorize_classified_action(State("review", "bro", "s"), classification, {})[0])

    def test_review_allows_canonical_read(self):
        classification = self.classified("Read", {"file_path": "README.md"})
        self.assertTrue(authorize_classified_action(State("review", "bro", "s"), classification, {})[0])

    def test_bro_cannot_mutate(self):
        classification = self.classified("Write", {"file_path": "runtime/x.py"})
        ok, reason = authorize_classified_action(State("work", "bro", "s"), classification, {})
        self.assertFalse(ok)
        self.assertIn("delegate", reason)

    def test_push_cannot_enter_downstream_policy(self):
        classification = self.classified("Bash", {"command": "git push origin HEAD:bro-execution-control-plane-v2"})
        ok, reason = authorize_classified_action(State("release", "push-executor", "s", "agent-1"), classification, {})
        self.assertFalse(ok)
        self.assertIn("Release Grant V3", reason)

    @patch("bro_policy._grant_bindings_ok", return_value=(True, "bound"))
    @patch("bro_policy.enforce_scope")
    @patch("bro_policy.load_mode_grant_from_env")
    @patch("bro_policy.load_contract_bundle_from_env")
    def test_specialist_mutation_uses_canonical_targets(self, load_bundle, load_mode, enforce, binding):
        load_bundle.return_value = bundle()
        load_mode.return_value = {"mode": "work"}
        classification = self.classified("Write", {"file_path": "runtime/x.py"})
        ok, reason = authorize_classified_action(State("work", "specialist", "s", "agent-1"), classification, {})
        self.assertTrue(ok, reason)
        enforce.assert_called_once_with(ROOT, ["runtime/x.py"], ["runtime/"], ["runtime/secret/"])
        binding.assert_called_once()

    @patch("bro_policy.load_contract_bundle_from_env", side_effect=Exception("must not load"))
    def test_review_read_needs_no_contract(self, load_bundle):
        classification = self.classified("Read", {"file_path": "README.md"})
        ok, _ = authorize_classified_action(State("review", "bro", "s"), classification, {})
        self.assertTrue(ok)
        load_bundle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
