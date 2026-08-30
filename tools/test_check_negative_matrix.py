"""The negative-matrix gate must FAIL when it should.

A gate that cannot fail is the exact defect this gate exists to catch: `T-045` swept its own
seven checks and found THREE tested by nothing plus a fourth with no test at all. So this gate
gets the treatment it imposes -- every rule it claims to enforce is broken here on a synthetic
tree and required to come back RED, and the GREEN control proves the RED verdicts are not just
"this gate refuses everything".

Each test builds a whole miniature repository in a tempdir: a markdown matrix, a mirror, and a
test file for the gate to bind against. Nothing here reads the real matrix -- a self-test that
depended on the repository's own 242 rows would go red every time the plan gained a row, which
is a test measuring the wrong thing.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_negative_matrix as gate  # noqa: E402

MATRIX = """# A miniature matrix

## 1. Replay (`NM-REPLAY-*`)

| Test ID | Under test | Fault injected | Expected fail-closed outcome | § ref |
|---|---|---|---|---|
| NM-REPLAY-01 | Desktop nonce consume | Replay a consumed nonce | Block | §6.1(14) |
| NM-REPLAY-02 | receipt_id uniqueness | A duplicate receipt_id | Block | §7.1 |

## 19. Parity (`NM-PARITY-*`)

