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


def _snapshot():
    # NOTE: the carrier PR (#33) is deliberately NOT in prs[] — only durable project PRs.
    return {
        "sync": {"baseline_main_head_at_sync": MAIN},
        "current_workflow_pr": {"number": 33, "branch": "chore/phase0-repository-truth", "base": "main"},
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


class PrEventTests(unittest.TestCase):
    def _event(self, base_sha=MAIN, base_ref="main", head_ref="chore/phase0-repository-truth", number=33):
        return {"pull_request": {"number": number, "base": {"ref": base_ref, "sha": base_sha},
                                 "head": {"ref": head_ref, "sha": "abc"}}}

    def test_base_sha_matches_baseline_passes(self):
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
