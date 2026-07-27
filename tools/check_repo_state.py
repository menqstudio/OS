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
import re
import subprocess
import sys

MERGE_MAP = {"open": "OPEN", "merged": "MERGED", "closed": "CLOSED"}
_GH_FIELDS = "state,isDraft,headRefName,baseRefName,headRefOid"
_HEX40 = "0123456789abcdef"
# Live GitHub `state` values we accept for a DURABLE PR. Anything else (null, "", unknown) is RED.
_LIVE_PR_STATES = ("OPEN", "MERGED", "CLOSED")
# The carrier's transition model only has two live states: OPEN (pre-merge) and MERGED (post-merge).
# A CLOSED-unmerged / null / unknown carrier state is fail-closed RED (we can't classify the branch).
ALLOWED_CARRIER_STATES = ("OPEN", "MERGED")


def _is_sha(s) -> bool:
    return isinstance(s, str) and len(s) == 40 and all(c in _HEX40 for c in s)


def load_snapshot(root: pathlib.Path) -> dict:
    return json.loads((root / "config" / "current_state.json").read_text(encoding="utf-8"))


def compare_external_prs(snapshot: dict, live: dict) -> list[str]:
    """EXACT-head fail-closed for the durable project PRs in prs[]. `live` maps pr_number ->
    {state,isDraft,headRefName,baseRefName,headRefOid} or None. Pure/offline-testable.

    Every durable live field must EXIST and be VALID; a missing / null / empty / malformed / unknown
    live value is RED (fail-closed) — we never skip a comparison because a live value is falsy. That
    'skip on falsy' is the exact fail-open the Owner flagged: a missing headRefName / isDraft / base
    would otherwise pass silently."""
    failures: list[str] = []
    for pr in snapshot.get("prs", []):
        if not isinstance(pr, dict) or pr.get("number") is None:
            continue
        n = pr["number"]
        lv = live.get(n)
        if not isinstance(lv, dict):
            failures.append(f"PR #{n}: live GitHub state unresolved — cannot verify (fail-closed)")
            continue
        # state: must be a known GitHub PR state, then must match the snapshot.
        state = lv.get("state")
        want = MERGE_MAP.get(pr.get("merge_state"))
        if state not in _LIVE_PR_STATES:
            failures.append(f"PR #{n}: live GitHub state missing/unknown: {state!r} (fail-closed)")
        elif want is None:
            failures.append(f"PR #{n}: snapshot merge_state invalid: {pr.get('merge_state')!r}")
        elif state != want:
            failures.append(f"PR #{n}: snapshot merge_state={pr.get('merge_state')!r} but GitHub={state!r}")
        # isDraft: must be a real boolean (a missing/null value must NOT collapse to False).
        is_draft = lv.get("isDraft")
        if is_draft not in (True, False):
            failures.append(f"PR #{n}: live GitHub isDraft missing/not boolean: {is_draft!r} (fail-closed)")
        elif pr.get("draft") is not None and bool(pr.get("draft")) != bool(is_draft):
            failures.append(f"PR #{n}: snapshot draft={pr.get('draft')} but GitHub isDraft={is_draft}")
        # headRefName / baseRefName: must be present non-empty strings (missing => RED, not skip).
        head_branch = lv.get("headRefName")
        if not (isinstance(head_branch, str) and head_branch):
            failures.append(f"PR #{n}: live GitHub headRefName missing/empty: {head_branch!r} (fail-closed)")
        elif pr.get("branch") and pr["branch"] != head_branch:
            failures.append(f"PR #{n}: snapshot branch={pr['branch']!r} but GitHub head branch={head_branch!r}")
        base_branch = lv.get("baseRefName")
        if not (isinstance(base_branch, str) and base_branch):
            failures.append(f"PR #{n}: live GitHub baseRefName missing/empty: {base_branch!r} (fail-closed)")
        elif pr.get("base") and pr["base"] != base_branch:
            failures.append(f"PR #{n}: snapshot base={pr['base']!r} but GitHub base={base_branch!r}")
        # EXACT head: both sides must be 40-hex; drift is a FAILURE (forces re-sync), missing live is RED.
        # NOTE: the PR that CARRIES this snapshot is NOT listed in prs[] — it is the current_workflow_pr,
        # exact-head-anchored out-of-band by its PR-body AUDIT_CANDIDATE_HEAD marker (verify_carrier_exact_head).
        # So every entry HERE is an external durable PR and is fully exact-head-verified (nothing is exempt).
        snap_head = pr.get("head", "")
        live_head = lv.get("headRefOid")
        if not _is_sha(snap_head):
            failures.append(f"PR #{n}: snapshot 'head' must be an exact 40-hex sha, got {snap_head!r}")
        if not _is_sha(live_head):
            failures.append(f"PR #{n}: live GitHub headRefOid missing/not 40-hex: {live_head!r} (fail-closed)")
        if _is_sha(snap_head) and _is_sha(live_head) and snap_head != live_head:
            failures.append(f"PR #{n}: snapshot head {snap_head[:7]} != live head {live_head[:7]} "
                            f"(exact-head drift — re-sync current_state.json in the same PR)")
    return failures


