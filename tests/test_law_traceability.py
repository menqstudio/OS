import copy
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from bro_traceability import (
    TraceabilityError,
    check_corpus,
    derive_static_proof,
    load_meta_layer,
    load_runtime_dependencies,
    validate_law_record,
    validate_traceability,
    verify_law_index_sync,
)


def base_record() -> dict:
    """A complete, statically-provable law record used as the allow-path fixture.

    Its links point at real, resolvable artifacts so static proof reaches
    STATIC_PROVEN (never LIVE_PROVEN from a static validator)."""
    return {
        "id": "L999",
        "responsibility": "Synthetic fixture law for OLTS self-application.",
        "policy_source": ["schemas/law-record.schema.json"],
        "execution_surfaces": [
            {"module": "bro_traceability", "symbol": "validate_law_record",
             "kind": "validator", "path_role": "primary"}
        ],
        "tests": [
            {"file": "tests/test_law_traceability.py", "case": "test_complete_record_is_accepted", "kind": "allow"},
            {"file": "tests/test_law_traceability.py", "case": "test_missing_surface_is_denied", "kind": "deny"},
        ],
        "evidence": {
            "schema": "law-record",
            "writer": "tools/bro_traceability.py",
            "verifier": "tools/bro_traceability.py",
            "retention": "retained",
            "integrity_level": "Unsigned",
            "trust_source": "Self",
        },
        "failure_behavior": {"class": "NORMATIVE_ENFORCEMENT", "mode": "fail-closed", "normative_strength": "MUST"},
        "owner": "owner-gev",
        "revisions": [{"ver": "1.0", "type": "Behavioral", "date": "2026-07-18", "note": "fixture"}],
        "runtime_prerequisites": ["python3"],
    }


class MetaLayerTests(unittest.TestCase):
    def test_meta_layer_v11_has_three_new_principles(self):
        data = load_meta_layer(ROOT)
        self.assertEqual(data["meta_layer_version"], "1.1")
        names = {p["name"] for p in data["principles"]}
        self.assertIn("Traceability Principle", names)
        self.assertIn("Verifiability Principle", names)
        self.assertIn("Derivability Principle", names)

    def test_human_view_is_declared_derived(self):
        data = load_meta_layer(ROOT)
        self.assertTrue(data["human_view_is_derived"])


class RuntimeDependencyTests(unittest.TestCase):
    def test_dependencies_load_and_are_pinned(self):
        deps = load_runtime_dependencies(ROOT)
        self.assertIn("python3", deps)
        self.assertIn("jsonschema", deps)
        # jsonschema is required for validation: its absence must be fail-closed, not optional.
        self.assertEqual(deps["jsonschema"]["optionality"], "required")
        self.assertIn("validation", deps["jsonschema"]["required_for"])


class LawRecordAllowTests(unittest.TestCase):
    def test_complete_record_is_accepted(self):
        validate_law_record(base_record(), known_dependencies={"python3"})

    def test_complete_record_is_static_proven(self):
        proof = derive_static_proof(ROOT, base_record())
        self.assertEqual(proof["links"]["surface"], "STATIC_PROVEN")
        self.assertEqual(proof["links"]["test"], "STATIC_PROVEN")
        self.assertEqual(proof["effective_proof_level"], "STATIC_PROVEN")
        # A MUST law needs LIVE proof to be ENFORCED; static alone can only be STATIC_ONLY.
        self.assertTrue(proof["live_required"])
        self.assertNotEqual(proof["enforcement_status"], "ENFORCED")


