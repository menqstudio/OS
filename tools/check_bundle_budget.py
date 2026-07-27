#!/usr/bin/env python3
"""Bundle-size performance budget gate — fail-closed on frontend payload regressions.

The cockpit frontend ships inside the Tauri bundle; every kilobyte the webview
must parse on launch is cold-start latency the user pays. This gate pins the
*initial gzipped payload* of each Vite entry to a committed budget so a careless
dependency or an accidental barrel import cannot silently bloat the app.

It reads two committed/produced artifacts and compares them:

    apps/desktop/perf-budget.json      (committed) per-entry max gzipped KB
      vs.
    apps/desktop/dist/.vite/manifest.json  (built)  Vite build manifest

For every entry in the manifest (`isEntry: true`) it resolves the entry chunk
plus its transitively-imported chunks and their CSS — i.e. everything the browser
must download before first paint — gzips each unique file, sums the bytes, and
fails if the total exceeds that entry's budget.

The check is bidirectional and fail-closed, matching the other CI gates in this
repo (capabilities/coordination):

  * an entry present in the build but absent from the budget  -> RED
    (a new entry chunk MUST be given an explicit budget);
  * a budget naming an entry the build no longer emits        -> RED
    (stale budget / typo);
  * any entry whose initial payload exceeds its budget        -> RED.

Enable the manifest in vite.config.ts with `build: { manifest: true }` so the
built `dist/.vite/manifest.json` exists for this gate to read.

Usage:  python tools/check_bundle_budget.py [--root DIR]
Exit 0 + "GREEN: ..." when every entry is within budget; exit 1 + the offenders
otherwise.
"""
from __future__ import annotations

import argparse
import gzip
import json
import pathlib
import sys

DESKTOP = pathlib.Path("apps/desktop")
BUDGET = DESKTOP / "perf-budget.json"
DIST = DESKTOP / "dist"
# Vite 5/6 write the manifest under .vite/; older layouts put it at the dist root.
MANIFEST_CANDIDATES = (DIST / ".vite" / "manifest.json", DIST / "manifest.json")

# gzip -9 is the best-case a static host will serve; budgets are measured against it
# so the number in perf-budget.json is a stable, reproducible ceiling.
_GZIP_LEVEL = 9


def load_budget(root: pathlib.Path) -> dict[str, float]:
    """entry name -> max gzipped KB, from the committed perf-budget.json."""
    path = root / BUDGET
    if not path.exists():
        raise SystemExit(f"RED: missing budget file {BUDGET} (commit a per-entry budget)")
    doc = json.loads(path.read_text(encoding="utf-8"))
    entries = doc.get("entries")
    if not isinstance(entries, dict) or not entries:
        raise SystemExit(f'RED: {BUDGET} must have a non-empty object "entries"')
    budget: dict[str, float] = {}
    for name, spec in entries.items():
        if not isinstance(spec, dict) or "max_gzip_kb" not in spec:
            raise SystemExit(f'RED: {BUDGET} entry {name!r} needs {{"max_gzip_kb": <number>}}')
        kb = spec["max_gzip_kb"]
        if not isinstance(kb, (int, float)) or isinstance(kb, bool) or kb <= 0:
            raise SystemExit(f"RED: {BUDGET} entry {name!r} max_gzip_kb must be a positive number")
        budget[name] = float(kb)
    return budget


def find_manifest(root: pathlib.Path) -> pathlib.Path:
    for candidate in MANIFEST_CANDIDATES:
        p = root / candidate
        if p.exists():
            return p
    raise SystemExit(
        "RED: no Vite build manifest found (looked for "
        + ", ".join(str(c) for c in MANIFEST_CANDIDATES)
        + "). Run `npm run build` with `build.manifest: true` in vite.config.ts."
    )


def gzip_size(path: pathlib.Path) -> int:
    """Deterministic gzipped byte length of a file (mtime zeroed)."""
    data = path.read_bytes()
    return len(gzip.compress(data, compresslevel=_GZIP_LEVEL, mtime=0))


def _collect_files(manifest: dict, key: str, seen: set[str]) -> set[str]:
    """Transitively gather dist-relative output paths for a manifest chunk.

    Includes the chunk's own file, its CSS, and everything it statically imports
    (the initial, render-blocking payload). Dynamic imports (`dynamicImports`) are
    deliberately excluded — they are lazy-loaded and not part of first paint.
    """
    if key in seen:
        return set()
    seen.add(key)
    record = manifest.get(key)
    if record is None:
        return set()
    files: set[str] = set()
    if record.get("file"):
        files.add(record["file"])
    for css in record.get("css", []) or []:
        files.add(css)
    for imp in record.get("imports", []) or []:
        files |= _collect_files(manifest, imp, seen)
    return files


def entry_payloads(manifest: dict, dist_dir: pathlib.Path) -> dict[str, int]:
    """entry name -> total initial gzipped bytes, for every isEntry record."""
    payloads: dict[str, int] = {}
    for key, record in manifest.items():
        if not isinstance(record, dict) or not record.get("isEntry"):
            continue
        name = record.get("name") or key
        files = _collect_files(manifest, key, set())
        total = 0
        for rel in sorted(files):
            f = dist_dir / rel
            if not f.exists():
                raise SystemExit(f"RED: manifest references missing built file {rel}")
            total += gzip_size(f)
        # Two entries could resolve to the same logical name; sum defensively.
        payloads[name] = payloads.get(name, 0) + total
    return payloads


def check(root: pathlib.Path) -> list[str]:
    problems: list[str] = []
    budget = load_budget(root)
    manifest = json.loads(find_manifest(root).read_text(encoding="utf-8"))
    payloads = entry_payloads(manifest, root / DIST)

    budgeted = set(budget)
    built = set(payloads)

    for name in sorted(built - budgeted):
        kb = payloads[name] / 1024
        problems.append(
            f"entry {name!r} is built ({kb:.1f} KB gzip) but has no budget in "
            f"{BUDGET.name}; add an explicit max_gzip_kb"
        )
    for name in sorted(budgeted - built):
        problems.append(
            f"budget names entry {name!r} but the build emits no such entry "
            f"(stale budget or renamed chunk)"
        )
    for name in sorted(budgeted & built):
        actual_kb = payloads[name] / 1024
        max_kb = budget[name]
        if payloads[name] > max_kb * 1024:
            over = actual_kb - max_kb
            problems.append(
                f"entry {name!r} initial payload {actual_kb:.1f} KB gzip exceeds "
                f"budget {max_kb:.1f} KB by {over:.1f} KB"
            )
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="Fail CI when a frontend entry exceeds its gzip budget.")
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    root = pathlib.Path(args.root)

    problems = check(root)
    if problems:
        print("RED: bundle-size budget exceeded —", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            f"\n{len(problems)} problem(s). Trim the payload or, if the growth is "
            f"intentional and justified, raise the ceiling in {BUDGET}.",
            file=sys.stderr,
        )
        return 1

    budget = load_budget(root)
    manifest = json.loads(find_manifest(root).read_text(encoding="utf-8"))
    payloads = entry_payloads(manifest, root / DIST)
    detail = ", ".join(
        f"{name} {payloads[name] / 1024:.1f}/{budget[name]:.0f} KB" for name in sorted(budget)
    )
    print(f"GREEN: {len(budget)} entr(y/ies) within gzip budget ({detail}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
