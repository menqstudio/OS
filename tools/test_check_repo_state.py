"""Tests for tools/check_repo_state.py — the live-GitHub truth verifier's pure compare()."""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_repo_state as rs  # noqa: E402


def _snapshot():
    return {"prs": [
        {"number": 31, "branch": "feat/wave-3b1-isolated-signer", "base": "main",
         "draft": False, "merge_state": "open",
         "head_at_last_sync": "6ebeca88627640eef8effe576b3d388417cb4949"},
        {"number": 32, "branch": "impl/wave-3b1b-execution-binding",
         "base": "feat/wave-3b1-isolated-signer", "draft": True, "merge_state": "open",
         "head_at_last_sync": "0e7ee1af0b96ca768cabe43c71d9caec30230430"},
    ]}


def _live_ok():
    return {
        31: {"state": "OPEN", "isDraft": False, "headRefName": "feat/wave-3b1-isolated-signer",
             "baseRefName": "main", "headRefOid": "6ebeca88627640eef8effe576b3d388417cb4949"},
        32: {"state": "OPEN", "isDraft": True, "headRefName": "impl/wave-3b1b-execution-binding",
             "baseRefName": "feat/wave-3b1-isolated-signer", "headRefOid": "0e7ee1af0b96ca768cabe43c71d9caec30230430"},
    }


class CompareTests(unittest.TestCase):
    def test_all_match_passes(self):
        f, w = rs.compare(_snapshot(), _live_ok())
        self.assertEqual(f, [])
        self.assertEqual(w, [])

    def test_merged_pr_called_open_fails(self):
        live = _live_ok(); live[31]["state"] = "MERGED"  # snapshot still says open
        f, _ = rs.compare(_snapshot(), live)
        self.assertTrue(any("PR #31" in p and "GitHub state='MERGED'" in p for p in f))

    def test_closed_pr_called_open_fails(self):
        live = _live_ok(); live[32]["state"] = "CLOSED"
        f, _ = rs.compare(_snapshot(), live)
        self.assertTrue(any("PR #32" in p and "CLOSED" in p for p in f))

    def test_draft_mismatch_fails(self):
        live = _live_ok(); live[32]["isDraft"] = False  # snapshot says draft=True
        f, _ = rs.compare(_snapshot(), live)
        self.assertTrue(any("PR #32" in p and "draft" in p for p in f))

    def test_head_branch_mismatch_fails(self):
        live = _live_ok(); live[31]["headRefName"] = "some/other"
        f, _ = rs.compare(_snapshot(), live)
        self.assertTrue(any("PR #31" in p and "head branch" in p for p in f))

    def test_base_mismatch_fails(self):
        live = _live_ok(); live[32]["baseRefName"] = "main"  # should be the parent branch
        f, _ = rs.compare(_snapshot(), live)
        self.assertTrue(any("PR #32" in p and "base" in p for p in f))

    def test_unresolvable_pr_fails_closed(self):
        live = _live_ok(); live[31] = None
        f, _ = rs.compare(_snapshot(), live)
        self.assertTrue(any("PR #31" in p and "could not be resolved" in p for p in f))

    def test_head_drift_is_warning_not_failure(self):
        live = _live_ok()
        live[31]["headRefOid"] = "1111111111111111111111111111111111111111"  # head advanced
        f, w = rs.compare(_snapshot(), live)
        self.assertEqual(f, [])  # not a failure — head_at_last_sync is a snapshot
        self.assertTrue(any("PR #31" in p and "snapshot is stale" in p for p in w))


if __name__ == "__main__":
    unittest.main()
