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
import subprocess
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


class ProjectStateDateTests(unittest.TestCase):
    """This tool edits a DATED file, so it moves the date — the omission that reddened `main`.

    Measured on 2026-09-21. `rewrite_banners` had written PROJECT_STATE.md on every run since it was
    written and had never touched its `**Last updated:**` line. `check_coordination`'s rule is not a
    calendar comparison — it refuses when the newest commit that touched the file left that line at
    its parent's value, which is the Startup Law — so every pull request had been passing on luck: the
    line's date happened to equal the merge commit's date. The squash that merged `#282` was committed
    at 00:06 local on the 21st while the line said the 20th, and `main` went red on two jobs AFTER the
    merge, where the only fix is another merge.
    """

    def setUp(self):
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = pathlib.Path(self._dir.name)
        self._real_root = sap.ROOT
        sap.ROOT = self.root
        self.addCleanup(lambda: setattr(sap, "ROOT", self._real_root))
        self.state = self.root / "PROJECT_STATE.md"

    def write(self, line: str) -> None:
        self.state.write_text(
            "# PROJECT_STATE\n\n" + line + "\nsecond line of the same paragraph.\n\n"
            + sap.BANNER_OPEN + "\nold banner\n" + sap.BANNER_CLOSE + "\n\n## Body\n",
            encoding="utf-8")

    def other_banner_files(self) -> None:
        for name in sap.BANNER_FILES:
            if name == "PROJECT_STATE.md":
                continue
            (self.root / name).write_text(
                "# T\n\n" + sap.BANNER_OPEN + "\nold\n" + sap.BANNER_CLOSE + "\n", encoding="utf-8")

    def test_the_date_moves_to_the_day_it_is_run(self):
        import datetime as dt
        self.write("**Last updated · Վերջին թարմացում:** 2026-09-20 — 49 merged, `main` at `2045830`.")
        moved = sap.refresh_project_state_date(dt.date(2026, 9, 21))
        self.assertEqual(moved, "2026-09-21")
        self.assertIn("2026-09-21 — 49 merged", self.state.read_text(encoding="utf-8"))

    def test_only_the_date_is_replaced(self):
        """The prose after the date is the state's own summary, and the label is bilingual. A tool
        that rewrote the line rather than the date would delete both."""
        import datetime as dt
        self.write("**Last updated · Վերջին թարմացում:** 2026-09-20 — 49 merged, `main` at `2045830`.")
        sap.refresh_project_state_date(dt.date(2026, 9, 21))
        text = self.state.read_text(encoding="utf-8")
        self.assertIn("**Last updated · Վերջին թարմացում:**", text)
        self.assertIn("49 merged, `main` at `2045830`.", text)
        self.assertIn("second line of the same paragraph.", text)
        self.assertIn("## Body", text)
        self.assertNotIn("2026-09-20", text)

    def test_the_SAME_date_further_down_the_document_is_not_touched(self):
        """Only the one date in the `Last updated` line moves — by OFFSET, not by string replacement.

        This is the real file's shape: the paragraph that opens with today's date closes with
        `Before: <yesterday>`, and after a run those two are one day apart. The day a run happens to
        follow a state whose `Before:` names the same date, a `text.replace(old, new)` would silently
        rewrite the history too, and the document would claim a previous state it never had.
        """
        import datetime as dt
        self.state.write_text(
            "# PROJECT_STATE\n\n"
            "**Last updated:** 2026-09-20 — 49 merged.\n"
            "Before: 2026-09-20 — `main` at `2045830`, a state this line must keep naming.\n\n"
            + sap.BANNER_OPEN + "\nold\n" + sap.BANNER_CLOSE + "\n", encoding="utf-8")
        sap.refresh_project_state_date(dt.date(2026, 9, 21))
        text = self.state.read_text(encoding="utf-8")
        self.assertIn("**Last updated:** 2026-09-21 — 49 merged.", text)
        self.assertIn("Before: 2026-09-20 — `main` at `2045830`", text)

    def test_a_second_run_on_the_same_day_changes_nothing(self):
        import datetime as dt
        self.write("**Last updated:** 2026-09-21 — already today.")
        before = self.state.read_bytes()
        self.assertIsNone(sap.refresh_project_state_date(dt.date(2026, 9, 21)))
        self.assertEqual(self.state.read_bytes(), before)

    def test_a_missing_line_is_left_to_the_gate_to_report(self):
        """No line ⇒ no invention. `check_coordination` reports the absence by name; a tool that
        added one here would manufacture the very claim the gate exists to check."""
        import datetime as dt
        self.write("**Not the line at all:** nothing here.")
        before = self.state.read_bytes()
        self.assertIsNone(sap.refresh_project_state_date(dt.date(2026, 9, 21)))
        self.assertEqual(self.state.read_bytes(), before)

    def test_a_line_carrying_no_iso_date_is_left_alone(self):
        import datetime as dt
        self.write("**Last updated:** recently, honestly.")
        before = self.state.read_bytes()
        self.assertIsNone(sap.refresh_project_state_date(dt.date(2026, 9, 21)))
        self.assertEqual(self.state.read_bytes(), before)

    def test_rewriting_the_banners_moves_the_date_BY_CONSTRUCTION(self):
        """The property, not the habit: the date moves because `rewrite_banners` does it, so a third
        call site cannot be written that forgets. Mutant: move the call out to the two call sites in
        `main()` ⇒ this fails while both of those still pass."""
        import datetime as dt
        self.write("**Last updated:** 2020-01-01 — stale by years.")
        self.other_banner_files()
        moved = sap.rewrite_banners("> **NEW**")
        today = dt.date.today().isoformat()
        self.assertEqual(moved, today)
        text = self.state.read_text(encoding="utf-8")
        self.assertIn(today, text)
        self.assertIn("> **NEW**", text)
        self.assertNotIn("2020-01-01", text)

    def test_the_stamp_is_the_LOCAL_date_because_that_is_what_git_records(self):
        """The bug this fix shipped with for one run, pinned.

        The first version stamped `datetime.now(timezone.utc).date()`. On this `UTC+04:00` box at 00:30
        local that is YESTERDAY, so the tool moved the line BACKWARDS and `check_coordination` — which
        reads the commit's date as `%cs`, in the committer's own recorded timezone — went red on the
        very thing the fix was for. Both sides have to be read off one clock.

        A test that asserts nothing where UTC and local agree is not a weakness of the test: the two
        differ for four hours of every day on this box, which is when the merges actually land.
        """
        import datetime as dt
        self.write("**Last updated:** 2020-01-01 — stale.")
        self.assertEqual(sap.refresh_project_state_date(), dt.date.today().isoformat())
        source = (pathlib.Path(sap.__file__)).read_text(encoding="utf-8")
        self.assertIn("today = today or dt.date.today()", source)
        self.assertNotIn("today or dt.datetime.now(dt.timezone.utc).date()", source)

    def test_the_readers_are_IMPORTED_from_the_gate_not_re_spelled(self):
        """Imported, not re-spelled. Two regexes for one line is how the tool comes to write
        something the gate does not read back.

        Asserted over the SOURCE TEXT, and not with `assertIs` against the gate's objects, because
        `re.compile` keeps an internal cache keyed by pattern and flags: a local `re.compile` of the
        same pattern returns the very same object, so identity passes for a copy. That mutant
        survived the identity version of this test, which is the whole reason it reads the source.
        """
        source = (pathlib.Path(sap.__file__)).read_text(encoding="utf-8")
        self.assertIn("from check_coordination import _ISO_DATE_RE, _LAST_UPDATED_RE", source)
        for name in ("_LAST_UPDATED_RE", "_ISO_DATE_RE"):
            self.assertNotIn(
                name + " = re.compile", source,
                "sync_active_pr.py compiles its own %s; it must use the gate's" % name)


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


