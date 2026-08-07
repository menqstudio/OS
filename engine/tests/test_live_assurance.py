import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "runtime"))

from bro_live_validate import WIRING_EXPECTED_CAUSE, assurance_failures


def _report(**over):
    """A fully live-proven report; override one field to model a specific shortfall."""
    base = {
        "wired_interpreter": "/usr/bin/python3",
        "wiring_denies": True,
        "wiring_decision": "deny",
        "wiring_reason": f"workspace scope gate RED: {WIRING_EXPECTED_CAUSE}; no active workspace",
        "bytecode_shadow": [],
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

    def test_the_dead_wiring_failure_reports_the_refusal_it_actually_saw(self):
        """A gate that only says "it did not deny" sends the operator hunting. The
        refusal that WAS observed is the first thing needed to tell dead wiring apart
        from a wall refusing for an unrelated reason."""
        failures = assurance_failures(_report(
            wiring_denies=False, wiring_decision="deny",
            wiring_reason="freeze state gate RED: missing BRO_SESSION_STATE_DIR"))
        self.assertTrue(any("freeze state gate RED" in f for f in failures), failures)
        self.assertTrue(any(WIRING_EXPECTED_CAUSE in f for f in failures), failures)

    def test_a_bytecode_shadow_fails_the_assurance_and_names_the_masking(self):
        """The O-1 consequence, as a gate. A `compileall` (or any interpreter started
        without -B) before the live validation leaves __pycache__ under a digest root;
        the wall then refuses for the shadow, the anti-dead-wiring negative still sees
        `deny`, and CI goes green on a proof nobody took. That state is RED here."""
        failures = assurance_failures(_report(
            bytecode_shadow=["runtime/__pycache__", "tools/__pycache__"]))
        self.assertTrue(any("runtime/__pycache__" in f for f in failures), failures)
        self.assertTrue(any("compileall" in f for f in failures), failures)

    def test_a_shadow_is_reported_before_the_wiring_failure_it_causes(self):
        failures = assurance_failures(_report(
            wiring_denies=False, bytecode_shadow=["runtime/__pycache__"]))
        shadow_at = next(i for i, f in enumerate(failures) if "__pycache__" in f)
        wiring_at = next(i for i, f in enumerate(failures) if "dead wiring" in f)
        self.assertLess(shadow_at, wiring_at, failures)

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
