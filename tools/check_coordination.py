#!/usr/bin/env python3
"""Coordination-docs consistency gate — the CI wall for the Startup Law.

The repo's rule "read the canonical files, keep them synced in the same commit" is
otherwise un-enforced: it degrades to *remember to*, and gets forgotten. This is the
enforcement — a deterministic, offline, fail-closed check that CI runs on every PR, so
malformed or structurally-inconsistent coordination docs **cannot merge**. It mirrors
the engine's `bro_docs_freshness.py` posture: green on structure, hard-fail otherwise.

Two layers:
  - STRUCTURAL (always, offline): canonical files present, roadmap 0..10 x 16 sections,
    balanced fences, TASKS status vocabulary, PROJECT_STATE freshness line.
  - SEMANTIC + PR-AWARE (Phase 0.2, strengthened): validate the machine-readable anchor
    config/current_state.json (schema 2) — closed enums, PR parent/child relationships,
    design-gate state, is_rc requires design-GREEN; require every human state doc to
    reference EVERY active PR + branch + task; and (on a PR diff) require a substantive
    change to sync the state files. So "did you update the state after this change" is NO
    LONGER only the Claude-side Stop-hook's job — CI now enforces it deterministically.
  - LIVE GITHUB (separate, tools/check_repo_state.py, CI): compares the current_state.json
    PR snapshot against live GitHub (open/merged/draft/base) and fails closed on mismatch,
    so a merged PR recorded as "open" cannot pass. This file stays offline-only by design.

Usage:  python tools/check_coordination.py [--root DIR]
Exit 0 + "GREEN: ..." when consistent; exit 1 + the problems otherwise.
"""
from __future__ import annotations

import argparse
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
    for field in ("sync", "active", "prs", "waves", "design_gate", "stop_gates", "next_action"):
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
    if ab and ab not in open_branches:
        problems.append(f"{CURRENT_STATE_JSON}: active.branch {ab!r} does not correspond to any OPEN PR branch")
    # relationships: parent PR exists in prs[]; child base == parent branch; open impl PR ⇒ code exists.
    for pr in prs:
        if not isinstance(pr, dict):
            continue
        num = pr.get("number")
        parent = pr.get("parent_pr")
        if parent is not None:
            p = pr_by_num.get(parent)
            if p is None:
                problems.append(f"{CURRENT_STATE_JSON}: PR #{num} parent_pr #{parent} is not listed in prs[]")
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
        if str(tokens.get("CURRENT_DESIGN_GATE")) == "PENDING_REAUDIT":
            for m in re.finditer(r"rev.?26[^.\n]{0,60}?(design[- ]?GREEN|exact-head (RED|GREEN))", region, re.I):
                pre = region[max(0, m.start() - 45):m.start()].lower()
                # a conditional/instruction ("do NOT merge UNTIL rev-26 is design-GREEN") is not an
                # assertion that rev-26 HAS a verdict — only flag a bare positive claim.
                if any(w in pre for w in ("until", "unless", "once ", "when ", "after ", "before ", "requires")):
                    continue
                problems.append(f"{doc}: CURRENT region asserts a rev-26 design verdict while the gate is "
                                f"PENDING_REAUDIT (rev-26 has no exact-head verdict)")
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

    roadmap = _read(root, ROADMAP)
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

    # 5. TASKS rows each carry a known status.
    tasks = _read(root, "TASKS.md")
    if tasks is not None:
        for line in tasks.splitlines():
            if re.match(r"\s*\|\s*\*\*T-\d+\*\*", line):
                if not any(s in line for s in TASK_STATUSES):
                    tid = re.search(r"T-\d+", line)
                    problems.append(
                        f"TASKS.md: row {tid.group() if tid else '?'} has no valid "
                        f"status ({'/'.join(TASK_STATUSES)})"
                    )

    # 6. PROJECT_STATE carries a non-empty 'Last updated'.
    state = _read(root, "PROJECT_STATE.md")
    if state is not None:
        m = re.search(r"(?m)^\*\*Last updated[^:]*:\*\*\s*(.+?)\s*$", state)
        if not m or len(m.group(1).strip()) < 3:
            problems.append("PROJECT_STATE.md: missing/empty '**Last updated ...:**' line")

    # 7. Semantic layer (Phase 0.2): machine-readable anchor + docs agree with it + manifest carries
    #    the active-wave docs. These skip cleanly when this is not a real coordination repo.
    problems += _check_current_state(root)
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
    print(f"GREEN: coordination docs consistent "
          f"(canonical files present; roadmap {len(EXPECTED_PHASES)} phases x "
          f"{len(REQUIRED_SECTIONS)} sections; TASKS statuses valid; PROJECT_STATE fresh{extra}{diff_note}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
