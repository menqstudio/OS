#!/usr/bin/env python3
"""Coordination-docs consistency gate — the CI wall for the Startup Law.

The repo's rule "read the canonical files, keep them synced in the same commit" is
otherwise un-enforced: it degrades to *remember to*, and gets forgotten. This is the
enforcement — a deterministic, offline, fail-closed check that CI runs on every PR, so
malformed or structurally-inconsistent coordination docs **cannot merge**. It mirrors
the engine's `bro_docs_freshness.py` posture: green on structure, hard-fail otherwise.

Two layers:
  - STRUCTURAL (always, offline): canonical files present, roadmap 0..10 x 16 sections,
    balanced fences, TASKS status vocabulary, and PROJECT_STATE's dated freshness line
    COMPARED against the newest commit that touched that file (it used to be compared
    against nothing while the output said "fresh").
  - SEMANTIC + PR-AWARE (Phase 0.2, strengthened): validate the machine-readable anchor
    config/current_state.json (schema 2) — closed enums, PR parent/child relationships,
    design-gate state, is_rc requires design-GREEN; require every human state doc to
    reference EVERY active PR + branch + task; and (on a PR diff) require a substantive
    change to sync the state files. Its FREE-TEXT fields (purpose, next_action,
    stop_gates, next_action_by_carrier) are checked against the structured ones in the
    same file, because until 2026-08-09 nothing read them and all four were wrong at once. So "did you update the state after this change" is NO
    LONGER only the Claude-side Stop-hook's job — CI now enforces it deterministically.
  - LIVE GITHUB (separate, tools/check_repo_state.py, CI): compares the current_state.json
    PR snapshot against live GitHub (open/merged/draft/base) and fails closed on mismatch,
    so a merged PR recorded as "open" cannot pass. This file stays offline-only by design.

Usage:  python tools/check_coordination.py [--root DIR]
Exit 0 + "GREEN: ..." when consistent; exit 1 + the problems otherwise.
"""
from __future__ import annotations

import argparse
import datetime
import fnmatch
import json
import os
import pathlib
import re
import subprocess
import sys

# The 16 sections every roadmap phase must carry (roadmap §"Phases").
REQUIRED_SECTIONS = (
    "Objective", "Scope", "Architecture", "UI/UX work", "Backend work",
    "Contracts / schemas", "Data models", "Dependencies", "Security gates",
    "Tests", "CI requirements", "Documentation updates", "Acceptance criteria",
    "Merge gate", "Stop conditions", "Definition of Done",
)
CANONICAL_FILES = (
    "CLAUDE.md", "PROJECT_STATE.md", "TASKS.md", "OWNERS.md",
    "MASTER_EXECUTION_ROADMAP.md", "docs/ARCHITECTURE.md",
)
ROADMAP = "MASTER_EXECUTION_ROADMAP.md"
EXPECTED_PHASES = list(range(0, 11))  # 0..10
TASK_STATUSES = ("Todo", "In-Progress", "Review", "Done", "Blocked")

# --- semantic + PR-aware layer (added Phase 0.2) --------------------------------------------------
# The structural checks above cannot catch the drift that actually happened: canonical docs frozen at
# a stale reality (a merged PR still called "awaiting merge"; "no code exists" while an impl PR is
# live). Root cause = multiple hand-maintained truth copies. Fix: ONE machine-readable anchor
# (config/current_state.json) that the human docs must agree with, plus a PR-aware "code change must
# update the state docs" check. All new checks fail-closed on malformed input and SKIP cleanly when
# this is not a real coordination repo (no NEXT_CHAT.md) or not a PR (no diff base) — so the offline
# unit tests and push->main runs stay green.
STATE_DOCS = ("NEXT_CHAT.md", "PROJECT_STATE.md", "TASKS.md")
CURRENT_STATE_JSON = "config/current_state.json"
MANIFEST = "config/canonical-read-manifest.json"
# active-wave normative docs that MUST be in the startup manifest WHEN they exist on disk (pinning
# them so a future edit cannot silently orphan the live normative chain).
ACTIVE_WAVE_DOCS = ("docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md",)
# git-diff globs that count as a "substantive change" requiring a same-PR state-doc update. fnmatch
# `*` spans `/`, so these match at any depth. Root coordination *.md and tooling are deliberately
# excluded (a typo fix must not demand a state bump — see the module docstring's structure/coordination
# line). current_state.json is BOTH substantive and a valid state-touch, so a PR editing only it passes.
SUBSTANTIVE_GLOBS = (
    "engine/*", "bridge/*", "apps/desktop/src/*", "apps/desktop/src-tauri/*",
    "*.rs", "*.sql", "*capabilit*", "*/contracts/*", "*.contract.json",
    "docs/design/*", "config/canonical-read-manifest.json", "config/current_state.json",
)
# closed enums for config/current_state.json (schema 2).
MERGE_STATES = ("open", "merged", "closed")
PR_ROLES = ("design", "implementation", "repository-truth", "release")
GATE_STATES = ("NOT_SUBMITTED", "PENDING_REAUDIT", "YELLOW", "RED", "GREEN")
VERDICTS = ("NONE", "YELLOW", "RED", "GREEN")
# --- contradiction gate (Phase-0 correction) -----------------------------------------------------
# Explicitly-marked historical prose is EXCLUDED from current-state validation. Everything outside
# these markers is "current" and must be internally consistent with the status tokens.
HISTORY_BEGIN = "<!-- HISTORY_BEGIN -->"
HISTORY_END = "<!-- HISTORY_END -->"
# a subject the status tokens mark "complete" must NOT be described as pending in the CURRENT region.
_PENDING_WORDS = r"(pending|not done|still open|not started|not yet done|still pending|are open|remain open)"
SUBJECT_PROSE = {
    "CURRENT_VERIFY_SEAM": r"verify.?seam",
    "CURRENT_RECEIPT_PLUMBING": r"receipt.?plumbing",
    "CURRENT_GOVERNED_ROUNDTRIP": r"governed round.?trip",
}
# Structured carrier-resolution tokens: every CURRENT block must carry ALL four (both transition
# branches), and each must equal the corresponding anchor field. Because they live in status_tokens
# they are ALSO required verbatim in every human doc's CURRENT region (via _check_status_tokens) — so
# a plain proximity regex is no longer the only defense: the machine-checked structured block is.
CARRIER_RESOLUTION_TOKENS = {
    "CARRIER_IF_OPEN_GATE": ("carrier_transition", "pre_merge", "gate"),
    "CARRIER_IF_MERGED_GATE": ("carrier_transition", "post_merge", "gate"),
}
# a carrier-action / carrier-state phrase that goes STALE the moment PR #33 merges. Any of these near a
# bare "PR #33" mention, unguarded by an IF-OPEN/IF-MERGED transition marker on the same line, is RED.
_CARRIER_UNCONDITIONAL = re.compile(
    r"not( yet)? merged|un-?merged|awaiting[ -]?re-?audit|pending[ -]?re-?audit|"
    r"→\s*merge|->\s*merge|merge it\b|merge PR ?#?33|"
    r"re-?audit[^.\n]{0,8}(→|->|then\b)|re-?audit\s+PR ?#?33|PR ?#?33[^.\n]{0,25}re-?audit",
    re.I)
