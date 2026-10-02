import ast
import copy
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "runtime"))

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
        # The count is `len(records)`, so "at least zero" asserted nothing. The floor is the
        # fifteen core laws (L0-L14), and every counted record has a derived proof beside it.
        self.assertGreaterEqual(report["law_records_backfilled"], 15)
        self.assertEqual(len(report["derived"]), report["law_records_backfilled"])


class BackfillTests(unittest.TestCase):
    """L0-L14 backfilled records: structurally valid, honestly derived."""

    def setUp(self):
        self.report = validate_traceability(ROOT)
        self.by_id = {d["id"]: d for d in self.report["derived"]}

    def test_all_core_laws_backfilled(self):
        # L0-L14 are the audited core; later phases may add further laws (L15+).
        self.assertGreaterEqual(self.report["law_records_backfilled"], 15)
        for i in range(15):
            self.assertIn(f"L{i}", self.by_id)

    def test_no_law_is_overclaimed_as_enforced(self):
        # Nothing may read ENFORCED before LIVE proof exists (P0). Verifiability MP-11.
        for d in self.report["derived"]:
            self.assertNotEqual(d["enforcement_status"], "ENFORCED", d["id"])

    def test_freshness_laws_static_proven_after_p1(self):
        # P1 closed the audit's freshness test gap: L1/L8 rise from NOT_ENFORCED to
        # STATIC_ONLY (test link now STATIC_PROVEN). They are still not ENFORCED --
        # that requires LIVE proof, gated on the P0.1 interpreter commit.
        self.assertEqual(self.by_id["L1"]["enforcement_status"], "STATIC_ONLY")
        self.assertEqual(self.by_id["L8"]["enforcement_status"], "STATIC_ONLY")
        self.assertEqual(self.by_id["L1"]["links"]["test"], "STATIC_PROVEN")
        self.assertNotEqual(self.by_id["L1"]["enforcement_status"], "ENFORCED")

    def test_wired_laws_are_static_proven(self):
        self.assertEqual(self.by_id["L0"]["links"]["surface"], "STATIC_PROVEN")
        self.assertEqual(self.by_id["L7"]["effective_proof_level"], "STATIC_PROVEN")


class HumanViewDriftTests(unittest.TestCase):
    def test_live_law_index_is_in_sync(self):
        registry = __import__("json").loads((ROOT / "laws" / "registry.json").read_text(encoding="utf-8"))
        records = [law for law in registry["laws"] if "responsibility" in law]
        verify_law_index_sync(ROOT, records)  # must not raise

    def test_a_law_id_must_stand_alone_and_is_not_satisfied_by_a_longer_one(self):
        """`lid in text` was a substring test, so `L1` was "present" in any index that carried
        `L10`..`L16`. Driven against a copy of the live index with the L1 entry's ID removed
        and its NAME left in place -- the one drift the name check cannot see."""
        import tempfile
        registry = __import__("json").loads(
            (ROOT / "laws" / "registry.json").read_text(encoding="utf-8"))
        records = [law for law in registry["laws"] if "responsibility" in law]
        live = (ROOT / "laws" / "LAW_INDEX.md").read_text(encoding="utf-8")
        self.assertIn("## L1 —", live)
        self.assertIn("L10", live)
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "laws").mkdir()
            index = root / "laws" / "LAW_INDEX.md"
            index.write_text(live, encoding="utf-8")
            verify_law_index_sync(root, records)                      # the control: a copy passes
            index.write_text(live.replace("## L1 —", "## —"), encoding="utf-8")
            with self.assertRaises(TraceabilityError) as caught:
                verify_law_index_sync(root, records)
            self.assertIn("L1 absent", str(caught.exception))

    def test_drifted_law_index_is_denied(self):
        with self.assertRaises(TraceabilityError):
            verify_law_index_sync(ROOT, [{"id": "L404", "name": "Nonexistent Law"}])


def _law(law_id: str) -> dict:
    registry = json.loads((ROOT / "laws" / "registry.json").read_text(encoding="utf-8"))
    return next(law for law in registry["laws"] if law["id"] == law_id)


def _primary(record: dict) -> list[tuple[str, str]]:
    return [(s["module"], s["symbol"]) for s in record["execution_surfaces"]
            if s["path_role"] == "primary"]


