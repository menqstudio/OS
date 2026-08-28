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
  * any entry whose initial payload exceeds its budget        -> RED;
  * a bundled source newer than the build manifest            -> RED
    (ninth audit `I-12`: the gate had no freshness check, so it reported GREEN
    at 151.6 KB against a dist/ built before the deletion it was cited to prove,
    and GREEN again at 133.0 KB after a rebuild of the same tree).

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


#: What the bundle is built FROM. A file newer than the manifest means the manifest describes a
#: build that never saw it, so every byte this gate reports is a measurement of the wrong tree.
_SOURCE_GLOBS = ("src/**/*",)
_SOURCE_FILES = ("index.html", "vite.config.ts", "package.json", "package-lock.json",
                 "tsconfig.json", "tsconfig.node.json")
#: Files inside src/ that no bundle contains. Editing a test does not invalidate a build, and a
#: gate that reds on it would be turned off within a week.
_NOT_BUNDLED = (".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", ".md")


def stale_sources(root: pathlib.Path, manifest_path: pathlib.Path) -> list[pathlib.Path]:
    """Bundled sources modified after the manifest was written — ninth audit `I-12`.

    The gate had no freshness check at all. It read whatever `dist/` happened to contain and
    reported a verdict on it, so it printed GREEN at 151.6 KB against a build made BEFORE the
    deletion whose effect it was being cited to prove, and GREEN again at 133.0 KB after a rebuild
    of the identical tree. Two different numbers, same source, both "GREEN" -- a gate that measures
    an artifact nobody checked is measuring the last time somebody ran a build.

    mtime is not a content hash and is not claimed to be one: a checkout can rewrite it, and a
    build that touches nothing leaves it alone. It is enough for the failure that actually happens,
    which is editing a source and reading a stale dist -- and CI builds immediately before this
    runs, so the comparison there is between a fresh build and the tree it was built from.
    """
    desktop = root / DESKTOP
    cutoff = manifest_path.stat().st_mtime
    stale: list[pathlib.Path] = []
    candidates: list[pathlib.Path] = []
    for pattern in _SOURCE_GLOBS:
        candidates.extend(p for p in desktop.glob(pattern) if p.is_file())
    candidates.extend(desktop / name for name in _SOURCE_FILES)
    for path in candidates:
        if not path.exists() or path.name.endswith(_NOT_BUNDLED):
            continue
        if path.stat().st_mtime > cutoff:
            stale.append(path.relative_to(root) if path.is_relative_to(root) else path)
    return sorted(stale)


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
    manifest_path = find_manifest(root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Freshness FIRST (ninth audit `I-12`): a verdict on a stale build is not a verdict, and
    # reporting the sizes anyway would put a precise-looking number next to the wrong tree.
    stale = stale_sources(root, manifest_path)
    if stale:
        shown = ", ".join(str(p) for p in stale[:5])
        more = f" (+{len(stale) - 5} more)" if len(stale) > 5 else ""
        return [
            f"the build is stale: {len(stale)} bundled source(s) are newer than "
            f"{manifest_path.relative_to(root)} — {shown}{more}. Run `npm run build` in "
            f"{DESKTOP} and re-run this gate; measuring the old dist/ reports a size this "
            f"tree never had"
        ]

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
        # The header used to say "budget exceeded" for every failure, which would be a false
        # description of a stale build — the one failure that is about the measurement rather
        # than the size.
        stale = any(p.startswith("the build is stale") for p in problems)
        print("RED: the build is stale —" if stale else "RED: bundle-size budget exceeded —",
              file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        advice = (
            "rebuild before trusting any number this gate prints."
            if stale else
            f"Trim the payload or, if the growth is intentional and justified, "
            f"raise the ceiling in {BUDGET}."
        )
        print(f"\n{len(problems)} problem(s). {advice}", file=sys.stderr)
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