_CARRIER_GUARD = re.compile(r"\b(if open|while open|if merged|when open|when merged|if pr ?#?33 is open)\b", re.I)
# strong clause boundaries: a sentence end, a blank line, a bullet, a numbered item, or a table pipe.
# We scope the carrier scan to a single CLAUSE (robust to markdown hard-wrapping), so a guarded
# transition sentence is fine while a SEPARATE unconditional sentence in the same block is still caught.
_STRONG_BOUNDARY = re.compile(r"\.\s|!\s|\?\s|\n\s*\n|\n\s*>?\s*[-*]\s|\n\s*\d+\.\s|\|")


def _dig(data, path):
    d = data
    for k in path:
        d = d.get(k) if isinstance(d, dict) else None
    return d


def _prose_only(region: str) -> str:
    """Drop structured `CURRENT_*: value` / `CARRIER_*: value` tokens so the carrier prose scan does not
    trip over the machine tokens themselves (which legitimately contain 'PR33', 'REAUDIT', 'merge')."""
    return re.sub(r"`?(CURRENT|CARRIER)_[A-Z0-9_]+`?\s*[:=]\s*`?[^`\n·]*`?", " ", region)


def _read(root: pathlib.Path, rel: str) -> str | None:
    p = root / rel
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


def _phase_blocks(text: str) -> dict[int, str]:
    """Map each phase number to its section text (up to the next phase / appendix)."""
    heads = list(re.finditer(r"(?m)^## Phase (\d+) —", text))
    end_marker = re.search(r"(?m)^# Appendix", text)
    hard_end = end_marker.start() if end_marker else len(text)
    blocks: dict[int, str] = {}
    for i, m in enumerate(heads):
        start = m.start()
        stop = heads[i + 1].start() if i + 1 < len(heads) else hard_end
        blocks[int(m.group(1))] = text[start:stop]
    return blocks


def _load_json(root: pathlib.Path, rel: str):
    """Return parsed JSON, None if absent, or the sentinel 'MALFORMED' on parse error."""
    txt = _read(root, rel)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except ValueError:
        return "MALFORMED"


def _glob_hit(path: str, globs) -> bool:
    return any(fnmatch.fnmatch(path, g) for g in globs)


def _changed_files(base_ref: str) -> list[str] | None:
    """git diff --name-only origin/<base>...HEAD (or <base>...HEAD). None if unavailable."""
    for ref in (f"origin/{base_ref}", base_ref):
        try:
            out = subprocess.run(
                ["git", "diff", "--name-only", f"{ref}...HEAD"],
                capture_output=True, text=True, timeout=30, check=True,
            ).stdout
            return [ln.strip().replace("\\", "/") for ln in out.splitlines() if ln.strip()]
        except (subprocess.SubprocessError, OSError):
            continue
    return None


PROJECT_STATE = "PROJECT_STATE.md"
_LAST_UPDATED_RE = re.compile(r"(?m)^\*\*Last updated[^:]*:\*\*\s*(.+?)\s*$")
_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _last_commit_date(root: pathlib.Path, rel: str) -> datetime.date | None:
    """The committer date of the newest commit that touched `rel`, or None when git cannot answer.

    None is returned for a non-repository, a shallow clone that does not reach the commit, an
    untracked file, or no git at all. The caller must then SAY it could not compare, never call the
    file fresh — reporting a comparison that did not happen is the defect this whole check replaces.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%cs", "--", rel],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None
    m = _ISO_DATE_RE.fullmatch(out)
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _claim_before_last_change(root: pathlib.Path, rel: str) -> tuple[str, datetime.date | None] | None:
    """What the `Last updated` line said BEFORE the newest commit that touched `rel`.

    ``("absent", None)`` when the file did not exist yet; ``("unreadable", None)`` when the line
    could not be parsed out of the parent; otherwise ``("date", <date>)``. ``None`` means git could
    not answer at all, and the caller must say so rather than assume.

    This is T-060's whole mechanism. A squash merge re-dates the commit to the merge moment — and
    both dates: over all 796 commits on ``main`` there is not one where ``%as`` differs from
    ``%cs``, measured, so reading the author date instead would have fixed nothing. A pull request
    written yesterday and merged today therefore produces a commit dated today touching a file
    whose line says yesterday, and the old comparison reddened ``main`` AFTER the merge, where
    nobody can fix it without another merge.

    The date comparison was a proxy for the actual law: *update the line in the SAME commit as the
    change*. So the law is what is checked. If the newest commit that touched the file also moved
    this line, the law was obeyed and the calendar gap is merge lag. If the file changed and the
    line did not, that is the real defect and it is refused exactly as before.
    """
    try:
        sha = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%H", "--", rel],
            capture_output=True, text=True, timeout=30, check=True).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return None
    previous = subprocess.run(
        ["git", "-C", str(root), "show", f"{sha}^:{rel}"],
        capture_output=True, text=True, timeout=30)
    if previous.returncode != 0:
        # No parent, or the file was created by that commit: there was no earlier claim to move.
        return ("absent", None)
    claimed, problem = _claimed_last_updated(previous.stdout)
    if problem or claimed is None:
        return ("unreadable", None)
    return ("date", claimed)


def _claimed_last_updated(text: str) -> tuple[datetime.date | None, str | None]:
    """(date, problem) for PROJECT_STATE.md's `**Last updated ...:**` line."""
    m = _LAST_UPDATED_RE.search(text)
    if not m or len(m.group(1).strip()) < 3:
        return None, f"{PROJECT_STATE}: missing/empty '**Last updated ...:**' line"
    raw = m.group(1).strip()
    d = _ISO_DATE_RE.search(raw)
    if not d:
        return None, (f"{PROJECT_STATE}: the '**Last updated ...:**' line carries no YYYY-MM-DD date "
                      f"({raw[:40]!r}) — this gate compares that date against the newest commit that "
                      f"touched the file, and it cannot compare prose")
    try:
        return datetime.date(int(d.group(1)), int(d.group(2)), int(d.group(3))), None
    except ValueError:
        return None, (f"{PROJECT_STATE}: '**Last updated ...:**' names {d.group(0)}, which is not a "
                      f"real calendar date")


