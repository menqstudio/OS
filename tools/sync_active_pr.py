#!/usr/bin/env python3
"""Point the state anchor and the three banners at the PR that is actually active.

`tools/check_repo_state.py` compares `config/current_state.json` against live GitHub, so opening a
PR without updating it turns the build red. That has happened three times in one day — not because
the rule is unclear, but because it is the last step of a long task and the cost of forgetting is
paid two minutes later by CI rather than immediately by the person forgetting.

So: one command, run right after `gh pr create`.

    python tools/sync_active_pr.py --pr 71 --branch fix/step6-readonly-deadlock \\
        --summary "One line on what this PR does and why."

It edits `config/current_state.json` and rewrites line 3 of NEXT_CHAT.md, PROJECT_STATE.md and
TASKS.md — the banner all three share. It does NOT commit or push: the state change belongs in the
same commit as the work, and a tool that pushed for you would be one more thing to trust.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BANNER_FILES = ("NEXT_CHAT.md", "PROJECT_STATE.md", "TASKS.md")
STATE = ROOT / "config" / "current_state.json"


def live_main_head() -> str:
    """The 40-hex sha the gate compares against. Read from git, never typed."""
    out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "origin/main"],
                         capture_output=True, text=True, check=True)
    sha = out.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise SystemExit(f"RED: origin/main did not resolve to a 40-hex sha: {sha!r}")
    return sha


def rewrite_state(pr: int, branch: str, summary: str, head: str) -> list[str]:
    text = STATE.read_text(encoding="utf-8")
    data = json.loads(text)              # parse first: refuse to touch a file we cannot read back
    changed = []

    def swap(old: str, new: str, label: str) -> None:
        nonlocal text
        if old != new and old in text:
            text = text.replace(old, new, 1)
            changed.append(label)

    swap(f'"baseline_main_head_at_sync": "{data["sync"]["baseline_main_head_at_sync"]}"',
         f'"baseline_main_head_at_sync": "{head}"', "baseline head")
    swap(f'"snapshot_branch": "{data["sync"]["snapshot_branch"]}"',
         f'"snapshot_branch": "{branch}"', "snapshot branch")
    swap(f'    "branch": "{data["active"]["branch"]}"\n  }},',
         f'    "branch": "{branch}"\n  }},', "active branch")

    current = data["current_workflow_pr"]
    swap(f'    "number": {current["number"]},\n    "branch": "{current["branch"]}",',
         f'    "number": {pr},\n    "branch": "{branch}",', "workflow pr")
    swap(f"marker in the PR #{current['number']} body.",
         f"marker in the PR #{pr} body.", "candidate-head marker")
    swap(f"self-carrier is PR #{current['number']}). PR #{current['number']}'s own exact-head",
         f"self-carrier is PR #{pr}). PR #{pr}'s own exact-head", "self-carrier")

    # The note is prose; replace it wholesale rather than patching around the old text.
    start = text.index('"note": "', text.index('"current_workflow_pr"'))
    end = text.index('"\n  },', start) + 1
    text = text[:start] + '"note": ' + json.dumps(summary) + text[end:]
    changed.append("note")

    json.loads(text)                     # and parse again: never leave it unreadable
    STATE.write_text(text, encoding="utf-8")
    return changed


def rewrite_banners(banner: str) -> None:
    for name in BANNER_FILES:
        p = ROOT / name
        lines = p.read_text(encoding="utf-8").split("\n")
        if not lines[2].startswith("> **"):
            raise SystemExit(f"RED: {name} line 3 is not the shared banner; refusing to overwrite it")
        lines[2] = banner
        p.write_text("\n".join(lines), encoding="utf-8")


def settle(head: str, next_up: str | None) -> int:
    """Record that nothing is open, and point the reader at main rather than at a dead branch.

    `check_repo_state` refuses a snapshot that still names a merged carrier, because the reader it
    misleads is a person or an agent arriving at the repository cold — and CI never noticed, since
    the PR-event checks only run on a `pull_request` and after the merge nothing asked.
    """
    text = STATE.read_text(encoding="utf-8")
    data = json.loads(text)
    line = '  "settled_at_main_head": "' + head + '",\n'
    existing = re.search(r'^\s*"settled_at_main_head":.*\n', text, re.M)
    if existing:
        text = text[: existing.start()] + line + text[existing.end() :]
    else:
        insert = text.index('  "sync":')
        text = text[:insert] + line + text[insert:]
    # The ACTIVE branch moves to main too. `check_coordination` requires the human docs to name
    # `active.branch`; leaving a deleted branch there asks every canonical document to point at
    # something that no longer exists -- the same staleness this mode exists to remove, one level
    # down, and it would have been caught only by whoever tried to check the branch out.
    for field, was in (("branch", (data.get("active") or {}).get("branch")),):
        if was and was != "main":
            text = text.replace('    "' + field + '": "' + was + '"\n  },',
                                '    "' + field + '": "main"\n  },', 1)
    snapshot_branch = (data.get("sync") or {}).get("snapshot_branch")
    if snapshot_branch and snapshot_branch != "main":
        text = text.replace('"snapshot_branch": "' + snapshot_branch + '"',
                            '"snapshot_branch": "main"', 1)
    json.loads(text)                     # never leave it unreadable
    STATE.write_text(text, encoding="utf-8")

    last = (data.get("current_workflow_pr") or {}).get("number")
    tail = ("\n>\n> **Next:** " + next_up) if next_up else ""
    rewrite_banners(
        "> **\u2705 SETTLED \u2014 nothing is open.** `main` is at `" + head[:7] + "`; PR #"
        + str(last) + " was the last to merge and its branch is gone. Start from "
        "`docs/OWNER_ACTION_REQUIRED.md`, the one page that says what is blocked and on whom."
        + tail + "\n>\n> **The governed surfaces stay fail-closed.** `governed_verification_unconfigured()` "
        "returns Some(...) unconditionally before the model is invoked, the broker hands out "
        "`UpstreamBlockedExecutor`, and `connect_broker()` refuses off Linux. Earlier "
        "prose below is HISTORY.")
    print("settled at main " + head[:7] + "; banners point at main, not at a deleted branch")
    print("  verify:  python tools/check_coordination.py && python tools/check_repo_state.py")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pr", type=int, help="required unless --settled")
    ap.add_argument("--branch", help="required unless --settled")
    ap.add_argument("--summary", help="required unless --settled")
    ap.add_argument("--settled", action="store_true",
                    help="nothing is open: record the main everything merged into, and say so in "
                         "the banner. Without this the docs keep naming a PR that no longer "
                         "exists, and a reader goes looking for a branch that was deleted.")
    ap.add_argument("--next", dest="next_up",
                    help="with --settled: one line on what happens next, for whoever reads this "
                         "repository cold")
    ap.add_argument("--banner", help="the human banner; defaults to a line built from --summary")
    args = ap.parse_args()

    head = live_main_head()
    if args.settled:
        return settle(head, args.next_up)
    if not (args.pr and args.branch and args.summary):
        raise SystemExit("RED: --pr, --branch and --summary are required unless --settled")
    changed = rewrite_state(args.pr, args.branch, args.summary, head)
    banner = args.banner or (
        f"> **⏭️ CURRENT ACTIVE: PR #{args.pr} · branch `{args.branch}`** (base `main`, tip "
        f"`{head[:7]}`, task T-017).\n>\n> {args.summary}\n>\n> **The gate is untouched.** "
        "`governed_verification_unconfigured()` returns Some(...) unconditionally before the "
        "model is invoked, the broker hands out `UpstreamBlockedExecutor`, and `connect_broker()` "
        "refuses off Linux. Earlier prose below is HISTORY.")

    print(f"state anchor → PR #{args.pr} on {args.branch}, main {head[:7]}")
    print(f"  fields changed: {', '.join(changed)}")
    print(f"  banners rewritten: {', '.join(BANNER_FILES)}")
    print("\nNot committed. Run the two gates, then commit with the work:")
    print("  python tools/check_coordination.py && python tools/check_repo_state.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