| Test ID | Formula | Assertion |
|---|---|---|
| NM-PARITY-01 | `system` (raw UTF-8) | identical `sha256` |
"""

TEST_FILE = '''
def test_nm_replay_01_binds_its_row():
    marker = "NM-REPLAY-01"
    assert marker


def test_nm_replay_02_does_not_name_its_row_in_the_body():
    assert True


def helper_without_the_id_in_its_name():
    marker = "NM-REPLAY-01"
    assert marker
'''


class NegativeMatrixGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="brops-nmgate-")).resolve()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        (self.tmp / "docs" / "design").mkdir(parents=True)
        (self.tmp / "config").mkdir(parents=True)
        (self.tmp / "engine" / "tests").mkdir(parents=True)
        (self.tmp / "docs" / "design" / "SECURITY_NEGATIVE_TEST_MATRIX.md").write_text(
            MATRIX, encoding="utf-8")
        (self.tmp / "engine" / "tests" / "test_mini.py").write_text(TEST_FILE, encoding="utf-8")

    def write_mirror(self, cases: dict, baseline=None):
        if baseline is None:
            baseline = sorted(i for i, c in cases.items() if c["status"] == "unreviewed")
        (self.tmp / "config" / "negative-matrix.json").write_text(
            json.dumps({"unreviewed_baseline": baseline, "cases": cases}), encoding="utf-8")

    def unreviewed(self, *ids):
        return {i: {"status": "unreviewed", "under_test": "x", "section": "x",
                    "reason": "nobody has checked"} for i in ids}

    def all_three_unreviewed(self):
        return self.unreviewed("NM-REPLAY-01", "NM-REPLAY-02", "NM-PARITY-01")

    def run_gate(self):
        return gate.check(self.tmp)

    # -- the GREEN control ------------------------------------------------------------------
    # Without it every RED below would also be produced by a gate that refuses everything.

    def test_a_fully_honest_mirror_is_green(self):
        self.write_mirror(self.all_three_unreviewed())
        self.assertEqual(self.run_gate(), [])

    # -- rule 1: the two ID sets must be identical, both directions -------------------------

    def test_an_id_in_the_matrix_and_missing_from_the_mirror_is_red(self):
        cases = self.all_three_unreviewed()
        del cases["NM-REPLAY-02"]
        self.write_mirror(cases)
        problems = self.run_gate()
        self.assertTrue(any("NM-REPLAY-02" in p and "missing from" in p for p in problems),
                        problems)

    def test_an_id_in_the_mirror_and_not_in_the_matrix_is_red(self):
        cases = self.all_three_unreviewed()
        cases.update(self.unreviewed("NM-INVENTED-99"))
        self.write_mirror(cases)
        problems = self.run_gate()
        self.assertTrue(any("NM-INVENTED-99" in p and "declared by no matrix row" in p
                            for p in problems), problems)

    # -- rule 2: implemented must name a test that EXISTS ------------------------------------

    def test_implemented_naming_a_missing_file_is_red(self):
        cases = self.all_three_unreviewed()
        cases["NM-REPLAY-01"] = {"status": "implemented", "under_test": "x", "section": "x",
                                 "test": "engine/tests/test_nm_replay_01_absent.py::test_x"}
        self.write_mirror(cases)
        self.assertTrue(any("not a file in the tree" in p for p in self.run_gate()))

    def test_implemented_naming_a_missing_function_is_red(self):
        cases = self.all_three_unreviewed()
        cases["NM-REPLAY-01"] = {
            "status": "implemented", "under_test": "x", "section": "x",
            "test": "engine/tests/test_mini.py::test_nm_replay_01_not_defined_here"}
        self.write_mirror(cases)
        self.assertTrue(any("is not defined in" in p for p in self.run_gate()))

    def test_implemented_with_no_test_field_is_red(self):
        cases = self.all_three_unreviewed()
        cases["NM-REPLAY-01"] = {"status": "implemented", "under_test": "x", "section": "x"}
        self.write_mirror(cases)
        self.assertTrue(any("with no `test`" in p for p in self.run_gate()))

    # -- rule 3: the test body must carry the ID, and so must the test name -------------------

    def test_implemented_whose_test_body_lacks_the_id_is_red(self):
        cases = self.all_three_unreviewed()
        cases["NM-REPLAY-02"] = {
            "status": "implemented", "under_test": "x", "section": "x",
            "test": "engine/tests/test_mini.py"
                    "::test_nm_replay_02_does_not_name_its_row_in_the_body"}
        self.write_mirror(cases)
        self.assertTrue(any("does not carry the string" in p for p in self.run_gate()))

    def test_implemented_whose_test_name_lacks_the_id_is_red(self):
        cases = self.all_three_unreviewed()
        cases["NM-REPLAY-01"] = {
            "status": "implemented", "under_test": "x", "section": "x",
            "test": "engine/tests/test_mini.py::helper_without_the_id_in_its_name"}
        self.write_mirror(cases)
        self.assertTrue(any("does not contain the ID" in p for p in self.run_gate()))

    def test_a_correctly_bound_implemented_row_is_green(self):
        """The other half of rule 2/3: a test that exists, is named for its row and carries the
        ID passes. Without this the RED tests above are satisfied by a gate that rejects every
        `implemented` row on principle."""
        cases = self.all_three_unreviewed()
        cases["NM-REPLAY-01"] = {
            "status": "implemented", "under_test": "x", "section": "x",
            "test": "engine/tests/test_mini.py::test_nm_replay_01_binds_its_row"}
        self.write_mirror(cases)
        self.assertEqual(self.run_gate(), [])

    # -- rule 4: blocked must name a cause ----------------------------------------------------

    def test_blocked_without_a_cause_is_red(self):
        cases = self.all_three_unreviewed()
        cases["NM-REPLAY-01"] = {"status": "blocked", "under_test": "x", "section": "x",
                                 "blocked_on": "   "}
        self.write_mirror(cases)
        self.assertTrue(any("indistinguishable from 'not done'" in p for p in self.run_gate()))

    def test_blocked_with_a_cause_is_green(self):
        cases = self.all_three_unreviewed()
        cases["NM-REPLAY-01"] = {"status": "blocked", "under_test": "x", "section": "x",
                                 "blocked_on": "the validator this row names does not exist"}
        self.write_mirror(cases)
        self.assertEqual(self.run_gate(), [])

    # -- rule 5: new debt is refused, frozen debt is not --------------------------------------

    def test_a_new_unreviewed_row_outside_the_baseline_is_red(self):
        """The load-bearing rule. A row added to the markdown lands in the mirror as
        `unreviewed`, and that must FAIL until someone establishes it or extends the baseline in
        a diff someone can see."""
        cases = self.all_three_unreviewed()
        self.write_mirror(cases, baseline=["NM-REPLAY-01", "NM-REPLAY-02"])
        problems = self.run_gate()
        self.assertTrue(any("NM-PARITY-01" in p and "NOT in unreviewed_baseline" in p
                            for p in problems), problems)

    def test_a_baseline_that_keeps_a_paid_down_entry_is_red(self):
        cases = self.all_three_unreviewed()
        cases["NM-REPLAY-01"] = {"status": "blocked", "under_test": "x", "section": "x",
                                 "blocked_on": "a real cause"}
        self.write_mirror(cases, baseline=["NM-REPLAY-01", "NM-REPLAY-02", "NM-PARITY-01"])
        self.assertTrue(any("no longer unreviewed" in p for p in self.run_gate()))

    def test_a_baseline_naming_an_id_that_is_not_a_case_is_red(self):
        self.write_mirror(self.all_three_unreviewed(),
                          baseline=["NM-REPLAY-01", "NM-REPLAY-02", "NM-PARITY-01", "NM-GONE-01"])
        self.assertTrue(any("stale baseline" in p for p in self.run_gate()))

    def test_unreviewed_without_a_reason_is_red(self):
        cases = self.all_three_unreviewed()
        cases["NM-REPLAY-01"]["reason"] = ""
        self.write_mirror(cases)
        self.assertTrue(any("with no `reason`" in p for p in self.run_gate()))

    # -- shape --------------------------------------------------------------------------------

    def test_an_invalid_status_is_red(self):
        cases = self.all_three_unreviewed()
        cases["NM-REPLAY-01"]["status"] = "probably_fine"
        self.write_mirror(cases)
        self.assertTrue(any("invalid status" in p for p in self.run_gate()))

    def test_a_missing_mirror_is_red_rather_than_an_exception(self):
        self.assertTrue(any("cannot read" in p for p in self.run_gate()))


class MatrixParserTests(unittest.TestCase):
    """The parser the gate and the generator share. the plan's section-20 cross-reference table names IDs as
    RANGES (`NM-REPLAY-01..10`), and taking those as rows would invent obligations nobody
    wrote; a row whose first cell is not exactly one ID is not a case."""

    def test_a_prose_first_cell_is_not_a_case(self):
        import generate_negative_matrix as generator
        text = MATRIX + """