def code_references(symbol: str, root: pathlib.Path = ROOT) -> list[str]:
    """Every place the engine's shipped Python USES `symbol`, as `path:line`.

    A use is a load of the name or of an attribute by that name -- a call, a reference handed
    to something else, an import is not one. Read from `runtime/`, `tools/` and `ci/`, which is
    everything the engine runs outside its tests; `tests/` is deliberately not read, because
    "its own test calls it" is the state this exists to tell apart from "something calls it".
    """
    found = []
    for directory in ("runtime", "tools", "ci"):
        for path in sorted((root / directory).rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                used = ((isinstance(node, ast.Name) and node.id == symbol)
                        or (isinstance(node, ast.Attribute) and node.attr == symbol))
                if used and isinstance(node.ctx, ast.Load):
                    found.append(f"{path.relative_to(root).as_posix()}:{node.lineno}")
    return found


def case_source(rel_file: str, case: str) -> str:
    """The source of a bound test case, plus that of each `self.<helper>` it calls.

    One level of helpers, from any class in the same file: enough to see through the
    `self.check(...)` / `self._validate(...)` fixtures these suites use, and no more -- a case
    that reaches its surface only through something further away is not obviously about it.
    """
    text = (ROOT / rel_file).read_text(encoding="utf-8")
    tree = ast.parse(text)
    methods: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.setdefault(node.name, []).append(node)
    assert case in methods, f"{rel_file} defines no {case}"
    parts = []
    for function in methods[case]:
        parts.append(ast.get_source_segment(text, function) or "")
        for node in ast.walk(function):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "self"):
                for helper in methods.get(node.attr, []):
                    parts.append(ast.get_source_segment(text, helper) or "")
    return "\n".join(parts)


