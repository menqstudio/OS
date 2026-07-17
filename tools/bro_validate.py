from __future__ import annotations

import json
import pathlib
import py_compile
import sys

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


def main() -> int:
    required = [
        "README.md", "CLAUDE.md", "AGENTS.md", "ROADMAP.md", "NEXT_CHAT.md",
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
        "runtime/bro_signature.py", "tools/broctl.py", "tools/bro_supervisor.py",
        "config/protected-control-plane.json",
        "tests/test_orchestration_runtime.py", "tests/test_orchestration_runtime_claims.py",
        "tests/test_control_room_api.py", "tests/test_workspace_scope.py",
        "tests/test_control_plane_digest.py", "tests/test_signature_authority.py",
        "tests/test_supervisor.py",
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

    for item in load_json("tests/catalog.json").get("tests", []):
        path = item.get("path")
        if not isinstance(path, str) or not (ROOT / path).is_file():
            fail(f"registered test missing: {path}")

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
    except (
        IdentityError,
        AuthorityError,
        DocsError,
        AnalyticsError,
        LearningError,
        OrchestrationError,
        SecurityError,
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
        "runtime/bro_signature.py",
        "tools/bro_docs_freshness.py", "tools/bro_bind_workspace.py", "tools/broctl.py",
        "tools/bro_supervisor.py",
    ]
    for rel in compile_targets:
        py_compile.compile(str(ROOT / rel), doraise=True)

    skill_count = load_json("skills/index.json").get("count")
    print(
        "GREEN: static foundation validation passed; "
        f"canonical={len(manifest.get('paths', []))}; sst_domains={len(domains)}; "
        f"packs={identity['pack_count']}; agents={identity['agent_count']}; "
        f"authorities={authority_count}; skills={skill_count}; schemas={len(schema_paths)}; "
        f"documents={docs_count}; metrics={analytics['metrics']}; "
        f"dashboards={analytics['dashboards']}; orchestration_states={orchestration['states']}; "
        f"control_room_surfaces={orchestration['surfaces']}; tools={len(tool_registry['tools'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
