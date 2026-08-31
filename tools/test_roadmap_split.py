"""The split must be lossless, and that has to be proven rather than believed.

`MASTER_EXECUTION_ROADMAP.md` was one 134 KB file. Its eleven phase bodies now live in
`docs/roadmap/phase-N.md` and `tools/roadmap_source.roadmap_text()` reassembles them.

A split that dropped a Definition-of-Done box, reordered phase 10 before phase 2, or lost
one of the sixteen required sections would pass every other gate and be invisible for
weeks — `check_coordination` counts sections and `check_roadmap_order` counts checkboxes,
and both would simply count the smaller number and agree with themselves.

So this compares the assembled text against the document as it stood in git before the
split, and against the structure the other gates depend on. It is written to keep working
after the pre-split commit has scrolled out of easy reach: the baseline is found by walking
back to the last commit whose `MASTER_EXECUTION_ROADMAP.md` still contained the phases, and
if there is no such commit the byte-comparison skips with a reason while every structural
assertion still runs.

Each test names the mutation that turns it red. `unittest.main()` is the last statement
(ninth audit `I-05`).
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import roadmap_source

REQUIRED_SECTIONS = (
    "Objective", "Scope", "Architecture", "UI/UX work", "Backend work",
    "Contracts / schemas", "Data models", "Dependencies", "Security gates",
    "Tests", "CI requirements", "Documentation updates", "Acceptance criteria",
    "Merge gate", "Stop conditions", "Definition of Done",
)
PHASE_HEAD = re.compile(r"(?m)^## Phase (\d+) —")


def git(*args: str) -> tuple[int, str]:
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    return r.returncode, r.stdout


#: The document as it stood immediately before the split, frozen in the tree.
#:
#: This was found by walking back 40 commits of `MASTER_EXECUTION_ROADMAP.md` and taking the last
#: one that still carried the phases. That worked on the branch and stopped working the moment the
#: branch was SQUASH-merged: the squash folded "correct the roadmap's facts" and "split it" into
#: one commit, so the newest pre-split version reachable became a document that differs for a
#: second, unrelated reason, and the test failed claiming the split was lossy when it was not.
#:
#: A proof that holds only while one particular commit is reachable is not a proof. The baseline
#: is a file now. `test_the_frozen_baseline_is_the_real_pre_split_commit` still ties it to
#: `5512d82^` while that commit is reachable, so the fixture cannot quietly become whatever makes
#: the comparison pass.
FIXTURE_REL = "tools/fixtures/roadmap-pre-split.md"
#: The commit that performed the split. Its parent carries the pre-split document.
SPLIT_COMMIT = "5512d82"

#: Zero-based line indices where the assembly is ALLOWED to differ from the baseline: the sixteen
#: Definition-of-Done rows `T-049` finished. Every one of them was left ending mid-clause by
#: `56e1cd7` ("Make the roadmap fit"), which got the document under its byte ceiling by deleting
#: the second half of each row -- the budget gate can only be satisfied by removing text, and the
#: cheapest text to remove was the end of every sentence. `tools/check_truncated_lines.py` is the
#: counterweight, and this set is the record of what it made necessary.
REPAIRED_LINES = {
    603, 604, 605, 606, 607, 608, 609, 612, 613, 614, 615, 617,  # phase 1
    1457, 1459, 1466, 1468,  # phase 10
}


def pre_split_roadmap() -> str | None:
    """The frozen pre-split document, or None if the fixture is missing."""
    path = ROOT / FIXTURE_REL
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def pre_split_from_git() -> str | None:
    """The same document read from `SPLIT_COMMIT^`, while that commit is still reachable."""
    code, text = git("show", f"{SPLIT_COMMIT}^:MASTER_EXECUTION_ROADMAP.md")
    return text if code == 0 else None


class SplitIsLossless(unittest.TestCase):
    def setUp(self):
        self.assembled = roadmap_source.roadmap_text(ROOT)

    def test_the_split_lost_nothing_and_every_later_change_is_enumerated(self):
        """The assembly may differ from the pre-split baseline ONLY at recorded lines.

        This was a flat `assertEqual` until 2026-08-30, and it was right to be: it proved the
        split itself lost nothing. Then `T-049` repaired sixteen Definition-of-Done rows that
        `56e1cd7` — "Make the roadmap fit" — had cut in half to get the document under its byte
        ceiling, leaving every one of them ending mid-clause. Those repairs are a deliberate
        divergence from the baseline, and there are exactly two honest ways to hold one: rewrite
        the fixture (which turns this into a snapshot that agrees with whatever it is shown), or
        ENUMERATE the divergence. Enumerated. The fixture stays byte-identical to `5512d82^`,
        which the test below still proves, and any line that drifts without being listed here is
        red exactly as before.

        Mutant: join the phase bodies with one newline instead of two ⇒ red (that was the real
        first attempt, and it silently removed the blank line between every pair of phases).
        Mutant: drop one index from REPAIRED_LINES ⇒ red. Mutant: add an unrepaired line to it
        ⇒ red, because a listed line that does NOT differ is a stale exemption."""
        before = pre_split_roadmap()
        self.assertIsNotNone(before, f"{FIXTURE_REL} is missing; the baseline is not optional")
        baseline = before.split("\n")
        assembled = self.assembled.split("\n")
        self.assertEqual(len(baseline), len(assembled), "the split changed the line count")
        differing = {i for i in range(len(baseline)) if baseline[i] != assembled[i]}
        self.assertEqual(
            differing, REPAIRED_LINES,
            "every difference from the pre-split baseline must be a recorded T-049 repair",
        )
        for i in sorted(REPAIRED_LINES):
            self.assertTrue(
                baseline[i].startswith("- ["),
                f"line {i + 1} of the baseline is not a checkbox row",
            )
            self.assertEqual(
                baseline[i][:6], assembled[i][:6],
                f"line {i + 1}: a repair may finish the sentence, never change the checkbox",
            )

    def test_the_frozen_baseline_is_the_real_pre_split_commit(self):
        """The fixture must be what `5512d82^` actually held, not whatever makes the test above
        pass. Skips once that commit is gone — at which point the fixture is the only record, which
        is exactly why it is committed.

        Mutant: edit one character of the fixture ⇒ red here AND red above, so a fixture doctored
        to fit a lossy assembly cannot survive both."""
        from_git = pre_split_from_git()
        if from_git is None:
            self.skipTest(f"{SPLIT_COMMIT} is no longer reachable; the fixture is the record")
        self.assertEqual(from_git, pre_split_roadmap())

    def test_every_phase_is_present_exactly_once_and_in_order(self):
        """Mutant: sort the phase files lexically ⇒ phase-10 lands after phase-1 ⇒ red."""
        found = [int(n) for n in PHASE_HEAD.findall(self.assembled)]
        self.assertEqual(found, list(range(0, 11)))

    def test_every_phase_keeps_all_sixteen_required_sections(self):
        """This is what check_coordination asserts. Asserting it here too means a lossy
        split is caught by the tool that did the splitting, not only downstream."""
        heads = list(PHASE_HEAD.finditer(self.assembled))
        end = self.assembled.find("\n# Appendix")
        for i, m in enumerate(heads):
            stop = heads[i + 1].start() if i + 1 < len(heads) else (end if end > 0 else len(self.assembled))
            block = self.assembled[m.start():stop]
            missing = [s for s in REQUIRED_SECTIONS if f"**{s}.**" not in block]
            self.assertEqual(missing, [], f"Phase {m.group(1)} lost section(s): {missing}")

    def test_no_checkbox_was_lost(self):
        """check_roadmap_order counts these. A split that dropped one would make a phase
        look closer to done than it is — in the direction nobody questions."""
        before = pre_split_roadmap()
        if before is None:
            self.skipTest("no committed pre-split roadmap reachable in the last 40 commits")
        count = lambda t: len(re.findall(r"(?m)^\s*[-*] \[[ xX]\]", t))
        self.assertEqual(count(before), count(self.assembled))

    def test_the_marker_is_where_the_phases_belong(self):
        """Between `# Phases` and `# Appendix`. check_coordination uses `^# Appendix` as the
        hard end of the phase region, so an assembly that put the bodies after it would give
        every phase an empty block. Mutant: move the marker below the appendix ⇒ red."""
        main = (ROOT / "MASTER_EXECUTION_ROADMAP.md").read_text(encoding="utf-8")
        self.assertIn(roadmap_source.MARKER, main)
        self.assertLess(main.index(roadmap_source.MARKER), main.index("\n# Appendix"))

    def test_the_main_file_carries_no_phase_body_of_its_own(self):
        """Two homes for one phase is the duplication this whole task exists to remove."""
        main = (ROOT / "MASTER_EXECUTION_ROADMAP.md").read_text(encoding="utf-8")
        self.assertEqual(PHASE_HEAD.findall(main), [])

    def test_phase_files_are_ordered_numerically_not_lexically(self):
        names = [p.stem for p in roadmap_source.phase_files(ROOT)]
        self.assertEqual(names, [f"phase-{n}" for n in range(0, 11)])


if __name__ == "__main__":
    unittest.main()
