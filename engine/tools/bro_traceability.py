"""OLTS traceability validator (Execution Surface kind=validator).

Static enforcement of the Operating Law Traceability Specification (OLTS) and the
Meta-Layer v1.1 Traceability / Verifiability / Derivability principles.

Design constraints (from OLTS):
  * Declared vs Derived: this module NEVER reads a proof level, effective proof or
    enforcement status from the SST. Those are DERIVED here and MUST NOT be declared
    (Derivability Principle MP-12). A record that declares them is rejected.
  * Proof honesty: static checks may emit at most STATIC_PROVEN. LIVE_PROVEN is only
    issuable by live/integration validation, not by this static validator
    (Verifiability Principle MP-11).
  * Pure standard library — no third-party import — so the validator itself has no
    unresolved runtime prerequisite.
"""
from __future__ import annotations

import ast
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


class TraceabilityError(ValueError):
    """Raised on any traceability compliance failure (fail-closed)."""


# ---- OLTS enums (declared-field legal values) ----------------------------------
SURFACE_KINDS = {
    "runtime", "startup", "hook", "validator", "recorder",
    "signer", "verifier", "scheduler", "build", "release", "recovery",
}
PATH_ROLES = {"primary", "defense_in_depth", "build_time"}
ENFORCEMENT_CLASSES = {"NORMATIVE_ENFORCEMENT", "RECOVERY_SELF_HEAL", "ADVISORY_OBSERVATION"}
FAILURE_MODES = {"fail-closed", "self-heal", "advisory"}
RETENTIONS = {"ephemeral", "session", "task", "retained"}
INTEGRITY_LEVELS = {"Unsigned", "Signed", "Hash-Chained"}
TRUST_SOURCES = {"Self", "Independent", "Owner", "External"}
NORMATIVE_STRENGTHS = {"MUST", "MUST_NOT", "SHALL", "SHOULD", "MAY"}
TEST_KINDS = {"allow", "deny"}
REQUIRED_FOR = {"runtime", "validation", "test", "build"}

# Derived attributes may never be declared in the SST.
DERIVED_FORBIDDEN = {
    "proof_level", "effective_proof_level", "enforcement_status",
    "achieved_proof", "required_proof",
}

# Proof Level lattice (derived only).
PROOF_ORDER = ["CLAIM_ONLY", "STATIC_PROVEN", "LIVE_PROVEN", "FORMALLY_VERIFIED"]
STRONG_NORMATIVE = {"MUST", "MUST_NOT", "SHALL"}

REQUIRED_LAW_FIELDS = {
    "id", "responsibility", "policy_source", "execution_surfaces",
    "tests", "evidence", "failure_behavior", "owner", "revisions",
    "runtime_prerequisites",
}