class CarrierProseTests(_StateFile):
    """`what` and `next_action_by_carrier.current` move with the carrier, or the tool refuses.

    On 2026-09-19 (#220) rewrite_state moved number, branch and note from #219 to #220 and left
    `what` reading "T-020 built under the Architect's five rulings ... NOT Architect-approved";
    rewrite_carrier_block rewrote `_note` and left `current` saying "PR #219 ... the next step is the
    ARCHITECT's audit, not a merge" a day after #219 merged. No gate reads either field, so both
    stayed wrong until a reader noticed. These pin the two behaviours that make that impossible.
    """

    def state(self, number=219, with_what=True, with_current=True):
        block = {"number": number, "branch": "feat/floor-writer-service", "state": "open"}
        if with_what:
            block["what"] = "T-020 built under the Architect's five rulings."
        block["note"] = "old note"
        block["base"] = "main"
        obj = {"schema": 2, "prs": [], "sync": {"baseline_main_head_at_sync": "a" * 40,
                                                "snapshot_branch": "feat/floor-writer-service"},
               "active": {"branch": "feat/floor-writer-service"}, "settled_at_main_head": "a" * 40,
               "current_workflow_pr": block,
               "next_action_by_carrier": ({"current": "PR #219: not a merge on the Builder's word.",
                                           "_note": "old"} if with_current else {"_note": "old"})}
        self.write(obj)

    def test_moving_the_number_without_what_refuses_and_writes_nothing(self):
        """Mutant: drop the refusal ⇒ number becomes 220 while `what` still says T-020."""
        self.state()
        before = self.path.read_text(encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            sap.rewrite_state(220, "fix/supply-chain-browserslist", "new note", "c" * 40)
        self.assertIn("--what", str(cm.exception))
        self.assertIn("#219", str(cm.exception))
        self.assertEqual(before, self.path.read_text(encoding="utf-8"), "a refusal writes nothing")

    def test_what_moves_with_the_number(self):
        """Mutant: skip the `what` surgery ⇒ the assertion on `what` fails."""
        self.state()
        changed = sap.rewrite_state(220, "fix/supply-chain-browserslist", "new note", "c" * 40,
                                    what="T-065: two lockfiles lifted, no source change.")
        after = self.read()["current_workflow_pr"]
        self.assertEqual(after["number"], 220)
        self.assertEqual(after["what"], "T-065: two lockfiles lifted, no source change.")
        self.assertEqual(after["note"], "new note")
        self.assertEqual(after["base"], "main", "the shape is untouched")
        self.assertIn("what", changed)

    def test_the_same_number_needs_no_what(self):
        self.state()
        sap.rewrite_state(219, "feat/floor-writer-service", "new note", "c" * 40)
        self.assertEqual(self.read()["current_workflow_pr"]["what"],
                         "T-020 built under the Architect's five rulings.")

    def test_a_block_without_what_is_not_given_one(self):
        self.state(with_what=False)
        sap.rewrite_state(220, "b", "new note", "c" * 40, what="ignored: no such key")
        self.assertNotIn("what", self.read()["current_workflow_pr"])

    def test_current_moves_with_the_carrier(self):
        """Mutant: drop `replaced["current"]` ⇒ `current` still names #219."""
        self.state()
        sap.rewrite_carrier_block(220, "fix/supply-chain-browserslist",
                                  current="PR #220 (fix/supply-chain-browserslist): T-065. Next: merge.")
        block = self.read()["next_action_by_carrier"]
        self.assertEqual(block["current"],
                         "PR #220 (fix/supply-chain-browserslist): T-065. Next: merge.")
        self.assertIn("#220", block["_note"])

    def test_a_block_without_current_is_not_given_one(self):
        self.state(with_current=False)
        sap.rewrite_carrier_block(220, "b", current="would be a new key")
        self.assertNotIn("current", self.read()["next_action_by_carrier"])


class RestRoadSlugTests(unittest.TestCase):
    """`_rest_open_prs` asks about THIS repository, established by `_repo_slug()`, never a literal.

    Eighth audit `H-05`, one file over: check_repo_state.py's REST fallback said `menqstudio/OS`
    while its GraphQL road inferred the slug from the remote, so a fork's two roads answered about
    different repositories. That was fixed there on 2026-08-18; this file kept the literal.
    """

    def setUp(self):
        self._real = (sap._repo_slug, sap.subprocess.run)
        self.addCleanup(lambda: setattr(sap, "_repo_slug", self._real[0]))
        self.addCleanup(lambda: setattr(sap.subprocess, "run", self._real[1]))

    def test_the_road_is_built_from_the_resolved_slug(self):
        """Mutant: the literal back ⇒ the URL names menqstudio/OS, not the fork."""
        seen = []

        page = json.dumps([{"number": 7, "head": {"ref": "b", "sha": "c" * 40},
                            "base": {"ref": "main"}, "draft": False, "title": "t"}])

        def fake_run(args, **kwargs):
            seen.append(args)
            return subprocess.CompletedProcess(args, 0, page + "\n", "")
        sap._repo_slug = lambda: "someone/fork"
        sap.subprocess.run = fake_run
        rows = sap._rest_open_prs()
        self.assertEqual([r["number"] for r in rows], [7])
        self.assertIn("repos/someone/fork/pulls?state=open&per_page=100", seen[0])
        self.assertFalse(any("menqstudio/OS" in a for a in seen[0]))

    def test_no_slug_means_no_read_and_no_gh_call(self):
        calls = []
        sap._repo_slug = lambda: None
        sap.subprocess.run = lambda *a, **k: calls.append(a) or None
        self.assertIsNone(sap._rest_open_prs())
        self.assertEqual(calls, [], "a road that cannot name its repository must not ask")


class ActiveLineTests(unittest.TestCase):
    """NEXT_CHAT.md's `**Active branch:**` line moves with the carrier, or is left alone by name.

    It sits outside the banner markers and was maintained by hand; on 2026-09-19 it named #220's
    branch and a `main` two merges old under a banner that named #221.
    """

    LINE = ("**Active branch:** `fix/supply-chain-browserslist` — `main` @ `2a50081`. A handoff "
            "names the merge base or `main`; a branch commit is a dead object after a squash. "
            "· **task** `floor-writer`\n")

    def setUp(self):
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = pathlib.Path(self._dir.name)
        self._real_root = sap.ROOT
        sap.ROOT = self.root
        self.addCleanup(lambda: setattr(sap, "ROOT", self._real_root))

    def doc(self, with_line=True):
        p = self.root / "NEXT_CHAT.md"
        p.write_text("# NEXT_CHAT\n\n" + (self.LINE if with_line else "") + sap.BANNER_OPEN
                     + "\nbanner\n" + sap.BANNER_CLOSE + "\n\n## Body\n", encoding="utf-8")
        return p

    def test_branch_and_head_move_and_the_tail_is_kept(self):
        """Mutant: skip the substitution ⇒ the old branch is still on the line."""
        p = self.doc()
        self.assertTrue(sap.rewrite_active_line("tools/utf8-decode-and-carrier-prose", "157e292e" + "f" * 32))
        text = p.read_text(encoding="utf-8")
        self.assertIn("**Active branch:** `tools/utf8-decode-and-carrier-prose` — `main` @ `157e292`.", text)
        self.assertNotIn("fix/supply-chain-browserslist", text)
        self.assertIn("a branch commit is a dead object after a squash. · **task** `floor-writer`", text)
        self.assertEqual(text.count("**Active branch:**"), 1)

    def test_a_file_without_the_line_is_left_byte_identical(self):
        p = self.doc(with_line=False)
        before = p.read_text(encoding="utf-8")
        self.assertFalse(sap.rewrite_active_line("b", "c" * 40))
        self.assertEqual(before, p.read_text(encoding="utf-8"))


class MainCiReadingTests(_StateFile):
    """`main_ci` is written from a reading, never typed.

    Until 2026-09-19 it was the last hand-maintained field in config/current_state.json, and on
    that day it still said `success` at 87bfe73 while `main` had been red at 2a50081 for a day —
    nobody had taken the reading. The generator now takes it the way the gate reads it
    (`check_repo_state._live_main_ci`) and refuses to write anything when it cannot.
    """

    def state(self, with_block=True):
        obj = {"schema": 2, "prs": [], "sync": {"baseline_main_head_at_sync": "a" * 40,
                                                "snapshot_branch": "b"},
               "active": {"branch": "b"}, "settled_at_main_head": "a" * 40,
               "current_workflow_pr": {"number": 1, "branch": "b", "state": "open",
                                       "note": "n", "base": "main"}}
        if with_block:
            obj["main_ci"] = {"_note": "what main's own runs said",
                              "ci": {"head": "a" * 40, "conclusion": "success", "run_id": 1,
                                     "note": "typed by hand"}}
        self.write(obj)

    READING_RED = {"ci": {"head": "b" * 40, "conclusion": "failure", "run_id": 77,
                          "failing": ["Repo-state · live GitHub truth verifier"]}}

    def test_the_reading_is_written_and_the_shape_is_kept(self):
        """Mutant: skip the `head` value ⇒ the head assertion fails."""
        self.state()
        written = sap.rewrite_main_ci(self.READING_RED, today=__import__("datetime").date(2026, 9, 19))
        self.assertEqual(written, ["ci"])
        block = self.read()["main_ci"]
        self.assertEqual(block["_note"], "what main's own runs said", "siblings untouched")
        ci = block["ci"]
        self.assertEqual(ci["head"], "b" * 40)
        self.assertEqual(ci["conclusion"], "failure")
        self.assertEqual(ci["run_id"], 77)
        self.assertIn("2026-09-19", ci["note"])
        self.assertIn("failure at bbbbbbb, run 77", ci["note"])
        self.assertIn("Repo-state · live GitHub truth verifier", ci["note"])
        self.assertEqual(set(ci), {"head", "conclusion", "run_id", "note"})

    def test_a_success_note_names_no_failing_job(self):
        note = sap.main_ci_note("success", "c" * 40, 5, [], __import__("datetime").date(2026, 9, 19))
        self.assertIn("success at ccccccc, run 5", note)
        self.assertNotIn("Not green", note)

    def test_a_red_reading_with_unlisted_jobs_says_so(self):
        note = sap.main_ci_note("failure", "c" * 40, 5, [], __import__("datetime").date(2026, 9, 19))
        self.assertIn("could not be listed", note)

    def test_a_file_without_main_ci_is_left_byte_identical(self):
        self.state(with_block=False)
        before = self.path.read_text(encoding="utf-8")
        self.assertEqual(sap.rewrite_main_ci(self.READING_RED), [])
        self.assertEqual(before, self.path.read_text(encoding="utf-8"))

    def test_a_workflow_the_file_does_not_model_is_not_added(self):
        self.state()
        sap.rewrite_main_ci({"extra": {"head": "b" * 40, "conclusion": "success", "run_id": 2,
                                       "failing": []}})
        self.assertEqual(set(self.read()["main_ci"]), {"_note", "ci"})

    def test_the_reading_comes_from_the_gate_reader_and_lists_jobs_only_when_red(self):
        """Mutant: read a different endpoint than the gate ⇒ the fake reader is never called."""
        calls = []
        real = (sap._repo_slug, sap._live_main_ci, sap._failing_jobs)
        sap._repo_slug = lambda: "o/r"
        sap._live_main_ci = lambda slug: calls.append(slug) or {"ci": [("c" * 40, "failure", 9),
                                                                       ("d" * 40, "success", 8)]}
        sap._failing_jobs = lambda slug, run_id: ["Coordination · docs consistency gate"]
        try:
            reading = sap.take_main_ci_reading()
        finally:
            sap._repo_slug, sap._live_main_ci, sap._failing_jobs = real
        self.assertEqual(calls, ["o/r"])
        self.assertEqual(reading, {"ci": {"head": "c" * 40, "conclusion": "failure", "run_id": 9,
                                          "failing": ["Coordination · docs consistency gate"]}})

    def test_an_unreadable_main_refuses_rather_than_asserting(self):
        with self.assertRaises(SystemExit) as cm:
            sap._refuse_without_main_ci(None)
        self.assertIn("nothing has been written", str(cm.exception))


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
        """Deliberate asymmetry with parked_roles(), which refuses. This helper only avoids
        MOVING a field that is already right; a gh outage must not turn a settle into a
        refusal, and the gate downstream still fails closed if the value is wrong.

        Driven through the REAL `carrier_merge_commit`, with `gh` itself failing. This test
        used to be byte-for-byte the open-carrier test above -- `_patch(None)` and the same
        assertion -- so it replaced the function under test with a lambda and the three
        fail-soft arms inside it (non-zero exit, unparseable JSON, an oid that is not 40 hex)
        were run by nothing.
        """
        for label, completed in self.GH_FAILURES:
            with self.subTest(gh=label):
                self._gh(completed)
                self.assertIsNone(sap.carrier_merge_commit(138))
                self.assertEqual(sap.settled_head_for(self.HEAD, 138), self.HEAD)

    GH_FAILURES = (
        # A failing `gh` that still printed a well-formed answer is not believed either.
        ("non-zero exit", subprocess.CompletedProcess(
            [], 1, json.dumps({"mergeCommit": {"oid": "a" * 40}}), "GraphQL: outage")),
        ("not JSON", subprocess.CompletedProcess([], 0, "<html>502</html>", "")),
        ("empty output", subprocess.CompletedProcess([], 0, "", "")),
        ("no merge commit", subprocess.CompletedProcess([], 0, '{"mergeCommit": null}', "")),
        ("short oid", subprocess.CompletedProcess([], 0, '{"mergeCommit": {"oid": "abc123"}}', "")),
        ("non-hex oid", subprocess.CompletedProcess(
            [], 0, json.dumps({"mergeCommit": {"oid": "z" * 40}}), "")),
    )

    def _gh(self, completed):
        real = sap.subprocess.run
        self.addCleanup(setattr, sap.subprocess, "run", real)
        sap.subprocess.run = lambda *a, **k: completed

    def test_a_readable_merge_commit_is_returned_as_it_is(self):
        """The control for the six failures above: the same road, answering."""
        self._gh(subprocess.CompletedProcess(
            [], 0, json.dumps({"mergeCommit": {"oid": self.HEAD}}), ""))
        self.assertEqual(sap.carrier_merge_commit(138), self.HEAD)


class _Repository(unittest.TestCase):
    """A whole throwaway repository for the two entry points: the mirror, the three banner
    documents, and every network read replaced by a value. `main()` and `settle()` had no test
    at all, which is how the ORDER of their steps went unexamined."""

    HEAD = "f" * 40
    PARENT = "e" * 40
    OLD = "a" * 40

    def setUp(self):
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = pathlib.Path(self._dir.name)
        (self.root / "config").mkdir()
        self.state = self.root / "config" / "current_state.json"
        self.state.write_text(json.dumps({
            "schema": 2,
            "settled_at_main_head": self.OLD,
            "sync": {"baseline_main_head_at_sync": self.OLD, "snapshot_branch": "feat/old"},
            "active": {"branch": "feat/old"},
            "prs": [],
            "current_workflow_pr": {"number": 300, "branch": "feat/old", "state": "open",
                                    "what": "the old carrier", "note": "old note", "base": "main"},
            "next_action_by_carrier": {"current": "PR #300", "_note": "old", "open": "o",
                                       "merged": "m"},
        }, indent=2), encoding="utf-8")
        for name in sap.BANNER_FILES:
            (self.root / name).write_text(
                "# " + name + "\n\n" + sap.BANNER_OPEN + "\nold banner\n" + sap.BANNER_CLOSE
                + "\n\n## Body\n", encoding="utf-8")
        self.merge_commit = None
        for name, value in (
            ("ROOT", self.root), ("STATE", self.state),
            ("live_main_head", lambda: self.HEAD),
            ("take_main_ci_reading", lambda: {}),
            ("live_open_prs", lambda: []),
            ("carrier_merge_commit", lambda number: self.merge_commit),
        ):
            self.addCleanup(setattr, sap, name, getattr(sap, name))
            setattr(sap, name, value)

    def snapshot(self) -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in [self.state] + [self.root / n for n in sap.BANNER_FILES]}

    def mirror(self) -> dict:
        return json.loads(self.state.read_text(encoding="utf-8"))

    def run_quietly(self, fn, *args, **kwargs):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return fn(*args, **kwargs)

    def refuse(self, name: str, message: str):
        def refusing(*a, **k):
            raise SystemExit("RED: " + message + ". Nothing has been written.")
        self.addCleanup(setattr, sap, name, getattr(sap, name))
        setattr(sap, name, refusing)

    def assertRefusesAndWritesNothing(self, fn, *args, needle: str = "Nothing has been written"):
        """`fn` refuses, and the mirror and the three documents are byte-identical after."""
        before = self.snapshot()
        with self.assertRaises(SystemExit) as caught:
            self.run_quietly(fn, *args)
        self.assertIn(needle, str(caught.exception))
        self.assertEqual(self.snapshot(), before,
                         "the tool refused, said nothing was written, and something was")


