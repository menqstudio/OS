"""Tests for tools/sync_active_pr.py — the generator that writes the snapshot and the three banners.

This file had no tests, and it is the single place where most of this repository's stale canon was
manufactured: the false "the broker hands out UpstreamBlockedExecutor" sentence, the invented "122
surviving findings", a `--banner` flag that was parsed and never passed, a `--settled` with no
carrier that rendered "PR #nothing is open at all", and — the one these tests are about — a
hard-coded "Nothing else is open" stamped into the snapshot while PR #112 was open.

The lesson each of those shares is the same: a GENERATOR that asserts a fact it never measured will
write that assertion into every canonical document at once. So what is pinned here is the measuring:
an open pull request that is not the carrier must be named, must carry a role nobody guessed, and a
refusal must leave the tree untouched.
"""
from __future__ import annotations

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sync_active_pr as sap  # noqa: E402

HEAD_112 = "3d0f053a79e1e3de118c6ce6ebab8e17e039c1f2"


def _pr(number=112, branch="design/floor-writer-service", base="main", draft=False,
        title="The floor-writer service has a design now (T-020)"):
    return {"number": number, "headRefName": branch, "baseRefName": base,
            "isDraft": draft, "headRefOid": HEAD_112, "title": title}


class _StateFile(unittest.TestCase):
    """Point the module's STATE at a throwaway snapshot; never touch the real one."""
    def setUp(self):
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = pathlib.Path(self._dir.name) / "current_state.json"
        self.write({"schema": 2, "prs": [], "sync": {}})
        self._real = sap.STATE
        sap.STATE = self.path
        self.addCleanup(lambda: setattr(sap, "STATE", self._real))

    def write(self, obj):
        # two-space indent, so the '"prs": [],' / '"prs": [\n' shapes the surgery keys off are real
        self.path.write_text(json.dumps(obj, indent=2), encoding="utf-8")

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))


class ParkedRoleTests(_StateFile):
    def test_missing_role_refuses_and_names_the_pr(self):
        with self.assertRaises(SystemExit) as cm:
            sap.parked_roles([_pr()], None)
        msg = str(cm.exception)
        self.assertIn("#112", msg)
        self.assertIn("--parked-role 112=design", msg)   # the exact command to re-run

    def test_role_outside_the_closed_enum_refuses(self):
        with self.assertRaises(SystemExit) as cm:
            sap.parked_roles([_pr()], ["112=whatever"])
        self.assertIn("not in", str(cm.exception))

    def test_malformed_pair_refuses(self):
        with self.assertRaises(SystemExit) as cm:
            sap.parked_roles([_pr()], ["not-a-number=design"])
        self.assertIn("NUMBER=ROLE", str(cm.exception))

    def test_valid_role_is_accepted_with_or_without_hash(self):
        self.assertEqual(sap.parked_roles([_pr()], ["#112=design"]), {112: "design"})

    def test_already_recorded_pr_needs_no_role(self):
        # its role is whatever the file already says; re-declaring it is not required.
        self.write({"schema": 2, "prs": [{"number": 112, "role": "design"}], "sync": {}})
        self.assertEqual(sap.parked_roles([_pr()], None), {})

    def test_nothing_parked_is_trivially_fine(self):
        self.assertEqual(sap.parked_roles([], None), {})

    def test_refusal_writes_nothing(self):
        before = self.path.read_text(encoding="utf-8")
        with self.assertRaises(SystemExit):
            sap.parked_roles([_pr()], None)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)


class RecordParkedTests(_StateFile):
    def test_entry_carries_the_exact_live_head_and_role(self):
        added = sap.record_parked_prs([_pr()], {112: "design"})
        self.assertEqual(added, [112])
        entry = self.read()["prs"][0]
        self.assertEqual(entry["number"], 112)
        self.assertEqual(entry["head"], HEAD_112)        # anchored: if #112 moves, the gate goes RED
        self.assertEqual(entry["role"], "design")
        self.assertEqual(entry["branch"], "design/floor-writer-service")
        self.assertEqual(entry["merge_state"], "open")
        self.assertIs(entry["draft"], False)

    def test_draft_flag_is_a_real_boolean_from_github(self):
        sap.record_parked_prs([_pr(draft=True)], {112: "design"})
        self.assertIs(self.read()["prs"][0]["draft"], True)

    def test_second_run_does_not_duplicate(self):
        sap.record_parked_prs([_pr()], {112: "design"})
        self.assertEqual(sap.record_parked_prs([_pr()], {112: "design"}), [])
        self.assertEqual(len(self.read()["prs"]), 1)

    def test_insertion_into_a_non_empty_prs_array_keeps_both(self):
        self.write({"schema": 2, "prs": [{"number": 99, "role": "design"}], "sync": {}})
        sap.record_parked_prs([_pr()], {112: "design"})
        self.assertEqual(sorted(p["number"] for p in self.read()["prs"]), [99, 112])

    def test_file_stays_valid_json(self):
        sap.record_parked_prs([_pr()], {112: "design"})
        json.loads(self.path.read_text(encoding="utf-8"))  # raises if the surgery broke it

    def test_nothing_parked_leaves_the_file_byte_identical(self):
        before = self.path.read_text(encoding="utf-8")
        self.assertEqual(sap.record_parked_prs([], {}), [])
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
