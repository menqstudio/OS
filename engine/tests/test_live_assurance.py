import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "runtime"))

from bro_live_validate import (WIRING_EXPECTED_CAUSE, advisory_laws, assurance_failures,
                               derive_live_status)


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

    def test_a_declared_advisory_law_passes_the_gate_without_being_enforced(self):
        """L13's shape: not enforced by declaration, its bound cases green."""
        report = _report(derived=[
            {"id": "L0", "enforcement_status": "ENFORCED"},
            {"id": "L13", "enforcement_status": "NOT_ENFORCED",
             "effective_proof_level": "STATIC_PROVEN",
             "declared_advisory": True, "bound_checks_pass": True},
        ])
        self.assertEqual(assurance_failures(report), [])
        self.assertEqual(advisory_laws(report), ["L13"])

    def test_a_declared_advisory_law_still_owes_its_bound_cases(self):
        """Declaring a law advisory must admit nothing that was refused before. What made it
        ENFORCED -- prerequisites, bound cases, resolving surfaces -- is still required, and a
        report that does not say they held is read as one where they did not."""
        for missing in ({"bound_checks_pass": False}, {}):
            with self.subTest(missing=missing):
                report = _report(derived=[
                    {"id": "L0", "enforcement_status": "ENFORCED"},
                    dict({"id": "L13", "enforcement_status": "NOT_ENFORCED",
                          "effective_proof_level": "STATIC_PROVEN",
                          "declared_advisory": True}, **missing),
                ])
                failures = assurance_failures(report)
                self.assertTrue(any("L13" in f and "declared advisory" in f for f in failures),
                                failures)

    def test_a_declared_advisory_law_reported_as_enforced_fails(self):
        for overclaim in ({"enforcement_status": "ENFORCED"},
                          {"effective_proof_level": "LIVE_PROVEN"}):
            with self.subTest(overclaim=overclaim):
                entry = {"id": "L13", "enforcement_status": "NOT_ENFORCED",
                         "effective_proof_level": "STATIC_PROVEN",
                         "declared_advisory": True, "bound_checks_pass": True}
                entry.update(overclaim)
                failures = assurance_failures(_report(derived=[
                    {"id": "L0", "enforcement_status": "ENFORCED"}, entry]))
                self.assertTrue(any("reported as enforced" in f and "L13" in f for f in failures),
                                failures)

    def test_a_normative_law_gets_nothing_from_the_advisory_arm(self):
        # The exemption is keyed on the declaration. A normative law that is merely not
        # enforced is still the failure it always was, whatever else its entry carries.
        report = _report(derived=[
            {"id": "L0", "enforcement_status": "ENFORCED"},
            {"id": "L1", "enforcement_status": "STATIC_ONLY",
             "declared_advisory": False, "bound_checks_pass": True},
        ])
        failures = assurance_failures(report)
        self.assertTrue(any("laws not LIVE_PROVEN: L1" in f for f in failures), failures)


def _record(**over):
    """A normative law record whose surface and tests resolve in this tree."""
    record = {
        "id": "L999",
        "execution_surfaces": [
            {"module": "bro_traceability", "symbol": "validate_law_record",
             "kind": "validator", "path_role": "primary"}],
        "failure_behavior": {"class": "NORMATIVE_ENFORCEMENT", "mode": "fail-closed",
                             "normative_strength": "MUST"},
    }
    record.update(over)
    return record


ADVISORY = {"class": "ADVISORY_OBSERVATION", "mode": "advisory", "normative_strength": "SHOULD"}
ALL_OBSERVED = {"prereq_ok": True, "tests_ok": True, "wiring_ok": True}


class LiveStatusDerivationTests(unittest.TestCase):
    """`derive_live_status`: what a law is CALLED, from what was observed and what it declares."""

    def test_a_normative_law_with_everything_observed_is_enforced(self):
        status = derive_live_status(ROOT, _record(), **ALL_OBSERVED)
        self.assertEqual(status["enforcement_status"], "ENFORCED")
        self.assertEqual(status["effective_proof_level"], "LIVE_PROVEN")
        self.assertFalse(status["declared_advisory"])
        self.assertTrue(status["bound_checks_pass"])

    def test_a_declared_advisory_law_is_never_enforced_or_live_proven(self):
        """The L13 case. Every observation green, and still: NOT_ENFORCED."""
        status = derive_live_status(ROOT, _record(failure_behavior=ADVISORY), **ALL_OBSERVED)
        self.assertEqual(status["enforcement_status"], "NOT_ENFORCED")
        self.assertEqual(status["effective_proof_level"], "STATIC_PROVEN")
        self.assertTrue(status["declared_advisory"])
        self.assertTrue(status["bound_checks_pass"])
        self.assertEqual(assurance_failures(_report(derived=[status])), [])

    def test_a_declared_advisory_law_with_failing_cases_fails_the_gate(self):
        status = derive_live_status(ROOT, _record(failure_behavior=ADVISORY),
                                    prereq_ok=True, tests_ok=False, wiring_ok=True)
        self.assertEqual(status["enforcement_status"], "NOT_ENFORCED")
        self.assertFalse(status["bound_checks_pass"])
        self.assertTrue(assurance_failures(_report(derived=[status])))

    def test_a_surface_that_does_not_exist_is_not_enforced_however_green_the_tests(self):
        """A record that names a function that was deleted or renamed. Its bound cases can
        all pass -- they test something -- and the law is still not enforced by a symbol that
        is not there. L5 named `bro_receipt.verify_receipt_set` this way once it was gone."""
        ghost = _record(execution_surfaces=[
            {"module": "bro_receipt", "symbol": "verify_receipt_set",
             "kind": "verifier", "path_role": "primary"}])
        status = derive_live_status(ROOT, ghost, **ALL_OBSERVED)
        self.assertFalse(status["live"]["surfaces_defined"])
        self.assertEqual(status["enforcement_status"], "STATIC_ONLY")
        self.assertEqual(status["effective_proof_level"], "STATIC_PROVEN")
        failures = assurance_failures(_report(derived=[status]))
        self.assertTrue(any("laws not LIVE_PROVEN: L999" in f for f in failures), failures)
        # Each surface is checked, not only the primary one.
        second = _record(execution_surfaces=_record()["execution_surfaces"] + [
            {"module": "bro_no_such_module", "symbol": "anything",
             "kind": "verifier", "path_role": "defense_in_depth"}])
        self.assertEqual(
            derive_live_status(ROOT, second, **ALL_OBSERVED)["enforcement_status"], "STATIC_ONLY")

    def test_each_observation_is_required(self):
        for missing in ("prereq_ok", "tests_ok"):
            with self.subTest(missing=missing):
                observed = dict(ALL_OBSERVED, **{missing: False})
                status = derive_live_status(ROOT, _record(), **observed)
                self.assertEqual(status["enforcement_status"], "STATIC_ONLY")
                self.assertFalse(status["bound_checks_pass"])

    def test_dead_wiring_fails_a_hook_primary_law_and_only_that(self):
        hook = _record(execution_surfaces=[
            {"module": "bro_protected", "symbol": "authorize_protected_scope",
             "kind": "hook", "path_role": "primary"}])
        dead = dict(ALL_OBSERVED, wiring_ok=False)
        self.assertEqual(derive_live_status(ROOT, hook, **dead)["enforcement_status"],
                         "STATIC_ONLY")
        self.assertEqual(derive_live_status(ROOT, _record(), **dead)["enforcement_status"],
                         "ENFORCED")


if __name__ == "__main__":
    unittest.main()