def _check_project_state_freshness(root: pathlib.Path) -> list[str]:
    """PROJECT_STATE.md's stated date must not be older than the file's newest commit.

    This used to check only that a non-empty `**Last updated:**` line EXISTED, while the gate's
    output said "PROJECT_STATE fresh" — so a date three days behind the last change to the very
    file it dates passed, and the green line asserted the opposite of the truth. The date is now
    compared to something real, and when it cannot be compared the output says so instead.
    """
    text = _read(root, PROJECT_STATE)
    if text is None:
        return []                       # absence is reported by the canonical-files check
    claimed, problem = _claimed_last_updated(text)
    if problem:
        return [problem]
    assert claimed is not None
    problems: list[str] = []
    # A date in the future is the other way to make this line say nothing. One day of slack covers
    # a runner whose clock sits on the far side of UTC midnight from the author's.
    today = datetime.datetime.now(datetime.timezone.utc).date()
    if claimed > today + datetime.timedelta(days=1):
        problems.append(f"{PROJECT_STATE}: '**Last updated:** {claimed}' is in the future "
                        f"(today is {today} UTC) — a date nothing has reached yet dates nothing")
    committed = _last_commit_date(root, PROJECT_STATE)
    if committed is None or claimed >= committed:
        return problems

    # The date is behind the newest commit. That is the QUESTION, not yet the verdict — a squash
    # merge re-dates the commit to the merge moment, so a correct pull request written yesterday
    # and merged today lands here. What separates the two cases is whether the line MOVED in that
    # same commit, which is the law the date was standing in for.
    before = _claim_before_last_change(root, PROJECT_STATE)
    if before is None:
        problems.append(
            f"{PROJECT_STATE}: '**Last updated:** {claimed}' is older than the newest commit that "
            f"touched the file ({committed}), and git could not say what the line claimed before "
            f"that commit — so this could not be compared. Not a pass: read it by hand")
        return problems
    kind, previous = before
    if kind == "date" and previous == claimed:
        problems.append(
            f"{PROJECT_STATE}: '**Last updated:** {claimed}' is older than the newest commit that "
            f"touched the file ({committed}) and that commit did NOT move the line — the file "
            f"changed after the date it claims, so every reader is told the state is "
            f"{(committed - claimed).days} day(s) fresher than it is. Update the line in the SAME "
            f"commit as the change (the Startup Law), or move the prose it dates into a HISTORY "
            f"block")
    elif kind == "date" and previous is not None and claimed < previous:
        # The line moved BACKWARDS. Moving it at all is not the property; moving it forward is.
        problems.append(
            f"{PROJECT_STATE}: '**Last updated:** {claimed}' is EARLIER than what the line said "
            f"before the newest commit ({previous}). A date that goes backwards dates nothing")
    return problems


