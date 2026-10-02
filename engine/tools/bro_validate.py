from __future__ import annotations

import json
import pathlib
import sys

# Before the imports below, which is the point: runtime/ and tools/ are digest roots, and
# compiled bytecode under one is the shadow `bro_protected.assert_no_bytecode_shadow`
# refuses on. A validator that mints it leaves the wall refusing for something the
# validator itself did.
sys.dont_write_bytecode = True

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

from bro_analytics import AnalyticsError, validate_analytics
from bro_authority import AuthorityError, validate_authority_policy
from bro_authorization import load_tool_registry
from bro_docs_freshness import DocsError, validate_docs
from bro_identity import IdentityError, validate_identity_registry
from bro_learning import LearningError, validate_learning_registry
from bro_orchestration import OrchestrationError, validate_orchestration_registry
from bro_security import SecurityError
from bro_signature import SignatureError, load_trusted_keys
from bro_traceability import TraceabilityError, validate_traceability
from bro_env_health import EnvHealthError, check_environment


def fail(message: str) -> None:
    print(f"RED: {message}")
    raise SystemExit(1)


def load_json(rel: str) -> dict:
    path = ROOT / rel
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing {rel}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {rel}: {exc}")
    if not isinstance(value, dict):
        fail(f"{rel} must contain a JSON object")
    return value


def check_compiles(root: pathlib.Path, targets: list[str]) -> None:
    """Syntax-check every target IN MEMORY.

    This was `py_compile.compile(path, doraise=True)`, which writes
    `__pycache__/<name>.pyc` beside each source whatever PYTHONDONTWRITEBYTECODE or `-B`
    say — one for every target, under two digest roots, on every run. CI grew a step to delete
    them again; a local run had nothing. `compile()` answers the same question and
    writes nothing.
    """
    for rel in targets:
        path = root / rel
        try:
            compile(path.read_bytes(), str(path), "exec", dont_inherit=True)
        except OSError as exc:
            fail(f"cannot read {rel}: {exc}")
        except (SyntaxError, ValueError) as exc:
            fail(f"{rel} does not compile: {exc}")


def count_skills(root: pathlib.Path, index: dict) -> int:
    """The number of skills, DERIVED, and refused unless every record of it agrees.

    The GREEN line used to print the index's stored `count` field, which nothing compared
    with anything: a wrong number would have been reported as fact. The list, the stored
    count, the per-skill entries and the SKILL.md files on disk must all say the same.
    """
    skills = index.get("skills")
    if not isinstance(skills, list) or not all(isinstance(item, str) and item for item in skills):
        fail("skills/index.json: `skills` must be a list of skill ids")
    if len(set(skills)) != len(skills):
        fail("skills/index.json: `skills` lists a skill more than once")
    if index.get("count") != len(skills):
        fail(f"skills/index.json: count says {index.get('count')!r}, the list holds {len(skills)}")
    entries = index.get("entries")
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        fail("skills/index.json: `entries` must be a list of objects")
    if sorted(str(item.get("id")) for item in entries) != sorted(skills):
        fail("skills/index.json: `entries` does not describe exactly the skills listed")
    for item in entries:
        if item.get("path") != f"skills/{item['id']}/SKILL.md":
            fail(f"skills/index.json: entry {item['id']!r} points at {item.get('path')!r}")
    on_disk = sorted(path.parent.name for path in (root / "skills").glob("*/SKILL.md"))
    if on_disk != sorted(skills):
        missing = sorted(set(skills) - set(on_disk))
        unlisted = sorted(set(on_disk) - set(skills))
        fail(f"skills/index.json disagrees with the skill directories: "
             f"listed but absent {missing}, present but unlisted {unlisted}")
    return len(skills)


#: The only keys a catalog entry carries. An unknown key is refused rather than ignored: a
#: field nothing reads is how `orphan_tests_forbidden` came to be declared and enforced by nothing.
CATALOG_ENTRY_KEYS = {"id", "path", "covers"}