class ARefusalWritesNothing_Sync(_Repository):
    """`--pr N --branch B --summary S`. Each of these refusals ends "Nothing has been written"
    and each fired AFTER `config/current_state.json` had been rewritten."""

    ARGS = ["--pr", "301", "--branch", "feat/new", "--what", "the new carrier"]

    def sync(self, summary: str = "One line on what this PR does."):
        return sap.main(self.ARGS + ["--summary", summary])

    def sync_unguarded(self, summary: str = "One line on what this PR does."):
        """`main` WITHOUT the restore-on-refusal guard, so what these tests show is the ORDER:
        the refusal came before any write, rather than a write that was then put back."""
        return sap.main.__wrapped__(self.ARGS + ["--summary", summary])

    def test_the_control_a_good_run_moves_the_mirror_and_all_three_banners(self):
        self.assertEqual(self.run_quietly(self.sync), 0)
        mirror = self.mirror()
        self.assertEqual(mirror["current_workflow_pr"]["number"], 301)
        self.assertEqual(mirror["current_workflow_pr"]["what"], "the new carrier")
        self.assertEqual(mirror["active"]["branch"], "feat/new")
        self.assertEqual(mirror["sync"]["baseline_main_head_at_sync"], self.HEAD)
        for name in sap.BANNER_FILES:
            text = (self.root / name).read_text(encoding="utf-8")
            self.assertIn("CURRENT ACTIVE: PR #301", text)
            self.assertNotIn("old banner", text)
            self.assertIn("## Body", text)

    def test_a_banner_over_its_ceiling_refuses_before_the_mirror_moves(self):
        """The reproduction in the finding: a 1500-character --summary."""
        self.assertRefusesAndWritesNothing(self.sync_unguarded, "x" * 1500)

    def test_an_unreadable_audit_position_refuses_before_the_mirror_moves(self):
        self.refuse("audit_position_sentence", "the audit ledger announces no round")
        self.assertRefusesAndWritesNothing(self.sync_unguarded)

    def test_an_unlistable_set_of_open_prs_refuses_before_the_mirror_moves(self):
        self.refuse("live_open_prs", "`gh pr list` failed AND the REST fallback failed")
        self.assertRefusesAndWritesNothing(self.sync_unguarded)

    def test_a_document_without_banner_markers_refuses_before_the_mirror_moves(self):
        (self.root / "TASKS.md").write_text("# TASKS\n\nno markers here\n", encoding="utf-8")
        self.assertRefusesAndWritesNothing(self.sync_unguarded, needle="TASKS.md carries no")

    def test_a_writer_that_refuses_midway_leaves_the_mirror_as_it_found_it(self):
        """rewrite_state has already written by the time rewrite_main_ci can refuse. The
        sentence is made true by putting the mirror's bytes back, not by rewording it."""
        self.refuse("rewrite_main_ci", "rewriting main_ci changed its SHAPE")
        self.assertRefusesAndWritesNothing(self.sync)