def _check_current_state(root: pathlib.Path) -> list[str]:
    """config/current_state.json (schema 2) is the machine-readable truth SNAPSHOT. Validate its
    structure + internal relationships + closed enums whenever this is a real coordination repo. Note:
    it is a snapshot synced against a baseline, NOT a live GitHub oracle — the live comparison is
    tools/check_repo_state.py (CI). Here we only check what is deterministic offline."""
    problems: list[str] = []
    if _read(root, "NEXT_CHAT.md") is None:
        return problems  # not a real coordination repo (offline unit-test fixtures) — skip
    data = _load_json(root, CURRENT_STATE_JSON)
    if data is None:
        return [f"missing {CURRENT_STATE_JSON} (machine-readable current-state anchor)"]
    if data == "MALFORMED" or not isinstance(data, dict):
        return [f"{CURRENT_STATE_JSON}: invalid JSON object"]
    for field in ("sync", "active", "prs", "waves", "design_gate", "stop_gates", "next_action_by_carrier"):
        if field not in data:
            problems.append(f"{CURRENT_STATE_JSON}: missing required field '{field}'")
    sync = data.get("sync") if isinstance(data.get("sync"), dict) else {}
    # A BASELINE head (honest snapshot), not a "live main_head" that goes stale on the next merge.
    head = sync.get("baseline_main_head_at_sync", "")
    if not (isinstance(head, str) and re.fullmatch(r"[0-9a-f]{40}", head)):
        problems.append(f"{CURRENT_STATE_JSON}: sync.baseline_main_head_at_sync must be a 40-hex sha, got {head!r}")
    active = data.get("active") if isinstance(data.get("active"), dict) else {}
    waves = data.get("waves") if isinstance(data.get("waves"), dict) else {}
    aw = active.get("wave")
    if aw is not None and aw not in waves:
        problems.append(f"{CURRENT_STATE_JSON}: active.wave {aw!r} is not present in waves{{}}")
    prs = data.get("prs") if isinstance(data.get("prs"), list) else []
    pr_by_num: dict = {}
    open_branches: set = set()
    for pr in prs:
        if not isinstance(pr, dict):
            continue
        num = pr.get("number")
        pr_by_num[num] = pr
        if pr.get("merge_state") not in MERGE_STATES:
            problems.append(f"{CURRENT_STATE_JSON}: PR #{num} merge_state must be one of {MERGE_STATES}, got {pr.get('merge_state')!r}")
        if pr.get("draft") not in (True, False):
            problems.append(f"{CURRENT_STATE_JSON}: PR #{num} draft must be true/false")
        if pr.get("role") not in PR_ROLES:
            problems.append(f"{CURRENT_STATE_JSON}: PR #{num} role must be one of {PR_ROLES}, got {pr.get('role')!r}")
        if pr.get("merge_state") == "open":
            open_branches.add(pr.get("branch"))
    ab = active.get("branch")
    # the active branch may be an OPEN durable PR branch OR the current_workflow_pr's branch (the PR that
    # carries this snapshot — e.g. the design-audit carrier PR #31, which is not listed in prs[]).
    cw_branch = (data.get("current_workflow_pr") or {}).get("branch") if isinstance(data.get("current_workflow_pr"), dict) else None
    # A SETTLED snapshot is the legitimate third case: nothing is open, everything merged, and the
    # active branch is main. Without this the rule forces the docs to keep naming a branch that was
    # deleted, which is the staleness `sync_active_pr.py --settled` exists to remove. The escape is
    # deliberately narrow -- only `main`, and only when a settled head is recorded.
    settled = bool(data.get("settled_at_main_head")) and ab == "main"
    if ab and not settled and ab not in open_branches and ab != cw_branch:
        problems.append(f"{CURRENT_STATE_JSON}: active.branch {ab!r} does not correspond to any OPEN PR branch "
                        f"or the current_workflow_pr branch")
    # relationships: parent PR exists in prs[] OR is the current_workflow_pr (the carrier, not in prs[]);
    # child base == parent branch; open impl PR ⇒ code exists.
    cw_pr = data.get("current_workflow_pr") if isinstance(data.get("current_workflow_pr"), dict) else {}
    for pr in prs:
        if not isinstance(pr, dict):
            continue
        num = pr.get("number")
        parent = pr.get("parent_pr")
        if parent is not None:
            p = pr_by_num.get(parent)
            if p is None and cw_pr.get("number") == parent:
                p = cw_pr  # the parent is the carrier PR (e.g. #32's parent #31 is the design-audit carrier)
            if p is None:
                problems.append(f"{CURRENT_STATE_JSON}: PR #{num} parent_pr #{parent} is not listed in prs[] or the current_workflow_pr")
            elif pr.get("base") != p.get("branch"):
                problems.append(f"{CURRENT_STATE_JSON}: PR #{num} base {pr.get('base')!r} != parent PR #{parent} branch {p.get('branch')!r}")
        if pr.get("role") == "implementation" and pr.get("merge_state") != "merged":
            w = waves.get(aw, {})
            if not (isinstance(w, dict) and w.get("code_exists") is True):
                problems.append(f"{CURRENT_STATE_JSON}: open implementation PR #{num} but waves[{aw!r}].code_exists is not true")
    # design gate: closed enums; a PENDING_REAUDIT candidate cannot also be an RC / claimed GREEN.
    dg = data.get("design_gate") if isinstance(data.get("design_gate"), dict) else {}
    gate = dg.get("current_candidate_gate")
    if gate is not None and gate not in GATE_STATES:
        problems.append(f"{CURRENT_STATE_JSON}: design_gate.current_candidate_gate must be one of {GATE_STATES}, got {gate!r}")
    if dg.get("last_architect_verdict") is not None and dg.get("last_architect_verdict") not in VERDICTS:
        problems.append(f"{CURRENT_STATE_JSON}: design_gate.last_architect_verdict must be one of {VERDICTS}")
    for pr in prs:
        if isinstance(pr, dict) and pr.get("is_rc") is True:
            if gate != "GREEN":
                problems.append(f"{CURRENT_STATE_JSON}: PR #{pr.get('number')} is_rc=true but design_gate is {gate!r}, not GREEN (CI-green is not audit-green)")
            if pr.get("code_verdict") != "GREEN":
                problems.append(f"{CURRENT_STATE_JSON}: PR #{pr.get('number')} is_rc=true but its code_verdict is not GREEN")
    # current_workflow_pr = the PR that carries this snapshot (the exact-head "carrier"). Its exact head
    # is anchored out-of-band by the PR-body AUDIT_CANDIDATE_HEAD marker (verified live by
    # tools/check_repo_state.py: event head == live headRefOid == marker). It MUST carry number+branch+base.
    cw = data.get("current_workflow_pr")
    if cw is not None:
        if not isinstance(cw, dict):
            problems.append(f"{CURRENT_STATE_JSON}: current_workflow_pr must be an object")
        else:
            for f in ("number", "branch", "base"):
                if cw.get(f) in (None, ""):
                    problems.append(f"{CURRENT_STATE_JSON}: current_workflow_pr.{f} is required")
            if cw.get("number") in {p.get("number") for p in prs if isinstance(p, dict)}:
                problems.append(f"{CURRENT_STATE_JSON}: current_workflow_pr #{cw.get('number')} must NOT also be "
                                f"listed in prs[] (a self-carrier cannot exact-head-verify itself; it uses the "
                                f"PR-body AUDIT_CANDIDATE_HEAD marker instead)")
        # carrier_transition models a MERGE-to-main transition (needed for the repository-truth carrier so
        # main is never knowingly stale post-merge). It is OPTIONAL: a design-audit carrier (e.g. PR #31)
        # does not merge to repair main and needs no transition block. Validate it ONLY when present.
        ct = data.get("carrier_transition")
        if ct is not None:
            if not isinstance(ct, dict):
                problems.append(f"{CURRENT_STATE_JSON}: carrier_transition must be an object when present")
            else:
                # gate NAMES are snapshot-declared (a repository-truth carrier and a design-audit carrier
                # use different gate strings); validate STRUCTURE — carrier_state + a non-empty gate.
                for phase, want_carrier in (("pre_merge", "open"), ("post_merge", "merged")):
                    blk = ct.get(phase)
                    if not isinstance(blk, dict):
                        problems.append(f"{CURRENT_STATE_JSON}: carrier_transition.{phase} block missing")
                        continue
                    if blk.get("carrier_state") != want_carrier:
                        problems.append(f"{CURRENT_STATE_JSON}: carrier_transition.{phase}.carrier_state must be {want_carrier!r}")
                    if not (isinstance(blk.get("gate"), str) and blk.get("gate").strip()):
                        problems.append(f"{CURRENT_STATE_JSON}: carrier_transition.{phase}.gate must be a non-empty string")
            # when a merge-transition IS modeled, the structured CARRIER_IF_* gate tokens must be present
            # and match the anchor, and next_action_by_carrier must carry both branches.
            na = data.get("next_action_by_carrier")
            if not (isinstance(na, dict) and na.get("open") and na.get("merged")):
                problems.append(f"{CURRENT_STATE_JSON}: next_action_by_carrier must have both 'open' and 'merged' branches when carrier_transition is modeled")
            tokens = data.get("status_tokens") if isinstance(data.get("status_tokens"), dict) else {}
            for tk, path in CARRIER_RESOLUTION_TOKENS.items():
                want = _dig(data, path)
                got = tokens.get(tk)
                if got is None:
                    problems.append(f"{CURRENT_STATE_JSON}: status_tokens.{tk} missing — carrier_transition is "
                                    f"modeled, so every CURRENT block must carry the structured carrier-resolution token")
                elif want is not None and str(got) != str(want):
                    problems.append(f"{CURRENT_STATE_JSON}: status_tokens.{tk}={got!r} != {'.'.join(path)}={want!r} "
                                    f"(structured carrier-resolution token must match the transition anchor)")
    return problems



