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
snapshot to have READ it: a real run, its real conclusion, and a non-empty note whenever that
conclusion is not `success`. A red main passes the moment somebody writes down that it is
red; an unread main never passes.

**T-059 changed one thing and these tests draw the new line.** The reading no longer has to be
of the NEWEST run. It could not be: recording a reading takes a merge, and the merge moves
`main`, so the snapshot passed inside the run that merged it and was stale on the next read —
the row's words were "stale by construction". An older reading is accepted now, but only while
every run since concluded `success`. The arm that matters most is
`test_an_older_reading_that_steps_over_a_red_main_is_red`: without it the change would be a
loosening rather than a fix, because the 2026-08-30 miss — four unread red merges — would sail
through.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_repo_state as gate  # noqa: E402

HEAD = "9c0888b7ead52f69e1a8005bca5898b0ea3de649"
OTHER = "d745c50360a6902f7c23e75f0ecae6c67512eac8"


#: Two more heads, so a window can be built with a reading behind the newest run.
NEWER = "3f2b1a0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a"
NEWEST = "aa11bb22cc33dd44ee55ff6677889900aabbccdd"


def live(conclusion: str = "success", head: str = HEAD) -> dict:
    """A window of ONE run — the shape most arms need, and the newest-run case."""
    return {"ci": [(head, conclusion, 33303739152)]}


def window(*runs: tuple) -> dict:
    """`window(newest, ..., oldest)` — each entry `(head, conclusion)`."""
    return {"ci": [(head, conclusion, 33303739152 + i)
                   for i, (head, conclusion) in enumerate(runs)]}


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

    def test_a_head_that_is_not_in_the_window_at_all_is_red(self):
        """Not "stale" — UNREAD. At this distance nobody has looked at main in twenty merges."""
        declared = {"ci": {"head": OTHER, "conclusion": "success"}}
        problems = gate.main_ci_failures(declared, live())
        self.assertTrue(any("not among the last" in p for p in problems), problems)

    def test_an_older_reading_passes_while_everything_since_is_green(self):
        """T-059's whole point. This arm is why the gate stopped demanding the impossible: the
        reading is two merges behind and both of them were green, so nothing has gone unread."""
        declared = {"ci": {"head": HEAD, "conclusion": "success"}}
        live_window = window((NEWEST, "success"), (NEWER, "success"), (HEAD, "success"))
        self.assertEqual(gate.main_ci_failures(declared, live_window), [])

    def test_an_older_reading_that_steps_over_a_red_main_is_red(self):
        """The 2026-08-30 miss, in the shape the new rule must still catch: the reading is true
        about the run it names, and main went red AFTER it. Delete the newer-runs loop and this
        is the test that goes red — checked by doing exactly that."""
        declared = {"ci": {"head": HEAD, "conclusion": "success"}}
        live_window = window((NEWEST, "success"), (NEWER, "failure"), (HEAD, "success"))
        problems = gate.main_ci_failures(declared, live_window)
        self.assertTrue(any("is not success" in p for p in problems), problems)
        self.assertTrue(any(NEWER[:7] in p for p in problems),
                        "the refusal must name WHICH later run went red")

    def test_a_reading_of_the_newest_run_still_passes(self):
        declared = {"ci": {"head": NEWEST, "conclusion": "success"}}
        live_window = window((NEWEST, "success"), (NEWER, "failure"), (HEAD, "success"))
        self.assertEqual(gate.main_ci_failures(declared, live_window), [],
                         "a red run BEFORE the reading is history, not an unread main")

    def test_an_empty_window_is_red_rather_than_silently_fine(self):
        problems = gate.main_ci_failures({"ci": {"head": HEAD, "conclusion": "success"}},
                                         {"ci": []})
        self.assertTrue(any("no completed `ci` run" in p for p in problems), problems)

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
