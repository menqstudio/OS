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

"Run this after every push" was a rule for whoever remembered it, and the Architect pushes too: on
#328 and again on #331 an audit commit landed, nothing moved the marker, and `Repo-state` went red
on a head whose every other check was green. So the job that READS the marker now WRITES it first
(`.github/workflows/ci.yml`, T-163):

    python tools/stamp_pr_head.py --pr 331 --head <the event's head sha>

`--head` is the head that run verifies. A CI checkout is the pull request's merge commit, so the
"local HEAD is what origin has" check below can never hold there; with `--head` the question is
instead whether origin's tip is STILL that head. If it has moved on, nothing is written: the newer
head has its own run, and this one verified nothing about it.

What the marker is evidence of, said plainly: that the body names the head CI judged. It never
showed that a person read that head -- this tool has always copied whatever `git ls-remote`
answered. What binds an audit to a commit is `Audited-Head` in the filed report, which
`check_merge_ready.py` compares with the head being merged.

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
import pathlib
import re
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
# The gate's own resolver: this tool writes the marker `check_repo_state.py` reads, so the two
# must be asking about the same repository. See `main()`.
from check_repo_state import _repo_slug  # noqa: E402

MARKER = re.compile(r"^AUDIT_CANDIDATE_HEAD:\s*[0-9a-f]{40}\s*$", re.M)


def run(*args: str) -> str:
    out = subprocess.run(args, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"RED: {' '.join(args)} failed:\n{out.stderr.strip()}")
    return out.stdout


def restamp(body: str, sha: str) -> str:
    """The body with EXACTLY one marker, naming `sha`.

    A body that ALREADY carries exactly one marker naming `sha` is returned untouched. That is not
    a micro-optimisation: stripping and re-appending MOVES the marker to the end, so a body with
    anything after it -- this project's pull requests end with an attribution line, after the
    marker -- came back different even though it already said the right thing, and the caller wrote
    it. A write fires `pull_request: edited`, which ci.yml subscribes to on purpose, so every job
    of `ci` restarted and the run in flight was cancelled. Measured 2026-09-19: 26 `ci` pull-request runs
    over 11 heads, 19 of them cancelled, every head with more than one run.

    Otherwise every existing marker goes first. Appending without stripping is how a body ends up
    with two, and `check_repo_state.py` requires exactly one -- two markers is the same red as none.
    """
    if stamped_sha(body) == sha:
        return body
    return f"{MARKER.sub('', body).rstrip()}\n\nAUDIT_CANDIDATE_HEAD: {sha}\n"


def markers(text: str) -> list[str]:
    """Every marker in `text`, normalised.

    GitHub returns a PR body with CRLF line endings whatever you wrote, so a raw comparison of
    `MARKER.findall(sent)` against `MARKER.findall(read_back)` differs by a trailing \r on every
    match and reports a mismatch that is not one. This was a false RED on PR #183 seconds after
    the read-back was added — the write had in fact landed correctly.
    """
    return [m.strip() for m in MARKER.findall(text.replace("\r\n", "\n"))]


def stamped_sha(text: str) -> str | None:
    """The sha `text` is already stamped at, or None if it is not stamped at exactly one.

    This is the question the write decision actually turns on, and asking it about the MARKER is
    what makes the decision robust. The old decision compared whole documents -- `restamp(body) ==
    body` -- which answers "would rewriting change anything", not "does it already say the right
    thing", and those differ the moment a body has text after the marker.

    Built on `markers()`, which is line-ending agnostic three times over: the pattern ends `\\s*$`,
    every match is `.strip()`ed, and CRLF is normalised first. Measured over five body shapes, that
    normalisation changes no answer, and no current `gh` read of a body returns CRLF at all -- it is
    belt and braces against the #183 observation, not the load-bearing part.

    Zero markers and two markers both answer None: both are states `check_repo_state.py` refuses,
    and neither is "already stamped".
    """
    found = markers(text)
    if len(found) != 1:
        return None
    return found[0].split(":", 1)[1].strip()


def patch_command(repo: str, pr: int) -> list[str]:
    """The argv that writes a PR body. REST, never `gh pr edit` -- see the module docstring."""
    return ["gh", "api", "-X", "PATCH", f"repos/{repo}/pulls/{pr}", "--input", "-"]


#: Attempts at one write, and the pause before each retry. A failed PATCH is asked about before
#: it is repeated: the one seen in CI (#336, 2026-10-03, `unexpected end of JSON input`) is
#: GitHub answering with an empty body, which says nothing about whether the write landed.
WRITE_ATTEMPTS = 3
RETRY_PAUSES = (2.0, 5.0)