class ARefusalWritesNothing_Settle(_Repository):
    """`--settled`, with and without the pull request that records it."""

    def settle(self, next_up=None, pr=302, branch="chore/settle"):
        return sap.settle(self.HEAD, next_up, pr, branch)

    def settle_unguarded(self, next_up=None, pr=302, branch="chore/settle"):
        """`settle` WITHOUT the restore-on-refusal guard: these show the ORDER of its steps."""
        return sap.settle.__wrapped__(self.HEAD, next_up, pr, branch)

    def test_a_banner_over_its_ceiling_refuses_before_the_mirror_moves(self):
        self.assertRefusesAndWritesNothing(self.settle_unguarded, "x" * 1500)

    def test_an_unreadable_audit_position_refuses_before_the_mirror_moves(self):
        self.refuse("audit_position_sentence", "config/current_state.json names no report")
        self.assertRefusesAndWritesNothing(self.settle_unguarded)

    def test_a_document_without_banner_markers_refuses_before_the_mirror_moves(self):
        (self.root / "NEXT_CHAT.md").write_text("# NEXT\n", encoding="utf-8")
        self.assertRefusesAndWritesNothing(self.settle_unguarded, needle="NEXT_CHAT.md carries no")

    def test_a_writer_that_refuses_midway_leaves_the_mirror_as_it_found_it(self):
        """settle() writes `settled_at_main_head` itself and THEN calls the writers; a refusal
        from any of them used to leave that first write behind."""
        self.refuse("rewrite_carrier_block", "the carrier block could not be rewritten")
        self.assertRefusesAndWritesNothing(self.settle)


