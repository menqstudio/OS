from __future__ import annotations

import json
import pathlib
import py_compile

ROOT = pathlib.Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"RED: {message}")
    raise SystemExit(1)


def main() -> int:
    required = [
        "README.md", "CLAUDE.md", "AGENTS.md", ".bro/policy.json", ".claude/settings.json",
        "config/canonical-read-manifest.json", "laws/LAW_INDEX.md", "packs/registry.json",
        "skills/index.json", "runtime/bro_policy.py", "runtime/bro_hook.py"
    ]
    for rel in required:
        if not (ROOT / rel).is_file():
            fail(f"missing {rel}")
    for rel in [".bro/policy.json", ".claude/settings.json", "config/canonical-read-manifest.json", "packs/registry.json", "skills/index.json"]:
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
    py_compile.compile(str(ROOT / "runtime/bro_policy.py"), doraise=True)
    py_compile.compile(str(ROOT / "runtime/bro_hook.py"), doraise=True)
    skill_count = json.loads((ROOT / "skills/index.json").read_text(encoding="utf-8"))["count"]
    print(f"GREEN: foundation valid; canonical={len(manifest['paths'])}; packs={registry['pack_count']}; skills={skill_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
