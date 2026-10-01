#!/usr/bin/env python3
"""Tests for check_state_fields.py.

Run: python -m unittest test_check_state_fields   (from tools/)

The gate ran in CI, and on every prompt through the root hook's FAST_GATES, with no test.
What that hid: it counted a TEST FIXTURE as a reader, and any file at all that happened to
quote the field's name, so it was GREEN on three fields nothing reads.

Every case builds its own small repository. The real mirror is not consulted: it is
rewritten by whichever session settles it, and CI runs the gate itself over that.
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import check_state_fields as gate  # noqa: E402

READER = 'import json\nstate = json.load(open("config/current_state.json"))\nprint(state["{field}"])\n'


class GateCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        (self.root / "config").mkdir()
        (self.root / "tools").mkdir()
        self.state({"head": "abc"})
        self.declare({})
        self.write("tools/check_thing.py", READER.format(field="head"))

    def state(self, fields) -> None:
        (self.root / gate.STATE_REL).write_text(json.dumps(fields), encoding="utf-8")

    def declare(self, unread) -> None:
        (self.root / gate.BUDGET_REL).write_text(
            json.dumps({"state_fields_read_by_nothing": unread}), encoding="utf-8")

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def run_gate(self) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gate.main(self.root)
        return code, out.getvalue()

    def assertRed(self, needle: str) -> None:
        code, out = self.run_gate()
        self.assertEqual(code, 1, out)
        self.assertIn(needle, out)

    def assertGreen(self) -> None:
        code, out = self.run_gate()
        self.assertEqual(code, 0, out)


class TheRule(GateCase):
    def test_a_field_with_a_reader_is_green(self):
        """If the happy path were not green, every red below would be meaningless."""
        self.assertGreen()

    def test_a_field_nothing_reads_is_red(self):
        self.state({"head": "abc", "essay": "x" * 100})
        self.assertRed("`essay` is in config/current_state.json and NO tool")

    def test_a_field_declared_unread_with_a_reason_is_green(self):
        self.state({"head": "abc", "essay": "x"})
        self.declare({"essay": "a note for the human reader"})
        code, out = self.run_gate()
        self.assertEqual(code, 0, out)
        self.assertIn("fields=2; declared-unread=1", out)

    def test_an_exemption_for_a_field_something_now_reads_is_red(self):
        self.declare({"head": "nothing reads it"})
        self.assertRed("`head` is declared as read by nothing, but something reads it now")

    def test_an_exemption_for_a_field_that_is_gone_is_red(self):
        self.declare({"ghost": "left over"})
        self.assertRed("state_fields_read_by_nothing names `ghost`, which is not in")

    def test_each_quoting_form_counts(self):
        for form in ('state["extra"]', "state['extra']", "prs[extra]"):
            with self.subTest(form=form):
                self.state({"head": "abc", "extra": 1})
                self.write("tools/check_thing.py",
                           READER.format(field="head") + f"# current_state.json\n{form}\n")
                self.assertGreen()

    def test_an_unquoted_mention_is_not_a_read(self):
        self.state({"head": "abc", "extra": 1})
        self.write("tools/check_thing.py",
                   READER.format(field="head") + "# extra is a field of the mirror\n")
        self.assertRed("`extra`")


class WhatIsNotAReader(GateCase):
    """The defect. Each of these quoted the field's name and none of them reads the mirror."""

    def setUp(self):
        super().setUp()
        self.state({"head": "abc", "product_roadmap": {}})

    def test_the_control_a_real_reader_makes_the_field_green(self):
        self.write("tools/check_roadmap.py", READER.format(field="product_roadmap"))
        self.assertGreen()

    def test_a_test_fixture_that_writes_the_field_is_not_a_reader(self):
        """`tools/test_check_repo_state.py` does `snap["product_roadmap"] = {...}`; that was
        the field's only quoted occurrence in the tree and the gate called it read."""
        fixture = ('# builds a current_state.json snapshot\nsnap = {}\n'
                   'snap["product_roadmap"] = {"phase_0": "done"}\n')
        for rel in ("tools/test_check_repo_state.py", "tools/tests/helpers.py",
                    "tools/fixtures/snapshot.py", "bridge/src/state.test.ts"):
            with self.subTest(rel=rel):
                self.write(rel, fixture)
                self.assertRed("`product_roadmap`")
                (self.root / rel).unlink()

    def test_a_file_that_never_names_the_mirror_is_not_a_reader(self):
        """`"schema"` and `"_comment"` are keys in a dozen unrelated JSON documents."""
        self.write("tools/check_other.py",
                   'doc = json.load(open("config/other.json"))\nprint(doc["product_roadmap"])\n')
        self.assertRed("`product_roadmap`")

    def test_the_gate_does_not_count_itself(self):
        """It names every field in its own messages. A copy of it in the scanned tree is
        just another file, so the exclusion is by PATH -- which is what is asserted."""
        own = pathlib.Path(gate.__file__).resolve()
        self.assertNotIn(own, [p.resolve() for p in gate.reader_files(own.parents[1])])

    def test_a_workflow_that_reads_the_field_is_a_reader(self):
        """The RED message has always said "workflow"; no workflow was scanned."""
        self.write(".github/workflows/ci.yml",
                   "      - run: jq '.[\"product_roadmap\"]' config/current_state.json\n")
        self.assertGreen()

    def test_a_directory_that_is_not_a_reader_home_is_not_scanned(self):
        self.write("docs/notes.py", READER.format(field="product_roadmap"))
        self.assertRed("`product_roadmap`")

    def test_every_scanned_directory_exists_in_this_repository(self):
        """`runtime` sat in READER_DIRS for a directory the repository root does not have:
        an entry that scans nothing and reads as coverage."""
        repo = pathlib.Path(gate.__file__).resolve().parents[1]
        for rel in gate.READER_DIRS:
            with self.subTest(rel=rel):
                self.assertTrue((repo / rel).is_dir(), f"{rel} is scanned and does not exist")


class TheVerdictWhenItCannotRead(GateCase):
    def test_a_missing_or_invalid_mirror_is_red(self):
        for label, damage in (("invalid", lambda: (self.root / gate.STATE_REL).write_text(
                                  "{", encoding="utf-8")),
                              ("missing", (self.root / gate.STATE_REL).unlink)):
            damage()
            with self.subTest(mirror=label):
                self.assertRed("cannot read the machine mirror or its budget")

    def test_a_mirror_that_is_not_an_object_is_red(self):
        (self.root / gate.STATE_REL).write_text("[]", encoding="utf-8")
        self.assertRed("must contain an object")

    def test_a_budget_without_the_declaration_map_is_red(self):
        (self.root / gate.BUDGET_REL).write_text("{}", encoding="utf-8")
        self.assertRed("must carry state_fields_read_by_nothing")
        (self.root / gate.BUDGET_REL).write_text(
            json.dumps({"state_fields_read_by_nothing": ["head"]}), encoding="utf-8")
        self.assertRed("must carry state_fields_read_by_nothing")


if __name__ == "__main__":
    unittest.main()
