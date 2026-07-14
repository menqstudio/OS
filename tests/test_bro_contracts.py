import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_contracts import ContractError, safe_repo_path, validate_agent_profile


class ContractTests(unittest.TestCase):
    def test_safe_repository_paths(self):
        self.assertEqual(safe_repo_path("docs/ARCHITECTURE.md"), "docs/ARCHITECTURE.md")
        for value in ("../secret", "/absolute/path", "C:/Windows/System32"):
            with self.assertRaises(ContractError):
                safe_repo_path(value)

    def test_only_push_executor_may_have_push_capability(self):
        value = {
            "schema": 1,
            "agent_id": "agt-p01-r01",
            "pack_id": "ai-agent-builders",
            "role": "Agent Architect",
            "core_skills": ["ai-agent-engineering"],
            "allowed_modes": ["review", "work"],
            "can_verify": False,
            "can_push": True,
        }
        with self.assertRaises(ContractError):
            validate_agent_profile(value, ROOT)

    def test_registered_base_agent_profile_is_valid(self):
        value = {
            "schema": 1,
            "agent_id": "agt-p01-r01",
            "pack_id": "ai-agent-builders",
            "role": "Agent Architect",
            "core_skills": ["ai-agent-engineering"],
            "allowed_modes": ["review", "work"],
            "can_verify": False,
            "can_push": False,
        }
        self.assertEqual(validate_agent_profile(value, ROOT), value)


if __name__ == "__main__":
    unittest.main()
