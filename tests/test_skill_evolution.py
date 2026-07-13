import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_learning import validate_learning_registry


class SkillEvolutionTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