# The FREE-TEXT fields of config/current_state.json were read by nothing. `_check_current_state`
# above validates structure, closed enums and PR relationships; `purpose`, `next_action`,
# `stop_gates[]` and `next_action_by_carrier` are prose, and prose written in the present tense at a
# moment that has passed is exactly what this gate exists to catch. On 2026-08-09 all four were
# wrong at once: `purpose` asserted "active.branch is main" while it was a branch;
# `next_action` opened "The independent CODE-audit is GREEN" while `code_audit.gate` in the same
# file said ARCHITECT_PENDING; `next_action_by_carrier` still modelled PR #48 as the open carrier
# thirty-odd merged PRs later; and `stop_gates` cited `platform_governed_execution_supported()` as a
# live flag when no function of that name exists in the tree.
#
# The four rules below are narrow on purpose. Each is deterministic, each names the exact drift it
# saw, and none of them tries to judge prose in general -- a check that guesses is a check that gets
# disabled.
def _unquoted(text: str) -> str:
    """Drop double-quoted spans: a sentence that QUOTES an old claim is not making it.

    Without this the prose rules below punish the correction note as if it were the defect --
    which is how honest history gets deleted instead of kept. Single quotes are deliberately NOT
    treated as quotation: apostrophes are far too common for that to be safe. Quote a superseded
    claim with double quotes if you want to keep it on the record.
    """
    text = re.sub(r'"[^"]*"', " ", text)
    return re.sub("“[^”]*”", " ", text)

PHANTOM_SYMBOL = "platform_governed_execution_supported()"
#: Saying the phantom symbol is fine when the sentence says it is a spec symbol. Any of these
#: nearby disclaimers satisfies the rule.
PHANTOM_DISCLAIMERS = (
    "no function of that name exists",
    "NO FUNCTION OF THAT NAME EXISTS",
    "spec symbol",
    "\u00a70.1 spec symbol",
)


def _check_current_state_prose(root: pathlib.Path) -> list[str]:
    """The free-text fields must not contradict the structured ones in the same file."""
    problems: list[str] = []
    if _read(root, "NEXT_CHAT.md") is None:
        return problems
    data = _load_json(root, CURRENT_STATE_JSON)
    if not isinstance(data, dict):
        return problems  # structure errors are already reported by _check_current_state

    purpose = data.get("purpose") if isinstance(data.get("purpose"), str) else ""
    next_action = data.get("next_action") if isinstance(data.get("next_action"), str) else ""
    stop_gates = [s for s in (data.get("stop_gates") or []) if isinstance(s, str)]
    nabc = data.get("next_action_by_carrier")
    nabc_text = " ".join(str(v) for v in nabc.values()) if isinstance(nabc, dict) else ""
    active_branch = ((data.get("active") or {}) if isinstance(data.get("active"), dict) else {}).get("branch")
    cw = data.get("current_workflow_pr") if isinstance(data.get("current_workflow_pr"), dict) else {}
    gate = ((data.get("code_audit") or {}) if isinstance(data.get("code_audit"), dict) else {}).get("gate")

    # 1. purpose must not assert a branch the structured field contradicts. Only the literal
    #    "active.branch is main" is judged -- an unambiguous claim with no false positives.
    if "active.branch is main" in _unquoted(purpose) and active_branch != "main":
        problems.append(
            f"{CURRENT_STATE_JSON}: purpose says 'active.branch is main' but active.branch is "
            f"{active_branch!r} (the prose fields are not exempt from the anchor)")

    # 2. an audit that has not passed must not be described as passed.
    if gate is not None and gate != "GREEN":
        for phrase in ("the independent CODE-audit is GREEN", "the independent code-audit is green"):
            if phrase.lower() in _unquoted(next_action).lower():
                problems.append(
                    f"{CURRENT_STATE_JSON}: next_action says {phrase!r} while code_audit.gate is "
                    f"{gate!r}. A waiver is not a pass; say which it was.")
                break

    # 3. the carrier block must name the carrier this snapshot actually has.
    if isinstance(nabc, dict) and cw.get("number") is not None:
        if f"#{cw['number']}" not in nabc_text:
            problems.append(
                f"{CURRENT_STATE_JSON}: next_action_by_carrier never names the carrier "
                f"#{cw['number']} (current_workflow_pr). It modelled PR #48 for three days after "
                f"#48 merged.")

    # 4. the spec symbol may be named, but not as though it were a function in the tree.
    for label, text in (("purpose", purpose), ("next_action", next_action),
                        ("next_action_by_carrier", nabc_text)) + \
                       tuple((f"stop_gates[{i}]", s) for i, s in enumerate(stop_gates)):
        if PHANTOM_SYMBOL in _unquoted(text) and not any(d.lower() in text.lower() for d in PHANTOM_DISCLAIMERS):
            problems.append(
                f"{CURRENT_STATE_JSON}: {label} names {PHANTOM_SYMBOL} without saying no function of "
                f"that name exists in the tree (it is the \u00a70.1 spec symbol; "
                f"config/spec-conformance.json records it as partial for that reason)")
    return problems