class SettleWritesOneAnswer(_Repository):
    """settle() computed three values that rewrite_state() then overwrote in the same run."""

    def settle(self, pr=302, branch="chore/settle"):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            sap.settle(self.HEAD, None, pr, branch)
        return out.getvalue()

    def test_with_its_own_pull_request_the_branch_fields_name_that_branch(self):
        said = self.settle()
        mirror = self.mirror()
        self.assertEqual(mirror["active"]["branch"], "chore/settle")
        self.assertEqual(mirror["sync"]["snapshot_branch"], "chore/settle")
        self.assertEqual(mirror["current_workflow_pr"]["number"], 302)
        self.assertEqual(mirror["settled_at_main_head"], self.HEAD)
        # ... and the closing line says so, instead of "banners point at main" over a banner
        # that names a pull request and its branch.
        self.assertIn("the banners name PR #302 on chore/settle", said)
        self.assertNotIn("banners point at main", said)
        self.assertIn("PR #302 on `chore/settle`",
                      (self.root / "NEXT_CHAT.md").read_text(encoding="utf-8"))

    def test_without_one_the_branch_fields_go_to_main(self):
        said = self.settle(pr=None, branch=None)
        mirror = self.mirror()
        self.assertEqual(mirror["active"]["branch"], "main")
        self.assertEqual(mirror["sync"]["snapshot_branch"], "main")
        self.assertIn("banners point at main, not at a deleted branch", said)

    def test_the_first_parent_rule_survives_the_carrier_rewrite(self):
        """`settled_head_for` exists to write the value the gate pins the field to: the first
        parent of the carrier's merge commit. rewrite_state() overwrote it with the live head
        a few lines later, so with --pr the rule was dead code."""
        self.merge_commit = self.HEAD                 # the settle PR merged AS the head settled at

        class _Parent:
            stdout = self.PARENT
            returncode = 0
        real = sap.subprocess.run
        self.addCleanup(setattr, sap.subprocess, "run", real)
        sap.subprocess.run = lambda *a, **k: _Parent()
        self.settle()
        mirror = self.mirror()
        self.assertEqual(mirror["settled_at_main_head"], self.PARENT)
        self.assertEqual(mirror["sync"]["baseline_main_head_at_sync"], self.HEAD)


