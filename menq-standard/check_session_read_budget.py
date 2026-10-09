#!/usr/bin/env python3
"""Hold the session-read core to its byte budget (decision D-028).

The manifest names an ordered CORE every AI session reads in full and, per
directory, the AREA files a session also reads when it works there. This gate
checks the manifest, the sizes and the reachability of every tracked Markdown
file. It does NOT check that any session read anything: no program in this
repository can. A receipt is a digest of the core content, nothing more.

Modes:
    (default)                check the manifest and the budget
    --receipt                print one sha256 over the ordered core content
    --verify-receipt DIGEST  exit non-zero unless DIGEST is the current receipt

Bytes are counted after CRLF is folded to LF, so a Windows checkout and a
Linux checkout of the same commit measure the same number.

This is the ONE implementation, and it is a file of the consumer kit
(decision D-029): a product repository holds an unchanged copy. Two things
differ between repositories and both are parameters, not edits:

    --root      the repository to check; default: the current directory
    --manifest  the manifest, relative to the root; default:
                SESSION_READ_MANIFEST.json at the repository root

MenQ Standard keeps its own manifest elsewhere, so its entry point,
scripts/check_session_read_budget.py, loads this file and passes its own two
defaults. Nothing else differs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

# The conventional place of the manifest in a repository that adopts the standard.
MANIFEST_REL = "SESSION_READ_MANIFEST.json"
SCHEMA_VERSION = 1
# One number for every MenQ repository (Owner, 2026-10-09, D-028): the universal
# maximum, taken from the largest read set in the ecosystem. A repository declares
# its own total_bytes_max in its manifest, at or below this; MenQ Standard declares
# 120,000. This script is the same file in every repository, so the number that
# differs lives in the manifest and the number that does not lives here.
UNIVERSAL_TOTAL_BYTES_MAX = 350_000
ROOT_AREA = "."


class Refusal(Exception):
    """The gate cannot continue; the message is the RED line."""


def normalised(data: bytes) -> bytes:
    """Fold CRLF to LF so the count does not depend on the checkout."""
    return data.replace(b"\r\n", b"\n")


def tracked_files(root: Path) -> list[str]:
    """Every tracked path, read NUL-separated so spaces and non-ASCII survive."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Refusal(f"cannot enumerate tracked files with git ls-files -z: {exc}") from exc
    return [part.decode("utf-8") for part in result.stdout.split(b"\0") if part]


def is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def path_problem(value: object) -> str | None:
    """Return why a manifest path is not a clean repository-relative path."""
    if not isinstance(value, str) or not value:
        return "is not a non-empty string"
    if "\\" in value:
        return "uses a backslash"
    if value.startswith("/"):
        return "is absolute"
    parts = value.split("/")
    if value != ROOT_AREA and any(part in ("", ".", "..") for part in parts):
        return "is not normalised (empty, '.' or '..' segment)"
    return None


def load_manifest(root: Path, manifest_rel: str) -> dict:
    path = root / manifest_rel
    if not path.is_file():
        raise Refusal(f"manifest is missing: {manifest_rel}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Refusal(f"manifest is malformed: {manifest_rel}: {exc}") from exc
    if not isinstance(data, dict):
        raise Refusal(f"manifest is malformed: {manifest_rel}: top level must be an object")
    return data


def shape_errors(data: dict) -> list[str]:
    """Structural faults. Any of them makes the manifest malformed."""
    errors: list[str] = []
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"manifest is malformed: schema_version is {data.get('schema_version')!r}, expected {SCHEMA_VERSION}"
        )
    if not is_positive_int(data.get("total_bytes_max")):
        errors.append(
            f"manifest is malformed: total_bytes_max is {data.get('total_bytes_max')!r}, expected a positive integer"
        )
    core = data.get("core")
    if not isinstance(core, list) or not core:
        errors.append("manifest is malformed: core must be a non-empty list")
    else:
        for index, entry in enumerate(core):
            if not isinstance(entry, dict):
                errors.append(f"manifest is malformed: core[{index}] is not an object")
                continue
            problem = path_problem(entry.get("path"))
            if problem or entry.get("path") == ROOT_AREA:
                errors.append(
                    f"manifest is malformed: core[{index}].path {entry.get('path')!r} {problem or 'is not a file'}"
                )
            if not is_positive_int(entry.get("bytes_max")):
                errors.append(
                    f"manifest is malformed: core[{index}].bytes_max is {entry.get('bytes_max')!r}, "
                    "expected a positive integer"
                )
            why = entry.get("why")
            if not isinstance(why, str) or not why.strip():
                errors.append(f"manifest is malformed: core[{index}].why is empty; every core file states why it is core")
    areas = data.get("areas")
    if not isinstance(areas, dict):
        errors.append("manifest is malformed: areas must be an object mapping a directory to a list of files")
    else:
        for directory, files in areas.items():
            problem = path_problem(directory)
            if problem:
                errors.append(f"manifest is malformed: area directory {directory!r} {problem}")
            if not isinstance(files, list) or not files:
                errors.append(f"manifest is malformed: area {directory!r} must be a non-empty list of files")
                continue
            for index, rel in enumerate(files):
                problem = path_problem(rel)
                if problem or rel == ROOT_AREA:
                    errors.append(
                        f"manifest is malformed: area {directory!r} file[{index}] {rel!r} {problem or 'is not a file'}"
                    )
    return errors


def core_measurements(root: Path, data: dict) -> list[tuple[str, int, int | None]]:
    """(path, bytes_max, measured normalised bytes or None when absent) in manifest order."""
    rows: list[tuple[str, int, int | None]] = []
    for entry in data["core"]:
        path = root / entry["path"]
        size = len(normalised(path.read_bytes())) if path.is_file() else None
        rows.append((entry["path"], entry["bytes_max"], size))
    return rows


