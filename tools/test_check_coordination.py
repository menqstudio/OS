"""Tests for tools/check_coordination.py — the coordination-docs CI gate."""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_coordination as cc  # noqa: E402


def _roadmap_text() -> str:
    out = ["# Roadmap", "", "**Status: `Active`**", "", "```", "code", "```", ""]
    for n in range(11):
        out.append(f"## Phase {n} — P{n}")
        out.append("")
        for s in cc.REQUIRED_SECTIONS:
            out.append(f"**{s}.** ok.")
        out.append("")
    out.append("# Appendix")
    return "\n".join(out)


def _good_docs(root: pathlib.Path) -> None:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    for f in ("CLAUDE.md", "OWNERS.md", "docs/ARCHITECTURE.md"):
        (root / f).write_text("x" * 80, encoding="utf-8")
    (root / "MASTER_EXECUTION_ROADMAP.md").write_text(_roadmap_text(), encoding="utf-8")
    (root / "TASKS.md").write_text(
        "| ID | Task | By | Status | PR |\n"
        "| **T-001** | do a thing | me | Done | - |\n",
        encoding="utf-8",
    )
    (root / "PROJECT_STATE.md").write_text(
        "# PROJECT_STATE\n\n**Last updated:** today, HEAD abc1234\n\n"
        "Where we are: everything is fine and this body is long enough.\n",
        encoding="utf-8",
    )


class CheckCoordinationTests(unittest.TestCase):
    def _tmp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return pathlib.Path(d.name)

    def test_good_docs_pass(self):
        root = self._tmp()
        _good_docs(root)
        self.assertEqual(cc.check(root), [])

    def test_missing_canonical_file(self):
        root = self._tmp()
        _good_docs(root)
        (root / "CLAUDE.md").unlink()
        probs = cc.check(root)
        self.assertTrue(any("missing canonical file: CLAUDE.md" in p for p in probs))

    def test_incomplete_roadmap_phase(self):
        root = self._tmp()
        _good_docs(root)
        # Drop one required section from Phase 3.
        text = _roadmap_text().replace("## Phase 3 — P3\n\n**Objective.** ok.\n", "## Phase 3 — P3\n\n")
        (root / "MASTER_EXECUTION_ROADMAP.md").write_text(text, encoding="utf-8")
        probs = cc.check(root)
        self.assertTrue(any("Phase 3 is missing section" in p and "Objective" in p for p in probs))

    def test_wrong_phase_count(self):
        root = self._tmp()
        _good_docs(root)
        # Only 10 phases (drop Phase 10 entirely).
        text = _roadmap_text().split("## Phase 10 —")[0] + "# Appendix"
        (root / "MASTER_EXECUTION_ROADMAP.md").write_text(text, encoding="utf-8")
        probs = cc.check(root)
        self.assertTrue(any("phases must be" in p for p in probs))

    def test_bad_task_status(self):
        root = self._tmp()
        _good_docs(root)
        (root / "TASKS.md").write_text(
            "| ID | Task | By | Status | PR |\n"
            "| **T-002** | broken | me | Pending | - |\n",  # 'Pending' not allowed
            encoding="utf-8",
        )
        probs = cc.check(root)
        self.assertTrue(any("T-002" in p and "no valid status" in p for p in probs))

    def test_unbalanced_fences(self):
        root = self._tmp()
        _good_docs(root)
        (root / "MASTER_EXECUTION_ROADMAP.md").write_text(
            _roadmap_text() + "\n```\ndangling fence\n", encoding="utf-8"
        )
        probs = cc.check(root)
        self.assertTrue(any("unbalanced" in p for p in probs))

    def test_stale_project_state(self):
        root = self._tmp()
        _good_docs(root)
        (root / "PROJECT_STATE.md").write_text("# state\n\nno last-updated line\n", encoding="utf-8")
        probs = cc.check(root)
        self.assertTrue(any("Last updated" in p for p in probs))

    def test_real_repo_is_consistent(self):
        # Dogfood: the live repo must pass its own gate.
        repo = pathlib.Path(__file__).resolve().parents[1]
        self.assertEqual(cc.check(repo), [])


if __name__ == "__main__":
    unittest.main()