class ASwapThatFindsNothingRefuses(_StateFile):
    """`swap()` was silent when its text was absent, which is how two swaps went on "patching"
    sentences the mirror had not carried for months."""

    def state(self, text: str):
        self.path.write_text(text, encoding="utf-8")

    GOOD = json.dumps({
        "schema": 2, "settled_at_main_head": "a" * 40,
        "sync": {"baseline_main_head_at_sync": "a" * 40, "snapshot_branch": "b"},
        "active": {"branch": "b"}, "prs": [],
        "current_workflow_pr": {"number": 180, "branch": "b", "state": "open", "note": "n"},
    }, indent=2)

    def test_the_control_the_expected_layout_is_rewritten(self):
        self.state(self.GOOD)
        changed = sap.rewrite_state(180, "c", "s", "f" * 40)
        self.assertEqual(self.read()["active"]["branch"], "c")
        for label in ("baseline head", "settled head", "snapshot branch", "active branch",
                      "workflow pr", "note"):
            self.assertIn(label, changed)

    def test_a_layout_the_patterns_do_not_match_is_refused_by_name(self):
        """`active` written on one line: valid JSON, same data, and the active-branch swap
        finds nothing. It used to report success and leave `active.branch` on the old value."""
        one_line = self.GOOD.replace('"active": {\n    "branch": "b"\n  },',
                                     '"active": {"branch": "b"},')
        self.assertNotEqual(one_line, self.GOOD)
        self.state(one_line)
        with self.assertRaises(SystemExit) as caught:
            sap.rewrite_state(180, "c", "s", "f" * 40)
        self.assertIn("cannot move the active branch", str(caught.exception))
        self.assertIn("Nothing has been written", str(caught.exception))
        self.assertEqual(self.path.read_text(encoding="utf-8"), one_line)

    def test_no_swap_patches_text_the_mirror_does_not_carry(self):
        """The two dead swaps named sentences -- "marker in the PR #N body." and "self-carrier
        is PR #N)" -- that are in neither the fixture nor the real mirror."""
        real = (pathlib.Path(sap.__file__).resolve().parents[1] / "config"
                / "current_state.json").read_text(encoding="utf-8")
        source = pathlib.Path(sap.__file__).read_text(encoding="utf-8")
        for phrase in ("marker in the PR #", "self-carrier is PR #"):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, real)
                self.assertNotIn(phrase, source)