class LawRecordDenyTests(unittest.TestCase):
    def test_missing_surface_is_denied(self):
        r = base_record()
        r["execution_surfaces"] = []
        with self.assertRaises(TraceabilityError):
            validate_law_record(r, known_dependencies={"python3"})

    def test_dead_prerequisite_is_denied(self):
        r = base_record()
        r["runtime_prerequisites"] = ["ghost-dependency"]
        with self.assertRaises(TraceabilityError):
            validate_law_record(r, known_dependencies={"python3"})

    def test_hand_written_proof_field_is_denied(self):
        r = base_record()
        r["proof_level"] = "LIVE_PROVEN"
        with self.assertRaises(TraceabilityError):
            validate_law_record(r, known_dependencies={"python3"})

    def test_must_law_with_advisory_mode_is_denied(self):
        r = base_record()
        r["failure_behavior"]["mode"] = "advisory"
        with self.assertRaises(TraceabilityError):
            validate_law_record(r, known_dependencies={"python3"})

    def test_missing_allow_or_deny_test_is_denied(self):
        r = base_record()
        r["tests"] = [{"file": "tests/test_law_traceability.py", "case": "x", "kind": "allow"},
                      {"file": "tests/test_law_traceability.py", "case": "y", "kind": "allow"}]
        with self.assertRaises(TraceabilityError):
            validate_law_record(r, known_dependencies={"python3"})

    def test_duplicate_law_ids_are_denied(self):
        with self.assertRaises(TraceabilityError):
            check_corpus([{"id": "L1"}, {"id": "L1"}])

    def test_unresolvable_test_case_is_not_static_proven(self):
        r = base_record()
        r["tests"][0]["case"] = "no_such_test_method_exists"
        proof = derive_static_proof(ROOT, r)
        self.assertEqual(proof["links"]["test"], "CLAIM_ONLY")
        self.assertNotEqual(proof["enforcement_status"], "ENFORCED")


class TraceabilityEntrypointTests(unittest.TestCase):
    def test_validate_traceability_runs_on_live_repo(self):
        report = validate_traceability(ROOT)
        self.assertGreaterEqual(report["meta_layer_principles"], 12)
        self.assertGreaterEqual(report["runtime_dependencies"], 3)
        self.assertGreaterEqual(report["law_records_backfilled"], 0)


class BackfillTests(unittest.TestCase):
    """L0-L14 backfilled records: structurally valid, honestly derived."""

    def setUp(self):
        self.report = validate_traceability(ROOT)
        self.by_id = {d["id"]: d for d in self.report["derived"]}

    def test_all_fifteen_laws_backfilled(self):
        self.assertEqual(self.report["law_records_backfilled"], 15)

    def test_no_law_is_overclaimed_as_enforced(self):
        # Nothing may read ENFORCED before LIVE proof exists (P0). Verifiability MP-11.
        for d in self.report["derived"]:
            self.assertNotEqual(d["enforcement_status"], "ENFORCED", d["id"])

    def test_freshness_laws_are_honestly_not_enforced(self):
        # The audit's freshness test gap must surface as NOT_ENFORCED, not be hidden.
        self.assertEqual(self.by_id["L1"]["enforcement_status"], "NOT_ENFORCED")
        self.assertEqual(self.by_id["L8"]["enforcement_status"], "NOT_ENFORCED")
        self.assertEqual(self.by_id["L1"]["links"]["test"], "CLAIM_ONLY")

    def test_wired_laws_are_static_proven(self):
        self.assertEqual(self.by_id["L0"]["links"]["surface"], "STATIC_PROVEN")
        self.assertEqual(self.by_id["L7"]["effective_proof_level"], "STATIC_PROVEN")


class HumanViewDriftTests(unittest.TestCase):
    def test_live_law_index_is_in_sync(self):
        registry = __import__("json").loads((ROOT / "laws" / "registry.json").read_text(encoding="utf-8"))
        records = [law for law in registry["laws"] if "responsibility" in law]
        verify_law_index_sync(ROOT, records)  # must not raise

    def test_drifted_law_index_is_denied(self):
        with self.assertRaises(TraceabilityError):
            verify_law_index_sync(ROOT, [{"id": "L404", "name": "Nonexistent Law"}])


if __name__ == "__main__":
    unittest.main()
