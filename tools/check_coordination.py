#!/usr/bin/env python3
"""Coordination-docs consistency gate — the CI wall for the Startup Law.

The repo's rule "read the canonical files, keep them synced in the same commit" is
otherwise un-enforced: it degrades to *remember to*, and gets forgotten. This is the
enforcement — a deterministic, offline, fail-closed check that CI runs on every PR, so
malformed or structurally-inconsistent coordination docs **cannot merge**. It mirrors
the engine's `bro_docs_freshness.py` posture: green on structure, hard-fail otherwise.

It intentionally checks only what is *deterministic and offline* (structure, presence,
vocabulary). "Did you update PROJECT_STATE after this code change" is the Stop-hook's
job (git-diff aware, Claude-side). Together: hook = early reminder, CI = universal wall.

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
    """config/current_state.json is the machine-readable truth anchor. Required + internally
    consistent whenever this is a real coordination repo (has NEXT_CHAT.md)."""
    problems: list[str] = []
    if _read(root, "NEXT_CHAT.md") is None:
        return problems  # not a real coordination repo (offline unit-test fixtures) — skip
    data = _load_json(root, CURRENT_STATE_JSON)
    if data is None:
        return [f"missing {CURRENT_STATE_JSON} (machine-readable current-state anchor)"]
    if data == "MALFORMED" or not isinstance(data, dict):
        return [f"{CURRENT_STATE_JSON}: invalid JSON object"]
    for field in ("main_head", "active_wave", "active_task", "active_branch",
                  "prs", "waves", "stop_gates", "next_action"):
        if field not in data:
            problems.append(f"{CURRENT_STATE_JSON}: missing required field '{field}'")
    head = data.get("main_head", "")
    if not (isinstance(head, str) and re.fullmatch(r"[0-9a-f]{40}", head)):
        problems.append(f"{CURRENT_STATE_JSON}: main_head must be a 40-hex sha, got {head!r}")
    waves = data.get("waves") if isinstance(data.get("waves"), dict) else {}
    prs = data.get("prs") if isinstance(data.get("prs"), list) else []
    for pr in prs:
        if not isinstance(pr, dict):
            continue
        num = pr.get("number")
        ms = pr.get("merge_state")
        if ms not in ("open", "merged", "closed"):
            problems.append(f"{CURRENT_STATE_JSON}: PR #{num} merge_state must be open|merged|closed, got {ms!r}")
        if pr.get("is_rc") is True and pr.get("design_verdict") == "RED":
            problems.append(f"{CURRENT_STATE_JSON}: PR #{num} is_rc=true while design_verdict is RED (CI-green is not audit-green)")
        if pr.get("role") == "implementation" and ms != "merged":
            w = waves.get(data.get("active_wave"), {})
            if not (isinstance(w, dict) and w.get("code_exists") is True):
                problems.append(
                    f"{CURRENT_STATE_JSON}: open implementation PR #{num} exists but "
                    f"waves[{data.get('active_wave')!r}].code_exists is not true "
                    f"(docs would wrongly imply 'no code exists')")
    return problems


def _check_docs_reference_state(root: pathlib.Path) -> list[str]:
    """The three human state docs must each reference the active branch + an active open PR from the
    anchor, and the active task must appear somewhere. This is what catches 'docs never mention the
    live PR' drift — robustly, without fragile full-text contradiction scanning of preserved history."""
    problems: list[str] = []
    if _read(root, "NEXT_CHAT.md") is None:
        return problems
    data = _load_json(root, CURRENT_STATE_JSON)
    if not isinstance(data, dict):
        return problems  # absence/malformed already reported by _check_current_state
    branch = data.get("active_branch", "")
    task = data.get("active_task", "")
    open_prs = [str(pr.get("number")) for pr in data.get("prs", [])
                if isinstance(pr, dict) and pr.get("merge_state") == "open" and pr.get("number") is not None]
    for doc in STATE_DOCS:
        txt = _read(root, doc)
        if txt is None:
            problems.append(f"missing current-state doc: {doc}")
            continue
        if branch and branch not in txt:
            problems.append(f"{doc}: does not reference the active branch '{branch}' (per {CURRENT_STATE_JSON})")
        if open_prs and not any((f"#{n}" in txt) for n in open_prs):
            problems.append(f"{doc}: does not reference any active open PR {open_prs} (per {CURRENT_STATE_JSON})")
    if task and not any(task in (_read(root, d) or "") for d in STATE_DOCS):
        problems.append(f"active task {task} (per {CURRENT_STATE_JSON}) is referenced in none of {STATE_DOCS}")
    return problems


def _check_manifest_active_docs(root: pathlib.Path) -> list[str]:
    data = _load_json(root, MANIFEST)
    if not isinstance(data, dict):
        return []  # absent/malformed handled by the structural manifest check elsewhere / not present
    paths = set(data.get("paths", []) if isinstance(data.get("paths"), list) else [])
    return [f"{MANIFEST}: active-wave normative doc present on disk but not in the startup read set: {d}"
            for d in ACTIVE_WAVE_DOCS if (root / d).exists() and d not in paths]


def _check_code_touch_state(changed: list[str]) -> list[str]:
    substantive = [f for f in changed if _glob_hit(f, SUBSTANTIVE_GLOBS)]
    touched_state = [f for f in changed if f in STATE_DOCS or f == CURRENT_STATE_JSON]
    if substantive and not touched_state:
        return [f"substantive change ({', '.join(sorted(substantive)[:5])}) did not update any of "
                f"{STATE_DOCS} or {CURRENT_STATE_JSON} in the same PR (state-doc drift guard)"]
    return []


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

    # 8. PR-aware (Phase 0.2): a substantive code/schema/design change must update the state docs in
    #    the same PR. Runs only when a diff file list is supplied (a PR run); skipped on push/local.
    if changed is not None:
        problems += _check_code_touch_state(changed)

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