class RecordsNameWhatRunsTests(unittest.TestCase):
    """Two records named enforcement that did not exist (T-153). These hold them to the code.

    L5 named `bro_receipt.verify_receipt_set` as its primary surface, and nothing called it.
    L13 named `bro_skill_evolution.validate_skill_evolution` as a fail-closed MUST surface,
    and no promotion flow calls it. The first was repointed at the function that runs; the
    second says, in the registry's own vocabulary, that it is not enforced. Neither statement
    is worth more than the last record unless something fails when it stops being true.
    """

    def test_every_declared_link_of_every_law_resolves(self):
        # `validate_traceability` DERIVES these and refuses nothing on them: a record naming
        # a function that had been deleted was reported CLAIM_ONLY and passed. On the shipped
        # registry every link must resolve.
        derived = validate_traceability(ROOT)["derived"]
        self.assertGreaterEqual(len(derived), 17)
        for entry in derived:
            with self.subTest(law=entry["id"]):
                self.assertEqual(
                    entry["links"],
                    {"surface": "STATIC_PROVEN", "test": "STATIC_PROVEN",
                     "policy": "STATIC_PROVEN", "evidence": "STATIC_PROVEN"})

    # ---- L5 ---------------------------------------------------------------

    def test_l5_names_the_function_the_completion_path_runs(self):
        self.assertEqual(_primary(_law("L5")), [("bro_receipt", "verify_receipt")])
        # ...and it does run there: the completion loop calls it, by name, inside the one
        # function the Stop gate reaches the receipts through.
        text = (ROOT / "runtime" / "bro_completion.py").read_text(encoding="utf-8")
        loop = next(node for node in ast.walk(ast.parse(text))
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "_validate_execution_receipts")
        calls = [node.func.id for node in ast.walk(loop)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        self.assertIn("verify_receipt", calls)
        self.assertNotIn("verify_receipt_set", text)

    def test_l5_cases_call_the_function_it_names(self):
        record = _law("L5")
        self.assertEqual({t["kind"] for t in record["tests"]}, {"allow", "deny"})
        for test in record["tests"]:
            with self.subTest(case=test["case"]):
                source = case_source(test["file"], test["case"])
                self.assertTrue(
                    "verify_receipt(" in source or "_validate_execution_receipts(" in source,
                    f"{test['case']} reaches neither bro_receipt.verify_receipt nor the "
                    "completion loop that calls it")

    def test_a_case_that_never_reaches_the_verifier_is_seen(self):
        # The control for the test above, on the very case L5 was bound to before: it asks
        # the RUNNER to sign with a builder key and never calls the verifier.
        source = case_source("tests/test_execution_receipts.py",
                             "test_builder_key_may_not_sign_a_receipt")
        self.assertNotIn("verify_receipt(", source)
        self.assertNotIn("_validate_execution_receipts(", source)

    def test_a_repointed_or_downgraded_law_says_so_in_a_behavioral_revision(self):
        for law_id in ("L5", "L12", "L13"):
            with self.subTest(law=law_id):
                last = _law(law_id)["revisions"][-1]
                self.assertEqual(last["type"], "Behavioral")
                self.assertEqual(last["date"], "2026-10-02")
                self.assertIn("T-153", last["note"])

    # ---- L13 --------------------------------------------------------------

    ADVISORY = {"class": "ADVISORY_OBSERVATION", "mode": "advisory",
                "normative_strength": "SHOULD"}

    def test_l13_is_declared_advisory(self):
        record = _law("L13")
        self.assertEqual(record["failure_behavior"], self.ADVISORY)
        self.assertEqual(_primary(record), [("bro_skill_evolution", "validate_skill_evolution")])
        note = record["revisions"][-1]["note"]
        self.assertIn("NOT ENFORCED AT RUNTIME", note)
        self.assertIn("nothing calls it", note)

    def test_l13_is_advisory_because_nothing_calls_its_validator(self):
        """Both directions. While nothing outside the tests calls the validator, the record
        may not claim enforcement; the day something does, this fails, and that is the day
        to give L13 back its MUST with cases that drive the flow."""
        self.assertEqual(
            code_references("validate_skill_evolution"), [],
            "something calls bro_skill_evolution.validate_skill_evolution now: L13 is no "
            "longer declared-only. Bind tests that drive that caller, then restore "
            "NORMATIVE_ENFORCEMENT / fail-closed / MUST in laws/registry.json.")
        # The control: the same question about a surface that IS called returns its callers,
        # so an empty answer above is not the scan finding nothing anywhere.
        self.assertIn("runtime/bro_completion.py",
                      {ref.split(":")[0] for ref in code_references("verify_receipt")})
        self.assertEqual({ref.split(":")[0] for ref in
                          code_references("validate_learning_registry")},
                         {"tools/bro_validate.py"})

    def test_l13_build_time_surface_is_declared_as_what_it_is(self):
        roles = {s["symbol"]: s["path_role"] for s in _law("L13")["execution_surfaces"]}
        self.assertEqual(roles["validate_learning_registry"], "build_time")

    def test_l13_cases_call_the_validator(self):
        for test in _law("L13")["tests"]:
            with self.subTest(case=test["case"]):
                self.assertIn("validate_skill_evolution(",
                              case_source(test["file"], test["case"]))

    def test_only_l13_is_declared_advisory(self):
        """Advisory is how a record stops claiming enforcement, and `bro_live_validate` then
        stops requiring ENFORCED of it. One law has given the claim up, by Owner decision.
        A second one doing so is a change to what this engine enforces, not an edit."""
        registry = json.loads((ROOT / "laws" / "registry.json").read_text(encoding="utf-8"))
        advisory = sorted(
            law["id"] for law in registry["laws"]
            if law["failure_behavior"]["class"] == "ADVISORY_OBSERVATION"
            or law["failure_behavior"]["mode"] == "advisory")
        self.assertEqual(advisory, ["L13"])

    def test_the_live_validator_never_calls_l13_enforced(self):
        from bro_live_validate import derive_live_status
        status = derive_live_status(ROOT, _law("L13"), prereq_ok=True, tests_ok=True,
                                    wiring_ok=True)
        self.assertEqual(status["enforcement_status"], "NOT_ENFORCED")
        self.assertNotEqual(status["effective_proof_level"], "LIVE_PROVEN")
        self.assertTrue(status["declared_advisory"])
        # ...and L5, repointed, is what it claims to be once its cases are observed green.
        enforced = derive_live_status(ROOT, _law("L5"), prereq_ok=True, tests_ok=True,
                                      wiring_ok=True)
        self.assertEqual(enforced["enforcement_status"], "ENFORCED")
        self.assertTrue(enforced["live"]["surfaces_defined"])

    def test_the_human_view_says_l13_is_not_enforced(self):
        index = (ROOT / "laws" / "LAW_INDEX.md").read_text(encoding="utf-8")
        section = index.split("## L13 —", 1)[1].split("\n## ", 1)[0]
        self.assertIn("not enforced at runtime", section)


if __name__ == "__main__":
    unittest.main()