def _active_ref_prs(data: dict) -> list[dict]:
    """The OPEN design+implementation PRs of the active wave that every state doc must name (all of
    them, not merely one). The repository-truth PR is excluded from the must-reference set."""
    return [pr for pr in (data.get("prs") or [])
            if isinstance(pr, dict) and pr.get("merge_state") == "open"
            and pr.get("role") in ("design", "implementation") and pr.get("number") is not None]


def _check_docs_reference_state(root: pathlib.Path) -> list[str]:
    """Every human state doc must reference EVERY active (design+impl) open PR + its branch, plus the
    active branch and active task. Referencing only one of two active PRs is the exact blind spot that
    let 'docs never mention PR #32' pass — now rejected."""
    problems: list[str] = []
    if _read(root, "NEXT_CHAT.md") is None:
        return problems
    data = _load_json(root, CURRENT_STATE_JSON)
    if not isinstance(data, dict):
        return problems
    active = data.get("active") if isinstance(data.get("active"), dict) else {}
    branch = active.get("branch", "")
    task = active.get("task", "")
    must_ref = _active_ref_prs(data)
    for doc in STATE_DOCS:
        txt = _read(root, doc)
        if txt is None:
            problems.append(f"missing current-state doc: {doc}")
            continue
        for pr in must_ref:
            n = pr.get("number")
            if f"#{n}" not in txt:
                problems.append(f"{doc}: does not reference active PR #{n} (per {CURRENT_STATE_JSON})")
            b = pr.get("branch")
            if b and b not in txt:
                problems.append(f"{doc}: does not reference PR #{n}'s branch '{b}'")
        if branch and branch not in txt:
            problems.append(f"{doc}: does not reference the active branch '{branch}'")
        if task and task not in txt:
            problems.append(f"{doc}: does not reference the active task '{task}'")
    return problems


def _check_manifest_active_docs(root: pathlib.Path) -> list[str]:
    data = _load_json(root, MANIFEST)
    if not isinstance(data, dict):
        return []  # absent/malformed handled by the structural manifest check elsewhere / not present
    paths = set(data.get("paths", []) if isinstance(data.get("paths"), list) else [])
    return [f"{MANIFEST}: active-wave normative doc present on disk but not in the startup read set: {d}"
            for d in ACTIVE_WAVE_DOCS if (root / d).exists() and d not in paths]


def _current_region(text: str) -> str:
    """The doc text with every <!-- HISTORY_BEGIN -->..<!-- HISTORY_END --> span removed. Current-state
    validation + the contradiction scan run ONLY on this region, so historical/audit prose (which may
    legitimately say 'pending') is excluded and cannot contradict the present-tense truth."""
    out, i = [], 0
    while True:
        b = text.find(HISTORY_BEGIN, i)
        if b == -1:
            out.append(text[i:])
            break
        out.append(text[i:b])
        e = text.find(HISTORY_END, b)
        if e == -1:                       # unterminated history block: drop the rest, and flag elsewhere
            break
        i = e + len(HISTORY_END)
    return "".join(out)


def _check_status_tokens(root: pathlib.Path) -> list[str]:
    """Every human state doc's CURRENT region must contain each `KEY: value` status token from
    config/current_state.json.status_tokens verbatim. This turns present-tense status into a single
    machine-checked source, so the docs cannot silently disagree with the anchor (or each other)."""
    problems: list[str] = []
    if _read(root, "NEXT_CHAT.md") is None:
        return problems
    data = _load_json(root, CURRENT_STATE_JSON)
    if not isinstance(data, dict):
        return problems
    tokens = data.get("status_tokens")
    if not isinstance(tokens, dict):
        return [f"{CURRENT_STATE_JSON}: missing 'status_tokens' object (contradiction gate needs it)"]
    wanted = {k: v for k, v in tokens.items() if not k.startswith("_")}
    for doc in STATE_DOCS:
        txt = _read(root, doc)
        if txt is None:
            continue  # missing-doc already reported elsewhere
        if HISTORY_BEGIN in txt and HISTORY_END not in txt:
            problems.append(f"{doc}: {HISTORY_BEGIN} without a matching {HISTORY_END}")
        region = _current_region(txt)
        for key, val in wanted.items():
            if not re.search(rf"{re.escape(key)}\s*[:=]\s*{re.escape(str(val))}\b", region):
                problems.append(f"{doc}: CURRENT region is missing status token '{key}: {val}' "
                                f"(must match {CURRENT_STATE_JSON}.status_tokens)")
    return problems


