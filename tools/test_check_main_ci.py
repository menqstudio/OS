#!/usr/bin/env python3
"""The main-CI reading rule, tested on its pure half.

Why this file exists, in one paragraph. On 2026-08-30 `main`'s own `ci` was RED for four
consecutive merges while every pull request was green. The rule that would have caught it
-- *"a green PR is not a green main; `gh pr checks` is not `gh run list --branch main`"* --
is written in `NEXT_CHAT.md`'s second paragraph and had already cost two false "green"
reports once before. It was enforced by nobody, so it held exactly as long as attention
did. Every other mistake that night was caught by an artifact.

The rule these tests cover does NOT require `main` to be green. That would block work on a
red main, and a red main is a fact somebody has to be able to work through. It requires the
snapshot to have READ it: same head, same conclusion, and a non-empty note whenever the
conclusion is not `success`. A red main passes the moment somebody writes down that it is
red; an unread main never passes.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_repo_state as gate  # noqa: E402

HEAD = "9c0888b7ead52f69e1a8005bca5898b0ea3de649"
OTHER = "d745c50360a6902f7c23e75f0ecae6c67512eac8"


def live(conclusion: str = "success", head: str = HEAD) -> dict:
    return {"ci": (head, conclusion, 33303739152)}


class MainCiReadingTests(unittest.TestCase):
    def test_a_matching_green_reading_passes(self):
        declared = {"ci": {"head": HEAD, "conclusion": "success"}}
        self.assertEqual(gate.main_ci_failures(declared, live()), [])

    def test_a_red_main_passes_when_it_is_written_down(self):
        """A red main is a fact, not a blocker. This is the arm that keeps the
        rule satisfiable: it demands a reading, never a repair."""
        declared = {"ci": {"head": HEAD, "conclusion": "failure",
                           "note": "check_doc_claims: the handoff named a branch commit"}}
        self.assertEqual(gate.main_ci_failures(declared, live("failure")), [])

    def test_a_red_main_with_no_note_is_red(self):
        declared = {"ci": {"head": HEAD, "conclusion": "failure", "note": "   "}}
        problems = gate.main_ci_failures(declared, live("failure"))
        self.assertTrue(any("with no `note`" in p for p in problems), problems)

    def test_no_block_at_all_is_red(self):
        problems = gate.main_ci_failures(None, live())
        self.assertTrue(any("no `main_ci` block" in p for p in problems), problems)

    def test_a_workflow_the_block_does_not_mention_is_red(self):
        problems = gate.main_ci_failures({}, live())
        self.assertTrue(any("does not mention the `ci` workflow" in p for p in problems), problems)

    def test_a_stale_head_is_red(self):
        """The exact failure of 2026-08-30: a reading that was true four merges ago."""
        declared = {"ci": {"head": OTHER, "conclusion": "success"}}
        problems = gate.main_ci_failures(declared, live())
        self.assertTrue(any("the reading is stale" in p for p in problems), problems)

    def test_a_conclusion_that_disagrees_with_github_is_red(self):
        """Writing 'success' over a failure is the false report this gate exists for."""
        declared = {"ci": {"head": HEAD, "conclusion": "success"}}
        problems = gate.main_ci_failures(declared, live("failure"))
        self.assertTrue(any("GitHub says 'failure'" in p for p in problems), problems)

    def test_the_real_snapshot_carries_a_reading(self):
        """The repository's own snapshot, so the block cannot quietly disappear."""
        import json
        root = pathlib.Path(__file__).resolve().parents[1]
        snap = json.loads((root / "config" / "current_state.json").read_text(encoding="utf-8"))
        block = snap.get("main_ci")
        self.assertIsInstance(block, dict, "config/current_state.json must carry `main_ci`")
        for wf in gate.MAIN_CI_WORKFLOWS:
            entry = block.get(wf)
            self.assertIsInstance(entry, dict, f"`main_ci` must mention `{wf}`")
            self.assertRegex(str(entry.get("head")), r"^[0-9a-f]{40}$")
            self.assertIn("conclusion", entry)
            if entry.get("conclusion") != "success":
                self.assertTrue(str(entry.get("note") or "").strip(),
                                "a non-success reading must carry a note")


if __name__ == "__main__":
    unittest.main()
