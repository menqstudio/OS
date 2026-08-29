"""Tests for the recommendation gate.

These are not optional here. Run over this repository the gate reports *"sections with
options=0"* — no canonical document currently offers a choice — so a green run proves
nothing about whether it works. That is the exact shape of the defect this repository has
already been bitten by: of roughly ninety checks swept in an earlier wave, four came back
green because they were testing nothing.

So every case is a fixture, and every test names the mutation that turns it red.

`unittest.main()` is the last statement (ninth audit `I-05`).
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_recommendation


class Gate(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="rec-gate-"))
        (self.dir / "config").mkdir(parents=True, exist_ok=True)

    def doc(self, body: str) -> int:
        (self.dir / "DOC.md").write_text(body, encoding="utf-8")
        (self.dir / "config" / "canonical-read-manifest.json").write_text(
            json.dumps({"paths": ["DOC.md"]}), encoding="utf-8")
        return check_recommendation.main(self.dir)

    def test_two_sibling_options_with_no_recommendation_are_red(self):
        """Mutant: drop the RECOMMEND check ⇒ green.

        The body carries a REASON word ("because") on purpose. Without it this test passed
        with the recommendation check disabled — the no-reason branch was catching it, so
        the test was green for the wrong reason and proved nothing about the check it
        names. The mutation sweep is what said so."""
        self.assertEqual(self.doc(
            "# Root model\n\n"
            "- **A · Submodule** — good because the engine stays untouched.\n"
            "- **B · Make it monorepo-aware** — good because it is a real one repo.\n"), 1)

    def test_a_recommendation_without_a_reason_is_red(self):
        """A preference is not a recommendation. Mutant: drop the REASON check ⇒ green."""
        self.assertEqual(self.doc(
            "# Root model\n\n"
            "- **A · Submodule** — the engine stays untouched.\n"
            "- **B · Monorepo-aware** — a real one-repo feel.\n\n"
            "Recommended: B.\n"), 1)

    def test_a_recommendation_with_a_reason_is_green(self):
        """The positive control. Without it, a gate that always says RED would pass every
        other test in this file."""
        self.assertEqual(self.doc(
            "# Root model\n\n"
            "- **A · Submodule** — the engine stays untouched.\n"
            "- **B · Monorepo-aware** — a real one-repo feel.\n\n"
            "Recommended: A, because it is the only one that leaves the audited security "
            "code untouched.\n"), 0)

    def test_the_phrase_alone_triggers_it(self):
        """'Two options:' with prose underneath and no list is still a choice handed over."""
        self.assertEqual(self.doc(
            "# Choice\n\nTwo options here. Either we split the file or we raise the ceiling.\n"), 1)

    def test_armenian_phrasing_triggers_it(self):
        self.assertEqual(self.doc("# Ընտրություն\n\nԵրկու տարբերակ կա այստեղ։\n"), 1)

    def test_armenian_recommendation_with_a_reason_is_green(self):
        self.assertEqual(self.doc(
            "# Ընտրություն\n\nԵրկու տարբերակ կա։\n\n"
            "Իմ առաջարկն առաջինն է, որովհետև այն չի դիպչում աուդիտ անցած կոդին։\n"), 0)

    def test_a_glossary_entry_naming_several_options_is_not_a_choice(self):
        """The gate's own first run flagged exactly this line in the roadmap's glossary.
        One list item defining what 'Option 1 / Option 2' MEAN is a definition; two sibling
        items are a decision. Mutant: require only ONE option item ⇒ red."""
        self.assertEqual(self.doc(
            "# K. Glossary\n\n"
            "- **Option 1 / Option 2 / T-005** — subtree+skip-guard (now) vs submodule.\n"
            "- **Wall** — the enforcement hook chain.\n"), 0)

    def test_one_lone_option_item_is_not_a_choice(self):
        """Exactly ONE matching item, which is a heading-style bullet rather than a set of
        alternatives. Mutant: accept a single option item ⇒ red.

        The glossary fixture above does not cover this: its line is
        `- **Option 1 / Option 2 / T-005** —`, and the separator after the digit is `/`, so
        the pattern finds ZERO items there and the test passed without exercising the rule
        at all. The mutation sweep is what showed that."""
        self.assertEqual(self.doc(
            "# Note\n\n- **A · the only bullet of this shape in the section** — some text.\n"
            "- plain follow-up bullet with no bold marker at all.\n"), 0)

    def test_a_list_of_steps_is_not_a_set_of_alternatives(self):
        """A gate that fires on every bulleted list is a gate that gets switched off."""
        self.assertEqual(self.doc(
            "# How to run\n\n- Install the deps.\n- Run the suite.\n- Read the output.\n"), 0)

    def test_options_inside_a_code_fence_are_not_prose(self):
        self.assertEqual(self.doc(
            "# Usage\n\n```\nOptions:\n  --root DIR\n  --session ID\n```\n"), 0)

    def test_each_section_is_judged_on_its_own(self):
        """A recommendation in section two must not excuse a choice in section one, or a
        long document only ever needs one recommendation anywhere in it."""
        self.assertEqual(self.doc(
            "# One\n\n- **A · this** — x\n- **B · that** — y\n\n"
            "# Two\n\n- **A · other** — p\n- **B · another** — q\n\n"
            "Recommended: A, because it is simpler.\n"), 1)


if __name__ == "__main__":
    unittest.main()
