import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_identity import all_agent_identities
from bro_learning import validate_learning_registry
from bro_skill_evolution import SkillEvolutionError, validate_skill_evolution


class SkillEvolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agents = sorted(all_agent_identities(ROOT))
        cls.skill = json.loads(
            (ROOT / "skills" / "index.json").read_text(encoding="utf-8"))["skills"][0]

    def proposal(self, **overrides):
        """A promotion every rule accepts: two DIFFERENT real agents, a real skill, three
        well-formed digests, a green review and the Owner's approval."""
        value = {
            "skill_id": self.skill,
            "proposed_by_agent_id": self.agents[0],
            "independent_review": {"verifier_agent_id": self.agents[1], "verdict": "green"},
            "owner_approval": {"approved": True, "approved_by": "Gev"},
            "candidate": {"sha256": "a" * 64, "baseline_sha256": "b" * 64},
            "rollback": {"previous_sha256": "b" * 64},
            "promotion_status": "promoted",
        }
        value.update(overrides)
        return value

    def refused(self, message, **overrides):
        with self.assertRaises(SkillEvolutionError) as caught:
            validate_skill_evolution(self.proposal(**overrides), ROOT)
        self.assertEqual(str(caught.exception), message)

    def test_learning_pipeline_is_locked(self):
        value = validate_learning_registry(ROOT)
        self.assertEqual(value["pipeline"][0], "observe")
        self.assertEqual(value["pipeline"][-1], "rollback")

    def test_promotion_is_not_self_approved(self):
        policy = json.loads((ROOT / "skills" / "evolution-policy.json").read_text(encoding="utf-8"))
        self.assertTrue(policy["independent_review_required"])
        self.assertTrue(policy["self_verification_forbidden"])
        self.assertTrue(policy["rollback_required"])
        self.assertIn("promote-canonical-skill", policy["owner_approval_required"])
        # The policy file SAYS self-verification is forbidden; the validator is what refuses
        # it. This case is the one `laws/registry.json` cites as L13's deny test, and until
        # 2026-10-01 it read the policy JSON and never called L13's `primary` validator.
        proposer = self.proposal()["proposed_by_agent_id"]
        self.refused("proposer cannot self-verify",
                     independent_review={"verifier_agent_id": proposer, "verdict": "green"})


class SkillEvolutionValidatorTests(SkillEvolutionTests):
    """`bro_skill_evolution.validate_skill_evolution`, called.

    `laws/registry.json` names it L13's `primary` validator, `fail-closed` / `MUST`. Before
    this class no test imported the module at all. NOT CLAIMED HERE: that anything in the
    runtime calls it. Nothing does -- there is no skill-promotion flow in this tree -- so
    these tests show what the validator would refuse, not that a promotion is gated by it.
    """

    def test_a_reviewed_owner_approved_promotion_is_accepted(self):
        value = self.proposal()
        self.assertIs(validate_skill_evolution(value, ROOT), value)

    def test_a_proposal_that_is_only_proposed_needs_no_approval_yet(self):
        validate_skill_evolution(self.proposal(
            promotion_status="proposed", owner_approval={},
            independent_review={"verifier_agent_id": self.agents[1], "verdict": "pending"}), ROOT)

    def test_identity_is_checked_against_the_real_rosters(self):
        self.refused("unknown skill_id", skill_id="no-such-skill")
        self.refused("unknown proposer agent", proposed_by_agent_id="agt-nobody")
        self.refused("unknown verifier agent",
                     independent_review={"verifier_agent_id": "agt-nobody", "verdict": "green"})

    def test_every_digest_binding_must_be_a_sha256(self):
        good = self.proposal()
        for section, field in (("candidate", "sha256"), ("candidate", "baseline_sha256"),
                               ("rollback", "previous_sha256")):
            for bad in (None, "A" * 64, "a" * 63, "a" * 64 + "\n"):
                with self.subTest(field=field, bad=bad):
                    self.refused("invalid SHA-256 binding",
                                 **{section: dict(good[section], **{field: bad})})

    def test_promotion_requires_a_green_review_and_the_owner(self):
        for status in ("approved", "promoted"):
            with self.subTest(status=status):
                self.refused("promotion requires GREEN independent review",
                             promotion_status=status,
                             independent_review={"verifier_agent_id": self.agents[1],
                                                 "verdict": "red"})
                self.refused("promotion requires Gev approval", promotion_status=status,
                             owner_approval={"approved": True, "approved_by": "someone-else"})
                self.refused("promotion requires Gev approval", promotion_status=status,
                             owner_approval={"approved": "yes", "approved_by": "Gev"})
                self.refused("promotion requires Gev approval", promotion_status=status,
                             owner_approval={})

    def test_a_promoted_candidate_must_differ_from_its_baseline(self):
        self.refused("promoted candidate must differ from baseline",
                     candidate={"sha256": "b" * 64, "baseline_sha256": "b" * 64})


if __name__ == "__main__":
    unittest.main()