REQUIRED_META_PRINCIPLES = {"Traceability Principle", "Verifiability Principle", "Derivability Principle"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TraceabilityError(message)


def load_json(root: pathlib.Path, rel: str) -> dict:
    path = root / rel
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TraceabilityError(f"missing {rel}") from exc
    except json.JSONDecodeError as exc:
        raise TraceabilityError(f"invalid JSON in {rel}: {exc}") from exc
    _require(isinstance(value, dict), f"{rel} must be a JSON object")
    return value


# ---- Meta-Layer -----------------------------------------------------------------
def load_meta_layer(root: pathlib.Path = ROOT) -> dict:
    data = load_json(root, "laws/meta-layer.json")
    principles = data.get("principles")
    _require(isinstance(principles, list) and principles, "meta-layer has no principles")
    ids, names = set(), set()
    for p in principles:
        _require(isinstance(p, dict), "meta-layer principle must be an object")
        pid, name = p.get("id"), p.get("name")
        _require(isinstance(pid, str) and pid not in ids, f"duplicate/invalid principle id: {pid}")
        _require(isinstance(name, str) and name not in names, f"duplicate/invalid principle name: {name}")
        _require(isinstance(p.get("normative_text"), str) and len(p["normative_text"]) >= 16,
                 f"principle {pid} has no normative text")
        ids.add(pid)
        names.add(name)
    missing = REQUIRED_META_PRINCIPLES - names
    _require(not missing, f"meta-layer v1.1 is missing principles: {sorted(missing)}")
    return data


# ---- Runtime dependencies (chain node: Runtime Prerequisites) --------------------
def load_runtime_dependencies(root: pathlib.Path = ROOT) -> dict:
    data = load_json(root, "config/runtime-dependencies.json")
    deps = data.get("dependencies")
    _require(isinstance(deps, list) and deps, "runtime-dependencies has no entries")
    by_id: dict[str, dict] = {}
    for d in deps:
        _require(isinstance(d, dict), "dependency entry must be an object")
        did = d.get("id")
        _require(isinstance(did, str) and did not in by_id, f"duplicate/invalid dependency id: {did}")
        version = d.get("version")
        _require(isinstance(version, str) and version.strip() != "",
                 f"dependency {did} MUST declare a pinned or constrained version")
        rf = d.get("required_for")
        _require(isinstance(rf, list) and rf and set(rf) <= REQUIRED_FOR,
                 f"dependency {did} has an invalid required_for")
        _require(d.get("optionality") in {"required", "optional"},
                 f"dependency {did} has an invalid optionality")
        by_id[did] = d
    return by_id


# ---- Static reachability helpers ------------------------------------------------
def _module_path(root: pathlib.Path, module: str) -> pathlib.Path | None:
    for base in ("runtime", "tools"):
        candidate = root / base / f"{module}.py"
        if candidate.is_file():
            return candidate
    return None


def symbol_defined(root: pathlib.Path, module: str, symbol: str) -> bool:
    """True if `symbol` is a top-level def/class in runtime/<module>.py or tools/<module>.py."""
    path = _module_path(root, module)
    if path is None:
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
            return True
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == symbol:
                    return True
    return False


def test_case_defined(root: pathlib.Path, rel_file: str, case: str) -> bool:
    """True if `case` is a concrete test method (not merely the file) in rel_file."""
    path = root / rel_file
    if not path.is_file():
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == case:
            return True
    return False


# ---- Law-record structural validation -------------------------------------------
def validate_law_record(record: dict, known_dependencies: set[str] | None = None) -> None:
    _require(isinstance(record, dict), "law record must be an object")

    declared_derived = DERIVED_FORBIDDEN & set(record)
    _require(not declared_derived,
             f"law {record.get('id')} declares derived field(s) {sorted(declared_derived)}; "
             "proof/status are derived, never hand-written (MP-12)")

    missing = REQUIRED_LAW_FIELDS - set(record)
    _require(not missing, f"law {record.get('id')} missing required fields: {sorted(missing)}")

    _require(isinstance(record["policy_source"], list) and record["policy_source"],
             f"law {record['id']} needs >=1 policy_source")

    surfaces = record["execution_surfaces"]
    _require(isinstance(surfaces, list) and surfaces, f"law {record['id']} has no execution_surfaces (orphan law)")
    for s in surfaces:
        _require(isinstance(s, dict), "surface must be an object")
        _require(s.get("kind") in SURFACE_KINDS, f"law {record['id']} surface has invalid kind {s.get('kind')}")
        _require(s.get("path_role") in PATH_ROLES, f"law {record['id']} surface has invalid path_role")
        _require(isinstance(s.get("module"), str) and isinstance(s.get("symbol"), str),
                 f"law {record['id']} surface missing module/symbol")

    tests = record["tests"]
    _require(isinstance(tests, list) and tests, f"law {record['id']} has no tests")
    kinds = set()
    for t in tests:
        _require(isinstance(t, dict), "test must be an object")
        _require(t.get("kind") in TEST_KINDS, f"law {record['id']} test has invalid kind")
        _require(isinstance(t.get("file"), str) and isinstance(t.get("case"), str),
                 f"law {record['id']} test missing file/case")
        kinds.add(t["kind"])
    _require({"allow", "deny"} <= kinds, f"law {record['id']} MUST bind >=1 allow and >=1 deny test")

    ev = record["evidence"]
    _require(isinstance(ev, dict), "evidence must be an object")
    _require(ev.get("retention") in RETENTIONS, f"law {record['id']} evidence has invalid retention")
    _require(ev.get("integrity_level") in INTEGRITY_LEVELS, f"law {record['id']} evidence has invalid integrity_level")
    _require(ev.get("trust_source") in TRUST_SOURCES, f"law {record['id']} evidence has invalid trust_source")
    for key in ("schema", "writer", "verifier"):
        _require(isinstance(ev.get(key), str) and ev[key], f"law {record['id']} evidence missing {key}")

    fb = record["failure_behavior"]
    _require(isinstance(fb, dict), "failure_behavior must be an object")
    _require(fb.get("class") in ENFORCEMENT_CLASSES, f"law {record['id']} invalid enforcement class")
    _require(fb.get("mode") in FAILURE_MODES, f"law {record['id']} invalid failure mode")
    strength = fb.get("normative_strength")
    _require(strength in NORMATIVE_STRENGTHS, f"law {record['id']} invalid normative_strength")

    # MP-11 binding: a MUST/MUST NOT/SHALL law's primary enforcement MUST be fail-closed
    # normative enforcement; advisory can never satisfy a MUST.
    if strength in STRONG_NORMATIVE:
        _require(fb["class"] == "NORMATIVE_ENFORCEMENT",
                 f"law {record['id']} is {strength} but not NORMATIVE_ENFORCEMENT")
        _require(fb["mode"] == "fail-closed",
                 f"law {record['id']} is {strength} but its primary mode is not fail-closed")
        _require(any(s.get("path_role") == "primary" for s in surfaces),
                 f"law {record['id']} is {strength} but declares no primary execution surface")

    prereqs = record["runtime_prerequisites"]
    _require(isinstance(prereqs, list), f"law {record['id']} runtime_prerequisites must be a list")
    if known_dependencies is not None:
        for dep in prereqs:
            _require(dep in known_dependencies,
                     f"law {record['id']} references undeclared dependency '{dep}' (dead prerequisite)")


# ---- Derived proof (STATIC only; LIVE is out of scope for this validator) --------
def derive_static_proof(root: pathlib.Path, record: dict) -> dict:
    """Return per-link static proof and the derived effective proof level.

    A link is STATIC_PROVEN when its artifact is statically resolvable; otherwise
    CLAIM_ONLY. This function MUST NOT return LIVE_PROVEN (MP-11): live reachability,
    prerequisite resolution and evidence round-trip are proven only by integration
    tests.
    """
    links: dict[str, str] = {}
    surfaces_ok = all(symbol_defined(root, s["module"], s["symbol"]) for s in record["execution_surfaces"])
    links["surface"] = "STATIC_PROVEN" if surfaces_ok else "CLAIM_ONLY"
    tests_ok = all(test_case_defined(root, t["file"], t["case"]) for t in record["tests"])
    links["test"] = "STATIC_PROVEN" if tests_ok else "CLAIM_ONLY"
    policy_ok = all((root / p).exists() for p in record["policy_source"])
    links["policy"] = "STATIC_PROVEN" if policy_ok else "CLAIM_ONLY"
    ev = record["evidence"]
    evidence_ok = (root / ev["writer"]).exists() and (root / ev["verifier"]).exists()
    links["evidence"] = "STATIC_PROVEN" if evidence_ok else "CLAIM_ONLY"

    effective = "STATIC_PROVEN"
    for level in links.values():
        if PROOF_ORDER.index(level) < PROOF_ORDER.index(effective):
            effective = level
    # A MUST-law can only reach ENFORCED at LIVE_PROVEN, which static analysis cannot grant.
    strong = record["failure_behavior"]["normative_strength"] in STRONG_NORMATIVE
    enforcement_status = "STATIC_ONLY" if effective == "STATIC_PROVEN" else "NOT_ENFORCED"
    return {
        "id": record["id"],
        "links": links,
        "effective_proof_level": effective,
        "enforcement_status": enforcement_status,
        "live_required": bool(strong),
    }


# ---- Corpus checks (orphans / duplicates) ---------------------------------------
def check_corpus(records: list[dict]) -> None:
    ids = [r.get("id") for r in records]
    dupes = {i for i in ids if ids.count(i) > 1}
    _require(not dupes, f"duplicate law ids: {sorted(dupes)}")


def verify_law_index_sync(root: pathlib.Path, records: list[dict]) -> None:
    """Mechanically verify the derived human view (LAW_INDEX.md) has not drifted.

    Derivability Principle MP-12: LAW_INDEX.md is a derived/verified view, never an
    independent authority. Every canonical law id and name MUST appear in it.
    """
    index_path = root / "laws" / "LAW_INDEX.md"
    if not index_path.is_file():
        raise TraceabilityError("laws/LAW_INDEX.md (derived human view) is missing")
    text = index_path.read_text(encoding="utf-8")
    for record in records:
        lid, name = record.get("id"), record.get("name", "")
        _require(lid in text, f"human view drift: {lid} absent from LAW_INDEX.md")
        _require(name == "" or name in text, f"human view drift: name of {lid} absent from LAW_INDEX.md")


# ---- Top-level entrypoint -------------------------------------------------------
def validate_traceability(root: pathlib.Path = ROOT) -> dict:
    """Validate the OLTS machinery + any backfilled law records. Returns a report.

    Fail-closed: raises TraceabilityError on any structural compliance failure.
    """
    load_meta_layer(root)
    known = set(load_runtime_dependencies(root))

    registry = load_json(root, "laws/registry.json")
    records = [law for law in registry.get("laws", []) if isinstance(law, dict) and "responsibility" in law]
    check_corpus(records)
    if records:
        verify_law_index_sync(root, records)
    derived = []
    for record in records:
        validate_law_record(record, known_dependencies=known)
        derived.append(derive_static_proof(root, record))

    return {
        "meta_layer_principles": len(load_meta_layer(root)["principles"]),
        "runtime_dependencies": len(known),
        "law_records_backfilled": len(records),
        "derived": derived,
    }


if __name__ == "__main__":
    report = validate_traceability()
    print(
        "GREEN: OLTS traceability structure valid; "
        f"principles={report['meta_layer_principles']}; "
        f"dependencies={report['runtime_dependencies']}; "
        f"law_records_backfilled={report['law_records_backfilled']}"
    )
