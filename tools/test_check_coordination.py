"""Tests for tools/check_coordination.py — the coordination-docs CI gate."""
from __future__ import annotations

import json
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


def _default_state() -> dict:
    return {
        "main_head": "a" * 40, "active_wave": "3b-1B", "active_task": "T-017",
        "active_branch": "feat/wave-3b1-isolated-signer",
        "prs": [
            {"number": 31, "role": "design-lock + 3b-1A code", "merge_state": "open", "design_verdict": "RED"},
            {"number": 32, "role": "implementation", "merge_state": "open", "design_verdict": "RED", "is_rc": False},
        ],
        "waves": {"3b-1B": {"status": "design_red_code_wip", "code_exists": True, "impl_pr": 32}},
        "stop_gates": ["no production Verified until the chain is exact-head GREEN"],
        "next_action": "submit PR #31 rev-26 for a fresh Architect design audit",
    }


def _state_repo(root: pathlib.Path, *, current_state="DEFAULT",
                next_chat=None, project_state=None, tasks=None) -> None:
    """A realistic coordination repo: structural docs + NEXT_CHAT + the machine-readable anchor, all
    consistent, so the semantic layer engages (it skips when NEXT_CHAT.md is absent)."""
    _good_docs(root)
    (root / "config").mkdir(parents=True, exist_ok=True)
    if current_state != "OMIT":
        cs = _default_state() if current_state == "DEFAULT" else current_state
        (root / "config/current_state.json").write_text(json.dumps(cs), encoding="utf-8")
    (root / "NEXT_CHAT.md").write_text(
        next_chat if next_chat is not None else
        "Active: PR #31 / PR #32 on `feat/wave-3b1-isolated-signer`, task T-017.\n",
        encoding="utf-8")
    (root / "PROJECT_STATE.md").write_text(
        project_state if project_state is not None else
        "# state\n\n**Last updated:** today\n\nPR #31 on `feat/wave-3b1-isolated-signer` (T-017).\n",
        encoding="utf-8")
    (root / "TASKS.md").write_text(
        tasks if tasks is not None else
        "| ID | Task | By | Status | PR |\n"
        "| **T-017** | wave 3b-1 | me | In-Progress | PR #31 `feat/wave-3b1-isolated-signer` |\n",
        encoding="utf-8")


class SemanticGateTests(unittest.TestCase):
    def _tmp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return pathlib.Path(d.name)

    def test_good_state_repo_passes(self):
        root = self._tmp(); _state_repo(root)
        self.assertEqual(cc.check(root), [])

    def test_rejects_missing_current_state(self):
        root = self._tmp(); _state_repo(root, current_state="OMIT")
        self.assertTrue(any("missing config/current_state.json" in p for p in cc.check(root)))

    def test_rejects_open_impl_pr_without_code_exists(self):
        root = self._tmp()
        cs = _default_state(); cs["waves"]["3b-1B"]["code_exists"] = False
        _state_repo(root, current_state=cs)
        self.assertTrue(any("code_exists is not true" in p for p in cc.check(root)))

    def test_rejects_rc_while_design_red(self):
        root = self._tmp()
        cs = _default_state(); cs["prs"][1]["is_rc"] = True  # PR #32 design RED + is_rc
        _state_repo(root, current_state=cs)
        self.assertTrue(any("is_rc=true while design_verdict is RED" in p for p in cc.check(root)))

    def test_rejects_bad_main_head(self):
        root = self._tmp()
        cs = _default_state(); cs["main_head"] = "not-a-sha"
        _state_repo(root, current_state=cs)
        self.assertTrue(any("main_head must be a 40-hex" in p for p in cc.check(root)))

    def test_rejects_doc_not_referencing_active_pr(self):
        # NEXT_CHAT names the branch + task but NOT the live PR number -> the exact "docs never mention
        # the active PR" drift (main was frozen at 3b-0 and never named PR #31/#32).
        root = self._tmp()
        _state_repo(root, next_chat="Active branch `feat/wave-3b1-isolated-signer`, task T-017.\n")
        self.assertTrue(any("NEXT_CHAT.md" in p and "active open PR" in p for p in cc.check(root)))

    def test_rejects_doc_not_referencing_active_branch(self):
        root = self._tmp()
        _state_repo(root, project_state="# state\n\n**Last updated:** today\n\nPR #31, task T-017.\n")
        self.assertTrue(any("PROJECT_STATE.md" in p and "active branch" in p for p in cc.check(root)))

    def test_substantive_change_requires_state_update(self):
        root = self._tmp(); _state_repo(root)
        probs = cc.check(root, changed=["engine/tools/brops_receipt_signer.py"])
        self.assertTrue(any("did not update" in p for p in probs))

    def test_substantive_change_with_state_update_ok(self):
        root = self._tmp(); _state_repo(root)
        probs = cc.check(root, changed=["engine/tools/brops_receipt_signer.py", "NEXT_CHAT.md"])
        self.assertFalse(any("did not update" in p for p in probs))

    def test_current_state_edit_alone_is_a_valid_state_touch(self):
        root = self._tmp(); _state_repo(root)
        probs = cc.check(root, changed=["config/current_state.json"])
        self.assertFalse(any("did not update" in p for p in probs))

    def test_manifest_missing_active_doc_is_flagged(self):
        root = self._tmp(); _state_repo(root)
        (root / "docs/design").mkdir(parents=True, exist_ok=True)
        (root / "docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md").write_text("design", encoding="utf-8")
        (root / "config/canonical-read-manifest.json").write_text(
            json.dumps({"paths": ["NEXT_CHAT.md"]}), encoding="utf-8")  # omits the design doc
        self.assertTrue(any("not in the startup read set" in p for p in cc.check(root)))


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
