import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_identity import (
    IdentityError,
    all_agent_identities,
    expected_agent_id,
    validate_agent_profile_identity,
    validate_identity_registry,
)


class AgentIdentityTests(unittest.TestCase):
    def test_registry_is_locked_and_complete(self):
        registry = validate_identity_registry(ROOT)
        self.assertEqual(registry["bro_id"], "bro-000")
        self.assertEqual(registry["pack_count"], 52)
        self.assertEqual(registry["agent_count"], 311)
        self.assertEqual(len(all_agent_identities(ROOT)), 311)

    def test_known_historical_ids_are_stable(self):
        self.assertEqual(expected_agent_id("ai-agent-builders", "Agent Architect", ROOT), "agt-p01-r01")
        self.assertEqual(expected_agent_id("git-release-control", "Push Executor", ROOT), "agt-p22-r03")
        self.assertEqual(expected_agent_id("red-team-offensive-security", "Safety Verifier", ROOT), "agt-p48-r05")

    def test_new_pack_and_flow_ids_are_deterministic(self):
        self.assertEqual(expected_agent_id("agent-intelligence-health", "Agent Intelligence Lead", ROOT), "agt-p49-r01")
        self.assertEqual(expected_agent_id("control-room-portfolio-status", "Control Room Verifier", ROOT), "agt-p52-r05")
        self.assertEqual(expected_agent_id("control-room-portfolio-status", "Automation & Flow Engineer", ROOT), "agt-p52-r06")

    def test_every_pack_has_exactly_one_flow_agent(self):
        identities = all_agent_identities(ROOT)
        flow_agents = [value for value in identities.values() if value[1] == "Automation & Flow Engineer"]
        self.assertEqual(len(flow_agents), 52)
        self.assertEqual(len({pack_id for pack_id, _ in flow_agents}), 52)

    def test_profile_must_use_exact_registered_id(self):
        profile = {"agent_id": "agt-p22-r03", "pack_id": "git-release-control", "role": "Push Executor"}
        self.assertEqual(validate_agent_profile_identity(profile, ROOT), "agt-p22-r03")
        profile["agent_id"] = "agt-p22-r02"
        with self.assertRaises(IdentityError):
            validate_agent_profile_identity(profile, ROOT)

    def test_bro_id_is_not_a_specialist_id(self):
        with self.assertRaises(IdentityError):
            validate_agent_profile_identity({"agent_id": "bro-000", "pack_id": "ai-agent-builders", "role": "Agent Architect"}, ROOT)


if __name__ == "__main__":
    unittest.main()