_MARKER_KEYWORD_RE = re.compile(r"AUDIT_CANDIDATE_HEAD", re.I)
_MARKER_RE = re.compile(r"AUDIT_CANDIDATE_HEAD:\s*([0-9a-f]{40})\b")


def parse_audit_candidate(body) -> str | None:
    """Fail-closed: return the exact audited head ONLY if the PR body contains EXACTLY ONE marker
    keyword AND that marker is a valid 40-hex sha. Zero markers, DUPLICATE markers, or a malformed
    (non-40-hex) marker all return None — which is RED at the call site. A duplicate/ambiguous marker
    must never silently pick one; that would let an attacker append a second marker to smuggle a head."""
    if not isinstance(body, str):
        return None
    if len(_MARKER_KEYWORD_RE.findall(body)) != 1:   # zero or duplicate keyword occurrences => fail-closed
        return None
    m = _MARKER_RE.search(body)
    return m.group(1) if m else None                 # single keyword but malformed sha => None (RED)


def pull_request_trigger_types(workflow_yaml: str) -> set:
    """Extract `on.pull_request.types` from a workflow YAML with a minimal, stdlib-only indent scan
    (no PyYAML dependency in CI). Returns the set of declared trigger types (empty if none listed).
    Used by the deterministic test that proves `edited` stays in the trigger — a PR-body edit (which
    is where the AUDIT_CANDIDATE_HEAD marker lives) must start a fresh repo-state verification run."""
    lines = workflow_yaml.splitlines()
    out: set = set()
    n = len(lines)
    i = 0
    while i < n:
        if lines[i].strip() == "pull_request:":
            pr_indent = len(lines[i]) - len(lines[i].lstrip())
            j = i + 1
            collecting = False
            while j < n:
                lj = lines[j]
                if not lj.strip():
                    j += 1
                    continue
                indent = len(lj) - len(lj.lstrip())
                if indent <= pr_indent:
                    break  # dedented out of the pull_request block
                s = lj.strip()
                if s.startswith("types:"):
                    collecting = True
                    rest = s[len("types:"):].strip()
                    if rest.startswith("["):          # inline list form: types: [a, b, c]
                        for tok in rest.strip("[]").split(","):
                            t = tok.strip().strip("'\"")
                            if t:
                                out.add(t)
                        collecting = False
                elif collecting and s.startswith("- "):
                    out.add(s[2:].strip().strip("'\""))
                elif collecting:
                    collecting = False
                j += 1
            break
        i += 1
    return out


def verify_pr_event(event: dict, snapshot: dict) -> list[str]:
    """Fail-closed checks against the CURRENT workflow (carrier) PR's event payload (base SHA ==
    baseline; carrier number/branch/base match). Exact-head equality is verified separately in
    verify_carrier_exact_head() (it needs live GitHub + the PR-body marker). Pure/testable."""
    failures: list[str] = []
    pr = event.get("pull_request") or {}
    base = pr.get("base") or {}
    head = pr.get("head") or {}
    base_ref = base.get("ref")
    base_sha = base.get("sha")
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
    return failures


