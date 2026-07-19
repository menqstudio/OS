import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "runtime"))

from bro_live_validate import assurance_failures


def _report(**over):
    """A fully live-proven report; override one field to model a specific shortfall."""
    base = {
        "wired_interpreter": "/usr/bin/python3",
        "wiring_denies": True,
        "prerequisites_resolve": True,
        "laws": 2,
        "derived": [
            {"id": "L0", "enforcement_status": "ENFORCED"},
            {"id": "L1", "enforcement_status": "ENFORCED"},
        ],
    }
    base.update(over)
    return base


class AssuranceGateTests(unittest.TestCase):
    """The gate that turns the live report from a description into a fail-closed check."""

    def test_fully_enforced_report_passes(self):
        self.assertEqual(assurance_failures(_report()), [])

    def test_no_wired_interpreter_fails(self):
        self.assertTrue(assurance_failures(_report(wired_interpreter=None)))

    def test_dead_wiring_fails(self):
        failures = assurance_failures(_report(wiring_denies=False))
        self.assertTrue(any("dead wiring" in f for f in failures), failures)

    def test_unresolved_prerequisites_fail(self):
        self.assertTrue(assurance_failures(_report(prerequisites_resolve=False)))

    def test_a_static_only_law_fails_and_is_named(self):
        report = _report(derived=[
            {"id": "L0", "enforcement_status": "ENFORCED"},
            {"id": "L1", "enforcement_status": "STATIC_ONLY"},
        ])
        failures = assurance_failures(report)
        self.assertTrue(any("L1" in f for f in failures), failures)

    def test_no_laws_to_validate_fails(self):
        self.assertTrue(assurance_failures(_report(derived=[])))


if __name__ == "__main__":
    unittest.main()
