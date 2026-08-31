"""Tests for tools/check_coordination.py — the coordination-docs CI gate."""
from __future__ import annotations

import datetime
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
        "# PROJECT_STATE\n\n**Last updated:** 2026-08-09, HEAD abc1234\n\n"
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
        "status_tokens": {
            "CURRENT_ACTIVE_TASK": "T-017",
            "CURRENT_DESIGN_GATE": "PENDING_REAUDIT",
            "CURRENT_DESIGN_CANDIDATE": "rev-26",
            "CURRENT_VERIFY_SEAM": "complete",
        },
        "stop_gates": ["no production Verified until the chain is exact-head GREEN"],
        "next_action_by_carrier": {"open": "re-audit + merge PR #33", "merged": "rebase PR #31"},
    }


_TOKENS = ("`CURRENT_ACTIVE_TASK: T-017` `CURRENT_DESIGN_GATE: PENDING_REAUDIT` "
           "`CURRENT_DESIGN_CANDIDATE: rev-26` `CURRENT_VERIFY_SEAM: complete`")


def _doc_mentioning_both(extra="") -> str:
    return (f"Active: PR #31 (`{BRANCH_31}`) + PR #32 (`{BRANCH_32}`), task T-017. {_TOKENS} {extra}\n")


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
        "# state\n\n**Last updated:** 2026-08-09\n\n" + _doc_mentioning_both(), encoding="utf-8")
    (root / "TASKS.md").write_text(
        tasks if tasks is not None else
        f"> tokens {_TOKENS}\n\n"
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

    def test_rejects_missing_next_chat_when_state_present(self):
        # F-19: deleting NEXT_CHAT.md must NOT silently disable the semantic layer when the machine
        # anchor config/current_state.json exists — the gate must fail closed, not print GREEN.
        root = self._tmp(); _state_repo(root)
        (root / "NEXT_CHAT.md").unlink()
        self.assertTrue(any("NEXT_CHAT.md is missing while config/current_state.json exists" in p
                            for p in cc.check(root)))

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
        _state_repo(root, project_state="# state\n\n**Last updated:** 2026-08-09\n\nPR #31 + PR #32, task T-017.\n")
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

    def test_rejects_two_rows_sharing_one_task_id(self):
        # Two sessions landed a T-060 on the same board within four hours --
        # different tasks, one ID -- and every gate stayed green. A claim on
        # T-060 then names two tasks, which is the collision TASKS.md's own
        # first rule exists to prevent.
        root = self._tmp()
        rows = ("| ID |\n"
                "| **T-060** | the first task | me | Todo | " + BRANCH_31 + " PR #31 PR #32 |\n"
                "| **T-060** | a DIFFERENT task | me | Todo | " + BRANCH_32 + " |\n")
        _state_repo(root, tasks=rows)
        probs = cc.check(root)
        self.assertTrue(any("T-060 is the ID of 2 different rows" in p for p in probs), probs)

    def test_accepts_distinct_task_ids(self):
        # ...and the refusal above is not a check that cannot pass: the same two
        # rows with distinct IDs are accepted, so what it objects to is the
        # DUPLICATE and not the presence of two rows.
        root = self._tmp()
        rows = ("| ID |\n"
                "| **T-060** | the first task | me | Todo | " + BRANCH_31 + " PR #31 PR #32 |\n"
                "| **T-063** | a DIFFERENT task | me | Todo | " + BRANCH_32 + " |\n")
        _state_repo(root, tasks=rows)
        self.assertFalse([p for p in cc.check(root) if "is the ID of" in p])

    def test_rejects_missing_status_token(self):
        # NEXT_CHAT omits the tokens -> every token is flagged missing.
        root = self._tmp()
        _state_repo(root, next_chat=_doc_mentioning_both().replace(_TOKENS, ""))
        self.assertTrue(any("NEXT_CHAT.md" in p and "missing status token" in p for p in cc.check(root)))

    def test_rejects_current_region_contradiction(self):
        # Token says verify-seam complete, but the CURRENT region also calls it pending -> contradiction.
        root = self._tmp()
        _state_repo(root, project_state="# state\n\n**Last updated:** 2026-08-09\n\n"
                    + _doc_mentioning_both("The verify-seam is still pending."))
        self.assertTrue(any("PROJECT_STATE.md" in p and "pending" in p for p in cc.check(root)))

    def test_history_region_pending_is_excluded(self):
        # The SAME 'verify-seam pending' phrase inside HISTORY markers must NOT be flagged.
        root = self._tmp()
        _state_repo(root, project_state="# state\n\n**Last updated:** 2026-08-09\n\n"
                    + _doc_mentioning_both()
                    + "\n<!-- HISTORY_BEGIN -->\nOld note: the verify-seam was still pending.\n<!-- HISTORY_END -->\n")
        self.assertFalse(any("contradict" in p or ("verify" in p.lower() and "pending" in p)
                             for p in cc.check(root)))

    def test_rejects_unterminated_history_block(self):
        root = self._tmp()
        _state_repo(root, next_chat=_doc_mentioning_both() + "\n<!-- HISTORY_BEGIN -->\ndangling\n")
        self.assertTrue(any("without a matching" in p for p in cc.check(root)))

    def test_rejects_rev26_red_in_current_region(self):
        # A PENDING_REAUDIT candidate may not be called rev-26 design RED (that was an earlier rev).
        root = self._tmp()
        _state_repo(root, next_chat=_doc_mentioning_both("The rev-26 design RED verdict stands."))
        self.assertTrue(any("rev-26 design verdict" in p for p in cc.check(root)))

    def test_rev26_red_in_history_is_excluded(self):
        root = self._tmp()
        _state_repo(root, next_chat=_doc_mentioning_both()
                    + "\n<!-- HISTORY_BEGIN -->\nrev-26 design RED (old note)\n<!-- HISTORY_END -->\n")
        self.assertFalse(any("rev-26 design verdict" in p for p in cc.check(root)))

    def test_conditional_until_green_is_allowed(self):
        root = self._tmp()
        _state_repo(root, next_chat=_doc_mentioning_both("Do NOT merge until rev-26 is design-GREEN."))
        self.assertFalse(any("rev-26 design verdict" in p for p in cc.check(root)))

    def test_marker_carrier_without_transition_ok(self):
        # a DESIGN-AUDIT self-carrier (e.g. PR #31): current_workflow_pr set, NOT in prs[], no
        # carrier_transition (it does not merge to repair main) — exact-head anchored by its PR-body
        # AUDIT_CANDIDATE_HEAD marker instead. Must pass; carrier_transition is OPTIONAL.
        root = self._tmp()
        cs = _default_state()
        cs["prs"] = [dict(cs["prs"][1])]                       # keep only the external #32 (parent #31)
        cs["current_workflow_pr"] = {"number": 31, "branch": BRANCH_31, "base": "main"}
        cs["active"]["branch"] = BRANCH_31                     # active branch == carrier branch (not in prs[])
        _state_repo(root, current_state=cs)
        self.assertEqual(cc.check(root), [])

    def test_rejects_current_workflow_pr_missing_base(self):
        root = self._tmp()
        cs = _default_state()
        cs["current_workflow_pr"] = {"number": 31, "branch": BRANCH_31}   # no base
        _state_repo(root, current_state=cs)
        self.assertTrue(any("current_workflow_pr.base is required" in p for p in cc.check(root)))

    def test_rejects_carrier_also_in_prs(self):
        # the self-carrier cannot ALSO be an exact-head-checked durable PR in prs[].
        root = self._tmp()
        cs = _default_state()
        cs["current_workflow_pr"] = {"number": 31, "branch": BRANCH_31, "base": "main"}  # #31 is also in prs[]
        _state_repo(root, current_state=cs)
        self.assertTrue(any("must NOT also be" in p and "#31" in p for p in cc.check(root)))

    # --- P0-1: strengthened carrier-resolution gate --------------------------------------------------
    def _carrier_state(self) -> dict:
        # a merge-transition carrier declares its OWN gate names (generic, not hard-coded).
        cs = _default_state()
        cs["current_workflow_pr"] = {"number": 33, "branch": "chore/phase0-repository-truth", "base": "main"}
        cs["carrier_transition"] = {
            "carrier_pr": 33,
            "pre_merge": {"gate": "PR33_REAUDIT", "carrier_state": "open"},
            "post_merge": {"gate": "REBASE_PR31", "carrier_state": "merged"},
        }
        cs["status_tokens"].update({
            "CARRIER_IF_OPEN_GATE": "PR33_REAUDIT", "CARRIER_IF_MERGED_GATE": "REBASE_PR31"})
        return cs

    def test_rejects_missing_structured_carrier_token(self):
        # a carrier PR exists but the structured CARRIER_IF_OPEN_GATE token is absent -> flagged.
        root = self._tmp()
        cs = self._carrier_state(); del cs["status_tokens"]["CARRIER_IF_OPEN_GATE"]
        _state_repo(root, current_state=cs)
        self.assertTrue(any("status_tokens.CARRIER_IF_OPEN_GATE missing" in p for p in cc.check(root)))

    def test_rejects_structured_carrier_token_mismatch(self):
        # the structured token must equal the transition anchor; a wrong value is flagged.
        root = self._tmp()
        cs = self._carrier_state(); cs["status_tokens"]["CARRIER_IF_MERGED_GATE"] = "WRONG_GATE"
        _state_repo(root, current_state=cs)
        self.assertTrue(any("CARRIER_IF_MERGED_GATE" in p and "!= carrier_transition.post_merge.gate" in p
                            for p in cc.check(root)))

    # The ACTUAL long sentences the Owner found escaping the old proximity regex.
    def test_rejects_unconditional_reaudit_merge_it(self):
        root = self._tmp()
        _state_repo(root, next_chat=_doc_mentioning_both(
            "Next permitted action: finish + re-audit PR #33 (repository truth) → merge it → rebase PR #31."))
        self.assertTrue(any("unconditional carrier sentence about PR #33" in p for p in cc.check(root)))

    def test_rejects_unconditional_pr33_not_merged(self):
        root = self._tmp()
        _state_repo(root, project_state="# state\n\n**Last updated:** 2026-08-09\n\n"
                    + _doc_mentioning_both("PR #33 is PENDING re-audit (not merged)."))
        self.assertTrue(any("unconditional carrier sentence about PR #33" in p for p in cc.check(root)))

    def test_rejects_unconditional_pr33_reaudit_then_merge(self):
        root = self._tmp()
        _state_repo(root, tasks=f"> tokens {_TOKENS}\n\nCorrect next sequence: PR #33 re-audit → merge.\n\n"
                    "| ID | Task | By | Status | PR |\n"
                    f"| **T-017** | wave 3b-1 | me | In-Progress | PR #31 `{BRANCH_31}` + PR #32 `{BRANCH_32}` |\n")
        self.assertTrue(any("unconditional carrier sentence about PR #33" in p for p in cc.check(root)))

    def test_allows_transition_aware_carrier_sentence(self):
        # the corrected transition-aware form (IF OPEN … / IF MERGED …) must NOT be flagged.
        root = self._tmp()
        _state_repo(root, next_chat=_doc_mentioning_both(
            "Resolve PR #33 live: IF OPEN → obtain repository-truth GREEN and merge PR #33; "
            "IF MERGED → rebase PR #31 onto main."))
        self.assertFalse(any("unconditional carrier sentence" in p for p in cc.check(root)))

    def test_carrier_prose_scan_excludes_history(self):
        # the same unconditional sentence inside HISTORY markers must NOT be flagged.
        root = self._tmp()
        _state_repo(root, next_chat=_doc_mentioning_both()
                    + "\n<!-- HISTORY_BEGIN -->\nOld: re-audit PR #33 → merge it.\n<!-- HISTORY_END -->\n")
        self.assertFalse(any("unconditional carrier sentence" in p for p in cc.check(root)))

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


class ProjectStateFreshnessTests(unittest.TestCase):
    """The `Last updated` date must be COMPARED, not merely present.

    The predecessor of this check asserted only that a non-empty line existed, while the gate's
    green output said "PROJECT_STATE fresh". These tests pin the comparison itself: each one fails
    if the comparison is deleted, which is the property the older check did not have.
    """

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = pathlib.Path(self._dir.name)
        self._real = cc._last_commit_date
        self.addCleanup(lambda: setattr(cc, "_last_commit_date", self._real))

    def _dated(self, value: str) -> None:
        (self.root / "PROJECT_STATE.md").write_text(
            "# state" + "\n\n" + "**Last updated:** " + value + "\n\nbody\n", encoding="utf-8")

    def _commit_date(self, iso):
        cc._last_commit_date = lambda root, rel: (
            None if iso is None
            else datetime.date(*(int(x) for x in iso.split("-"))))

    def test_date_older_than_the_newest_commit_is_red(self):
        self._dated("2026-08-06")
        self._commit_date("2026-08-09")
        probs = cc._check_project_state_freshness(self.root)
        self.assertTrue(any("older than the newest commit" in p for p in probs), probs)

    def test_date_equal_to_the_newest_commit_is_green(self):
        self._dated("2026-08-09")
        self._commit_date("2026-08-09")
        self.assertEqual([], cc._check_project_state_freshness(self.root))

    def test_date_newer_than_the_newest_commit_is_green(self):
        self._dated("2026-08-09")
        self._commit_date("2026-08-01")
        self.assertEqual([], cc._check_project_state_freshness(self.root))

    def test_a_future_date_is_red(self):
        far = datetime.datetime.now(datetime.timezone.utc).date() + datetime.timedelta(days=30)
        self._dated(far.isoformat())
        self._commit_date("2026-08-01")
        probs = cc._check_project_state_freshness(self.root)
        self.assertTrue(any("in the future" in p for p in probs), probs)

    def test_prose_instead_of_a_date_is_red(self):
        self._dated("today, HEAD abc1234")
        self._commit_date("2026-08-09")
        probs = cc._check_project_state_freshness(self.root)
        self.assertTrue(any("no YYYY-MM-DD date" in p for p in probs), probs)

    def test_an_impossible_date_is_red(self):
        self._dated("2026-02-31")
        self._commit_date(None)
        probs = cc._check_project_state_freshness(self.root)
        self.assertTrue(any("not a real calendar date" in p for p in probs), probs)

    def test_ungitted_tree_cannot_be_compared_and_says_nothing_false(self):
        # No git answer -> no invented failure, and (in main()) no claim that it was compared.
        self._dated("2026-08-06")
        self._commit_date(None)
        self.assertEqual([], cc._check_project_state_freshness(self.root))

    def test_missing_line_is_still_red(self):
        (self.root / "PROJECT_STATE.md").write_text("# state" + "\n\nnothing\n", encoding="utf-8")
        self._commit_date("2026-08-09")
        probs = cc._check_project_state_freshness(self.root)
        self.assertTrue(any("missing/empty" in p for p in probs), probs)


if __name__ == "__main__":
    unittest.main()


class CurrentStateProseTests(unittest.TestCase):
    """The FREE-TEXT fields of config/current_state.json, which nothing read until 2026-08-09.

    On that day all four were wrong at once and every structural check was green: `purpose`
    asserted "active.branch is main" while it was a branch; `next_action` opened "The independent
    CODE-audit is GREEN" while `code_audit.gate` in the same file said ARCHITECT_PENDING;
    `next_action_by_carrier` still modelled PR #48 as the open carrier thirty-odd merged PRs later;
    and `stop_gates` cited `platform_governed_execution_supported()` as a live flag when no function
    of that name exists in the tree. Each test below fails if its rule is deleted.
    """

    def _repo(self, tmp: str, **state_overrides) -> pathlib.Path:
        root = pathlib.Path(tmp)
        state = _default_state()
        state["current_workflow_pr"] = {"number": 82, "branch": "settle/after-81", "base": "main"}
        state["code_audit"] = {"gate": "ARCHITECT_PENDING"}
        state.update(state_overrides)
        _state_repo(root, current_state=state)
        return root

    def test_purpose_may_not_claim_a_branch_the_anchor_contradicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp, purpose="prs[] is empty and active.branch is main, so nothing is queued.")
            self.assertTrue(any("purpose says" in p and "active.branch" in p for p in cc.check(root)))

    def test_purpose_quoting_the_old_claim_is_not_the_claim(self) -> None:
        """A correction note must be able to quote what it corrects, or history gets deleted."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp, purpose='This field asserted "active.branch is main" until 2026-08-09.')
            self.assertFalse(any("purpose says" in p for p in cc.check(root)))

    def test_a_pending_audit_may_not_be_described_as_green(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp, next_action="The independent CODE-audit is GREEN, so proceed.")
            self.assertTrue(any("code_audit.gate" in p for p in cc.check(root)))

    def test_a_green_gate_makes_the_same_sentence_legitimate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp, next_action="The independent CODE-audit is GREEN, so proceed.",
                              code_audit={"gate": "GREEN"})
            self.assertFalse(any("code_audit.gate" in p for p in cc.check(root)))

    def test_the_carrier_block_must_name_the_carrier_this_snapshot_has(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp, next_action_by_carrier={
                "_note": "PR #48 self-carrier.", "open": "x", "merged": "y"})
            self.assertTrue(any("next_action_by_carrier never names the carrier #82" in p
                                for p in cc.check(root)))

    def test_the_spec_symbol_may_not_be_cited_as_a_function(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp, stop_gates=["platform_governed_execution_supported() stays false."])
            self.assertTrue(any("platform_governed_execution_supported()" in p for p in cc.check(root)))

    def test_the_spec_symbol_with_its_disclaimer_is_fine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp, stop_gates=[
                "Do not cite platform_governed_execution_supported(): no function of that name "
                "exists in the tree; it is the spec symbol."])
            self.assertFalse(any("without saying no function" in p for p in cc.check(root)))
