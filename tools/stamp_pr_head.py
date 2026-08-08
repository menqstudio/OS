#!/usr/bin/env python3
"""Point a PR's AUDIT_CANDIDATE_HEAD marker at what is actually pushed.

`tools/check_repo_state.py` is exact-head fail-closed: it reads the single
`AUDIT_CANDIDATE_HEAD: <40-hex>` marker out of the PR body and requires it to equal the branch tip
on GitHub. That is the right design — an audit that cannot name the exact commit it audited is an
audit of nothing in particular. It also means the marker is stale the moment you push again, and a
stale marker is indistinguishable from a wrong one, so the gate goes red.

That red has happened twice for this reason alone. Run this after every push:

    python tools/stamp_pr_head.py --pr 72

It reads the pushed tip from `git ls-remote` rather than from the local HEAD, because the question
the gate asks is what GitHub has, not what you have. If those differ you have unpushed work, and it
says so instead of stamping a commit nobody else can see.

Requires `gh` on PATH and authenticated. Network, by nature.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

MARKER = re.compile(r"^AUDIT_CANDIDATE_HEAD:\s*[0-9a-f]{40}\s*$", re.M)


def run(*args: str) -> str:
    out = subprocess.run(args, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"RED: {' '.join(args)} failed:\n{out.stderr.strip()}")
    return out.stdout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--repo", default="menqstudio/OS")
    args = ap.parse_args()

    meta = json.loads(run("gh", "pr", "view", str(args.pr), "-R", args.repo,
                          "--json", "body,headRefName"))
    branch = meta["headRefName"]

    remote = run("git", "ls-remote", "origin", f"refs/heads/{branch}").split()
    if not remote:
        raise SystemExit(f"RED: origin has no {branch}; push it before stamping")
    pushed = remote[0]

    local = run("git", "rev-parse", "HEAD").strip()
    if local != pushed:
        # Stamping the local tip would name a commit the auditor cannot fetch.
        raise SystemExit(f"RED: local HEAD {local[:8]} is not what origin has ({pushed[:8]}). "
                         "Push first — the marker must name a commit that exists on GitHub.")

    body = MARKER.sub("", meta["body"]).rstrip()
    new = f"{body}\n\nAUDIT_CANDIDATE_HEAD: {pushed}\n"
    if new == meta["body"]:
        print(f"already stamped at {pushed[:8]}")
        return 0

    subprocess.run(["gh", "pr", "edit", str(args.pr), "-R", args.repo, "--body", new],
                   check=True, capture_output=True, text=True)
    print(f"PR #{args.pr} ({branch}) stamped at {pushed}")
    print("Now verify against live GitHub:  python tools/check_repo_state.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
