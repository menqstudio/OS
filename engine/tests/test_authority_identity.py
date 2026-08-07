import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_authority import (
    AuthorityError,
    enforce_risk_ceiling,
    resolve_agent_authority,
    resolve_role_authority,
    validate_authority_policy,
    validate_verifier_assignment,
)
from bro_identity import all_agent_identities, expected_agent_id


class AuthorityIdentityTests(unittest.TestCase):
    def test_authority_resolves_for_all_canonical_agents(self):
        self.assertEqual(validate_authority_policy(ROOT), 311)

    def test_fake_builder_id_is_denied(self):
        with self.assertRaises(AuthorityError):
            resolve_agent_authority("agt-p99-r99", "ai-agent-builders", "Agent Architect", ROOT)

    def test_canonical_id_with_wrong_role_is_denied(self):
        agent_id = expected_agent_id("ai-agent-builders", "Agent Architect", ROOT)
        with self.assertRaises(AuthorityError):
            resolve_agent_authority(agent_id, "ai-agent-builders", "Agent Builder", ROOT)

    def test_fake_verifier_id_is_denied(self):
        builder = expected_agent_id("ai-agent-builders", "Agent Architect", ROOT)
        with self.assertRaises(AuthorityError):
            validate_verifier_assignment(builder_agent_id=builder, verifier_agent_id="fake-verifier-001", verifier_role="Independent Verifier", risk="high", root=ROOT)

    def test_non_verifier_role_cannot_verify(self):
        builder = expected_agent_id("ai-agent-builders", "Agent Architect", ROOT)
        candidate = expected_agent_id("ai-agent-builders", "Agent Builder", ROOT)
        with self.assertRaises(AuthorityError):
            validate_verifier_assignment(builder_agent_id=builder, verifier_agent_id=candidate, verifier_role="Agent Builder", risk="medium", root=ROOT)

    def test_verifier_role_must_match_canonical_identity(self):
        builder = expected_agent_id("ai-agent-builders", "Agent Architect", ROOT)
        verifier = expected_agent_id("ai-agent-builders", "Independent Verifier", ROOT)
        with self.assertRaises(AuthorityError):
            validate_verifier_assignment(builder_agent_id=builder, verifier_agent_id=verifier, verifier_role="Safety Verifier", risk="critical", root=ROOT)

    def test_canonical_independent_verifier_is_authorized(self):
        builder = expected_agent_id("ai-agent-builders", "Agent Architect", ROOT)
        verifier = expected_agent_id("ai-agent-builders", "Independent Verifier", ROOT)
        authority = validate_verifier_assignment(builder_agent_id=builder, verifier_agent_id=verifier, verifier_role="Independent Verifier", risk="critical", root=ROOT)
        self.assertTrue(authority.can_verify)
        self.assertFalse(authority.can_build)
        self.assertEqual(authority.risk_ceiling, "critical")

    def test_builder_and_verifier_must_differ(self):
        identities = all_agent_identities(ROOT)
        verifier = next(agent_id for agent_id, (_pack, role) in identities.items() if role == "Independent Verifier")
        with self.assertRaises(AuthorityError):
            validate_verifier_assignment(builder_agent_id=verifier, verifier_agent_id=verifier, verifier_role="Independent Verifier", risk="medium", root=ROOT)

    def test_non_designated_tester_and_reviewer_roles_cannot_verify(self):
        builder = expected_agent_id("ai-agent-builders", "Agent Architect", ROOT)
        for pack_id, role in (("testing-quality", "Mutation Tester"), ("integration-api", "Contract Tester"), ("accounting-tax", "Controls Reviewer")):
            candidate = expected_agent_id(pack_id, role, ROOT)
            authority = resolve_agent_authority(candidate, pack_id, role, ROOT)
            self.assertFalse(authority.can_verify, msg=f"{pack_id}/{role}")
            with self.assertRaises(AuthorityError, msg=f"{pack_id}/{role}"):
                validate_verifier_assignment(builder_agent_id=builder, verifier_agent_id=candidate, verifier_role=role, risk="medium", root=ROOT)

    def test_final_declared_pack_verifier_is_authorized(self):
        builder = expected_agent_id("ai-agent-builders", "Agent Architect", ROOT)
        verifier = expected_agent_id("testing-quality", "Quality Verifier", ROOT)
        authority = validate_verifier_assignment(builder_agent_id=builder, verifier_agent_id=verifier, verifier_role="Quality Verifier", risk="critical", root=ROOT)
        self.assertTrue(authority.can_verify)
        self.assertFalse(authority.can_build)


class RiskCeilingTests(unittest.TestCase):
    """authority-policy.json caps every role at a risk_ceiling. Until it is
    compared against a task's risk it is data, not a ceiling."""

    def test_default_builder_is_capped_at_high(self):
        authority = resolve_role_authority("ai-agent-builders", "Agent Architect", ROOT)
        self.assertEqual(authority.risk_ceiling, "high")
        for risk in ("low", "medium", "high"):
            self.assertEqual(
                enforce_risk_ceiling("ai-agent-builders", "Agent Architect", risk, ROOT),
                "high")
        with self.assertRaises(AuthorityError) as caught:
            enforce_risk_ceiling("ai-agent-builders", "Agent Architect", "critical", ROOT)
        self.assertIn("risk ceiling", str(caught.exception))

    def test_designated_verifier_reaches_critical(self):
        self.assertEqual(
            enforce_risk_ceiling("ai-agent-builders", "Independent Verifier", "critical", ROOT),
            "critical")

    def test_the_mandatory_flow_role_resolves_authority(self):
        # These 52 identities are derived, not declared, so a consumer that reads
        # the pack registry directly does not know they exist.
        authority = resolve_role_authority(
            "control-room-portfolio-status", "Automation & Flow Engineer", ROOT)
        self.assertEqual(authority.agent_id, "agt-p52-r06")
        self.assertTrue(authority.can_build)
        self.assertFalse(authority.can_verify)

    def test_ceiling_check_refuses_an_unregistered_role(self):
        with self.assertRaises(AuthorityError):
            enforce_risk_ceiling("ai-agent-builders", "Chief Of Everything", "low", ROOT)


if __name__ == "__main__":
    unittest.main()