def area_bytes(root: Path, files: list[str]) -> int:
    return sum(len(normalised((root / rel).read_bytes())) for rel in files if (root / rel).is_file())


def check(root: Path, manifest_rel: str = MANIFEST_REL) -> tuple[list[str], list[str]]:
    """Return (errors, report lines). No errors means GREEN."""
    try:
        data = load_manifest(root, manifest_rel)
    except Refusal as refusal:
        return [str(refusal)], []
    errors = shape_errors(data)
    if errors:
        return errors, []
    try:
        tracked = tracked_files(root)
    except Refusal as refusal:
        return [str(refusal)], []
    tracked_set = set(tracked)
    tracked_dirs = {ROOT_AREA}
    for rel in tracked:
        parts = rel.split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            tracked_dirs.add("/".join(parts[:depth]))

    total_max = data["total_bytes_max"]
    if total_max > UNIVERSAL_TOTAL_BYTES_MAX:
        errors.append(
            f"total_bytes_max is {total_max}, above the universal ceiling {UNIVERSAL_TOTAL_BYTES_MAX} (D-028); "
            "that ceiling moves only with a decision"
        )

    core_paths = [entry["path"] for entry in data["core"]]
    seen: set[str] = set()
    for rel in core_paths:
        if rel in seen:
            errors.append(f"core path is listed twice: {rel}")
        seen.add(rel)

    rows = core_measurements(root, data)
    total = 0
    for rel, ceiling, size in rows:
        if size is None:
            errors.append(f"core file is absent: {rel}")
            continue
        if rel not in tracked_set:
            errors.append(f"core file is not tracked by git: {rel}")
        total += size
        if size > ceiling:
            errors.append(f"core file exceeds its ceiling: {rel} is {size} bytes, bytes_max is {ceiling}")
    if total > total_max:
        errors.append(f"core total exceeds the budget: {total} bytes, total_bytes_max is {total_max}")
    ceiling_sum = sum(entry["bytes_max"] for entry in data["core"])
    if ceiling_sum > total_max:
        errors.append(
            f"sum of core bytes_max exceeds the budget: {ceiling_sum} bytes, total_bytes_max is {total_max}; "
            "every file could be inside its own ceiling while the core is over the total"
        )

    core_set = set(core_paths)
    reachable = set(core_paths)
    area_sizes: list[tuple[int, str, int]] = []
    for directory, files in data["areas"].items():
        if directory not in tracked_dirs:
            errors.append(f"area names a directory that does not exist: {directory}")
        listed: set[str] = set()
        for rel in files:
            if rel in listed:
                errors.append(f"area {directory} lists a path twice: {rel}")
            listed.add(rel)
            if rel in core_set:
                errors.append(f"area {directory} lists a path that is already in the core: {rel}")
            if not (root / rel).is_file():
                errors.append(f"area {directory} names a file that does not exist: {rel}")
            elif rel not in tracked_set:
                errors.append(f"area {directory} names a file that is not tracked by git: {rel}")
            reachable.add(rel)
        area_sizes.append((area_bytes(root, files), directory, len(files)))

    for rel in tracked:
        if rel.lower().endswith(".md") and rel not in reachable:
            errors.append(f"tracked Markdown file is in neither the core nor any area: {rel}")

    report = [
        f"core: {len(rows)} files, {total} bytes of {total_max} "
        f"(headroom {total_max - total}); sum of ceilings {ceiling_sum}",
    ]
    for rel, ceiling, size in rows:
        report.append(f"  {size if size is not None else 'ABSENT':>7} / {ceiling:>7}  {rel}")
    if area_sizes:
        largest = max(area_sizes)
        report.append(
            f"areas: {len(area_sizes)} directories; largest is {largest[1]} "
            f"({largest[2]} files, {largest[0]} bytes, no ceiling)"
        )
    return errors, report


def receipt(root: Path, manifest_rel: str = MANIFEST_REL) -> str:
    """One digest over the ordered core: for each file its path, its length and its normalised bytes."""
    data = load_manifest(root, manifest_rel)
    digest = hashlib.sha256()
    for entry in data["core"]:
        content = normalised((root / entry["path"]).read_bytes())
        digest.update(entry["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b"\0")
        digest.update(content)
    return digest.hexdigest()


def main(
    argv: list[str] | None = None,
    *,
    default_root: Path | None = None,
    default_manifest: str = MANIFEST_REL,
) -> int:
    """Run the gate. The two keyword defaults exist for an entry point that lives elsewhere."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=default_root if default_root is not None else Path.cwd(),
        help="repository root (default: %(default)s)",
    )
    parser.add_argument(
        "--manifest", default=default_manifest, help="manifest path relative to the root (default: %(default)s)"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--receipt", action="store_true", help="print the sha256 receipt of the current core")
    mode.add_argument("--verify-receipt", metavar="DIGEST", help="exit non-zero unless DIGEST is the current receipt")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if hasattr(sys.stdout, "reconfigure"):
        # A path may be Armenian; a non-UTF-8 console must not turn a verdict into a crash.
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    errors, report = check(root, args.manifest)
    if errors:
        print("SESSION READ BUDGET: RED")
        for error in errors:
            print(f"- {error}")
        return 1

    if args.receipt:
        print(receipt(root, args.manifest))
        return 0
    if args.verify_receipt is not None:
        current = receipt(root, args.manifest)
        offered = args.verify_receipt.strip().lower()
        if offered != current:
            print("SESSION READ RECEIPT: RED")
            print(f"- receipt does not match the current core: offered {offered}, current {current}")
            return 1
        print(f"SESSION READ RECEIPT: GREEN ({current})")
        return 0

    print("SESSION READ BUDGET: GREEN")
    for line in report:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
