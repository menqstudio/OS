#!/usr/bin/env python3
"""Tests for check_no_assumptions.py.

Run: python -m unittest test_check_no_assumptions   (from tools/)

The gate ran in CI with no test at all, so nothing had ever shown that any one of its rules
could go red -- or that its exemptions exempted what they were written for. Two of them did
not: the `reproduc` and `mutat` evidence stems were dead behind a trailing word boundary.

Every case here is a line of text. The gate reads the canonical documents, which other
sessions own and rewrite; a test that asserted on THEIR content would be a test of the day's
prose, so the real read set is not consulted here -- CI runs the gate itself over that.
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import check_no_assumptions as gate  # noqa: E402


def flagged(text: str) -> list[int]:
    return [n for n, _ in gate.offending_lines(text)]


class AHedgeIsFlagged(unittest.TestCase):
    """One sentence per alternative in `HEDGES`. Deleting any one alternative turns exactly
    its sentence green, which is what makes the list a list of rules rather than of words."""

    HEDGED = [
        "I think the broker binds before it reads the roster.",
        "I believe the lease is consumed there.",
        "This rests on the assumption that the store is local.",
        "The caller is presumably the desktop app.",
        "It is probably the cache.",
        "The failure is likely a timeout.",
        "My guess is the pin moved.",
        "We guessed the ceiling.",
        "The author was just guessing at the size.",
        "The gate seems to be wired.",
        "The signer appears to have started.",
        "That should be fine on Windows.",
        "The presumed owner is the installer.",
        "Սա ենթադրում է, որ ֆայլը կա։",
        "Հավանաբար սխալը cache-ում է։",
    ]

    def test_every_hedge_form_is_flagged(self):
        for line in self.HEDGED:
            with self.subTest(line=line):
                self.assertEqual(flagged(line), [1])

    def test_the_line_number_and_the_text_are_reported(self):
        text = "A fact.\n\n  It is probably the cache.  \nAnother fact."
        self.assertEqual(gate.offending_lines(text), [(3, "It is probably the cache.")])

    def test_normative_should_and_shall_are_not_hedges(self):
        """A specification says what a system should do. That is not a guess, and a rule
        that cannot tell the two apart is a rule people switch off."""
        for line in ("The broker should refuse an unsigned manifest.",
                     "A lease shall expire after one use.",
                     "Treat every head on this page as a date-stamped guess."):
            with self.subTest(line=line):
                self.assertEqual(flagged(line), [])


class TheThreeWaysOut(unittest.TestCase):
    BARE = "It is probably the cache."

    def test_the_bare_sentence_is_flagged(self):
        """The control. Without it every exemption below proves nothing."""
        self.assertEqual(flagged(self.BARE), [1])

    def test_a_marked_line_is_not_flagged(self):
        for line in (self.BARE + " <!-- UNVERIFIED: run the suite with the cache off -->",
                     "UNVERIFIED: " + self.BARE,
                     "> UNVERIFIED: " + self.BARE,
                     self.BARE + " <!--unverified: lowercase is the same mark -->"):
            with self.subTest(line=line):
                self.assertEqual(flagged(line), [])

    def test_a_line_that_names_its_evidence_is_not_flagged(self):
        for evidence in ("measured at 24 ms", "ran it twice", "it printed GREEN", "verified",
                         "checked", "observed on the box", "git show 962743a", "git log -1",
                         "rev-parse HEAD", "cat-file -s", "see check_x.py:118", "88 tests",
                         "2437 OK", "1288 passed", "8446 bytes", "4034 lines"):
            with self.subTest(evidence=evidence):
                self.assertEqual(flagged(f"{self.BARE} ({evidence})"), [])

    def test_the_real_words_reproduced_and_mutation_are_evidence(self):
        """The defect: `reproduc` and `mutat` sat bare inside a trailing `\\b`, so the only
        strings they matched were those two non-words. A sentence that said how the claim
        was established was reported as an unmarked guess."""
        for line in ("I assume it was reproduced on the box.",
                     "Probably fixed; the mutation sweep is done.",
                     "Likely the same defect: reproduction steps are in the row above.",
                     "Presumably right -- reproducing it took one command."):
            with self.subTest(line=line):
                self.assertEqual(flagged(line), [])

    def test_a_sentence_ABOUT_assuming_is_not_an_assumption(self):
        for line in ("The chain node is earned, never assumed.",
                     "Probed rather than assumed.",
                     "This is not a REUSE assumption.",
                     "Measured on four accounts instead of presumed."):
            with self.subTest(line=line):
                self.assertEqual(flagged(line), [])

    def test_a_negation_far_from_the_hedge_does_not_excuse_it(self):
        """The window is 60 characters and stops at a sentence boundary."""
        self.assertEqual(flagged("Nothing was run. It is probably the cache."), [1])
        self.assertEqual(flagged("not " + "x" * 70 + " probably the cache"), [1])

    def test_a_code_fence_is_not_prose(self):
        text = "```\nprobably = guess()\n```\nIt is probably the cache.\n```sh\nlikely\n```"
        self.assertEqual(flagged(text), [4])


class TheVerdict(unittest.TestCase):
    """`main()`'s return value is what CI reads."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        (self.root / "config").mkdir()

    def manifest(self, *paths: str) -> None:
        (self.root / gate.MANIFEST_REL).write_text(json.dumps({"paths": list(paths)}),
                                                   encoding="utf-8")

    def run_gate(self) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gate.main(self.root)
        return code, out.getvalue()

    def test_a_clean_read_set_is_green_and_counts_what_it_scanned(self):
        self.manifest("A.md", "B.md")
        (self.root / "A.md").write_text("Measured, and it printed 12.\n", encoding="utf-8")
        (self.root / "B.md").write_text("A fact.\n", encoding="utf-8")
        code, out = self.run_gate()
        self.assertEqual(code, 0, out)
        self.assertIn("files=2", out)

    def test_an_unmarked_guess_in_the_read_set_is_red_and_named(self):
        self.manifest("A.md")
        (self.root / "A.md").write_text("A fact.\nIt is probably the cache.\n", encoding="utf-8")
        code, out = self.run_gate()
        self.assertEqual(code, 1)
        self.assertIn("A.md:2  It is probably the cache.", out)

    def test_a_document_outside_the_manifest_is_not_judged(self):
        self.manifest("A.md")
        (self.root / "A.md").write_text("A fact.\n", encoding="utf-8")
        (self.root / "ARCHIVE.md").write_text("It is probably the cache.\n", encoding="utf-8")
        code, out = self.run_gate()
        self.assertEqual(code, 0, out)

    def test_a_missing_or_broken_manifest_is_red_never_a_silent_pass(self):
        for label, write in (
            ("missing", lambda: None),
            ("invalid", lambda: (self.root / gate.MANIFEST_REL).write_text("{", encoding="utf-8")),
            ("no paths", lambda: (self.root / gate.MANIFEST_REL).write_text("{}", encoding="utf-8")),
        ):
            write()
            with self.subTest(manifest=label):
                code, out = self.run_gate()
                self.assertEqual(code, 1)
                self.assertIn("cannot read", out)


if __name__ == "__main__":
    unittest.main()
