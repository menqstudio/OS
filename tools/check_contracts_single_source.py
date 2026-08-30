#!/usr/bin/env python3
"""`contracts/` is the single source for the cross-half schemas — fail-closed drift gate.

Ninth audit `I-13`: *"Two Phase-10 boxes are closable by a Builder change, against the claim that
every open box is blocked by the production gate or deployment."* They were. `contracts/` was a lone
README describing an intention while `engine/schemas/` held the real files, and no service principal,
launcher, broker or deployment stood between that state and a finished one.

WHAT "SINGLE SOURCE" MEANS HERE, EXACTLY
  `contracts/` holds the source of record for the five schemas both halves consume. `engine/schemas/`
  keeps a byte-identical vendored copy, because the engine resolves every schema path relative to its
  OWN root and is a git subtree of `menqstudio/Bro` — pointing its loaders outside that root is a
  deliberate change to the containment model its perimeter is built on, and moving files out forks
  the vendored half from upstream. So the copy stays and this gate makes it not a duplicate: edit
  one side alone and CI goes RED naming the file and the direction of the drift.

  That is a weaker claim than "one file exists", and it is stated rather than dressed up. What it
  buys is the property the roadmap box actually asks for — one definition both halves are held to —
  at no cost to audited security code. The remaining relocation is M2's last step in
  `docs/design/CONTRACTS_DEDUPE_PLAN.md`, and it needs its own audited engine branch.

WHAT IS CHECKED
  1. every contract in `contracts/index.json` exists in `contracts/`                       -> else RED
  2. its `engine/schemas/` copy exists and is BYTE-IDENTICAL                               -> else RED
  3. `engine/schemas/registry.json` still lists it (the engine really loads this file)     -> else RED
  4. the declared `version` equals the schema's own const at `version_pointer`             -> else RED
  5. the cross-half + engine-internal split is EXHAUSTIVE over `engine/schemas/`           -> else RED
     (a new engine schema has to be classified by a person, not defaulted into silence)
  6. no `*.schema.json` basename appears anywhere else in the tree                         -> else RED
     (a third copy is the failure this whole milestone exists to prevent)

Usage:  python tools/check_contracts_single_source.py [--root DIR]
Exit 0 + "GREEN: ..." / exit 1 + the problems.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

CONTRACTS = pathlib.Path("contracts")
INDEX = CONTRACTS / "index.json"
ENGINE_SCHEMAS = pathlib.Path("engine") / "schemas"
#: The desktop half's equivalent (T-055). Symmetric with ENGINE_SCHEMAS and held to
#: the same rule: a schema here must be classified by a person, and an id the index
#: names with no file behind it is refused.
DESKTOP_SCHEMAS = pathlib.Path("apps") / "desktop" / "src-tauri" / "core" / "schema"
ENGINE_REGISTRY = ENGINE_SCHEMAS / "registry.json"

#: Trees that legitimately hold their own `*.schema.json` and are not part of this milestone:
#: two wire protocols between named processes (M3 of the plan) plus the two source/copy homes.
_ALLOWED_SCHEMA_DIRS = (
    "contracts",
    "engine/schemas",
    "engine/contracts",
    "bridge/contracts",
    # The desktop half's own schemas, added by T-055 and symmetric with
    # `engine/schemas`. It is NOT `contracts/`: every entry in the index there
    # carries `crosses`, and a schema written and read by `brops-core` alone
    # does not cross halves -- putting it there would assert a binding that does
    # not exist, which is the failure this gate is for, arriving from the other
    # side. The split stays exhaustive rather than assumed because
    # `contracts/index.json` lists these ids under `desktop_internal`, the way
    # `engine_internal` already lists the engine's fifteen.
    "apps/desktop/src-tauri/core/schema",
)
#: Never walked: build output and dependency trees carry thousands of unrelated schema files,
#: and `worktrees` carries a whole second copy of this repository.
#:
#: The Agent tool checks a subagent's isolated copy out under `.claude/worktrees/<agent-id>/`.
#: On 2026-08-30 that copy put all five `contracts/` schemas and all four `bridge/contracts/`
#: schemas outside every declared home at once, and this gate reported nine strays on a tree
#: whose real content was untouched -- RED locally, green in CI, which is a verdict about the
#: machine rather than the code.
_SKIP_DIRS = {".git", "node_modules", "target", "dist", "dist-ssr", ".venv", "__pycache__",
              "build", "worktrees"}


def load_index(root: pathlib.Path) -> dict:
    path = root / INDEX
    if not path.exists():
        raise SystemExit(f"RED: missing {INDEX} — the contract index is what makes contracts/ a source")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc.get("contracts"), list) or not doc["contracts"]:
        raise SystemExit(f'RED: {INDEX} must carry a non-empty "contracts" array')
    return doc


def resolve_pointer(doc: object, pointer: str):
    """Minimal RFC-6901 resolution — enough for the `/properties/.../const` paths in the index."""
    cur = doc
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(cur, dict) or token not in cur:
            return None
        cur = cur[token]
    return cur


def stray_schema_files(root: pathlib.Path) -> list[pathlib.Path]:
    """`*.schema.json` outside every declared home — a third copy nobody is holding to anything."""
    strays: list[pathlib.Path] = []
    for path in root.rglob("*.schema.json"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        if any(rel.startswith(d + "/") for d in _ALLOWED_SCHEMA_DIRS):
            continue
        strays.append(path.relative_to(root))
    return sorted(strays)


def check(root: pathlib.Path) -> list[str]:
    problems: list[str] = []
    doc = load_index(root)

    registry_ids: set[str] = set()
    reg_path = root / ENGINE_REGISTRY
    if not reg_path.exists():
        problems.append(f"missing {ENGINE_REGISTRY} — cannot confirm the engine still loads these")
    else:
        registry = json.loads(reg_path.read_text(encoding="utf-8"))
        registry_ids = {
            item.get("id") for item in registry.get("schemas", []) if isinstance(item, dict)
        }

    declared_cross: set[str] = set()
    for entry in doc["contracts"]:
        cid = entry.get("id")
        declared_cross.add(cid)
        name = entry.get("file")
        if not cid or not name:
            problems.append(f"index entry {entry!r} needs both an id and a file")
            continue

        src = root / CONTRACTS / name
        copy = root / ENGINE_SCHEMAS / name
        if not src.exists():
            problems.append(f"{cid}: {CONTRACTS / name} is missing — the SOURCE of record is not there")
            continue
        if not copy.exists():
            problems.append(f"{cid}: {ENGINE_SCHEMAS / name} is missing — the engine loads by that path")
            continue

        src_bytes, copy_bytes = src.read_bytes(), copy.read_bytes()
        if src_bytes != copy_bytes:
            problems.append(
                f"{cid}: {CONTRACTS / name} and {ENGINE_SCHEMAS / name} have DRIFTED "
                f"({len(src_bytes)} vs {len(copy_bytes)} bytes). contracts/ is the source: make the "
                f"change there and copy it across in the same commit"
            )

        if registry_ids and cid not in registry_ids:
            problems.append(
                f"{cid}: not listed in {ENGINE_REGISTRY}, so the engine does not load it — either it "
                f"is not a cross-half contract or the registry lost an entry"
            )

        pointer = entry.get("version_pointer")
        declared = entry.get("version")
        if pointer:
            found = resolve_pointer(json.loads(src.read_text(encoding="utf-8")), pointer)
            if found is None:
                problems.append(f"{cid}: version_pointer {pointer} resolves to nothing in the schema")
            elif found != declared:
                problems.append(
                    f"{cid}: index says version {declared!r} but the schema says {found!r} at "
                    f"{pointer} — a version bump belongs in both, in one commit"
                )

    internal = set(doc.get("engine_internal", {}).get("ids", []))
    overlap = declared_cross & internal
    if overlap:
        problems.append(f"classified twice: {', '.join(sorted(overlap))} is both cross-half and engine-internal")

    schemas_dir = root / ENGINE_SCHEMAS
    if schemas_dir.is_dir():
        on_disk = {p.name[: -len(".schema.json")] for p in schemas_dir.glob("*.schema.json")}
        unclassified = on_disk - declared_cross - internal
        if unclassified:
            problems.append(
                f"{len(unclassified)} schema(s) in {ENGINE_SCHEMAS} are in neither list — "
                f"{', '.join(sorted(unclassified))}. A new schema has to be classified as cross-half "
                f"or engine-internal by a person; defaulting it into silence is how the two halves "
                f"drift in the first place"
            )
        phantom = (declared_cross | internal) - on_disk
        if phantom:
            problems.append(
                f"the index names schema(s) that {ENGINE_SCHEMAS} does not have: "
                f"{', '.join(sorted(phantom))}"
            )

    # The same rule for the desktop half. Without this the `desktop_internal` block
    # in the index would be prose: a registry entry nothing reads is the defect
    # T-056 exists to catch, and adding one while writing this gate would be a poor
    # joke. Deleting either arm below turns a test red.
    desktop_internal = set(doc.get("desktop_internal", {}).get("ids", []))
    both = desktop_internal & (declared_cross | internal)
    if both:
        problems.append(
            f"classified twice: {', '.join(sorted(both))} is desktop-internal and also "
            f"cross-half or engine-internal"
        )
    desktop_dir = root / DESKTOP_SCHEMAS
    if desktop_dir.is_dir():
        on_disk = {p.name[: -len(".schema.json")] for p in desktop_dir.glob("*.schema.json")}
        unclassified = on_disk - desktop_internal
        if unclassified:
            problems.append(
                f"{len(unclassified)} schema(s) in {DESKTOP_SCHEMAS} are not listed under "
                f"`desktop_internal` in {INDEX} — {', '.join(sorted(unclassified))}. A schema "
                f"nobody classified is a schema nobody is holding to anything, which is the "
                f"same failure as a stray"
            )
        phantom = desktop_internal - on_disk
        if phantom:
            problems.append(
                f"the index names desktop schema(s) that {DESKTOP_SCHEMAS} does not have: "
                f"{', '.join(sorted(phantom))}"
            )

    for stray in stray_schema_files(root):
        problems.append(
            f"stray schema {stray} lives outside every declared home "
            f"({', '.join(_ALLOWED_SCHEMA_DIRS)}) — a copy nobody is holding to anything"
        )

    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fail CI when contracts/ stops being the single source.")
    ap.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root)

    problems = check(root)
    if problems:
        print("RED: contracts/ is not the single source —", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            f"\n{len(problems)} problem(s). See contracts/index.json and "
            f"docs/design/CONTRACTS_DEDUPE_PLAN.md.",
            file=sys.stderr,
        )
        return 1

    doc = load_index(root)
    ids = ", ".join(e["id"] for e in doc["contracts"])
    print(
        f"GREEN: {len(doc['contracts'])} cross-half contract(s) sourced from {CONTRACTS.as_posix()}/ "
        f"and byte-identical in {ENGINE_SCHEMAS.as_posix()}/ ({ids}); "
        f"{len(doc.get('engine_internal', {}).get('ids', []))} engine-internal schemas classified; "
        f"{len(doc.get('desktop_internal', {}).get('ids', []))} desktop-internal; "
        f"no stray copies."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
