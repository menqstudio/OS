#!/usr/bin/env python3
"""Stop-hook: enforce the docs-sync discipline as a satisfiable, fail-open gate.

When a turn ends with SOURCE code changed on the branch but no coordination-doc
change (PROJECT_STATE.md / TASKS.md / MASTER_EXECUTION_ROADMAP.md), block the stop
with a clear, satisfiable message — so keeping the docs synced is enforced, not merely
remembered. This is the early Claude-side gate; the CI job `check_coordination.py` is
the hard universal wall.

SAFETY (this hook must never wedge a session):
  * FAIL-OPEN — any error (git missing, no `main`, bad payload) allows the stop.
  * SATISFIABLE — clear the block by syncing a doc, or bypass an intentional deferral
    with BRO_SKIP_DOC_SYNC=1 or a commit message tagged [no-doc-sync].
  * ASCII-only output (a Windows cp1252 console raises on non-ASCII — CLAUDE.md §5).
"""
import json
import os
import subprocess
import sys

COORDINATION_DOCS = {"PROJECT_STATE.md", "TASKS.md", "MASTER_EXECUTION_ROADMAP.md"}
CODE_DIRS = ("apps/", "engine/", "bridge/", "contracts/")


def _git(args):
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=10)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def _changed_files():
    files = set()
    for args in (
        ["diff", "--name-only", "main...HEAD"],  # committed on this branch
        ["diff", "--name-only"],                  # unstaged
        ["diff", "--name-only", "--cached"],      # staged
    ):
        for line in _git(args).splitlines():
            p = line.strip()
            if p:
                files.add(p)
    return files


def _allow(msg=None):
    if msg:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop",
                                                  "additionalContext": msg}}))
    sys.exit(0)


def _block(reason):
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def main():
    # Bypass for an intentional deferral (e.g. a separate docs-sync PR).
    if str(os.environ.get("BRO_SKIP_DOC_SYNC", "")).strip().lower() in ("1", "true", "yes", "on"):
        _allow()
    last_msg = _git(["log", "-1", "--pretty=%B"])
    if "[no-doc-sync]" in last_msg:
        _allow()

    changed = _changed_files()
    if not changed:
        _allow()

    code_changed = [
        f for f in changed
        if f.startswith(CODE_DIRS) and not f.endswith(".md") and "/tests/" not in f
        and not f.endswith(("Cargo.lock", "package-lock.json"))
    ]
    docs_synced = any(os.path.basename(f) in COORDINATION_DOCS for f in changed)

    if code_changed and not docs_synced:
        sample = ", ".join(sorted(code_changed)[:4])
        _block(
            "Docs-sync gate: this branch changes source code (" + sample
            + (", ..." if len(code_changed) > 4 else "")
            + ") but no coordination doc (PROJECT_STATE.md / TASKS.md / "
            "MASTER_EXECUTION_ROADMAP.md). Per the Startup Law, keep them synced in the "
            "same change. Either update the relevant doc, or — if this is an intentional "
            "separate docs PR — set BRO_SKIP_DOC_SYNC=1 or tag the commit [no-doc-sync]."
        )
    _allow()


if __name__ == "__main__":
    try:
        # Drain any stdin payload (unused) so the hook doesn't block on it.
        try:
            sys.stdin.read()
        except Exception:
            pass
        main()
    except Exception:
        # Fail-open: a guard bug must never prevent finishing a turn.
        sys.exit(0)