def _check_current_contradictions(root: pathlib.Path) -> list[str]:
    """In each doc's CURRENT region, a subject the tokens mark 'complete' must not also be described as
    pending, and a PENDING_REAUDIT design gate must not be described as design-GREEN. Catches the exact
    'verify-seam DONE and verify-seam pending in the same file' drift the Owner flagged."""
    problems: list[str] = []
    if _read(root, "NEXT_CHAT.md") is None:
        return problems
    data = _load_json(root, CURRENT_STATE_JSON)
    tokens = (data.get("status_tokens") if isinstance(data, dict) else None) or {}
    for doc in STATE_DOCS:
        txt = _read(root, doc)
        if txt is None:
            continue
        region = _current_region(txt)
        for token_key, subject_re in SUBJECT_PROSE.items():
            if str(tokens.get(token_key)).lower() == "complete":
                pat = rf"{subject_re}[^.\n]{{0,80}}?{_PENDING_WORDS}"
                if re.search(pat, region, re.I):
                    problems.append(f"{doc}: CURRENT region calls '{token_key}' pending, but the status "
                                    f"token says complete (contradictory present-tense claim)")
        # the carrier's state/next-action must be described conditionally: any unconditional carrier
        # sentence (PR #33 not merged / awaiting re-audit / re-audit→merge / merge PR #33) goes stale
        # the moment it merges. We scan the PROSE (structured tokens stripped) for a carrier-action
        # phrase near a bare "PR #33" mention that is NOT guarded by an IF-OPEN/IF-MERGED transition
        # marker earlier on the SAME line. This catches "next action is re-audit/merge PR #33" phrasings
        # a proximity "PR #33 … not merged" regex misses.
        prose = _prose_only(region)
        for m in re.finditer(r"PR ?#?33\b", prose, re.I):
            # the mention's CLAUSE = text between the nearest strong boundaries on each side. A clause
            # that is a transition-aware statement contains an IF-OPEN/IF-MERGED marker; a standalone
            # unconditional sentence is its own clause with no such marker.
            starts = [b.end() for b in _STRONG_BOUNDARY.finditer(prose, 0, m.start())]
            clause_start = starts[-1] if starts else 0
            nxt = _STRONG_BOUNDARY.search(prose, m.end())
            clause_end = nxt.start() if nxt else len(prose)
            clause = prose[clause_start:clause_end]
            if _CARRIER_UNCONDITIONAL.search(clause) and not _CARRIER_GUARD.search(clause):
                problems.append(f"{doc}: CURRENT region has an unconditional carrier sentence about PR #33 "
                                f"(merge / re-audit / not-merged) not guarded by an IF OPEN / IF MERGED "
                                f"transition marker — make every carrier-current statement transition-aware")
                break
        candidate = str(tokens.get("CURRENT_DESIGN_CANDIDATE") or "").strip()
        if str(tokens.get("CURRENT_DESIGN_GATE")) == "PENDING_REAUDIT" and candidate:
            # the CURRENT (unreviewed) candidate must not be described in the current region as having an
            # exact-head verdict — neither GREEN nor RED. PRIOR reviewed candidates (last_reviewed) MAY be
            # stated as RED (that's history/fact); only a claim about THIS candidate is forbidden.
            cand_re = re.escape(candidate).replace(r"\-", r".?").replace(r"\ ", r".?")
            for m in re.finditer(rf"{cand_re}[^.\n]{{0,60}}?(design[- ]?(RED|GREEN)|exact-head[- ]?(RED|GREEN))", region, re.I):
                pre = region[max(0, m.start() - 45):m.start()].lower()
                # a conditional/instruction ("do NOT merge UNTIL rev-28 is design-GREEN") is not an
                # assertion that the candidate HAS a verdict — only flag a bare positive claim.
                if any(w in pre for w in ("until", "unless", "once ", "when ", "after ", "before ", "requires")):
                    continue
                problems.append(f"{doc}: CURRENT region asserts a {candidate} design verdict while the gate is "
                                f"PENDING_REAUDIT ({candidate} is the current candidate and has no exact-head verdict yet)")
                break
    return problems


def _check_state_sync(changed: list[str]) -> list[str]:
    """PR-aware. (a) a substantive code/schema/design change must touch a state file. (b) if the
    machine anchor current_state.json changes, all three human mirrors must be synced in the SAME PR
    (touching only one arbitrary state doc is insufficient — the checkpoint must stay coherent)."""
    problems: list[str] = []
    substantive = [f for f in changed if _glob_hit(f, SUBSTANTIVE_GLOBS)]
    state_touched = [f for f in changed if f in STATE_DOCS or f == CURRENT_STATE_JSON]
    if substantive and not state_touched:
        problems.append(f"substantive change ({', '.join(sorted(substantive)[:5])}) did not update any "
                        f"state file ({CURRENT_STATE_JSON} / {STATE_DOCS}) in the same PR")
    if CURRENT_STATE_JSON in changed:
        missing = [d for d in STATE_DOCS if d not in changed]
        if missing:
            problems.append(f"{CURRENT_STATE_JSON} changed but its human mirrors were not synced in the "
                            f"same PR: {missing} (checkpoint desync)")
    return problems


