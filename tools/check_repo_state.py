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
#: `mergeCommit` is read so `verify_settled_snapshot` can bound settled_at_main_head from BELOW.
#: An ancestor-of-main check alone can never go stale (the first commit ever made is an ancestor
#: of every head), which is A-07 from the fifth audit; the carrier's own merge is the real floor.
_GH_FIELDS = "state,isDraft,headRefName,baseRefName,headRefOid,mergeCommit"
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
        elif pr.get("draft") is None:
            failures.append(f"PR #{n}: snapshot omits `draft`. It used to be optional, which meant an "
                            f"entry could satisfy the settled-snapshot rule while anchoring only its "
                            f"head (A-05, fifth audit) — three of the four claimed anchors were "
                            f"conditional on the snapshot bothering to state them.")
        elif bool(pr.get("draft")) != bool(is_draft):
            failures.append(f"PR #{n}: snapshot draft={pr.get('draft')} but GitHub isDraft={is_draft}")
        # headRefName / baseRefName: must be present non-empty strings (missing => RED, not skip).
        head_branch = lv.get("headRefName")
        if not (isinstance(head_branch, str) and head_branch):
            failures.append(f"PR #{n}: live GitHub headRefName missing/empty: {head_branch!r} (fail-closed)")
        elif not pr.get("branch"):
            failures.append(f"PR #{n}: snapshot omits `branch` — a reader is told a pull request is "
                            f"open and not which branch to check out (A-05).")
        elif pr["branch"] != head_branch:
            failures.append(f"PR #{n}: snapshot branch={pr['branch']!r} but GitHub head branch={head_branch!r}")
        base_branch = lv.get("baseRefName")
        if not (isinstance(base_branch, str) and base_branch):
            failures.append(f"PR #{n}: live GitHub baseRefName missing/empty: {base_branch!r} (fail-closed)")
        elif not pr.get("base"):
            failures.append(f"PR #{n}: snapshot omits `base` — whether a pull request targets main or "
                            f"stacks on another branch changes what merging it means (A-05).")
        elif pr["base"] != base_branch:
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
    which transition branch applies). If MERGED, the snapshot's post_merge branch must ALREADY declare
    the post-merge truth (carrier_state 'merged' + a non-empty gate + a merged next-action) so main is
    NOT knowingly stale — the exact anti-self-stale rule. Gate NAMES are snapshot-declared (generic
    across a repository-truth carrier and a design-audit carrier), not hard-coded. Pure/testable."""
    ct = snapshot.get("carrier_transition") or {}
    post = ct.get("post_merge") or {}
    if not isinstance(carrier_live, dict) or carrier_live.get("state") is None:
        return ["carrier PR could not be resolved live on the main push — cannot prove pre/post-merge (fail-closed)"]
    failures: list[str] = []
    if carrier_live.get("state") == "MERGED":
        if post.get("carrier_state") != "merged":
            failures.append("carrier is live-MERGED but carrier_transition.post_merge.carrier_state != 'merged' "
                            "— canonical state still describes the carrier as open/pending (self-stale main)")
        if not (isinstance(post.get("gate"), str) and post.get("gate")):
            failures.append("carrier MERGED but carrier_transition.post_merge.gate is missing/empty")
        na = snapshot.get("next_action_by_carrier") or {}
        if not na.get("merged"):
            failures.append("carrier MERGED but next_action_by_carrier.merged is missing")
    return failures


def verify_carrier_state(carrier_live: dict | None, snapshot: dict) -> list[str]:
    """Enumerate the carrier's allowed live states and validate the MATCHING transition branch.
    Fail-closed: unresolved / missing / unknown live state => RED (we can't classify pre vs post
    merge). OPEN validates the pre_merge branch; MERGED validates the post_merge branch. Gate NAMES are
    snapshot-declared (a repository-truth carrier and a design-audit carrier use different gate strings),
    so this validates STRUCTURE (carrier_state + a non-empty gate), not a hard-coded value. Pure/testable."""
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
    if not (isinstance(pre.get("gate"), str) and pre.get("gate")):
        failures.append("carrier OPEN but carrier_transition.pre_merge.gate is missing/empty")
    return failures


def verify_settled_snapshot(carrier_no: int, carrier_state: str, snapshot: dict,
                            open_now: set[int] | None, live_main: str | None, is_ancestor,
                            carrier_merge_commit: str | None = None) -> list[str]:
    """The carrier has stopped being OPEN. What must the snapshot then say? Pure/testable.

    A carrier that has MERGED is the staleness this gate could not see. The event-context checks only
    run on a pull_request, so after the carrier merges the snapshot keeps naming it -- and a reader
    arriving at the repository goes looking for an open PR and a branch that no longer exist. CI stayed
    green throughout, because nothing asked. It asks here: once the carrier is no longer OPEN, the
    snapshot must say so explicitly, must record the main it settled at, and must leave no open pull
    request unnamed.

    THE THIRD ARM WAS WRONG, AND WROTE ITS OWN CORRECTION IN ITS FAILURE MESSAGE. It demanded
    `carrier_no in open_prs_now()` while telling the reader "the snapshot names NONE of them". Naming
    is the real requirement; carrier identity is not, because prs[] is exactly where this file records
    the other durable pull requests (see compare_external_prs, which exact-head-anchors every one of
    them). Demanding carrier identity made the rule UNSATISFIABLE the moment a second pull request
    stayed open across a merge:

      - main after any merge:  carrier is MERGED, the parked PR is open -> RED.
      - the repair PR:         must name ITSELF as carrier, or verify_carrier_exact_head compares the
                               repair PR's event head against the parked PR's head and goes RED.
      - so the repair merges:  carrier MERGED again, the parked PR still open -> RED again.

    A gate whose only repair re-creates the condition it fires on is not a gate, it is a trap; and the
    single file that holds it shut cannot be edited except through the pull request it refuses. That
    state is reachable from ordinary use -- one design proposal parked open for review while the
    builder keeps working -- and it is where this repository actually arrived, at PR #113 with #112
    open. Naming an open PR in prs[] is NOT a free pass out of it: every entry there is anchored to
    an exact live head, so a parked PR that moves still turns main RED and forces a deliberate
    re-sync. Only "named nowhere" is the failure.

    THAT SENTENCE USED TO CLAIM FOUR ANCHORS -- "exact live head, branch, base and draft flag" --
    and three of them were conditional in `compare_external_prs`, so an entry carrying only a
    number and a head satisfied it (A-05, fifth audit). A defence described as four checks and
    delivered as one is the same overclaim pattern the audit ledger exists to catch. The three are
    unconditional now for an OPEN entry, which makes the sentence true rather than trimming it.

    `open_now` is `None` when nothing could determine what is open. That is a REFUSAL, not an
    empty set: the whole justification for relaxing carrier-identity to naming is that the set of
    open pull requests is known, and `gh` failing is exactly when it is not.
    """
    if not carrier_state or carrier_state == "OPEN":
        return []
    if open_now is None:
        return [f"current_workflow_pr #{carrier_no} is {carrier_state} and the set of open pull "
                f"requests could not be determined (gh unavailable or failing). This rule permits a "
                f"merged carrier only when every open pull request is provably named, so it refuses "
                f"rather than assuming there are none."]
    settled = snapshot.get("settled_at_main_head")
    if not settled:
        return [f"current_workflow_pr #{carrier_no} is {carrier_state}, but the snapshot still names "
                f"it as active and records no settled_at_main_head. A reader would look for an open "
                f"PR that does not exist. Run: python tools/sync_active_pr.py --settled"]
    if live_main and settled != live_main and not is_ancestor(settled, live_main):
        # ANCESTOR, not equality. The first version demanded equality and could never be satisfied:
        # the settle commit is what MOVES main, so a file recording the head it produces can never
        # match it. Every settle left main red and the next settle inherited the same impossibility.
        # What the field actually means is "everything up to here has merged", and an ancestor check
        # says exactly that -- while still refusing a snapshot that settled at a commit which is not
        # on this main at all, which is the case worth catching.
        return [f"settled_at_main_head {str(settled)[:7]} is not an ancestor of live main "
                f"{live_main[:7]} — the snapshot settled at a commit that is not on this main. "
                f"Re-run: python tools/sync_active_pr.py --settled"]
    # AND BOUNDED FROM BELOW. An ancestor check alone can never go stale: the repository's very
    # first commit is an ancestor of every head, so a snapshot recording it would pass forever,
    # and the live value sat three merges behind HEAD while the gate was content (A-07, fifth
    # audit). The carrier's own merge commit is the floor that means something -- you cannot have
    # settled EARLIER than the pull request you are naming as the thing that merged.
    if carrier_merge_commit and settled != carrier_merge_commit \
            and not is_ancestor(carrier_merge_commit, settled):
        return [f"settled_at_main_head {str(settled)[:7]} is older than the merge commit of the "
                f"carrier it names (#{carrier_no} merged as {carrier_merge_commit[:7]}). An "
                f"ancestor-of-main check alone passes for the first commit ever made; the carrier's "
                f"own merge is the floor. Re-run: python tools/sync_active_pr.py --settled"]
    named = {carrier_no} | {pr["number"] for pr in snapshot.get("prs", [])
                            if isinstance(pr, dict) and isinstance(pr.get("number"), int)}
    unnamed = sorted(n for n in open_now if n not in named)
    if unnamed:
        listed = ", ".join(f"#{n}" for n in unnamed)
        return [f"current_workflow_pr #{carrier_no} is {carrier_state} and the snapshot names no "
                f"open pull request: {listed} {'is' if len(unnamed) == 1 else 'are'} open and "
                f"unnamed. Carry it as the new current_workflow_pr, or record it in prs[] with its "
                f"exact live head — a parked pull request still has to be visible from this file."]
    return []


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


def open_prs_now() -> set[int] | None:
    """Which pull requests are open right now, or None when nothing could find out.

    IT USED TO RETURN AN EMPTY SET ON FAILURE, and called that deliberate -- "must not invent a
    mismatch out of a network problem". That reasoning fit the old rule, which used the set only to
    ask whether the carrier was among the open PRs. It stopped fitting the moment the rule was
    relaxed to "every open pull request must be NAMED", because then an empty set does not mean
    "no mismatch", it means "no pull requests are open" -- the most permissive answer available,
    returned precisely when the truth is unknown. A non-zero exit, a rate limit, an expired token
    or empty stdout all produced a clean GREEN on a snapshot naming nothing (A-05, fifth audit).

    None is the honest answer, and the caller refuses on it. The failure is also PRINTED rather
    than swallowed, because a gate that quietly degrades is one nobody knows to distrust.
    """
    try:
        out = subprocess.run(["gh", "pr", "list", "--state", "open", "--json", "number"],
                             capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            print(f"  (gh pr list failed, exit {out.returncode}: {(out.stderr or '').strip()[:200]})",
                  file=sys.stderr)
            return None
        if not (out.stdout or "").strip():
            print("  (gh pr list returned no output)", file=sys.stderr)
            return None
        return {int(pr["number"]) for pr in json.loads(out.stdout)}
    except (subprocess.SubprocessError, OSError, ValueError, KeyError) as exc:
        print(f"  (gh pr list unavailable: {exc})", file=sys.stderr)
        return None


def _live_main_head() -> str | None:
    """origin/main as GitHub has it. None when git cannot answer, so the caller stays permissive
    about the thing it could not measure rather than inventing a failure."""
    try:
        out = subprocess.run(["git", "ls-remote", "origin", "refs/heads/main"],
                             capture_output=True, text=True, timeout=30)
    except (subprocess.SubprocessError, OSError):
        return None
    parts = out.stdout.split()
    return parts[0] if parts and _is_sha(parts[0]) else None


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

    # Once the carrier is no longer OPEN the snapshot has to say so, record the main it settled at,
    # and leave no open pull request unnamed. The rule itself lives in verify_settled_snapshot, which
    # is pure and therefore mutation-testable; this call site only supplies the live measurements.
    if carrier_no is not None:
        carrier_live = fetch_live([carrier_no]).get(carrier_no) or {}
        carrier_state = str(carrier_live.get("state") or "").upper()
        merge_commit = ((carrier_live.get("mergeCommit") or {}).get("oid")
                        if isinstance(carrier_live.get("mergeCommit"), dict) else None)
        failures += verify_settled_snapshot(carrier_no, carrier_state, snap,
                                            open_prs_now(), _live_main_head(), _git_is_ancestor,
                                            merge_commit if _is_sha(merge_commit) else None)

    # The EXACT-head anchor ALWAYS applies to the current_workflow_pr (the self-carrier): on its
    # pull_request, event head == live headRefOid == PR-body AUDIT_CANDIDATE_HEAD marker. The
    # merge-transition check (verify_carrier_state) applies ONLY when the snapshot models a
    # carrier_transition (the repository-truth carrier that merges to repair main). A design-audit
    # carrier (e.g. PR #31) has no transition block and needs only the exact-head anchor.
    models_transition = isinstance(snap.get("carrier_transition"), dict)
    # Fail closed on a CI pull_request whose snapshot omits current_workflow_pr: the self-carrier
    # exact-head anchor below is gated on `carrier_no is not None`, so an omitted current_workflow_pr
    # silently skips the ONLY live-head check on the PR and still prints GREEN (audit F-16). A PR CI
    # run MUST declare its self-carrier so its exact head can be anchored against live GitHub.
    if in_ci and carrier_no is None and event is not None and event.get("pull_request") is not None:
        failures.append(
            "snapshot omits current_workflow_pr on a pull_request CI run — the self-carrier "
            "exact-head anchor cannot be verified (fail-closed); declare current_workflow_pr.number"
        )
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
