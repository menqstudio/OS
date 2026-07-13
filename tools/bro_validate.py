from __future__ import annotations

import json
import pathlib
import py_compile
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_identity import IdentityError, validate_identity_registry


def fail(message: str) -> None:
    print(f"RED: {message}")
    raise SystemExit(1)


def main() -> int:
    required = [
        "README.md", "CLAUDE.md", "AGENTS.md", ".bro/policy.json", ".claude/settings.json",
        "config/canonical-read-manifest.json", "laws/LAW_INDEX.md", "packs/registry.json",
        "agents/README.md", "agents/registry.json", "skills/index.json", "runtime/bro_policy.py",
        "runtime/bro_hook.py", "runtime/bro_contracts.py", "runtime/bro_identity.py",
        "runtime/bro_identity_hook.py", "schemas/agent-profile.schema.json"
    ]
    for rel in required:
        if not (ROOT / rel).is_file():
            fail(f"missing {rel}")
    json_files = [
        ".bro/policy.json", ".claude/settings.json", "config/canonical-read-manifest.json",
        "packs/registry.json", "agents/registry.json", "skills/index.json",
        "schemas/task-contract.schema.json", "schemas/skill-receipt.schema.json",
        "schemas/agent-profile.schema.json", "schemas/release-grant.schema.json"
    ]
    for rel in json_files:
        json.loads((ROOT / rel).read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "config/canonical-read-manifest.json").read_text(encoding="utf-8"))
    for rel in manifest["paths"]:
        if not (ROOT / rel).is_file():
            fail(f"canonical path missing: {rel}")
    policy = json.loads((ROOT / ".bro/policy.json").read_text(encoding="utf-8"))
    if policy["bro_identity_count"] != 1:
        fail("Bro identity count must be exactly one")
    registry = json.loads((ROOT / "packs/registry.json").read_text(encoding="utf-8"))
    for pack in registry["packs"]:
        for role in pack["roles"]:
            if " bro" in f" {role.lower()} ":
                fail(f"subordinate role may not use Bro: {role}")
    try:
        identity = validate_identity_registry(ROOT)
    except IdentityError as exc:
        fail(f"agent identity registry invalid: {exc}")
    for rel in [
        "runtime/bro_policy.py", "runtime/bro_hook.py", "runtime/bro_contracts.py",
        "runtime/bro_identity.py", "runtime/bro_identity_hook.py"
    ]:
        py_compile.compile(str(ROOT / rel), doraise=True)
    skill_count = json.loads((ROOT / "skills/index.json").read_text(encoding="utf-8"))["count"]
    print(
        f"GREEN: foundation valid; canonical={len(manifest['paths'])}; "
        f"packs={registry['pack_count']}; agents={identity['agent_count']}; skills={skill_count}; schemas=4"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