def check_test_catalog(root: pathlib.Path, catalog: dict) -> int:
    """The number of registered test modules, refused unless the catalog names every one.

    `tests/catalog.json` declared `orphan_tests_forbidden: true` while listing 47 of the 98
    test modules on disk, and nothing read the field: this file only checked that the paths it
    DID list exist. That matters beyond tidiness, because `bro_receipt.catalog_sha256` hashes
    the catalog and an execution receipt binds that hash as "the registered tests" -- a
    catalog naming half the suite binds half of it.

    So the declaration is enforced, and is not optional: the field must be literally `true`.
    Setting it false, or deleting it, is refused in the same way `.bro/policy.json` is refused
    for a `bro_identity_count` other than one -- a switch that turns the rule off is not a
    setting, it is the rule's absence. With it true, every `tests/**/test_*.py` on disk must
    be an entry, every entry must be such a file, and each entry says what it covers.

    The helper modules beside the suites (`_kit_scripts.py`, `_brops_fixtures.py`, ...) are not
    `test_*.py`, are not collected by unittest discovery, and are correctly not entries.
    """
    where = "tests/catalog.json"
    if catalog.get("orphan_tests_forbidden") is not True:
        fail(f"{where}: `orphan_tests_forbidden` must be true -- it says "
             f"{catalog.get('orphan_tests_forbidden')!r}. The catalog's hash is what a receipt "
             "binds as the registered tests, so a catalog that may omit test modules is not "
             "one a receipt can bind")
    tests = catalog.get("tests")
    if not isinstance(tests, list) or not tests or not all(isinstance(item, dict) for item in tests):
        fail(f"{where}: `tests` must be a non-empty list of objects")
    ids: list[str] = []
    paths: list[str] = []
    for item in tests:
        test_id, path, covers = item.get("id"), item.get("path"), item.get("covers")
        if not isinstance(path, str) or not (root / path).is_file():
            fail(f"registered test missing: {path}")
        if not isinstance(test_id, str) or not test_id:
            fail(f"{where}: the entry for {path} has no id")
        if set(item) != CATALOG_ENTRY_KEYS:
            fail(f"{where}: entry {test_id!r} must carry exactly {sorted(CATALOG_ENTRY_KEYS)}, "
                 f"it carries {sorted(item)}")
        if (not isinstance(covers, list) or not covers
                or not all(isinstance(cover, str) and cover for cover in covers)):
            fail(f"{where}: entry {test_id!r} must say what it covers")
        if len(set(covers)) != len(covers):
            fail(f"{where}: entry {test_id!r} lists a cover more than once")
        ids.append(test_id)
        paths.append(path)
    repeated = sorted({value for value in ids if ids.count(value) > 1}
                      | {value for value in paths if paths.count(value) > 1})
    if repeated:
        fail(f"{where}: registered more than once: {repeated}")
    on_disk = sorted(path.relative_to(root).as_posix()
                     for path in (root / "tests").rglob("test_*.py"))
    not_modules = sorted(set(paths) - set(on_disk))
    if not_modules:
        fail(f"{where}: registered but not a tests/**/test_*.py module: {not_modules}")
    orphans = sorted(set(on_disk) - set(paths))
    if orphans:
        fail(f"{where}: orphan test modules (on disk, in no catalog entry): {orphans}")
    return len(tests)


