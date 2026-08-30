"""Tests for tools/check_truncated_lines.py — the roadmap row that stops mid-clause.

The case of record is reconstructed verbatim: the eleven Phase-1 Definition-of-Done rows that
have ended in the middle of a sentence since commit 8e446d4 (2026-08-10). If those do not trip
this gate, it is decoration.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_truncated_lines as gate  # noqa: E402

# Verbatim from docs/roadmap/phase-1.md as it stood on 2026-08-30.
CUT_ROUND_TRIP = ("- [ ] One governed round-trip proven end-to-end. **Still open, and an "
                  "independent auditor has now")
CUT_CONTRACTS = ("- [x] `task-request` + `bridge-result` contracts defined and tested — "
                 "**but only `task-request` is")
CUT_PROVIDER = ("- [x] Opt-in `Provider::GovernedEngine` in desktop `ai.rs` (default OFF) — "
                "**transport shipped** (PR #8,")


class TheCaseOfRecord(unittest.TestCase):
    def test_the_round_trip_row_is_truncated(self):
        self.assertTrue(gate.is_truncated(CUT_ROUND_TRIP))

    def test_a_row_cut_after_an_em_dash_clause_is_truncated(self):
        self.assertTrue(gate.is_truncated(CUT_CONTRACTS))

    def test_a_row_cut_after_a_comma_is_truncated(self):
        self.assertTrue(gate.is_truncated(CUT_PROVIDER))

    def test_the_repaired_form_of_the_same_row_passes(self):
        repaired = (CUT_ROUND_TRIP.replace("an independent auditor has now",
                                           "an independent auditor has now read it at source."))
        self.assertFalse(gate.is_truncated(repaired))


class CompleteRowsPass(unittest.TestCase):
    def test_a_full_stop_ends_a_row(self):
        self.assertFalse(gate.is_truncated("- [x] Bridge CI leg added and green."))

    def test_a_closed_parenthesis_is_a_finished_thought(self):
        # The first run's false positive: docs/roadmap/phase-10.md:20 ends
        # "(keyboard-complete, AA contrast, live regions, HY SR labels)".
        self.assertFalse(gate.is_truncated(
            "- [ ] Every page passes a production a11y audit (keyboard-complete, AA contrast)"))

    def test_trailing_emphasis_is_stripped_before_judging(self):
        self.assertFalse(gate.is_truncated("- [x] Done, and proven on a real Linux runner.**"))
        self.assertTrue(gate.is_truncated("- [x] Done 2026-08-12 — **DONE"))

    def test_an_armenian_full_stop_ends_a_row(self):
        self.assertFalse(gate.is_truncated("- [x] Կամուրջը վազում է։"))

    def test_a_colon_introducing_a_block_ends_a_row(self):
        self.assertFalse(gate.is_truncated("- [ ] The three refusals are:"))


class ScopeIsCheckboxRows(unittest.TestCase):
    def test_a_descriptive_bullet_is_prose_and_not_judged(self):
        # 22 of these are cut the same way; they are on the board, not in this gate.
        self.assertFalse(gate.is_truncated(
            "- **`approvals` ✔ (Approval gate).** Components: approval queue, decision pill"))

    def test_a_table_row_is_not_judged(self):
        self.assertFalse(gate.is_truncated("| 1 | Bridge | In-Progress |"))

    def test_a_heading_is_not_judged(self):
        self.assertFalse(gate.is_truncated("## Phase 1 — Bridge"))

    def test_an_empty_row_is_not_judged(self):
        self.assertFalse(gate.is_truncated("- [ ] "))


class ScanTests(unittest.TestCase):
    def test_scan_reports_path_line_and_text(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "docs" / "roadmap").mkdir(parents=True)
            (root / "docs" / "roadmap" / "phase-1.md").write_text(
                "## Phase 1\n- [x] Complete row.\n" + CUT_ROUND_TRIP + "\n", encoding="utf-8")
            found = gate.scan(root)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], "docs/roadmap/phase-1.md")
        self.assertEqual(found[0][1], 3)

    def test_a_clean_tree_reports_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "docs" / "roadmap").mkdir(parents=True)
            (root / "docs" / "roadmap" / "phase-2.md").write_text(
                "- [x] One complete row.\n- [ ] Another one.\n", encoding="utf-8")
            self.assertEqual(gate.scan(root), [])


if __name__ == "__main__":
    unittest.main()