def verify_carrier_exact_head(event_head, live_head, body_marker) -> list[str]:
    """TRUE exact-head anchor (no descendant slack): the event PR head, the live GitHub headRefOid, and
    the PR-body `AUDIT_CANDIDATE_HEAD:` marker must ALL be present, 40-hex, and EQUAL. Because the PR
    body is out-of-band mutable metadata (not inside any commit), it can name the exact live head after
    the final push. A new descendant commit changes the live/event head while the body marker stays old
    -> RED, forcing a deliberate marker update + rerun + re-audit of the new exact HEAD. Pure/testable."""
    failures: list[str] = []
    if not _is_sha(event_head):
        failures.append(f"event PR head sha missing/not 40-hex: {event_head!r}")
    if not _is_sha(live_head):
        failures.append("live GitHub carrier head (headRefOid) unresolved (fail-closed)")
    if not _is_sha(body_marker):
        failures.append(f"PR-body AUDIT_CANDIDATE_HEAD marker missing/not 40-hex: {body_marker!r}")
    if _is_sha(event_head) and _is_sha(live_head) and event_head != live_head:
        failures.append(f"event head {event_head[:7]} != live GitHub head {live_head[:7]}")
    if _is_sha(event_head) and _is_sha(body_marker) and event_head != body_marker:
        failures.append(f"event head {event_head[:7]} != PR-body AUDIT_CANDIDATE_HEAD {body_marker[:7]} "
                        f"(a new commit needs a marker update + re-audit of the new exact HEAD)")
    return failures


def verify_carrier_post_merge(carrier_live: dict | None, snapshot: dict) -> list[str]:
    """On a push to main, resolve the carrier live. Fail closed if it cannot be resolved (can't prove
    which transition branch applies). If MERGED, the snapshot's post_merge state + phase_0 + merged
    next_action must already be correct so main is NOT knowingly stale. Pure/testable."""
    ct = snapshot.get("carrier_transition") or {}
    post = ct.get("post_merge") or {}
    if not isinstance(carrier_live, dict) or carrier_live.get("state") is None:
        return ["carrier PR could not be resolved live on the main push — cannot prove pre/post-merge (fail-closed)"]
    failures: list[str] = []
    if carrier_live.get("state") == "MERGED":
        if post.get("carrier_state") != "merged":
            failures.append("carrier MERGED but carrier_transition.post_merge.carrier_state != 'merged'")
        if post.get("gate") != "REBASE_PR31":
            failures.append(f"carrier MERGED but post_merge.gate is {post.get('gate')!r}, expected 'REBASE_PR31'")
        if post.get("phase_0") != "done":
            failures.append(f"carrier MERGED but post_merge.phase_0 is {post.get('phase_0')!r}, expected 'done'")
        phase0 = (snapshot.get("product_roadmap") or {}).get("phase_0")
        if isinstance(phase0, dict) and phase0.get("if_carrier_merged") != "done":
            failures.append("carrier MERGED but product_roadmap.phase_0.if_carrier_merged != 'done'")
        na = snapshot.get("next_action_by_carrier") or {}
        if not na.get("merged"):
            failures.append("carrier MERGED but next_action_by_carrier.merged is missing")
    return failures