def write_body(repo: str, pr: int, body: str) -> None:
    """Write the body, then read it back. A write nobody verified is a claim, not a fact.

    Since T-166 a failed write is not the end of the run. `Repo-state` now stamps the head it
    verifies (T-163), so one malformed answer from GitHub turned a green head red -- it did on
    #336. After a failure the body is read: if it already names the head the write was about,
    the write landed and is not repeated; otherwise it is tried again, `WRITE_ATTEMPTS` in all.
    The read-back below still decides, whatever the attempts said.
    """
    errors: list[str] = []
    for attempt in range(WRITE_ATTEMPTS):
        out = subprocess.run(patch_command(repo, pr), input=json.dumps({"body": body}),
                             capture_output=True, text=True)
        if out.returncode == 0:
            break
        errors.append(out.stderr.strip() or f"exit {out.returncode}")
        try:
            landed = markers(run("gh", "api", f"repos/{repo}/pulls/{pr}", "--jq", ".body"))
        except SystemExit:
            landed = None
        if landed == markers(body):
            break
        if attempt + 1 < WRITE_ATTEMPTS:
            time.sleep(RETRY_PAUSES[min(attempt, len(RETRY_PAUSES) - 1)])
    else:
        raise SystemExit(f"RED: writing the body of PR #{pr} failed {WRITE_ATTEMPTS} times:\n"
                         + "\n".join(errors))
    live = run("gh", "api", f"repos/{repo}/pulls/{pr}", "--jq", ".body")
    if markers(live) != markers(body):
        raise SystemExit(f"RED: PR #{pr} was written but reads back with a different marker; "
                         "check the pull request by hand before pushing again.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--repo", default=None,
                    help="owner/name; default: the repository this checkout's remote names")
    ap.add_argument("--head", default=None,
                    help="the 40-hex head a CI run verifies; stamped only while origin's tip is "
                         "still that head, and in place of the local-HEAD comparison")
    args = ap.parse_args()
    if args.head is not None and not re.fullmatch(r"[0-9a-f]{40}", args.head):
        raise SystemExit(f"RED: --head must be a 40-hex commit id, not {args.head!r}. Nothing "
                         "has been read or written.")

    # The slug is RESOLVED, not a literal. It was `default="menqstudio/OS"` while the tip two
    # lines below is read from `git ls-remote origin` -- so in a fork the body would be read from
    # and written to one repository and the head compared with another's. That literal is the
    # eighth audit's `H-05`, fixed in check_repo_state.py and in sync_active_pr.py and left
    # here. No slug, no write: a tool that cannot say which repository it is stamping has not
    # established what the marker would be about.
    repo = args.repo or _repo_slug()
    if not repo:
        raise SystemExit("RED: could not establish which repository this checkout is (`gh repo "
                         "view`), and no --repo was given. Nothing has been written.")
    args.repo = repo

    meta = json.loads(run("gh", "pr", "view", str(args.pr), "-R", args.repo,
                          "--json", "body,headRefName"))
    branch = meta["headRefName"]

    remote = run("git", "ls-remote", "origin", f"refs/heads/{branch}").split()
    if not remote:
        raise SystemExit(f"RED: origin has no {branch}; push it before stamping")
    pushed = remote[0]

    if args.head is not None:
        if pushed != args.head:
            print(f"origin's {branch} is at {pushed[:8]}, not the {args.head[:8]} this run "
                  "verifies; the newer head has its own run. Nothing is written.")
            return 0
    elif (local := run("git", "rev-parse", "HEAD").strip()) != pushed:
        # Stamping the local tip would name a commit the auditor cannot fetch.
        raise SystemExit(f"RED: local HEAD {local[:8]} is not what origin has ({pushed[:8]}). "
                         "Push first — the marker must name a commit that exists on GitHub.")

    # Idempotence is not a nicety here, it is minutes. `.github/workflows/ci.yml` listens for
    # `pull_request: edited` BY DESIGN -- a body edit has to re-run `Repo-state` so the marker is
    # re-read -- so a PATCH that changes nothing still starts every job of `ci` and cancels the
    # run already in flight. (This comment said "all 21 jobs" and the docstring above "all 22"
    # -- two counts for one workflow in one file, one of them wrong. Neither is kept.) A cancelled run is not a reading of anything, which is the rule this
    # repository states about `main` in that same file. Measured 2026-09-19: 26 `ci` runs over 11
    # heads, 19 of them cancelled, every head with more than one run.
    #
    # The check below used to be `restamp(body, pushed) == body`. That fires for a body whose marker
    # is LAST, and not otherwise: `restamp` re-appends at the end, so a body with an attribution
    # line after the marker came back reordered and was written even though it already named the
    # pushed head. Every pull request here ends that way, so every one paid for it once.
    if stamped_sha(meta["body"]) == pushed:
        print(f"already stamped at {pushed[:8]}; the body is not rewritten")
        return 0

    write_body(args.repo, args.pr, restamp(meta["body"], pushed))
    print(f"PR #{args.pr} ({branch}) stamped at {pushed}")
    print("Now verify against live GitHub:  python tools/check_repo_state.py")
    return 0


if __name__ == "__main__":
    # Ask GitHub as this repository's owner whatever `gh` login is active (tools/gh_account.py).
    # Here and not in main(): a test that calls main() must not start `gh` or gain a token.
    import gh_account
    gh_account.use_repo_account()
    sys.exit(main())
