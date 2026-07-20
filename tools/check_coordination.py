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
import pathlib
import re
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


def check(root: pathlib.Path) -> list[str]:
    """Return a list of problems (empty list == consistent)."""
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

    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Coordination-docs consistency gate")
    ap.add_argument(
        "--root", default=str(pathlib.Path(__file__).resolve().parents[1]),
        help="repository root (default: the repo this script lives in)",
    )
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root)

    problems = check(root)
    if problems:
        print("RED: coordination docs inconsistent —", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(f"\n{len(problems)} problem(s). Fix the docs above (see the Startup Law "
              f"in CLAUDE.md / the roadmap §A).", file=sys.stderr)
        return 1
    # ASCII-only output on purpose: a Windows cp1252 console raises UnicodeEncodeError
    # on non-ASCII (the exact hazard CLAUDE.md §5 warns about), which would break a hook.
    print(f"GREEN: coordination docs consistent "
          f"(canonical files present; roadmap {len(EXPECTED_PHASES)} phases x "
          f"{len(REQUIRED_SECTIONS)} sections; TASKS statuses valid; PROJECT_STATE fresh).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
