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



class BannerLocationTests(unittest.TestCase):
    """The banner is found by MARKER, never by counting lines.

    `rewrite_banners` replaced "every consecutive blockquote line from line 3 down" until
    2026-08-30. `T-045` then rewrote all three documents and put a purpose note in exactly that
    position, so the first `--settled` run afterwards overwrote NEXT_CHAT.md's explanation of what
    the file is and what its ceiling is — and then refused on the SECOND file, leaving one document
    rewritten and two not. Both halves are pinned here.
    """

    def setUp(self):
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = pathlib.Path(self._dir.name)
        self._real_root = sap.ROOT
        sap.ROOT = self.root
        self.addCleanup(lambda: setattr(sap, "ROOT", self._real_root))

    def doc(self, name: str, *, markers: bool = True) -> pathlib.Path:
        body = "# Title\n\n> **This file is the live handoff and nothing else.** Its ceiling is 12 KB.\n\n"
        if markers:
            body += sap.BANNER_OPEN + "\nold banner\n" + sap.BANNER_CLOSE + "\n"
        body += "\n## Body that must survive\n"
        p = self.root / name
        p.write_text(body, encoding="utf-8")
        return p

    def test_only_the_marked_block_is_replaced(self):
        """Mutant: go back to lines[2:] ⇒ the purpose note is eaten."""
        paths = [self.doc(n) for n in sap.BANNER_FILES]
        sap.rewrite_banners("> **NEW**")
        for p in paths:
            text = p.read_text(encoding="utf-8")
            self.assertIn("> **NEW**", text)
            self.assertNotIn("old banner", text)
            self.assertIn("This file is the live handoff", text)
            self.assertIn("## Body that must survive", text)

    def test_a_file_without_markers_refuses_by_name(self):
        """Mutant: fall back to line 3 when the markers are absent ⇒ green, and the tool is back to
        overwriting whatever happens to be there."""
        self.doc(sap.BANNER_FILES[0])
        self.doc(sap.BANNER_FILES[1], markers=False)
        self.doc(sap.BANNER_FILES[2])
        with self.assertRaises(SystemExit) as cm:
            sap.rewrite_banners("> **NEW**")
        self.assertIn(sap.BANNER_FILES[1], str(cm.exception))

    def test_a_refusal_leaves_EVERY_file_untouched(self):
        """THE REAL DEFECT, as a test: the refusal came after the first file was already written.
        Mutant: write each file as it is validated ⇒ the first document is rewritten."""
        first = self.doc(sap.BANNER_FILES[0])
        self.doc(sap.BANNER_FILES[1], markers=False)
        self.doc(sap.BANNER_FILES[2])
        before = first.read_text(encoding="utf-8")
        with self.assertRaises(SystemExit):
            sap.rewrite_banners("> **NEW**")
        self.assertEqual(first.read_text(encoding="utf-8"), before)

    def test_a_second_run_does_not_accumulate(self):
        """The bug the line-counting version was written to fix must stay fixed: two runs leave one
        banner, not a fresh first line above a stale tail."""
        paths = [self.doc(n) for n in sap.BANNER_FILES]
        sap.rewrite_banners("> **ONE**")
        sap.rewrite_banners("> **TWO**")
        for p in paths:
            text = p.read_text(encoding="utf-8")
            self.assertNotIn("> **ONE**", text)
            self.assertEqual(text.count(sap.BANNER_OPEN), 1)