## 20. Coverage cross-reference

| Architect-required negative | Sections / representative IDs |
|---|---|
| replay | §1 (NM-REPLAY-01..10) |
"""
        cases = generator.parse(text)
        self.assertEqual(sorted(cases), ["NM-PARITY-01", "NM-REPLAY-01", "NM-REPLAY-02"])

    def test_an_id_RANGE_in_the_first_cell_is_not_a_case(self):
        """`ID_RE` is anchored on BOTH ends, and this is why. The coverage table writes ranges
        (`NM-REPLAY-01..10`); a prefix match would turn one of those into a row and invent an
        obligation nobody wrote. Found by mutation: loosening `ID_RE.match` to a `startswith`
        left `test_a_prose_first_cell_is_not_a_case` green, because that test only exercises a
        cell that does not begin with `NM-` at all."""
        import generate_negative_matrix as generator
        text = MATRIX + """
## 20. Coverage cross-reference

| Test ID | Sections |
|---|---|
| NM-REPLAY-01..10 | the whole replay domain |
"""
        cases = generator.parse(text)
        self.assertNotIn("NM-REPLAY-01..10", cases)
        self.assertEqual(sorted(cases), ["NM-PARITY-01", "NM-REPLAY-01", "NM-REPLAY-02"])

    def test_a_table_without_a_section_ref_column_records_the_plan_section(self):
        import generate_negative_matrix as generator
        cases = generator.parse(MATRIX)
        self.assertEqual(cases["NM-PARITY-01"]["section"], "plan 19")
        self.assertEqual(cases["NM-REPLAY-01"]["section"], "§6.1(14)")

    def test_an_over_wide_row_still_resolves_its_section_from_the_last_cell(self):
        """The real matrix contains one: NM-CRASH-16 carries FIVE cells in a FOUR-column
        table, so a renderer drops its `§5(9)-(10)`. The parser reads the section from the END
        because the section-ref column is last in every table that has one."""
        import generate_negative_matrix as generator
        text = """## 6. Crash

| Test ID | Cut point | Expected durable state | § ref |
|---|---|---|---|
| NM-CRASH-16 | Marker misuse | Present the marker | RECOVERY_REQUIRED | §5(9)-(10) |
"""
        cases = generator.parse(text)
        self.assertEqual(cases["NM-CRASH-16"]["section"], "§5(9)-(10)")
        self.assertEqual(cases["NM-CRASH-16"]["under_test"], "Marker misuse")

    def test_a_short_row_is_a_hard_parse_error_rather_than_a_dropped_case(self):
        import generate_negative_matrix as generator
        text = """## 1. Replay

| Test ID | Under test | Fault injected | Expected outcome | § ref |
|---|---|---|---|---|
| NM-REPLAY-01 | Under test | Fault |
"""
        with self.assertRaises(generator.ParseError):
            generator.parse(text)

    def test_a_duplicated_test_id_is_a_hard_parse_error(self):
        import generate_negative_matrix as generator
        with self.assertRaises(generator.ParseError):
            generator.parse(MATRIX + MATRIX)


if __name__ == "__main__":
    unittest.main()
