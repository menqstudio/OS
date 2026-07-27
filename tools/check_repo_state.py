#!/usr/bin/env python3
"""Live-GitHub exact-head truth verifier for config/current_state.json.

check_coordination.py validates the snapshot's INTERNAL consistency + human-doc agreement (offline).
This script verifies the snapshot against LIVE GitHub, FAIL-CLOSED, and — unlike the earlier version —
enforces EXACT heads and the CI event context, so:

  1. NO self-red merge trap. The repository-truth CARRIER PR is NOT stored in prs[]; only the durable
     project PRs (#31/#32) are. So merging the carrier cannot leave a "recorded-open-but-merged" PR.
     On a push to `main` we require baseline_main_head_at_sync to be an ANCESTOR of the pushed HEAD
     (it always is, post-merge) — never that a just-merged carrier stays open.

  2. EXACT-head, not "head drift is only a warning":
     - External durable PRs (prs[]): live head MUST equal the stored exact `head` (drift => RED, forcing
       a same-PR state re-sync), plus state/draft/branch/base.
     - Current workflow PR (from the Actions event): on `pull_request`, the event's base SHA MUST equal
       baseline_main_head_at_sync when the base is `main` (a stale baseline => RED, forcing rebase/sync);
       the event base branch MUST match; and if the snapshot names an expected current PR number/branch
       it must match the event.

Run context:
  - CI (GITHUB_ACTIONS=true): live verification REQUIRED; missing `gh`/event/ancestry => fail closed.
  - Local without an authenticated `gh`: the ONLINE portion is SKIPPED (exit 0); CI is the wall.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

MERGE_MAP = {"open": "OPEN", "merged": "MERGED", "closed": "CLOSED"}
_GH_FIELDS = "state,isDraft,headRefName,baseRefName,headRefOid"
_HEX40 = "0123456789abcdef"


def _is_sha(s) -> bool:
    return isinstance(s, str) and len(s) == 40 and all(c in _HEX40 for c in s)


def load_snapshot(root: pathlib.Path) -> dict:
    return json.loads((root / "config" / "current_state.json").read_text(encoding="utf-8"))


def compare_external_prs(snapshot: dict, live: dict) -> list[str]:
    """EXACT-head fail-closed for the durable project PRs in prs[]. `live` maps pr_number ->
    {state,isDraft,headRefName,baseRefName,headRefOid} or None. Pure/offline-testable."""
    failures: list[str] = []
    for pr in snapshot.get("prs", []):
        if not isinstance(pr, dict) or pr.get("number") is None:
            continue
        n = pr["number"]
        lv = live.get(n)
        if lv is None:
            failures.append(f"PR #{n}: live GitHub state unresolved — cannot verify (fail-closed)")
            continue
        want = MERGE_MAP.get(pr.get("merge_state"))
        if want and lv.get("state") != want:
            failures.append(f"PR #{n}: snapshot merge_state={pr.get('merge_state')!r} but GitHub={lv.get('state')!r}")
        if pr.get("draft") is not None and bool(pr.get("draft")) != bool(lv.get("isDraft")):
            failures.append(f"PR #{n}: snapshot draft={pr.get('draft')} but GitHub isDraft={lv.get('isDraft')}")
        if pr.get("branch") and lv.get("headRefName") and pr["branch"] != lv["headRefName"]:
            failures.append(f"PR #{n}: snapshot branch={pr['branch']!r} but GitHub head branch={lv['headRefName']!r}")
        if pr.get("base") and lv.get("baseRefName") and pr["base"] != lv["baseRefName"]:
            failures.append(f"PR #{n}: snapshot base={pr['base']!r} but GitHub base={lv['baseRefName']!r}")
        # EXACT head: drift is now a FAILURE (forces re-sync), not a warning.
        snap_head = pr.get("head", "")
        live_head = lv.get("headRefOid", "")
        if not _is_sha(snap_head):
            failures.append(f"PR #{n}: snapshot 'head' must be an exact 40-hex sha, got {snap_head!r}")
        elif live_head and snap_head != live_head:
            failures.append(f"PR #{n}: snapshot head {snap_head[:7]} != live head {live_head[:7]} "
                            f"(exact-head drift — re-sync current_state.json in the same PR)")
    return failures


def verify_pr_event(event: dict, snapshot: dict, is_ancestor=None) -> list[str]:
    """Fail-closed checks against the CURRENT workflow (carrier) PR's event payload. Pure/testable.
    Enforces: base SHA == baseline (when base is main); carrier number/branch/base match; and the
    carrier HEAD is bound — the live PR head must equal, or descend from, current_workflow_pr.head.

    Head binding note (honest): a commit cannot contain its own git hash, so current_workflow_pr.head
    records the exact candidate sync-tip and the live PR head must be that sha OR a descendant of it
    (`is_ancestor(recorded, live)`), i.e. the running candidate is cryptographically on the recorded
    lineage. Bit-exact when the branch is frozen for audit; a divergent/unrelated head fails closed."""
    if is_ancestor is None:
        is_ancestor = lambda a, b: False  # noqa: E731  (no git in the pure/test path -> exact-only)
    failures: list[str] = []
    pr = event.get("pull_request") or {}
    base = pr.get("base") or {}
    head = pr.get("head") or {}
    base_ref = base.get("ref")
    base_sha = base.get("sha")
    head_sha = head.get("sha")
    baseline = (snapshot.get("sync") or {}).get("baseline_main_head_at_sync")
    if base_ref == "main":
        if not _is_sha(base_sha):
            failures.append(f"event base sha is not a 40-hex sha: {base_sha!r}")
        elif baseline != base_sha:
            failures.append(f"snapshot baseline_main_head_at_sync {str(baseline)[:7]} != PR base sha "
                            f"{str(base_sha)[:7]} — the snapshot is stale vs its base; rebase/re-sync")
    cw = snapshot.get("current_workflow_pr") or {}
    if cw:
        if cw.get("number") is not None and pr.get("number") != cw.get("number"):
            failures.append(f"event PR #{pr.get('number')} != snapshot current_workflow_pr #{cw.get('number')}")
        if cw.get("branch") and head.get("ref") and cw.get("branch") != head.get("ref"):
            failures.append(f"event head branch {head.get('ref')!r} != snapshot current_workflow_pr branch {cw.get('branch')!r}")
        if cw.get("base") and base_ref and cw.get("base") != base_ref:
            failures.append(f"event base {base_ref!r} != snapshot current_workflow_pr base {cw.get('base')!r}")
        # carrier HEAD binding (exact-or-descendant of the recorded candidate).
        recorded = cw.get("head")
        if not _is_sha(recorded):
            failures.append(f"current_workflow_pr.head must be an exact 40-hex sha, got {recorded!r}")
        elif _is_sha(head_sha) and head_sha != recorded and not is_ancestor(recorded, head_sha):
            failures.append(f"event head {head_sha[:7]} is not the recorded carrier candidate "
                            f"{recorded[:7]} nor a descendant of it (carrier head unbound / divergent)")
    return failures


def verify_carrier_post_merge(carrier_live: dict, snapshot: dict) -> list[str]:
    """On a push to main, the carrier PR has (usually) just merged. If GitHub reports it MERGED, the
    snapshot's carrier_transition.post_merge must be the semantically-correct post-merge state — so the
    same merged content already declares gate=REBASE_PR31 / carrier=merged / phase_0=done and main is
    NOT knowingly stale. Pure/testable. carrier_live = {'state': 'MERGED'|...} or None."""
    failures: list[str] = []
    ct = snapshot.get("carrier_transition") or {}
    post = ct.get("post_merge") or {}
    if carrier_live is None:
        return []  # cannot resolve the carrier live -> the external-PR/ancestor checks still guard
    if carrier_live.get("state") == "MERGED":
        if post.get("carrier_state") != "merged":
            failures.append("carrier is MERGED on GitHub but carrier_transition.post_merge.carrier_state != 'merged'")
        if post.get("gate") != "REBASE_PR31":
            failures.append(f"carrier merged but post_merge.gate is {post.get('gate')!r}, expected 'REBASE_PR31'")
        if post.get("phase_0") != "done":
            failures.append(f"carrier merged but post_merge.phase_0 is {post.get('phase_0')!r}, expected 'done'")
    return failures


def verify_main_push(pushed_sha: str, baseline: str, is_ancestor) -> list[str]:
    """On a push to main, the recorded baseline must be an ANCESTOR of (or equal to) the pushed HEAD.
    This is what makes merging the carrier PR safe — post-merge main is a descendant of the baseline,
    so this stays GREEN. `is_ancestor(a, b)` -> bool (a is ancestor of b). Pure/testable."""
    failures: list[str] = []
    if not _is_sha(baseline):
        return [f"baseline_main_head_at_sync is not a 40-hex sha: {baseline!r}"]
    if not _is_sha(pushed_sha):
        return [f"pushed main sha is not a 40-hex sha: {pushed_sha!r}"]
    if baseline != pushed_sha and not is_ancestor(baseline, pushed_sha):
        failures.append(f"baseline_main_head_at_sync {baseline[:7]} is not an ancestor of pushed main "
                        f"{pushed_sha[:7]} — resync the snapshot baseline to main")
    return failures


# ---- CI I/O (not unit-tested; the pure functions above are) ----------------------------------------

def _have_gh() -> bool:
    try:
        return subprocess.run(["gh", "--version"], capture_output=True, timeout=15).returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def fetch_live(numbers: list[int]) -> dict:
    live: dict = {}
    for n in numbers:
        try:
            out = subprocess.run(["gh", "pr", "view", str(n), "--json", _GH_FIELDS],
                                 capture_output=True, text=True, timeout=30, check=True).stdout
            live[n] = json.loads(out)
        except (subprocess.SubprocessError, OSError, ValueError):
            live[n] = None
    return live


def _git_is_ancestor(a: str, b: str) -> bool:
    try:
        return subprocess.run(["git", "merge-base", "--is-ancestor", a, b],
                              capture_output=True, timeout=30).returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Live-GitHub exact-head verifier for current_state.json")
    ap.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[1]))
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root)
    try:
        snap = load_snapshot(root)
    except (OSError, ValueError) as exc:
        print(f"RED: cannot read config/current_state.json: {exc}", file=sys.stderr)
        return 1

    in_ci = os.environ.get("GITHUB_ACTIONS") == "true"
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    failures: list[str] = []

    # (a) CI event-context checks.
    on_main_push = event_name == "push" and os.environ.get("GITHUB_REF") == "refs/heads/main"
    if event_name == "pull_request" and event_path:
        try:
            event = json.loads(pathlib.Path(event_path).read_text(encoding="utf-8"))
            failures += verify_pr_event(event, snap, is_ancestor=_git_is_ancestor)
        except (OSError, ValueError) as exc:
            if in_ci:
                failures.append(f"cannot read GITHUB_EVENT_PATH: {exc}")
    elif on_main_push:
        pushed = os.environ.get("GITHUB_SHA", "")
        baseline = (snap.get("sync") or {}).get("baseline_main_head_at_sync", "")
        failures += verify_main_push(pushed, baseline, _git_is_ancestor)

    # (b) External durable PR exact-head verification (needs gh).
    numbers = [pr["number"] for pr in snap.get("prs", [])
               if isinstance(pr, dict) and pr.get("number") is not None]
    if not _have_gh():
        if in_ci:
            print("RED: gh CLI unavailable in CI — cannot verify live GitHub PR state (fail-closed).", file=sys.stderr)
            return 1
        if failures:
            for f in failures:
                print(f"  - {f}", file=sys.stderr)
            return 1
        print("SKIPPED (online PR checks): gh unavailable locally; event-context checks passed. CI is the wall.")
        return 0
    failures += compare_external_prs(snap, fetch_live(numbers))

    # (c) On a main push, resolve the carrier PR live and require the snapshot's post-merge transition
    #     to already be semantically correct (so merged main is not knowingly stale).
    if on_main_push:
        carrier = (snap.get("current_workflow_pr") or {}).get("number")
        if carrier is not None:
            failures += verify_carrier_post_merge(fetch_live([carrier]).get(carrier), snap)

    if failures:
        print("RED: config/current_state.json disagrees with live GitHub / CI context —", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print(f"\n{len(failures)} mismatch(es). Re-sync current_state.json.", file=sys.stderr)
        return 1
    print(f"GREEN: current_state.json exact-head-matches live GitHub for durable PRs {numbers} + CI event context.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