def check(root: pathlib.Path, *, changed: list[str] | None = None) -> list[str]:
    """Return a list of problems (empty list == consistent). `changed` = PR diff file list (PR-aware
    checks run only when provided); offline semantic checks always run."""
    problems: list[str] = []

    # 1. Canonical files exist and are non-trivial.
    for rel in CANONICAL_FILES:
        txt = _read(root, rel)
        if txt is None:
            problems.append(f"missing canonical file: {rel}")
        elif len(txt.strip()) < 40:
            problems.append(f"canonical file is empty/stub: {rel}")

    # 1b. F-19: the four semantic checks below each early-return when NEXT_CHAT.md is absent, so
    # deleting NEXT_CHAT.md silently disables the ENTIRE semantic layer while the gate still prints
    # GREEN. A real coordination repo is identified by the machine anchor config/current_state.json;
    # if that anchor exists but NEXT_CHAT.md does not, the skip is not "this isn't a coordination
    # repo" — it is a deleted state doc. Fail closed instead of skipping.
    if _read(root, "NEXT_CHAT.md") is None and _read(root, CURRENT_STATE_JSON) is not None:
        problems.append(
            "NEXT_CHAT.md is missing while config/current_state.json exists — the semantic "
            "coordination checks are gated on NEXT_CHAT.md and would silently skip (fail-closed)"
        )

    # The phase bodies live in docs/roadmap/phase-N.md; roadmap_source assembles the
    # document exactly as it read before the split, so every check below is unchanged.
    import roadmap_source
    roadmap = roadmap_source.roadmap_text(root) if (root / ROADMAP).is_file() else None
    if roadmap is not None:
        # 2. Roadmap has a status line.
        if not re.search(r"(?m)^\*\*Status:", roadmap):
            problems.append(f"{ROADMAP}: no '**Status:' line")

        # 3. Balanced code fences.
        if roadmap.count("```") % 2 != 0:
            problems.append(f"{ROADMAP}: unbalanced ``` code fences")

        # 4. Exactly phases 0..10, each with all 16 required sections.
        blocks = _phase_blocks(roadmap)
        found = sorted(blocks)
        if found != EXPECTED_PHASES:
            problems.append(
                f"{ROADMAP}: phases must be {EXPECTED_PHASES}, found {found}"
            )
        for n, block in blocks.items():
            missing = [s for s in REQUIRED_SECTIONS if f"**{s}.**" not in block]
            if missing:
                problems.append(
                    f"{ROADMAP}: Phase {n} is missing section(s): {', '.join(missing)}"
                )

    # 5. TASKS rows each carry a known status, and each ID appears ONCE.
    #
    # The uniqueness half exists because two sessions landed a T-060 on the same
    # board within four hours -- different tasks, one ID -- and every gate stayed
    # green. TASKS.md's own first rule is "claim a row before you touch anything
    # -- never two agents on one row", and two rows sharing an ID is precisely
    # the collision that rule is for: a claim on T-060 no longer names one task,
    # and a document citing T-060 no longer names one either.
    tasks = _read(root, "TASKS.md")
    if tasks is not None:
        seen: dict[str, int] = {}
        for line in tasks.splitlines():
            if re.match(r"\s*\|\s*\*\*T-\d+\*\*", line):
                if not any(s in line for s in TASK_STATUSES):
                    tid = re.search(r"T-\d+", line)
                    problems.append(
                        f"TASKS.md: row {tid.group() if tid else '?'} has no valid "
                        f"status ({'/'.join(TASK_STATUSES)})"
                    )
                row_id = re.match(r"\s*\|\s*\*\*(T-\d+)\*\*", line).group(1)
                seen[row_id] = seen.get(row_id, 0) + 1
        for row_id, n in sorted(seen.items()):
            if n > 1:
                problems.append(
                    f"TASKS.md: {row_id} is the ID of {n} different rows. One ID, one "
                    f"row -- give the newer task the next free ID and update anything "
                    f"citing it, because a claim on {row_id} otherwise names two tasks"
                )

    # 6. PROJECT_STATE's 'Last updated' date is compared against the file's newest commit.
    problems += _check_project_state_freshness(root)

    # 7. Semantic layer (Phase 0.2): machine-readable anchor + docs agree with it + manifest carries
    #    the active-wave docs. These skip cleanly when this is not a real coordination repo.
    problems += _check_current_state(root)
    problems += _check_current_state_prose(root)
    problems += _check_docs_reference_state(root)
    problems += _check_manifest_active_docs(root)
    problems += _check_status_tokens(root)
    problems += _check_current_contradictions(root)

    # 8. PR-aware (Phase 0.2): a substantive code/schema/design change must update the state docs in
    #    the same PR. Runs only when a diff file list is supplied (a PR run); skipped on push/local.
    if changed is not None:
        problems += _check_state_sync(changed)

    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Coordination-docs consistency gate")
    ap.add_argument(
        "--root", default=str(pathlib.Path(__file__).resolve().parents[1]),
        help="repository root (default: the repo this script lives in)",
    )
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root)

    # PR-aware: on a GitHub `pull_request` run, GITHUB_BASE_REF names the base branch; derive the
    # changed-file list so the state-doc drift guard can run. Absent (push/local) -> None -> skipped.
    base_ref = os.environ.get("GITHUB_BASE_REF") or None
    changed = _changed_files(base_ref) if base_ref else None
    problems = check(root, changed=changed)
    if problems:
        print("RED: coordination docs inconsistent —", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(f"\n{len(problems)} problem(s). Fix the docs above (see the Startup Law "
              f"in CLAUDE.md / the roadmap §A).", file=sys.stderr)
        return 1
    # ASCII-only output on purpose: a Windows cp1252 console raises UnicodeEncodeError
    # on non-ASCII (the exact hazard CLAUDE.md §5 warns about), which would break a hook.
    extra = " + state anchor consistent + docs reference the active PR/branch/task" if _read(root, "NEXT_CHAT.md") else ""
    diff_note = " + state-doc drift guard (PR diff)" if changed is not None else ""
    # Say what was measured, not a word. The previous version printed "PROJECT_STATE fresh" while
    # comparing the date to nothing at all; the reader who trusted that word was the person this
    # gate exists to protect.
    claimed, _ = _claimed_last_updated(_read(root, PROJECT_STATE) or "")
    committed = _last_commit_date(root, PROJECT_STATE)
    if claimed is None:
        fresh = "PROJECT_STATE undated"
    elif committed is None:
        fresh = (f"PROJECT_STATE dated {claimed} (NOT compared: git could not date the file here — "
                 f"CI has full history and does compare it)")
    elif claimed >= committed:
        fresh = f"PROJECT_STATE dated {claimed} >= its newest commit {committed}"
    else:
        # The date is behind, and the gate passed anyway — which is only legitimate when that
        # commit MOVED the line. Saying ">= its newest commit" here would be the green line
        # asserting the opposite of the truth, which is the defect this whole check replaced.
        fresh = (f"PROJECT_STATE dated {claimed}, behind its newest commit {committed} but moved "
                 f"in it (merge lag, not staleness)")
    print(f"GREEN: coordination docs consistent "
          f"(canonical files present; roadmap {len(EXPECTED_PHASES)} phases x "
          f"{len(REQUIRED_SECTIONS)} sections; TASKS statuses valid; {fresh}{extra}{diff_note}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
