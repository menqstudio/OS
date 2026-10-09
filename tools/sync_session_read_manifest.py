#!/usr/bin/env python3
"""Derive the MenQ Standard session-read manifest from OS's own two read configs.

MenQ Standard (decision D-028) checks a repository's mandatory session read through one file in
one schema: an ordered core with a byte ceiling per file, and per directory the Markdown files a
session reads when it works there. OS already states the same two things, in its own schema, and
its hooks read them there:

    config/canonical-read-manifest.json   the ordered core
    config/canon-budget.json              the ceiling of each core file, the total, and why

A second hand-kept copy would be the two-boards mistake again. So the standard's file,
config/session-read-manifest.json, is DERIVED: this tool writes it and nothing else may. The
areas are every tracked Markdown file outside the core, grouped by its directory.

    python3 tools/sync_session_read_manifest.py --check   exit 1 when the file is stale
    python3 tools/sync_session_read_manifest.py --write   rewrite it

The check reads tracked files, so `git add` a new Markdown file before running it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
READ_MANIFEST_REL = "config/canonical-read-manifest.json"
BUDGET_REL = "config/canon-budget.json"
OUTPUT_REL = "config/session-read-manifest.json"
SCHEMA_VERSION = 1
ROOT_AREA = "."
WHY_MAX = 160
NO_RATIONALE = f"Named in {READ_MANIFEST_REL}; its ceiling is set in {BUDGET_REL}."


class Refusal(Exception):
    """The manifest cannot be derived; the message is the RED line."""


def load_json(root: Path, rel: str) -> dict:
    try:
        data = json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Refusal(f"cannot read {rel}: {exc}") from exc
    if not isinstance(data, dict):
        raise Refusal(f"{rel}: top level must be an object")
    return data


def tracked_files(root: Path) -> list[str]:
    try:
        result = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Refusal(f"cannot enumerate tracked files with git ls-files -z: {exc}") from exc
    return [part.decode("utf-8") for part in result.stdout.split(b"\0") if part]


def first_sentence(text: str) -> str:
    """The rationale's first sentence, bounded: the manifest names why, the budget file argues it."""
    text = " ".join(text.split())
    end = text.find(". ")
    if end != -1:
        text = text[: end + 1]
    if len(text) > WHY_MAX:
        text = text[: WHY_MAX - 3].rstrip() + "..."
    return text


def derive(root: Path) -> dict:
    read_manifest = load_json(root, READ_MANIFEST_REL)
    budget = load_json(root, BUDGET_REL)
    paths = read_manifest.get("paths")
    per_file = budget.get("per_file_bytes")
    rationale = budget.get("rationale")
    total = budget.get("total_bytes_max")
    if not isinstance(paths, list) or not paths:
        raise Refusal(f"{READ_MANIFEST_REL}: paths must be a non-empty list")
    if not isinstance(per_file, dict) or not isinstance(rationale, dict):
        raise Refusal(f"{BUDGET_REL}: per_file_bytes and rationale must be objects")
    if not isinstance(total, int) or isinstance(total, bool) or total <= 0:
        raise Refusal(f"{BUDGET_REL}: total_bytes_max must be a positive integer")

    core = []
    for path in paths:
        if path not in per_file:
            raise Refusal(f"{path} is in {READ_MANIFEST_REL} but has no ceiling in {BUDGET_REL} per_file_bytes")
        why = rationale.get(path)
        # Not every core file has a rationale entry; the standard requires a why, so say where
        # the argument is rather than invent one.
        why = first_sentence(why) if isinstance(why, str) and why.strip() else NO_RATIONALE
        core.append({"path": path, "bytes_max": per_file[path], "why": why})

    in_core = set(paths)
    areas: dict[str, list[str]] = {}
    for rel in sorted(tracked_files(root)):
        if not rel.lower().endswith(".md") or rel in in_core:
            continue
        directory = rel.rsplit("/", 1)[0] if "/" in rel else ROOT_AREA
        areas.setdefault(directory, []).append(rel)

    return {
        "schema_version": SCHEMA_VERSION,
        "derived_by": "tools/sync_session_read_manifest.py from "
        f"{READ_MANIFEST_REL} and {BUDGET_REL}; never edited by hand",
        "total_bytes_max": total,
        "core": core,
        "areas": dict(sorted(areas.items())),
    }


def rendered(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="exit 1 when the derived file is stale")
    mode.add_argument("--write", action="store_true", help="rewrite the derived file")
    parser.add_argument("--root", default=str(ROOT), help="the repository (default: this checkout)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    try:
        want = rendered(derive(root))
    except Refusal as exc:
        print(f"SESSION-READ MANIFEST: RED\n- {exc}")
        return 1

    output = root / OUTPUT_REL
    have = None
    if output.is_file():
        have = output.read_bytes().replace(b"\r\n", b"\n").decode("utf-8", errors="replace")

    if args.write:
        if have == want:
            print(f"SESSION-READ MANIFEST: unchanged ({OUTPUT_REL})")
        else:
            output.write_text(want, encoding="utf-8", newline="\n")
            print(f"SESSION-READ MANIFEST: WRITTEN ({OUTPUT_REL})")
        return 0

    if have == want:
        data = json.loads(want)
        files = sum(len(v) for v in data["areas"].values())
        print(
            f"SESSION-READ MANIFEST: GREEN ({len(data['core'])} core files, "
            f"{files} area files in {len(data['areas'])} directories)"
        )
        return 0
    print("SESSION-READ MANIFEST: RED")
    if have is None:
        print(f"- {OUTPUT_REL} does not exist")
    else:
        print(f"- {OUTPUT_REL} is not what {READ_MANIFEST_REL}, {BUDGET_REL} and the tracked Markdown files give")
    print("  fix: git add the new files, then python3 tools/sync_session_read_manifest.py --write")
    return 1


if __name__ == "__main__":
    sys.exit(main())
