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


class StaleWindowTests(unittest.TestCase):
    """T-162. The runs endpoint answered `branch=main` from months ago, and this gate then
    reported a green `main` as "the newest is failure at 95c52c5" — once in CI, where it cost a
    re-run. Run ids only grow."""

    RECORDED = 36992048558
    OLD = [("95c52c5" + "0" * 33, "failure", 35542745168), ("87bfe73" + "0" * 33, "success", 35542000000)]
    NOW = [(HEAD, "success", RECORDED)]
    DECLARED = {"ci": {"head": HEAD, "conclusion": "success", "run_id": RECORDED, "note": ""}}

    def setUp(self):
        self.addCleanup(setattr, gate, "_live_main_ci", gate._live_main_ci)
        self.addCleanup(setattr, gate, "STALE_WINDOW_PAUSE", gate.STALE_WINDOW_PAUSE)
        gate.STALE_WINDOW_PAUSE = 0

    def answers(self, *windows):
        queue, calls = list(windows), []

        def take(slug):
            calls.append(slug)
            answer = queue.pop(0) if len(queue) > 1 else queue[0]
            return None if answer is None else {"ci": answer}
        gate._live_main_ci = take
        return calls

    def test_a_window_wholly_older_than_the_recorded_run_is_stale(self):
        """Mutant: compare with the NEWEST run only when it is the same head ⇒ not stale."""
        self.assertEqual(gate.window_predates_reading(self.DECLARED, {"ci": self.OLD}), ["ci"])

    def test_a_window_that_holds_the_recorded_run_or_a_newer_one_is_not(self):
        """Mutant: `>=` for `>` ⇒ the ordinary case, a reading of the newest run, is stale."""
        newer = [(NEWER, "failure", self.RECORDED + 9)] + self.NOW
        older_too = newer + [(OTHER, "success", self.RECORDED - 5)]     # the usual window
        for runs in (self.NOW, newer, older_too, [(NEWER, "success", self.RECORDED + 9)]):
            with self.subTest(runs=runs):
                self.assertEqual(gate.window_predates_reading(self.DECLARED, {"ci": runs}), [])

    def test_a_mirror_with_no_integer_run_id_is_never_called_stale(self):
        for declared in (None, {}, {"ci": None}, {"ci": {"head": HEAD}},
                         {"ci": {"run_id": str(self.RECORDED)}}, {"ci": {"run_id": True}},
                         {"other": {"run_id": self.RECORDED}}):
            with self.subTest(declared=declared):
                self.assertEqual(gate.window_predates_reading(declared, {"ci": self.OLD}), [])

    def test_a_stale_page_is_asked_for_again_and_the_real_one_is_used(self):
        """Mutant: return the first window ⇒ the stale one comes back."""
        calls = self.answers(self.OLD, self.NOW)
        live_window, stale = gate.live_main_ci_past_stale_pages("o/r", self.DECLARED)
        self.assertEqual((live_window, stale), ({"ci": self.NOW}, []))
        self.assertEqual(len(calls), 2)
        self.assertEqual(gate.main_ci_failures(self.DECLARED, live_window), [])

    def test_a_page_that_stays_stale_is_reported_as_stale_after_the_tries(self):
        """Mutant: give up after one try ⇒ one call. Mutant: return no stale list ⇒ the caller
        judges the mirror against a page from the past."""
        calls = self.answers(self.OLD)
        live_window, stale = gate.live_main_ci_past_stale_pages("o/r", self.DECLARED)
        self.assertEqual(stale, ["ci"])
        self.assertEqual(len(calls), gate.STALE_WINDOW_TRIES)

    def test_a_fresh_window_costs_one_call(self):
        calls = self.answers(self.NOW)
        self.assertEqual(gate.live_main_ci_past_stale_pages("o/r", self.DECLARED),
                         ({"ci": self.NOW}, []))
        self.assertEqual(len(calls), 1)

    def test_an_unreadable_main_is_still_unreadable(self):
        """Mutant: treat None as a window ⇒ AttributeError instead of the refusal."""
        self.answers(None)
        self.assertEqual(gate.live_main_ci_past_stale_pages("o/r", self.DECLARED), (None, []))

    def test_the_gate_takes_its_reading_through_this_and_says_stale_by_name(self):
        """Mutant: call `_live_main_ci` directly in `main()` ⇒ the first assertion. Mutant:
        fall through to `main_ci_failures` on a stale page ⇒ the second."""
        source = pathlib.Path(gate.__file__).read_text(encoding="utf-8")
        self.assertIn("live_main, stale = live_main_ci_past_stale_pages(slug_for_ci, "
                      'snap.get("main_ci"))', source)
        self.assertEqual(source.count("_live_main_ci(slug"), 2,
                         "the raw reader is called by the retrying one and defined once")
        block = source[source.index("        elif stale:"):source.index(
            '            failures += main_ci_failures(snap.get("main_ci"), live_main)')]
        self.assertIn("that is a stale page", block)
        self.assertIn("NOT judged against it", block)
        self.assertIn("A check that could not run", block)


if __name__ == "__main__":
    unittest.main()
