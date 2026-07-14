from __future__ import annotations

import json
import pathlib
import py_compile
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_analytics import AnalyticsError, validate_analytics
from bro_authorization import load_tool_registry
from bro_identity import IdentityError, validate_identity_registry
from bro_learning import LearningError, validate_learning_registry
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
        "config/sst-registry.json", "laws/LAW_INDEX.md", "laws/registry.json",
        "packs/registry.json", "agents/README.md", "agents/registry.json",
        "skills/index.json", "tests/catalog.json", "schemas/registry.json",
        "analytics/registry.json", "learning/registry.json", "release/registry.json",
        "tools/registry.json",
        "runtime/bro_policy.py", "runtime/bro_hook.py", "runtime/bro_contracts.py",
        "runtime/bro_identity.py", "runtime/bro_identity_hook.py", "runtime/bro_analytics.py",
        "runtime/bro_learning.py", "runtime/bro_skill_evolution.py",
        "runtime/bro_authorization.py", "runtime/bro_control_plane.py",
    ]
    for rel in required:
        if not (ROOT / rel).is_file():
            fail(f"missing {rel}")

    manifest = load_json("config/canonical-read-manifest.json")
    for rel in manifest.get("paths", []):
        if not (ROOT / rel).is_file():
            fail(f"canonical path missing: {rel}")

    sst = load_json("config/sst-registry.json")
    domains = sst.get("domains")
    if not isinstance(domains, list) or not domains:
        fail("SST registry has no domains")
    seen_domains: set[str] = set()
    seen_sources: set[str] = set()
    for item in domains:
        if not isinstance(item, dict):
            fail("SST domain entry must be an object")
        domain = item.get("domain")
        source = item.get("sst")
        validator = item.get("validator")
        if not isinstance(domain, str) or not isinstance(source, str) or not isinstance(validator, str):
            fail("SST domain entry is incomplete")
        if domain in seen_domains:
            fail(f"duplicate SST domain owner: {domain}")
        if source in seen_sources:
            fail(f"one SST path owns multiple domains: {source}")
        seen_domains.add(domain)
        seen_sources.add(source)
        if not (ROOT / source).is_file():
            fail(f"SST path missing for {domain}: {source}")
        if not (ROOT / validator).is_file():
            fail(f"SST validator missing for {domain}: {validator}")

    test_catalog = load_json("tests/catalog.json")
    for item in test_catalog.get("tests", []):
        path = item.get("path")
        if not isinstance(path, str) or not (ROOT / path).is_file():
            fail(f"registered test missing: {path}")

    schema_registry = load_json("schemas/registry.json")
    schema_paths = []
    for item in schema_registry.get("schemas", []):
        path = item.get("path")
        if not isinstance(path, str) or not (ROOT / path).is_file():
            fail(f"registered schema missing: {path}")
        load_json(path)
        schema_paths.append(path)

    policy = load_json(".bro/policy.json")
    if policy.get("bro_identity_count") != 1:
        fail("Bro identity count must be exactly one")

    try:
        identity = validate_identity_registry(ROOT)
        analytics = validate_analytics(ROOT)
        validate_learning_registry(ROOT)
        tool_registry = load_tool_registry(ROOT)
    except (IdentityError, AnalyticsError, LearningError, SecurityError) as exc:
        fail(str(exc))

    compile_targets = [
        "runtime/bro_policy.py", "runtime/bro_hook.py", "runtime/bro_contracts.py",
        "runtime/bro_identity.py", "runtime/bro_identity_hook.py", "runtime/bro_analytics.py",
        "runtime/bro_learning.py", "runtime/bro_skill_evolution.py",
        "runtime/bro_authorization.py", "runtime/bro_control_plane.py",
    ]
    for rel in compile_targets:
        py_compile.compile(str(ROOT / rel), doraise=True)

    skill_count = load_json("skills/index.json").get("count")
    print(
        "GREEN: foundation valid; "
        f"canonical={len(manifest.get('paths', []))}; "
        f"sst_domains={len(domains)}; packs={identity['pack_count']}; "
        f"agents={identity['agent_count']}; skills={skill_count}; "
        f"schemas={len(schema_paths)}; metrics={analytics['metrics']}; "
        f"dashboards={analytics['dashboards']}; tools={len(tool_registry['tools'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