class AuditPositionTests(unittest.TestCase):
    """The verdict in the banner is READ, not typed.

    It was a hard-coded paragraph naming the FOURTH round while the standing verdict was the
    NINTH — five rounds stale in the one generator that writes three canonical documents at once,
    under a comment instructing whoever changed the verdict to edit it. Five rounds went by.
    """

    def test_the_real_repository_names_the_round_the_ledger_announces(self):
        import check_audit_reports as audit
        sentence = sap.audit_position_sentence()
        ordinal = audit.ordinal_of((sap.ROOT / audit.LEDGER).read_text(encoding="utf-8"))
        self.assertIn(ordinal.upper(), sentence)
        self.assertIn(audit.state_audit_pointer(
            (sap.ROOT / "config" / "current_state.json").read_text(encoding="utf-8")), sentence)

    def test_a_state_file_with_no_audit_record_refuses(self):
        """Mutant: return a sentence anyway ⇒ the banner states a verdict from nowhere, in three
        canonical files at once, which is this file's whole history."""
        import tempfile
        root = pathlib.Path(tempfile.mkdtemp())
        (root / "config").mkdir()
        (root / "config" / "current_state.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            sap.audit_position_sentence(root)
        self.assertIn("names no last-independent-audit report", str(cm.exception))

    def test_a_record_pointing_at_a_report_that_is_not_filed_refuses(self):
        import tempfile, json as _json
        root = pathlib.Path(tempfile.mkdtemp())
        (root / "config").mkdir()
        (root / "config" / "current_state.json").write_text(_json.dumps(
            {"code_audit": {"last_independent_audit": "apps/desktop/AUDIT/never-filed.md"}}),
            encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            sap.audit_position_sentence(root)
        self.assertIn("which does not exist", str(cm.exception))

    def test_a_ledger_announcing_no_round_refuses(self):
        """The pointer alone is not the position: a report can be filed and the ledger still lead
        with nothing, and a banner that names a file but no round tells a cold reader less than
        silence would."""
        import tempfile, json as _json, check_audit_reports as audit
        root = pathlib.Path(tempfile.mkdtemp())
        (root / "config").mkdir()
        (root / audit.AUDIT_DIR).mkdir(parents=True)
        (root / audit.AUDIT_DIR / "r.md").write_text("x", encoding="utf-8")
        (root / audit.LEDGER).write_text("# Ledger with no round announced\n", encoding="utf-8")
        (root / "config" / "current_state.json").write_text(_json.dumps(
            {"code_audit": {"last_independent_audit": f"{audit.AUDIT_DIR}/r.md"}}), encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            sap.audit_position_sentence(root)
        self.assertIn("announces no round", str(cm.exception))


class NoteSurgeryTests(_StateFile):
    """The note is replaced by scanning its own string, not by finding the end of the block.

    The old slice ran from `"note": "` to the block's closing `"\\n  },`, so it was correct only
    while `note` was the last key. On 2026-08-30 `base` sat after it and a settle refused — the
    shape guard doing its job, and the tool unable to do its own. `json.loads` cannot catch this
    alone: deleting whole key/value pairs leaves valid JSON (A-10, fifth audit).
    """

    def block(self, note_last: bool):
        keys = {"number": 180, "branch": "b", "state": "open", "note": "old note"}
        if not note_last:
            keys["base"] = "main"
        self.write({"schema": 2, "prs": [], "sync": {"baseline_main_head_at_sync": "a" * 40,
                                                     "snapshot_branch": "b"},
                    "active": {"branch": "b"}, "settled_at_main_head": "a" * 40,
                    "current_workflow_pr": keys})

    def test_a_key_after_note_is_not_swallowed(self):
        """Mutant: go back to text.index('"\\n  },', start) ⇒ `base` disappears, or the shape
        guard refuses and the settle cannot run at all. Both were reachable; this is which."""
        self.block(note_last=False)
        sap.rewrite_state(181, "settle", "the new note", "c" * 40)
        after = self.read()["current_workflow_pr"]
        self.assertEqual(after["base"], "main")
        self.assertEqual(after["note"], "the new note")
        self.assertEqual(after["number"], 181)

    def test_note_last_still_works(self):
        self.block(note_last=True)
        sap.rewrite_state(181, "settle", "the new note", "c" * 40)
        self.assertEqual(self.read()["current_workflow_pr"]["note"], "the new note")

    def test_an_escaped_quote_in_the_old_note_does_not_end_the_scan(self):
        """A note is prose written by a session; it will contain a quotation eventually."""
        self.write({"schema": 2, "prs": [], "sync": {"baseline_main_head_at_sync": "a" * 40,
                                                     "snapshot_branch": "b"},
                    "active": {"branch": "b"}, "settled_at_main_head": "a" * 40,
                    "current_workflow_pr": {"number": 180, "branch": "b", "state": "open",
                                            "note": 'it said "green" and it was not',
                                            "base": "main"}})
        sap.rewrite_state(181, "settle", "the new note", "c" * 40)
        after = self.read()["current_workflow_pr"]
        self.assertEqual(after["note"], "the new note")
        self.assertEqual(after["base"], "main")


class SettledHeadTests(unittest.TestCase):
    """The generator must compute `settled_at_main_head` the way its VERIFIER does.

    `check_repo_state.verify_settled_snapshot` pins the field to the FIRST PARENT of the carrier's
    merge commit -- "the main that carrier #N merged into". `--settled` wrote the live main head,
    which is the same commit only while the carrier is still open. Run the documented ritual in the
    documented order -- merge, pull, settle -- and the tool produced a snapshot its own gate
    refused, naming the merge commit where the pin wanted that commit's parent. Observed
    2026-08-17, on the settle of PR #138.

    This is the SECOND disagreement between a generator and a gate over this one field; the first
    was the unsatisfiable floor the fifth audit's A-07 fix shipped. Both are pinned here, because a
    generator that can emit a state its verifier rejects teaches whoever hits it that the gate is
    noise.
    """

    HEAD = "a" * 40
    PARENT = "b" * 40

    def _patch(self, merge_commit, parent=None):
        self.addCleanup(setattr, sap, "carrier_merge_commit", sap.carrier_merge_commit)
        sap.carrier_merge_commit = lambda number: merge_commit
        if parent is not None:
            import subprocess
            real = subprocess.run
            self.addCleanup(setattr, subprocess, "run", real)

            class _Out:
                stdout = parent
            subprocess.run = lambda *a, **k: _Out()

    def test_a_merged_carrier_settles_at_the_parent_of_its_merge_commit(self):
        # THE DEFECT, as a test. The gate wants the main the carrier merged INTO.
        self._patch(self.HEAD, self.PARENT)
        self.assertEqual(sap.settled_head_for(self.HEAD, 138), self.PARENT)

    def test_an_open_carrier_settles_at_the_live_main_head(self):
        # Nothing has merged, so the field means exactly what it used to.
        self._patch(None)
        self.assertEqual(sap.settled_head_for(self.HEAD, 138), self.HEAD)

    def test_a_carrier_that_merged_somewhere_else_does_not_move_the_field(self):
        # Settling at a head the carrier did not produce: the parent of THIS head says nothing
        # about that carrier, so guessing would be worse than leaving the live head.
        self._patch("c" * 40)
        self.assertEqual(sap.settled_head_for(self.HEAD, 138), self.HEAD)

    def test_no_carrier_at_all_settles_at_the_live_main_head(self):
        self.assertEqual(sap.settled_head_for(self.HEAD, None), self.HEAD)

    def test_an_unreadable_gh_fails_SOFT_rather_than_refusing_the_settle(self):
        # Deliberate asymmetry with parked_roles(), which refuses. This helper only avoids MOVING a
        # field that is already right; a gh outage must not turn a settle into a refusal, and the
        # gate downstream still fails closed if the value is wrong.
        self._patch(None)
        self.assertEqual(sap.settled_head_for(self.HEAD, 138), self.HEAD)


if __name__ == "__main__":
    unittest.main()
