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

The body is written through the REST endpoint, not `gh pr edit`. On gh 2.46.0 -- the version
Debian ships and the one this repository is driven from -- `gh pr edit` resolves the PR through
GraphQL and asks for `repository.pullRequest.projectCards`, which GitHub sunset with Projects
(classic). The call dies before it writes anything:

    GraphQL: Projects (classic) is being deprecated ... (repository.pullRequest.projectCards)

so the marker silently stayed at whatever it was and `check_repo_state.py` went red on the next
push for a reason that had nothing to do with the push. `gh api -X PATCH repos/OWNER/REPO/pulls/N`
touches no GraphQL at all, and this reads the body back afterwards rather than trusting the write.
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


def restamp(body: str, sha: str) -> str:
    """The body with EXACTLY one marker, naming `sha`.

    Every existing marker goes first. Appending without stripping is how a body ends up with two,
    and `check_repo_state.py` requires exactly one -- two markers is the same red as none.
    """
    return f"{MARKER.sub('', body).rstrip()}\n\nAUDIT_CANDIDATE_HEAD: {sha}\n"


def markers(text: str) -> list[str]:
    """Every marker in `text`, normalised.

    GitHub returns a PR body with CRLF line endings whatever you wrote, so a raw comparison of
    `MARKER.findall(sent)` against `MARKER.findall(read_back)` differs by a trailing \r on every
    match and reports a mismatch that is not one. This was a false RED on PR #183 seconds after
    the read-back was added — the write had in fact landed correctly.
    """
    return [m.strip() for m in MARKER.findall(text.replace("\r\n", "\n"))]


def patch_command(repo: str, pr: int) -> list[str]:
    """The argv that writes a PR body. REST, never `gh pr edit` -- see the module docstring."""
    return ["gh", "api", "-X", "PATCH", f"repos/{repo}/pulls/{pr}", "--input", "-"]


def write_body(repo: str, pr: int, body: str) -> None:
    """Write the body, then read it back. A write nobody verified is a claim, not a fact."""
    out = subprocess.run(patch_command(repo, pr), input=json.dumps({"body": body}),
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"RED: writing the body of PR #{pr} failed:\n{out.stderr.strip()}")
    live = run("gh", "api", f"repos/{repo}/pulls/{pr}", "--jq", ".body")
    if markers(live) != markers(body):
        raise SystemExit(f"RED: PR #{pr} was written but reads back with a different marker; "
                         "check the pull request by hand before pushing again.")


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

    new = restamp(meta["body"], pushed)
    if new == meta["body"]:
        print(f"already stamped at {pushed[:8]}")
        return 0

    write_body(args.repo, args.pr, new)
    print(f"PR #{args.pr} ({branch}) stamped at {pushed}")
    print("Now verify against live GitHub:  python tools/check_repo_state.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