class RestRoadParsing(unittest.TestCase):
    """The REST road parses with the gate's `_json_documents` and is bounded by a timeout."""

    ROW = {"number": 7, "head": {"ref": "b", "sha": "c" * 40}, "base": {"ref": "main"},
           "draft": False, "title": "t"}

    def setUp(self):
        self._real = (sap._repo_slug, sap.subprocess.run)
        self.addCleanup(lambda: setattr(sap, "_repo_slug", self._real[0]))
        self.addCleanup(lambda: setattr(sap.subprocess, "run", self._real[1]))
        sap._repo_slug = lambda: "someone/fork"

    def rows(self, stdout: str):
        sap.subprocess.run = lambda args, **k: subprocess.CompletedProcess(args, 0, stdout, "")
        return sap._rest_open_prs()

    def page(self, number: int) -> str:
        return json.dumps([dict(self.ROW, number=number)])

    def test_every_shape_gh_paginate_can_emit_is_read(self):
        """`[..][..]` is the one the old `.replace("][", "],[")` turned into `Extra data` and a
        None -- the shape it was written to defend."""
        for label, stdout in (
            ("one array", json.dumps([dict(self.ROW, number=7), dict(self.ROW, number=9)])),
            ("concatenated arrays", self.page(7) + self.page(9)),
            ("one array per line", self.page(7) + "\n" + self.page(9) + "\n"),
        ):
            with self.subTest(shape=label):
                self.assertEqual([r["number"] for r in self.rows(stdout)], [7, 9])

    def test_a_truncated_page_is_no_answer_rather_than_a_partial_one(self):
        self.assertIsNone(self.rows(self.page(7) + '[{"number": 9, "head"'))

    def test_the_read_is_bounded_and_a_hang_is_no_answer(self):
        seen = {}

        def hang(args, **kwargs):
            seen.update(kwargs)
            raise subprocess.TimeoutExpired(args, kwargs.get("timeout"))
        sap.subprocess.run = hang
        self.assertIsNone(sap._rest_open_prs())
        self.assertEqual(seen.get("timeout"), 60)


if __name__ == "__main__":
    unittest.main()
