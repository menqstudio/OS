"""The spec-conformance gate must FAIL when it should.

A gate that cannot fail is the exact defect this gate exists to catch — the previous audit round
found a production guard whose two operands were provably equal, marked CLOSED on the strength of
it. So the gate gets the treatment it imposes: tests that delete the thing it checks and require
red.
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_spec_references as gate  # noqa: E402


class SpecReferenceGateTests(unittest.TestCase):
    def setUp(self):
        self.original_root = gate.ROOT
        self.original_declaration = gate.DECLARATION
        self.tmp = pathlib.Path(
            __import__("tempfile").mkdtemp(prefix="brops-specgate-")
        ).resolve()
        self.addCleanup(
            lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True)
        )
        self.addCleanup(self._restore)
        (self.tmp / "engine").mkdir(parents=True)
        (self.tmp / "config").mkdir(parents=True)
        gate.ROOT = self.tmp
        gate.DECLARATION = self.tmp / "config" / "spec-conformance.json"

    def _restore(self):
        gate.ROOT = self.original_root
        gate.DECLARATION = self.original_declaration

    def write_source(self, text: str, name: str = "thing.py"):
        (self.tmp / "engine" / name).write_text(text, encoding="utf-8")

    def declare(self, sections: dict):
        gate.DECLARATION.write_text(
            json.dumps({"sections": sections}), encoding="utf-8"
        )

    # ---- the load-bearing rule: a new reference cannot appear undeclared -------------------

    def test_an_undeclared_reference_fails(self):
        self.write_source("# implements §9.9 exactly\n")
        self.declare({})
        problems = gate.check()
        self.assertTrue(any("not declared" in p for p in problems), problems)

    def test_a_declared_reference_passes(self):
        self.write_source("# see §9.9\n")
        self.declare({"§9.9": {"status": "unreviewed", "reason": "nobody has looked"}})
        self.assertEqual(gate.check(), [])

    # ---- implemented must be backed by a test that exists ----------------------------------

    def test_implemented_without_a_test_fails(self):
        self.write_source("# §9.9 holds\n")
        self.declare({"§9.9": {"status": "implemented"}})
        problems = gate.check()
        self.assertTrue(any("names no test" in p for p in problems), problems)

    def test_implemented_naming_a_test_that_does_not_exist_fails(self):
        self.write_source("# §9.9 holds\n")
        self.declare({"§9.9": {"status": "implemented", "tests": ["test_nowhere_at_all"]}})
        problems = gate.check()
        self.assertTrue(any("does not exist" in p for p in problems), problems)

    def test_implemented_naming_a_real_test_passes(self):
        self.write_source("# §9.9 holds\n")
        self.write_source("def test_the_real_one():\n    pass\n", "test_thing.py")
        self.declare({"§9.9": {"status": "implemented", "tests": ["test_the_real_one"]}})
        self.assertEqual(gate.check(), [])

    # ---- not_implemented must be marked at EVERY site --------------------------------------

    def test_not_implemented_cited_as_fact_fails(self):
        self.write_source("# enforced per §9.9\n")
        self.declare({"§9.9": {"status": "not_implemented", "reason": "nothing does this"}})
        problems = gate.check()
        self.assertTrue(any("assumes the" in p for p in problems), problems)

    def test_not_implemented_marked_at_the_site_passes(self):
        self.write_source("# §9.9 is NOT IMPLEMENTED — the check does not exist\n")
        self.declare({"§9.9": {"status": "not_implemented", "reason": "nothing does this"}})
        self.assertEqual(gate.check(), [])

    def test_one_marked_site_does_not_excuse_another_unmarked_one(self):
        # The failure mode is a reader landing on ONE line. A marker elsewhere in the tree does
        # not reach them.
        self.write_source("# §9.9 is NOT IMPLEMENTED\n", "a.py")
        self.write_source("# guaranteed by §9.9\n", "b.py")
        self.declare({"§9.9": {"status": "not_implemented", "reason": "nothing does this"}})
        problems = gate.check()
        self.assertTrue(any("b.py" in p for p in problems), problems)

    # ---- partial must say what is missing, in the code ---------------------------------------

    def test_partial_without_naming_the_gap_fails(self):
        self.write_source("# see §9.9\n")
        self.declare({"§9.9": {"status": "partial"}})
        problems = gate.check()
        self.assertTrue(any("WHICH part is missing" in p for p in problems), problems)

    def test_partial_whose_gap_is_only_in_the_json_fails(self):
        self.write_source("# see §9.9\n")
        self.declare({"§9.9": {"status": "partial", "missing": "the signature"}})
        problems = gate.check()
        self.assertTrue(any("discoverable from the code" in p for p in problems), problems)

    def test_partial_named_in_the_code_passes(self):
        self.write_source("# §9.9 — PARTIAL: the signature half is missing\n")
        self.declare({"§9.9": {"status": "partial", "missing": "the signature"}})
        self.assertEqual(gate.check(), [])

    # ---- shape ------------------------------------------------------------------------------

    def test_an_unknown_status_fails(self):
        self.write_source("# §9.9\n")
        self.declare({"§9.9": {"status": "probably-fine"}})
        problems = gate.check()
        self.assertTrue(any("status must be one of" in p for p in problems), problems)

    def test_the_real_repository_passes_its_own_gate(self):
        self._restore()
        self.assertEqual(gate.check(), [])


if __name__ == "__main__":
    unittest.main()
