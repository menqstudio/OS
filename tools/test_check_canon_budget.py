"""Tests for the canon budget gate.

Each test names the mutation that turns it red, because a gate nobody has broken on
purpose is a gate nobody has tested. That discipline is this repository's own: *when
you add a check, delete it once and confirm its test goes red, then restore it* — four
of roughly ninety checks stayed green when that was done, meaning four tests were
testing nothing.

`unittest.main()` is the last statement in this file and `EntryPointRunsEverything`
keeps it there. The ninth audit's `I-05` found `unittest.main()` sitting four lines
above the class it should run, so the file's own entry point silently collected 74 of
88 tests and printed `OK`.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_canon_budget


def build(root: pathlib.Path, files: dict[str, str], budget: dict) -> None:
    """Write a miniature repository: the files, a manifest naming them, a budget."""
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "canonical-read-manifest.json").write_text(
        json.dumps({"paths": list(files)}), encoding="utf-8")
    (root / "config" / "canon-budget.json").write_text(json.dumps(budget), encoding="utf-8")


def line(n: int) -> str:
    """A substantive line — over MIN_SUBSTANTIVE, and distinct per n."""
    return f"this is substantive line number {n:06d} and it is long enough to count"


def body(count: int, offset: int = 0) -> str:
    return "\n".join(line(i + offset) for i in range(count)) + "\n"


class Budgets(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="canon-budget-"))

    def run_gate(self) -> int:
        return check_canon_budget.main(self.dir)

    def test_green_when_every_file_is_inside_its_ceiling(self):
        build(self.dir,
              {"A.md": body(10), "B.md": body(10, offset=1000)},
              {"per_file_bytes": {"A.md": 10_000, "B.md": 10_000},
               "total_bytes_max": 20_000, "max_shared_fraction": 0.2})
        self.assertEqual(self.run_gate(), 0)

    def test_a_file_over_its_ceiling_is_red(self):
        """Mutant: delete the per-file comparison ⇒ this goes green."""
        build(self.dir,
              {"A.md": body(400), "B.md": body(10, offset=1000)},
              {"per_file_bytes": {"A.md": 1_000, "B.md": 10_000},
               "total_bytes_max": 10_000_000, "max_shared_fraction": 0.2})
        self.assertEqual(self.run_gate(), 1)

    def test_the_set_can_be_over_budget_while_every_file_is_inside_its_own(self):
        """The total is not implied by the parts. This is the case that matters: the
        read manifest reached 1917 KB while each of its files read as merely long."""
        build(self.dir,
              {"A.md": body(100), "B.md": body(100, offset=1000)},
              {"per_file_bytes": {"A.md": 100_000, "B.md": 100_000},
               "total_bytes_max": 5_000, "max_shared_fraction": 0.2})
        self.assertEqual(self.run_gate(), 1)

    def test_two_files_carrying_one_document_are_red(self):
        """Mutant: delete the overlap loop ⇒ green, and NEXT_CHAT/PROJECT_STATE pass."""
        shared = body(100)
        build(self.dir,
              {"A.md": shared, "B.md": shared + line(9999) + "\n"},
              {"per_file_bytes": {"A.md": 100_000, "B.md": 100_000},
               "total_bytes_max": 10_000_000, "max_shared_fraction": 0.2})
        self.assertEqual(self.run_gate(), 1)

    def test_near_duplicates_under_the_ceiling_are_green(self):
        """A positive control: sharing some lines is normal. Only carrying the same
        DOCUMENT is the defect, so the gate must not fire on ordinary repetition."""
        common = body(10)
        build(self.dir,
              {"A.md": common + body(100, offset=2000),
               "B.md": common + body(100, offset=5000)},
              {"per_file_bytes": {"A.md": 100_000, "B.md": 100_000},
               "total_bytes_max": 10_000_000, "max_shared_fraction": 0.2})
        self.assertEqual(self.run_gate(), 0)

    def test_a_canonical_file_with_no_ceiling_is_red(self):
        """Otherwise the budget is opt-in, and the next canonical file opts out."""
        build(self.dir,
              {"A.md": body(10), "B.md": body(10, offset=1000)},
              {"per_file_bytes": {"A.md": 10_000},
               "total_bytes_max": 20_000, "max_shared_fraction": 0.2})
        self.assertEqual(self.run_gate(), 1)

    def test_a_ceiling_for_a_file_nobody_reads_is_red(self):
        """The reverse direction. An entry that outlives its file is how the next
        stale exemption hides — the same argument check_dead_tokens.py makes."""
        build(self.dir,
              {"A.md": body(10)},
              {"per_file_bytes": {"A.md": 10_000, "GONE.md": 10_000},
               "total_bytes_max": 20_000, "max_shared_fraction": 0.2})
        self.assertEqual(self.run_gate(), 1)

    def test_a_manifest_path_that_is_not_on_disk_is_red(self):
        build(self.dir, {"A.md": body(10)},
              {"per_file_bytes": {"A.md": 10_000, "B.md": 10_000},
               "total_bytes_max": 20_000, "max_shared_fraction": 0.2})
        manifest = self.dir / "config" / "canonical-read-manifest.json"
        manifest.write_text(json.dumps({"paths": ["A.md", "B.md"]}), encoding="utf-8")
        self.assertEqual(self.run_gate(), 1)

    def test_a_malformed_budget_is_red_rather_than_ignored(self):
        build(self.dir, {"A.md": body(10)},
              {"per_file_bytes": {"A.md": 10_000}, "total_bytes_max": "20000",
               "max_shared_fraction": 0.2})
        self.assertEqual(self.run_gate(), 1)

    def test_a_missing_budget_file_fails_closed(self):
        build(self.dir, {"A.md": body(10)},
              {"per_file_bytes": {"A.md": 10_000},
               "total_bytes_max": 20_000, "max_shared_fraction": 0.2})
        (self.dir / "config" / "canon-budget.json").unlink()
        with self.assertRaises(SystemExit) as caught:
            self.run_gate()
        self.assertEqual(caught.exception.code, 1)


class TheRealCanon(unittest.TestCase):
    """The gate is expected to be RED on this repository until the canon is cut down.
    Asserting that is not asserting a defect is fine: it pins the gate to a tree it is
    known to refuse, so a change that accidentally neuters it cannot pass unnoticed."""

    def test_the_budget_names_exactly_the_manifest(self):
        manifest = json.loads(
            (ROOT / "config" / "canonical-read-manifest.json").read_text(encoding="utf-8"))
        budget = json.loads(
            (ROOT / "config" / "canon-budget.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(budget["per_file_bytes"]), sorted(manifest["paths"]))

    def test_the_ceilings_do_not_sum_past_the_total(self):
        """Two constraints that can disagree are one constraint and one surprise."""
        budget = json.loads(
            (ROOT / "config" / "canon-budget.json").read_text(encoding="utf-8"))
        self.assertLessEqual(sum(budget["per_file_bytes"].values()),
                             budget["total_bytes_max"])


class EntryPointRunsEverything(unittest.TestCase):
    """`I-05`: `unittest.main()` four lines above the last class collected 74 of 88
    tests and printed OK. The entry point must follow every class."""

    def test_unittest_main_is_the_last_statement(self):
        source = pathlib.Path(__file__).read_text(encoding="utf-8").splitlines()
        classes = [i for i, ln in enumerate(source) if ln.startswith("class ")]
        guard = [i for i, ln in enumerate(source) if ln.startswith('if __name__')]
        self.assertEqual(len(guard), 1)
        self.assertGreater(guard[0], max(classes))


if __name__ == "__main__":
    unittest.main()