def main() -> int:
    # `CLAUDE.md`, `AGENTS.md` and `NEXT_CHAT.md` were required here when `engine/` was its own
    # repository. In the monorepo they were agent-INSTRUCTION files that tools load by directory
    # proximity, and they told an agent working in `engine/` that it was "inside the canonical
    # menqstudio/Bro repository" and must "not touch BroPS" -- the other half of the same
    # repository. They were removed on 2026-08-08; the monorepo has exactly one of each, at the
    # root. `README.md` stays: it describes the engine rather than instructing an agent.
    # `ROADMAP.md` went with them on 2026-08-08 for a related reason -- it was a "Post-Merge"
    # roadmap frozen at 2026-07-19, naming PR #52 of the standalone repository as current. A
    # monorepo has ONE plan, and it is MASTER_EXECUTION_ROADMAP.md at the root.
    required = [
        "README.md",
        ".bro/policy.json", ".claude/settings.json", "config/canonical-read-manifest.json",
        "config/documentation-manifest.json", "config/sst-registry.json",
        "laws/LAW_INDEX.md", "laws/registry.json", "packs/registry.json",
        "agents/README.md", "agents/registry.json", "agents/authority-policy.json",
        "skills/index.json", "tests/catalog.json", "schemas/registry.json",
        "schemas/execution-lease.schema.json", "schemas/evidence-event.schema.json",
        "schemas/completion-manifest.schema.json", "schemas/verifier-receipt.schema.json",
        "schemas/recovery-record.schema.json", "schemas/release-grant.schema.json",
        "analytics/registry.json", "learning/registry.json", "release/registry.json",
        "tools/registry.json", "tools/bro_docs_freshness.py",
        "tools/bro_bind_workspace.py",
        "runtime/bro_policy.py", "runtime/bro_hook.py", "runtime/bro_contracts.py",
        "runtime/bro_identity.py", "runtime/bro_identity_hook.py", "runtime/bro_analytics.py",
        "runtime/bro_learning.py", "runtime/bro_skill_evolution.py",
        "runtime/bro_authority.py", "runtime/bro_authorization.py",
        "runtime/bro_control_plane.py", "runtime/bro_repository_state.py",
        "runtime/bro_execution_lease.py", "runtime/bro_completion.py",
        "runtime/bro_release_v3.py", "runtime/bro_recovery.py",
        "runtime/bro_orchestration.py", "runtime/bro_orchestration_runtime.py",
        "runtime/bro_orchestration_runtime_v1.py", "runtime/bro_control_room_api.py",
        "runtime/bro_workspace.py", "runtime/bro_protected.py", "runtime/bro_freeze.py",
        "runtime/bro_signature.py", "runtime/bro_evidence.py", "runtime/bro_receipt.py",
        "tools/broctl.py", "tools/bro_supervisor.py", "tools/bro_run_receipt.py",
        "config/protected-control-plane.json",
        "tests/test_orchestration_runtime.py", "tests/test_orchestration_runtime_claims.py",
        "tests/test_control_room_api.py", "tests/test_workspace_scope.py",
        "tests/test_control_plane_digest.py", "tests/test_signature_authority.py",
        "tests/test_runtime_atomicity.py", "tests/test_evidence_chain.py",
        "tests/test_reconciler.py", "tests/test_supervisor.py",
        "tests/test_execution_receipts.py",
    ]
    for rel in required:
        if not (ROOT / rel).is_file():
            fail(f"missing {rel}")

    manifest = load_json("config/canonical-read-manifest.json")
    for rel in manifest.get("paths", []):
        if not (ROOT / rel).is_file():
            fail(f"canonical path missing: {rel}")

    domains = load_json("config/sst-registry.json").get("domains")
    if not isinstance(domains, list) or not domains:
        fail("SST registry has no domains")
    seen_domains: set[str] = set()
    seen_sources: set[str] = set()
    for item in domains:
        if not isinstance(item, dict):
            fail("SST domain entry must be an object")
        domain, source, validator = item.get("domain"), item.get("sst"), item.get("validator")
        if not all(isinstance(x, str) for x in (domain, source, validator)):
            fail("SST domain entry is incomplete")
        if domain in seen_domains or source in seen_sources:
            fail("duplicate SST domain or source")
        seen_domains.add(domain)
        seen_sources.add(source)
        if not (ROOT / source).is_file() or not (ROOT / validator).is_file():
            fail(f"SST source or validator missing for {domain}")

    test_modules = check_test_catalog(ROOT, load_json("tests/catalog.json"))

    schema_paths = []
    for item in load_json("schemas/registry.json").get("schemas", []):
        path = item.get("path")
        if not isinstance(path, str) or not (ROOT / path).is_file():
            fail(f"registered schema missing: {path}")
        load_json(path)
        schema_paths.append(path)

    if load_json(".bro/policy.json").get("bro_identity_count") != 1:
        fail("Bro identity count must be exactly one")

    try:
        identity = validate_identity_registry(ROOT)
        authority_count = validate_authority_policy(ROOT)
        docs_count = validate_docs(ROOT)
        analytics = validate_analytics(ROOT)
        validate_learning_registry(ROOT)
        orchestration = validate_orchestration_registry(ROOT)
        tool_registry = load_tool_registry(ROOT)
        traceability = validate_traceability(ROOT)
        env_health = check_environment(ROOT)
        trusted_keys = load_trusted_keys(ROOT)
    except (
        IdentityError,
        AuthorityError,
        DocsError,
        AnalyticsError,
        LearningError,
        OrchestrationError,
        SecurityError,
        SignatureError,
        TraceabilityError,
        EnvHealthError,
    ) as exc:
        fail(str(exc))

    compile_targets = [
        "runtime/bro_policy.py", "runtime/bro_hook.py", "runtime/bro_contracts.py",
        "runtime/bro_identity.py", "runtime/bro_identity_hook.py", "runtime/bro_analytics.py",
        "runtime/bro_learning.py", "runtime/bro_skill_evolution.py",
        "runtime/bro_authority.py", "runtime/bro_authorization.py",
        "runtime/bro_control_plane.py", "runtime/bro_repository_state.py",
        "runtime/bro_execution_lease.py", "runtime/bro_completion.py",
        "runtime/bro_release_v3.py", "runtime/bro_recovery.py",
        "runtime/bro_orchestration.py", "runtime/bro_orchestration_runtime.py",
        "runtime/bro_orchestration_runtime_v1.py", "runtime/bro_control_room_api.py",
        "runtime/bro_workspace.py", "runtime/bro_protected.py", "runtime/bro_freeze.py",
        "runtime/bro_signature.py", "runtime/bro_evidence.py",
        "runtime/bro_receipt.py",
        "tools/bro_docs_freshness.py", "tools/bro_bind_workspace.py", "tools/broctl.py",
        "tools/bro_skill_receipt.py", "tools/bro_authorize_specialist.py",
        "tools/bro_supervisor.py", "tools/bro_run_receipt.py", "tools/bro_traceability.py",
        "runtime/bro_env_health.py", "runtime/bro_secrets.py",
        "runtime/bro_audit_log.py", "runtime/bro_stop_controller.py",
        "tools/bro_live_validate.py", "tools/bro_backup.py", "tools/bro_monitor.py",
    ]
    check_compiles(ROOT, compile_targets)

    skill_count = count_skills(ROOT, load_json("skills/index.json"))
    print(
        "GREEN: static foundation validation passed; "
        f"canonical={len(manifest.get('paths', []))}; sst_domains={len(domains)}; "
        f"packs={identity['pack_count']}; agents={identity['agent_count']}; "
        f"authorities={authority_count}; skills={skill_count}; schemas={len(schema_paths)}; "
        f"test_modules={test_modules}; "
        f"documents={docs_count}; metrics={analytics['metrics']}; "
        f"dashboards={analytics['dashboards']}; orchestration_states={orchestration['states']}; "
        f"control_room_surfaces={orchestration['surfaces']}; tools={len(tool_registry['tools'])}; "
        f"meta_principles={traceability['meta_layer_principles']}; "
        f"runtime_deps={traceability['runtime_dependencies']}; "
        f"law_records={traceability['law_records_backfilled']}; "
        f"deps_healthy={len(env_health['checked'])}; "
        f"trusted_keys={len(trusted_keys)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
