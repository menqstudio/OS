#!/usr/bin/env python3
"""Live-GitHub truth verifier for config/current_state.json.

check_coordination.py validates the snapshot's INTERNAL consistency + human-doc agreement (offline).
This script closes the remaining gap the Owner flagged: it verifies the snapshot against LIVE GitHub
and FAILS CLOSED when the snapshot lies about the live world — the exact "a genuinely merged PR is
still recorded 'open'" drift, which the offline gate cannot see.

Semantics (honest):
  - merge_state / draft / head-branch / base-branch MISMATCH  -> FAILURE (fail-closed).
  - head SHA drift (head_at_last_sync != live head)           -> INFO/WARNING only: heads legitimately
    advance, and current_state.json labels the field a snapshot ("_at_last_sync"), not a live value.
    The warning tells a session the snapshot is stale and to resolve the live head.
  - a PR whose live state cannot be resolved                  -> FAILURE in CI (cannot prove the claim).

Run context:
  - CI (GITHUB_ACTIONS=true): live verification is REQUIRED; if `gh` is unavailable it fails closed.
  - Local without an authenticated `gh`: the ONLINE portion is SKIPPED (exit 0); CI is the wall.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

# snapshot merge_state -> GitHub PR `state`
MERGE_MAP = {"open": "OPEN", "merged": "MERGED", "closed": "CLOSED"}
_GH_FIELDS = "state,isDraft,headRefName,baseRefName,headRefOid"


def load_snapshot(root: pathlib.Path) -> dict:
    return json.loads((root / "config" / "current_state.json").read_text(encoding="utf-8"))


def compare(snapshot: dict, live: dict) -> tuple[list[str], list[str]]:
    """Pure, offline-testable. `live` maps pr_number -> {state,isDraft,headRefName,baseRefName,
    headRefOid} or None when unresolved. Returns (failures, warnings)."""
    failures: list[str] = []
    warnings: list[str] = []
    for pr in snapshot.get("prs", []):
        if not isinstance(pr, dict) or pr.get("number") is None:
            continue
        n = pr["number"]
        lv = live.get(n)
        if lv is None:
            failures.append(f"PR #{n}: live GitHub state could not be resolved — cannot verify the snapshot (fail-closed)")
            continue
        want = MERGE_MAP.get(pr.get("merge_state"))
        if want and lv.get("state") != want:
            failures.append(f"PR #{n}: snapshot merge_state={pr.get('merge_state')!r} but GitHub state={lv.get('state')!r}")
        if pr.get("draft") is not None and bool(pr.get("draft")) != bool(lv.get("isDraft")):
            failures.append(f"PR #{n}: snapshot draft={pr.get('draft')} but GitHub isDraft={lv.get('isDraft')}")
        if pr.get("branch") and lv.get("headRefName") and pr["branch"] != lv["headRefName"]:
            failures.append(f"PR #{n}: snapshot branch={pr['branch']!r} but GitHub head branch={lv['headRefName']!r}")
        if pr.get("base") and lv.get("baseRefName") and pr["base"] != lv["baseRefName"]:
            failures.append(f"PR #{n}: snapshot base={pr['base']!r} but GitHub base={lv['baseRefName']!r}")
        snap_head = pr.get("head_at_last_sync", "")
        live_head = lv.get("headRefOid", "")
        if live_head and len(snap_head) == 40 and snap_head != live_head:
            warnings.append(f"PR #{n}: head_at_last_sync {snap_head[:7]} != live head {live_head[:7]} — snapshot is stale; resolve the live head")
    return failures, warnings


def _have_gh() -> bool:
    try:
        return subprocess.run(["gh", "--version"], capture_output=True, timeout=15).returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def fetch_live(numbers: list[int]) -> dict:
    live: dict = {}
    for n in numbers:
        try:
            out = subprocess.run(
                ["gh", "pr", "view", str(n), "--json", _GH_FIELDS],
                capture_output=True, text=True, timeout=30, check=True,
            ).stdout
            live[n] = json.loads(out)
        except (subprocess.SubprocessError, OSError, ValueError):
            live[n] = None
    return live


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Live-GitHub verifier for current_state.json")
    ap.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[1]))
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root)

    try:
        snap = load_snapshot(root)
    except (OSError, ValueError) as exc:
        print(f"RED: cannot read config/current_state.json: {exc}", file=sys.stderr)
        return 1
    numbers = [pr["number"] for pr in snap.get("prs", [])
               if isinstance(pr, dict) and pr.get("number") is not None]
    in_ci = os.environ.get("GITHUB_ACTIONS") == "true"

    if not _have_gh():
        if in_ci:
            print("RED: gh CLI unavailable in CI — cannot verify live GitHub state (fail-closed).", file=sys.stderr)
            return 1
        print("SKIPPED: gh CLI unavailable locally; live GitHub verification runs in CI.")
        return 0

    live = fetch_live(numbers)
    failures, warnings = compare(snap, live)
    for w in warnings:
        print(f"  (info) {w}")
    if failures:
        print("RED: config/current_state.json disagrees with live GitHub —", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print(f"\n{len(failures)} live-truth mismatch(es). Re-sync current_state.json to GitHub.", file=sys.stderr)
        return 1
    print(f"GREEN: current_state.json matches live GitHub for PRs {numbers} "
          f"(merge_state/draft/branch/base verified).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
