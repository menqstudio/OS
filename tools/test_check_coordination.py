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


BRANCH_31 = "feat/wave-3b1-isolated-signer"
BRANCH_32 = "impl/wave-3b1b-execution-binding"


def _default_state() -> dict:
    return {
        "sync": {"baseline_main_head_at_sync": "a" * 40},
        "active": {"wave": "3b-1B", "task": "T-017", "branch": BRANCH_31},
        "prs": [
            {"number": 31, "branch": BRANCH_31, "base": "main", "role": "design",
             "draft": False, "merge_state": "open", "parent_pr": None, "code_verdict": "GREEN"},
            {"number": 32, "branch": BRANCH_32, "base": BRANCH_31, "role": "implementation",
             "draft": True, "merge_state": "open", "parent_pr": 31, "is_rc": False},
        ],
        "waves": {"3b-1B": {"status": "design_pending_reaudit_code_wip", "code_exists": True, "impl_pr": 32}},
        "design_gate": {"current_candidate_gate": "PENDING_REAUDIT", "last_architect_verdict": "RED"},
        "stop_gates": ["no production Verified until the chain is exact-head GREEN"],
        "next_action": "re-audit + merge PR #33, rebase PR #31, then submit rev-26 for audit",
    }


def _doc_mentioning_both(extra="") -> str:
    return (f"Active: PR #31 (`{BRANCH_31}`) + PR #32 (`{BRANCH_32}`), task T-017. {extra}\n")


def _state_repo(root: pathlib.Path, *, current_state="DEFAULT",
                next_chat=None, project_state=None, tasks=None) -> None:
    """A realistic coordination repo whose human docs reference BOTH active PRs + branches + task."""
    _good_docs(root)
    (root / "config").mkdir(parents=True, exist_ok=True)
    if current_state != "OMIT":
        cs = _default_state() if current_state == "DEFAULT" else current_state
        (root / "config/current_state.json").write_text(json.dumps(cs), encoding="utf-8")
    (root / "NEXT_CHAT.md").write_text(
        next_chat if next_chat is not None else _doc_mentioning_both(), encoding="utf-8")
    (root / "PROJECT_STATE.md").write_text(
        project_state if project_state is not None else
        "# state\n\n**Last updated:** today\n\n" + _doc_mentioning_both(), encoding="utf-8")
    (root / "TASKS.md").write_text(
        tasks if tasks is not None else
        "| ID | Task | By | Status | PR |\n"
        f"| **T-017** | wave 3b-1 | me | In-Progress | PR #31 `{BRANCH_31}` + PR #32 `{BRANCH_32}` |\n",
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

    def test_rejects_rc_while_gate_not_green(self):
        # PR #32 is_rc=true while the design gate is PENDING_REAUDIT (not GREEN) — CI-green ≠ audit-green.
        root = self._tmp()
        cs = _default_state(); cs["prs"][1]["is_rc"] = True
        _state_repo(root, current_state=cs)
        self.assertTrue(any("is_rc=true but design_gate" in p and "not GREEN" in p for p in cc.check(root)))

    def test_rejects_bad_baseline_head(self):
        root = self._tmp()
        cs = _default_state(); cs["sync"]["baseline_main_head_at_sync"] = "not-a-sha"
        _state_repo(root, current_state=cs)
        self.assertTrue(any("baseline_main_head_at_sync must be a 40-hex" in p for p in cc.check(root)))

    def test_rejects_bad_gate_enum(self):
        root = self._tmp()
        cs = _default_state(); cs["design_gate"]["current_candidate_gate"] = "kinda-green"
        _state_repo(root, current_state=cs)
        self.assertTrue(any("current_candidate_gate must be one of" in p for p in cc.check(root)))

    def test_rejects_child_base_mismatch(self):
        # PR #32 base must equal parent PR #31's branch.
        root = self._tmp()
        cs = _default_state(); cs["prs"][1]["base"] = "main"  # should be BRANCH_31
        _state_repo(root, current_state=cs)
        self.assertTrue(any("base 'main' != parent PR #31 branch" in p for p in cc.check(root)))

    def test_rejects_parent_pr_missing(self):
        root = self._tmp()
        cs = _default_state(); cs["prs"][1]["parent_pr"] = 99  # not in prs[]
        _state_repo(root, current_state=cs)
        self.assertTrue(any("parent_pr #99 is not listed" in p for p in cc.check(root)))

    def test_rejects_active_branch_not_open_pr(self):
        root = self._tmp()
        cs = _default_state(); cs["active"]["branch"] = "some/other-branch"
        _state_repo(root, current_state=cs)
        self.assertTrue(any("does not correspond to any OPEN PR branch" in p for p in cc.check(root)))

    def test_rejects_doc_missing_second_pr(self):
        # THE Owner blind spot: a doc names PR #31 but omits the equally-active PR #32 -> must reject.
        root = self._tmp()
        _state_repo(root, next_chat=f"Active: PR #31 (`{BRANCH_31}`), task T-017.\n")
        self.assertTrue(any("NEXT_CHAT.md" in p and "active PR #32" in p for p in cc.check(root)))

    def test_rejects_doc_not_referencing_active_branch(self):
        root = self._tmp()
        _state_repo(root, project_state="# state\n\n**Last updated:** today\n\nPR #31 + PR #32, task T-017.\n")
        self.assertTrue(any("PROJECT_STATE.md" in p and "active branch" in p for p in cc.check(root)))

    def test_rejects_doc_missing_active_task(self):
        root = self._tmp()
        _state_repo(root, tasks="| ID |\n| **T-999** | x | me | Done | PR #31 " + BRANCH_31 + " PR #32 " + BRANCH_32 + " |\n")
        self.assertTrue(any("TASKS.md" in p and "active task 'T-017'" in p for p in cc.check(root)))

    def test_substantive_change_requires_state_update(self):
        root = self._tmp(); _state_repo(root)
        probs = cc.check(root, changed=["engine/tools/brops_receipt_signer.py"])
        self.assertTrue(any("did not update" in p for p in probs))

    def test_substantive_change_with_full_sync_ok(self):
        root = self._tmp(); _state_repo(root)
        probs = cc.check(root, changed=[
            "engine/tools/brops_receipt_signer.py", "config/current_state.json",
            "NEXT_CHAT.md", "PROJECT_STATE.md", "TASKS.md"])
        self.assertEqual([], probs)

    def test_current_state_change_requires_all_human_mirrors(self):
        # Owner rule: touching the machine anchor without syncing all three human mirrors is a desync.
        root = self._tmp(); _state_repo(root)
        probs = cc.check(root, changed=["config/current_state.json", "NEXT_CHAT.md"])  # missing 2 mirrors
        self.assertTrue(any("checkpoint desync" in p for p in probs))

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
