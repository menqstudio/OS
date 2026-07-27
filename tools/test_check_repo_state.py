"""Tests for tools/check_repo_state.py — the live-GitHub EXACT-HEAD verifier's pure functions.

Covers the Owner's required regressions: merge-of-carrier -> main-push must be GREEN (no self-red),
exact-head drift must be RED, event base/head/number mismatch must be RED, merged-called-open RED.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_repo_state as rs  # noqa: E402

HEAD_31 = "6ebeca88627640eef8effe576b3d388417cb4949"
HEAD_32 = "0e7ee1af0b96ca768cabe43c71d9caec30230430"
MAIN = "df3c0aca80cbe4a5537a9fdd53e16e26541c9c19"
NEWMAIN = "1111111111111111111111111111111111111111"


CARRIER_HEAD = "2222222222222222222222222222222222222222"


def _snapshot():
    # NOTE: the carrier PR (#33) is deliberately NOT in prs[] — only durable project PRs.
    return {
        "sync": {"baseline_main_head_at_sync": MAIN},
        "current_workflow_pr": {"number": 33, "branch": "chore/phase0-repository-truth",
                                "base": "main", "head": CARRIER_HEAD},
        "carrier_transition": {
            "carrier_pr": 33,
            "pre_merge": {"gate": "PR33_REAUDIT", "carrier_state": "open", "phase_0": "in_progress"},
            "post_merge": {"gate": "REBASE_PR31", "carrier_state": "merged", "phase_0": "done"},
        },
        "prs": [
            {"number": 31, "branch": "feat/wave-3b1-isolated-signer", "base": "main",
             "draft": False, "merge_state": "open", "head": HEAD_31},
            {"number": 32, "branch": "impl/wave-3b1b-execution-binding",
             "base": "feat/wave-3b1-isolated-signer", "draft": True, "merge_state": "open", "head": HEAD_32},
        ],
    }


def _live_ok():
    return {
        31: {"state": "OPEN", "isDraft": False, "headRefName": "feat/wave-3b1-isolated-signer",
             "baseRefName": "main", "headRefOid": HEAD_31},
        32: {"state": "OPEN", "isDraft": True, "headRefName": "impl/wave-3b1b-execution-binding",
             "baseRefName": "feat/wave-3b1-isolated-signer", "headRefOid": HEAD_32},
    }


class ExternalPrTests(unittest.TestCase):
    def test_exact_match_passes(self):
        self.assertEqual(rs.compare_external_prs(_snapshot(), _live_ok()), [])

    def test_merged_called_open_fails(self):
        live = _live_ok(); live[31]["state"] = "MERGED"
        self.assertTrue(any("PR #31" in p and "MERGED" in p for p in rs.compare_external_prs(_snapshot(), live)))

    def test_exact_head_drift_is_now_a_failure(self):
        live = _live_ok(); live[31]["headRefOid"] = NEWMAIN  # head advanced
        f = rs.compare_external_prs(_snapshot(), live)
        self.assertTrue(any("PR #31" in p and "exact-head drift" in p for p in f))

    def test_draft_mismatch_fails(self):
        live = _live_ok(); live[32]["isDraft"] = False
        self.assertTrue(any("PR #32" in p and "draft" in p for p in rs.compare_external_prs(_snapshot(), live)))

    def test_base_mismatch_fails(self):
        live = _live_ok(); live[32]["baseRefName"] = "main"
        self.assertTrue(any("PR #32" in p and "base" in p for p in rs.compare_external_prs(_snapshot(), live)))

    def test_unresolvable_fails_closed(self):
        live = _live_ok(); live[31] = None
        self.assertTrue(any("PR #31" in p and "unresolved" in p for p in rs.compare_external_prs(_snapshot(), live)))

    def test_non_sha_head_fails(self):
        snap = _snapshot(); snap["prs"][0]["head"] = "PENDING"
        self.assertTrue(any("PR #31" in p and "40-hex" in p for p in rs.compare_external_prs(snap, _live_ok())))

    # --- P1: malformed / missing live metadata must be RED (no skip-on-falsy fail-open) -------------
    def test_null_live_head_fails_closed(self):
        live = _live_ok(); live[31]["headRefOid"] = None
        self.assertTrue(any("PR #31" in p and "headRefOid" in p for p in rs.compare_external_prs(_snapshot(), live)))

    def test_missing_live_head_branch_fails_closed(self):
        live = _live_ok(); live[31]["headRefName"] = ""
        self.assertTrue(any("PR #31" in p and "headRefName" in p for p in rs.compare_external_prs(_snapshot(), live)))

    def test_missing_live_base_fails_closed(self):
        live = _live_ok(); del live[32]["baseRefName"]
        self.assertTrue(any("PR #32" in p and "baseRefName" in p for p in rs.compare_external_prs(_snapshot(), live)))

    def test_null_live_state_fails_closed(self):
        live = _live_ok(); live[31]["state"] = None
        self.assertTrue(any("PR #31" in p and "state missing/unknown" in p for p in rs.compare_external_prs(_snapshot(), live)))

    def test_unknown_live_state_fails_closed(self):
        live = _live_ok(); live[31]["state"] = "LOCKED"
        self.assertTrue(any("PR #31" in p and "state missing/unknown" in p for p in rs.compare_external_prs(_snapshot(), live)))

    def test_null_live_isdraft_fails_closed(self):
        live = _live_ok(); live[32]["isDraft"] = None
        self.assertTrue(any("PR #32" in p and "isDraft" in p for p in rs.compare_external_prs(_snapshot(), live)))


class PrEventTests(unittest.TestCase):
    def _event(self, base_sha=MAIN, base_ref="main", head_ref="chore/phase0-repository-truth",
               number=33, head_sha=CARRIER_HEAD):
        return {"pull_request": {"number": number, "base": {"ref": base_ref, "sha": base_sha},
                                 "head": {"ref": head_ref, "sha": head_sha}}}

    def test_ok_event_passes(self):
        self.assertEqual(rs.verify_pr_event(self._event(), _snapshot()), [])

    def test_stale_baseline_vs_pr_base_fails(self):
        f = rs.verify_pr_event(self._event(base_sha=NEWMAIN), _snapshot())
        self.assertTrue(any("stale vs its base" in p for p in f))

    def test_wrong_current_pr_number_fails(self):
        f = rs.verify_pr_event(self._event(number=99), _snapshot())
        self.assertTrue(any("!= snapshot current_workflow_pr #33" in p for p in f))

    def test_wrong_head_branch_fails(self):
        f = rs.verify_pr_event(self._event(head_ref="some/other"), _snapshot())
        self.assertTrue(any("head branch" in p for p in f))


class CarrierExactHeadTests(unittest.TestCase):
    def test_exact_triple_equality_passes(self):
        self.assertEqual(rs.verify_carrier_exact_head(CARRIER_HEAD, CARRIER_HEAD, CARRIER_HEAD), [])

    def test_descendant_with_old_marker_fails(self):
        # a new commit advances the event/live head; the PR-body marker is still the old sha -> RED.
        f = rs.verify_carrier_exact_head(NEWMAIN, NEWMAIN, CARRIER_HEAD)
        self.assertTrue(any("AUDIT_CANDIDATE_HEAD" in p for p in f))

    def test_event_differs_from_live_fails(self):
        f = rs.verify_carrier_exact_head(CARRIER_HEAD, NEWMAIN, CARRIER_HEAD)
        self.assertTrue(any("live GitHub head" in p for p in f))

    def test_missing_event_head_fails(self):
        self.assertTrue(any("event PR head" in p for p in rs.verify_carrier_exact_head(None, CARRIER_HEAD, CARRIER_HEAD)))

    def test_non_hex_event_head_fails(self):
        self.assertTrue(any("event PR head" in p for p in rs.verify_carrier_exact_head("abc", CARRIER_HEAD, CARRIER_HEAD)))

    def test_missing_body_marker_fails(self):
        self.assertTrue(any("AUDIT_CANDIDATE_HEAD marker missing" in p
                            for p in rs.verify_carrier_exact_head(CARRIER_HEAD, CARRIER_HEAD, None)))

    def test_unresolved_live_head_fails(self):
        self.assertTrue(any("live GitHub carrier head" in p
                            for p in rs.verify_carrier_exact_head(CARRIER_HEAD, None, CARRIER_HEAD)))

    def test_parse_marker(self):
        self.assertEqual(rs.parse_audit_candidate(f"body\nAUDIT_CANDIDATE_HEAD: {CARRIER_HEAD}\nmore"), CARRIER_HEAD)
        self.assertIsNone(rs.parse_audit_candidate("no marker here"))

    # --- P0-2: parse_audit_candidate must fail closed on zero / duplicate / malformed markers -------
    def test_parse_duplicate_marker_fails_closed(self):
        body = f"AUDIT_CANDIDATE_HEAD: {CARRIER_HEAD}\nsome text\nAUDIT_CANDIDATE_HEAD: {NEWMAIN}"
        self.assertIsNone(rs.parse_audit_candidate(body))  # ambiguous: never silently pick one

    def test_parse_malformed_marker_fails_closed(self):
        self.assertIsNone(rs.parse_audit_candidate("AUDIT_CANDIDATE_HEAD: not-a-40-hex-sha"))

    def test_parse_zero_marker_is_none(self):
        self.assertIsNone(rs.parse_audit_candidate("release notes with no marker at all"))

    def test_duplicate_marker_makes_exact_head_red(self):
        # a duplicate marker -> parse None -> the exact-head anchor is RED.
        marker = rs.parse_audit_candidate(f"AUDIT_CANDIDATE_HEAD: {CARRIER_HEAD}\nAUDIT_CANDIDATE_HEAD: {CARRIER_HEAD}")
        self.assertTrue(any("AUDIT_CANDIDATE_HEAD" in p
                            for p in rs.verify_carrier_exact_head(CARRIER_HEAD, CARRIER_HEAD, marker)))


class CarrierPostMergeTests(unittest.TestCase):
    def test_merged_with_correct_post_merge_is_green(self):
        snap = _snapshot()
        snap["product_roadmap"] = {"phase_0": {"if_carrier_open": "in_progress", "if_carrier_merged": "done"}}
        snap["next_action_by_carrier"] = {"open": "x", "merged": "y"}
        self.assertEqual(rs.verify_carrier_post_merge({"state": "MERGED"}, snap), [])

    def test_merged_with_empty_gate_fails(self):
        # gate NAME is snapshot-declared (generic); an EMPTY/missing post_merge gate is RED.
        snap = _snapshot(); snap["next_action_by_carrier"] = {"open": "x", "merged": "y"}
        snap["carrier_transition"]["post_merge"]["gate"] = ""
        f = rs.verify_carrier_post_merge({"state": "MERGED"}, snap)
        self.assertTrue(any("post_merge.gate is missing/empty" in p for p in f))

    def test_merged_self_stale_carrier_state_fails(self):
        # anti-self-stale: live-MERGED but the snapshot still says the carrier is not merged -> RED.
        snap = _snapshot(); snap["next_action_by_carrier"] = {"open": "x", "merged": "y"}
        snap["carrier_transition"]["post_merge"]["carrier_state"] = "open"
        f = rs.verify_carrier_post_merge({"state": "MERGED"}, snap)
        self.assertTrue(any("self-stale main" in p for p in f))

    def test_merged_missing_merged_next_action_fails(self):
        snap = _snapshot(); snap["next_action_by_carrier"] = {"open": "x"}  # no merged
        self.assertTrue(any("next_action_by_carrier.merged is missing" in p
                            for p in rs.verify_carrier_post_merge({"state": "MERGED"}, snap)))

    def test_unresolvable_carrier_fails_closed(self):
        # P0-3: None must be a FAILURE, not a no-op.
        self.assertTrue(any("could not be resolved" in p for p in rs.verify_carrier_post_merge(None, _snapshot())))

    def test_open_carrier_is_noop(self):
        self.assertEqual(rs.verify_carrier_post_merge({"state": "OPEN"}, _snapshot()), [])


class CarrierStateTests(unittest.TestCase):
    """P1: the carrier's live state is explicitly enumerated; unresolved/unknown => RED; OPEN validates
    the pre_merge branch, MERGED the post_merge branch."""
    def _snap_full(self):
        snap = _snapshot()
        snap["product_roadmap"] = {"phase_0": {"if_carrier_open": "in_progress", "if_carrier_merged": "done"}}
        snap["next_action_by_carrier"] = {"open": "x", "merged": "y"}
        return snap

    def test_open_correct_pre_merge_is_green(self):
        self.assertEqual(rs.verify_carrier_state({"state": "OPEN"}, self._snap_full()), [])

    def test_open_empty_pre_merge_gate_fails(self):
        snap = self._snap_full(); snap["carrier_transition"]["pre_merge"]["gate"] = ""
        self.assertTrue(any("pre_merge.gate is missing/empty" in p for p in rs.verify_carrier_state({"state": "OPEN"}, snap)))

    def test_open_any_declared_gate_ok(self):
        # a design-audit carrier declares its OWN gate name (not the Phase-0 value) — must pass.
        snap = self._snap_full(); snap["carrier_transition"]["pre_merge"]["gate"] = "PR31_DESIGN_AUDIT"
        self.assertEqual(rs.verify_carrier_state({"state": "OPEN"}, snap), [])

    def test_unresolved_carrier_state_fails_closed(self):
        self.assertTrue(any("unresolved/missing" in p for p in rs.verify_carrier_state(None, self._snap_full())))
        self.assertTrue(any("unresolved/missing" in p for p in rs.verify_carrier_state({"state": None}, self._snap_full())))

    def test_unknown_carrier_state_fails_closed(self):
        f = rs.verify_carrier_state({"state": "CLOSED"}, self._snap_full())
        self.assertTrue(any("not an allowed carrier state" in p for p in f))

    def test_merged_delegates_to_post_merge_green(self):
        self.assertEqual(rs.verify_carrier_state({"state": "MERGED"}, self._snap_full()), [])

    def test_merged_delegates_to_post_merge_red(self):
        snap = self._snap_full(); snap["carrier_transition"]["post_merge"]["gate"] = ""
        self.assertTrue(any("post_merge.gate is missing/empty" in p for p in rs.verify_carrier_state({"state": "MERGED"}, snap)))


class WorkflowTriggerTests(unittest.TestCase):
    """P0-2: prove `edited` (and the other required types) stay in the real pull_request trigger, so a
    PR-body AUDIT_CANDIDATE_HEAD edit starts a fresh repo-state run; plus the pure-parser forms."""
    def _real_yaml(self):
        return (pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    def test_required_types_present_in_real_workflow(self):
        types = rs.pull_request_trigger_types(self._real_yaml())
        for required in ("opened", "reopened", "synchronize", "edited", "ready_for_review"):
            self.assertIn(required, types, f"pull_request trigger is missing '{required}'")

    def test_parser_block_list_form(self):
        y = "on:\n  pull_request:\n    types:\n      - opened\n      - edited\n"
        self.assertEqual(rs.pull_request_trigger_types(y), {"opened", "edited"})

    def test_parser_inline_list_form(self):
        y = "on:\n  pull_request:\n    types: [opened, edited, synchronize]\n"
        self.assertEqual(rs.pull_request_trigger_types(y), {"opened", "edited", "synchronize"})

    def test_parser_detects_missing_edited(self):
        y = "on:\n  pull_request:\n    types:\n      - opened\n      - synchronize\n\npermissions:\n  contents: read\n"
        self.assertNotIn("edited", rs.pull_request_trigger_types(y))


class MainPushTests(unittest.TestCase):
    def test_merge_of_carrier_then_main_push_is_green(self):
        # THE self-red guard: baseline is an ancestor of the post-merge main HEAD -> GREEN.
        self.assertEqual(rs.verify_main_push(NEWMAIN, MAIN, is_ancestor=lambda a, b: True), [])

    def test_baseline_equal_pushed_is_green(self):
        self.assertEqual(rs.verify_main_push(MAIN, MAIN, is_ancestor=lambda a, b: False), [])

    def test_baseline_not_ancestor_fails(self):
        f = rs.verify_main_push(NEWMAIN, MAIN, is_ancestor=lambda a, b: False)
        self.assertTrue(any("not an ancestor" in p for p in f))


if __name__ == "__main__":
    unittest.main()