def verify_carrier_state(carrier_live: dict | None, snapshot: dict) -> list[str]:
    """Enumerate the carrier's allowed live states and validate the MATCHING transition branch.
    Fail-closed: unresolved / missing / unknown live state => RED (we can't classify pre vs post
    merge). OPEN validates the pre_merge branch; MERGED validates the post_merge branch. This runs on
    BOTH the pull_request event (carrier expected OPEN) and the main push (expected MERGED), so a
    malformed / unexpected live carrier state can never fail-open. Pure/testable."""
    if not isinstance(carrier_live, dict) or carrier_live.get("state") is None:
        return ["carrier PR live state unresolved/missing — cannot classify pre/post-merge (fail-closed)"]
    state = carrier_live.get("state")
    if state not in ALLOWED_CARRIER_STATES:
        return [f"carrier PR live state {state!r} is not an allowed carrier state {ALLOWED_CARRIER_STATES} "
                f"(fail-closed — expected OPEN pre-merge or MERGED post-merge)"]
    if state == "MERGED":
        return verify_carrier_post_merge(carrier_live, snapshot)
    # OPEN: the pre_merge branch must be the active truth.
    pre = (snapshot.get("carrier_transition") or {}).get("pre_merge") or {}
    failures: list[str] = []
    if pre.get("carrier_state") != "open":
        failures.append("carrier OPEN but carrier_transition.pre_merge.carrier_state != 'open'")
    if pre.get("gate") != "PR33_REAUDIT":
        failures.append(f"carrier OPEN but pre_merge.gate is {pre.get('gate')!r}, expected 'PR33_REAUDIT'")
    if pre.get("phase_0") != "in_progress":
        failures.append(f"carrier OPEN but pre_merge.phase_0 is {pre.get('phase_0')!r}, expected 'in_progress'")
    phase0 = (snapshot.get("product_roadmap") or {}).get("phase_0")
    if isinstance(phase0, dict) and phase0.get("if_carrier_open") != "in_progress":
        failures.append("carrier OPEN but product_roadmap.phase_0.if_carrier_open != 'in_progress'")
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


def fetch_carrier(number: int) -> dict | None:
    """Fetch the carrier PR's live state + headRefOid + body (for the AUDIT_CANDIDATE_HEAD marker)."""
    try:
        out = subprocess.run(
            ["gh", "pr", "view", str(number), "--json", "state,isDraft,headRefName,baseRefName,headRefOid,body"],
            capture_output=True, text=True, timeout=30, check=True).stdout
        return json.loads(out)
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


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

    on_main_push = event_name == "push" and os.environ.get("GITHUB_REF") == "refs/heads/main"
    event = None
    if event_name == "pull_request" and event_path:
        try:
            event = json.loads(pathlib.Path(event_path).read_text(encoding="utf-8"))
            failures += verify_pr_event(event, snap)
        except (OSError, ValueError) as exc:
            if in_ci:
                failures.append(f"cannot read GITHUB_EVENT_PATH: {exc}")
    elif on_main_push:
        pushed = os.environ.get("GITHUB_SHA", "")
        baseline = (snap.get("sync") or {}).get("baseline_main_head_at_sync", "")
        failures += verify_main_push(pushed, baseline, _git_is_ancestor)

    # (b) Live GitHub. External durable PR exact-head + carrier exact-head anchor / post-merge.
    numbers = [pr["number"] for pr in snap.get("prs", [])
               if isinstance(pr, dict) and pr.get("number") is not None]
    carrier_no = (snap.get("current_workflow_pr") or {}).get("number")
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

    # The EXACT-head anchor ALWAYS applies to the current_workflow_pr (the self-carrier): on its
    # pull_request, event head == live headRefOid == PR-body AUDIT_CANDIDATE_HEAD marker. The
    # merge-transition check (verify_carrier_state) applies ONLY when the snapshot models a
    # carrier_transition (the repository-truth carrier that merges to repair main). A design-audit
    # carrier (e.g. PR #31) has no transition block and needs only the exact-head anchor.
    models_transition = isinstance(snap.get("carrier_transition"), dict)
    if event is not None and carrier_no is not None:
        cl = fetch_carrier(carrier_no)
        event_head = ((event.get("pull_request") or {}).get("head") or {}).get("sha")
        failures += verify_carrier_exact_head(event_head, (cl or {}).get("headRefOid"),
                                              parse_audit_candidate((cl or {}).get("body")))
        if models_transition:
            failures += verify_carrier_state(cl, snap)
    # Carrier state on a main push (fail-closed if unresolvable/unknown; MERGED => post_merge branch).
    if on_main_push and carrier_no is not None and models_transition:
        failures += verify_carrier_state(fetch_carrier(carrier_no), snap)

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
