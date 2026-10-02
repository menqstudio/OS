#!/usr/bin/env python3
"""May this pull request be merged right now -- and will `main` still be green after it?

    python3 tools/check_merge_ready.py --pr N

Exit 0 GREEN, 1 RED. GREEN prints the one command that may then be run. RED prints one
line per problem, each with its remedy.

WHY IT EXISTS
-------------
Pull request #314 had 39 of 39 checks green and was squash-merged a few minutes after
midnight. A squash is a NEW commit, dated at the moment of the merge; `PROJECT_STATE.md`
line 3 still said the day before; and `tools/check_coordination.py` went RED on `main`
("the file changed after the date it claims"), where no pull request can show it and only
another merge can repair it. Every rule that would have stopped it was written down. None
of them was a program, and the remedy on file afterwards was a memory note. This is the
program. `.claude/hooks/canonical_law_gate.py` runs it before every `gh pr merge` and
refuses the command unless it is GREEN.

WHAT GREEN MEANS -- all five, each one refusable on its own
  a. the pull request is OPEN and its head commit H is known;
  b. every check on H has completed and passed: none pending, none failed, at least one
     present. A check list that is empty or unreadable is RED, never GREEN;
  c. GitHub's merge state is CLEAN;
  d. `PROJECT_STATE.md` AS IT IS AT H carries a `Last updated` date that is not earlier
     than the date the squash commit will get -- in BOTH this machine's local zone and UTC;
  e. the exact command is printed: `gh pr merge N --squash --match-head-commit H`.

THE DATE RULE, and the evidence it was derived from
  `check_coordination._check_project_state_freshness` reads `git log -1 --format=%cs --
  PROJECT_STATE.md`: the COMMITTER date of the newest commit that touched the file, as a
  calendar date IN THAT COMMIT'S OWN UTC OFFSET (`%cs` applies no conversion). It is RED
  when the line's date is earlier than that AND the commit did not move the line forward.

  The offset is whatever GitHub stamps, and it is not UTC here. #314 reports
  `mergedAt: 2026-10-01T20:05:15Z`, and its squash commit on `main` reads
  `2026-10-02 00:05:15 +0400`, committer `GitHub <noreply@github.com>`. Same instant, two
  calendar dates: on that night a rule written in UTC would have accepted the line that
  turned `main` red. So the date must hold in both zones at once -- it cannot be right in
  one and wrong in the other.

  This is deliberately STRICTER than the rule it protects. `check_coordination` also accepts
  a line that merely moved forward, to any date; this gate does not, because "moved, but to
  yesterday" passes today's merge and is one unrelated commit away from red.

  One exemption, and it is the squash's own arithmetic: if `PROJECT_STATE.md` at H is
  byte-identical to the base branch's, the squash commit will not touch the file, the
  newest commit that touched it stays the one `main` already has, and this merge cannot
  redden that rule. When the base cannot be read the exemption is NOT taken.

WHAT THIS DOES NOT COVER -- listed, not implied
  * a person merging in the GitHub web UI. Nothing here runs there; branch protection is
    the only thing that does;
  * a session opened outside this checkout. The hook that calls this loads from the
    SESSION's project root, and a session opened elsewhere gets no hooks at all;
  * `gh pr merge` run from inside a script file rather than typed as the command. The hook
    reads the command line, not the files the command line runs;
  * a GitHub account whose zone is neither this machine's nor UTC;
  * the seconds between this gate and the merge. It reads the date when it runs; a merge
    typed at 23:59:58 can land tomorrow;
  * the heavy `tools/check_produced_artifact.py`, and every other local gate. This asks
    GitHub what ITS checks said about H. It does not re-run them.

Every input comes through `Inputs`, so the tests need no network and no repository. A `gh`
or `git` call that fails is RED with the reason -- never a traceback, and never GREEN: "I
could not check" and "it is fine" are different answers.

Stdlib only.
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

STATE_REL = "PROJECT_STATE.md"
VIEW_FIELDS = "number,state,headRefOid,baseRefName,mergeStateStatus,statusCheckRollup"
SHA_RE = re.compile(r"[0-9a-f]{40}")

#: What a finished check may conclude and still not be a failure. SKIPPED and NEUTRAL are
#: what a job with an unmet `if:` reports; they are not failures and they are not passes,
#: which is why GREEN needs at least one real SUCCESS beside them.
PASSED = "SUCCESS"
NOT_A_FAILURE = {"NEUTRAL", "SKIPPED"}
STILL_RUNNING = {"PENDING", "EXPECTED"}


class GateError(Exception):
    """An input could not be read. The message is the reason, and the verdict is RED."""


class Result:
    def __init__(self) -> None:
        self.problems: list[tuple[str, str]] = []

    def bad(self, what: str, remedy: str) -> None:
        self.problems.append((what, remedy))


def _run(args: list[str], *, cwd: pathlib.Path, timeout: int = 40) -> str:
    """Run one program and return its stdout, or raise GateError saying why not."""
    try:
        done = subprocess.run(args, cwd=str(cwd), capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise GateError(f"`{' '.join(args[:4])} ...` did not answer within {timeout}s") from None
    except OSError as exc:
        raise GateError(f"`{args[0]}` could not be run: {exc}") from None
    out = (done.stdout or b"").decode("utf-8", errors="replace")
    if done.returncode != 0:
        err = (done.stderr or b"").decode("utf-8", errors="replace").strip()
        first = (err or out.strip() or "no output").splitlines()[0][:300]
        raise GateError(f"`{' '.join(args[:4])} ...` exited {done.returncode}: {first}")
    return out


class Inputs:
    """Every fact this gate reads, behind a method a test can replace."""

    def __init__(self, root: pathlib.Path = ROOT, repo: str | None = None) -> None:
        self.root = root
        self.repo = repo

    def pr_view(self, pr: int) -> dict:
        """`gh pr view` for the fields this gate decides on."""
        args = ["gh", "pr", "view", str(pr), "--json", VIEW_FIELDS]
        if self.repo:
            args += ["-R", self.repo]
        raw = _run(args, cwd=self.root)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GateError(f"`gh pr view {pr}` did not print JSON: {exc}") from None
        if not isinstance(data, dict):
            raise GateError(f"`gh pr view {pr}` printed {type(data).__name__}, not an object")
        return data

    def _has_commit(self, sha: str) -> bool:
        try:
            _run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=self.root)
        except GateError:
            return False
        return True

    def file_at(self, sha: str, rel: str, pr: int) -> str:
        """`rel` as it is AT `sha`, fetching the commit when this clone does not have it."""
        if not self._has_commit(sha):
            for ref in (sha, f"pull/{pr}/head"):
                try:
                    _run(["git", "fetch", "--quiet", "origin", ref], cwd=self.root)
                except GateError:
                    continue
                if self._has_commit(sha):
                    break
            else:
                raise GateError(f"commit {sha[:12]} is not in this clone and could not be fetched")
        return _run(["git", "show", f"{sha}:{rel}"], cwd=self.root)

    def base_file(self, base: str, rel: str) -> str:
        """`rel` as the base branch has it on GitHub NOW -- fetched, not remembered."""
        _run(["git", "fetch", "--quiet", "origin", base], cwd=self.root)
        return _run(["git", "show", f"FETCH_HEAD:{rel}"], cwd=self.root)

    def today_local(self) -> datetime.date:
        return datetime.datetime.now().astimezone().date()

    def today_utc(self) -> datetime.date:
        return datetime.datetime.now(datetime.timezone.utc).date()


def latest_checks(rollup: list) -> list[dict]:
    """One entry per check NAME: the newest run of it.

    `statusCheckRollup` keeps the superseded runs. On #317 it listed 62 entries for 39
    checks -- 23 CANCELLED runs of a workflow that a later push restarted, each beside the
    run that replaced it. Judging all 62 would call a green head failed; judging any one
    per name would let a stale SUCCESS hide a newer failure. So: the newest per name, and
    on a tie the one listed last.
    """
    newest: dict[tuple[str, str], tuple[str, int, dict]] = {}
    for index, entry in enumerate(rollup):
        if not isinstance(entry, dict):
            # Kept, under a name nothing else has, so `judge` meets it and refuses it.
            newest[("", f"<unreadable entry {index}>")] = ("", index, {})
            continue
        key = (str(entry.get("workflowName") or ""),
               str(entry.get("name") or entry.get("context") or f"<unnamed {index}>"))
        stamp = (str(entry.get("startedAt") or ""), index)
        if key not in newest or stamp >= newest[key][:2]:
            newest[key] = (stamp[0], index, entry)
    return [dict(entry, _name=key[1]) for key, (_, _, entry) in sorted(newest.items())]


def judge(entry: dict) -> str:
    """`pass`, `skip`, `pending` or `fail` for one check. Anything unreadable is `fail`."""
    if "status" in entry:                                    # a CheckRun
        if str(entry.get("status") or "").upper() != "COMPLETED":
            return "pending"
        conclusion = str(entry.get("conclusion") or "").upper()
    elif "state" in entry:                                   # a StatusContext
        conclusion = str(entry.get("state") or "").upper()
        if conclusion in STILL_RUNNING:
            return "pending"
    else:
        return "fail"
    if conclusion == PASSED:
        return "pass"
    if conclusion in NOT_A_FAILURE:
        return "skip"
    return "fail"


def check_open(view: dict, pr: int, res: Result) -> bool:
    state = str(view.get("state") or "").upper()
    if state != "OPEN":
        res.bad(f"pull request #{pr} is {state or 'in no readable state'}, not OPEN",
                "there is nothing to merge; open `gh pr view` and read what happened to it")
        return False
    return True


def check_head(view: dict, pr: int, expect: str | None, res: Result) -> str | None:
    head = view.get("headRefOid")
    if not isinstance(head, str) or not SHA_RE.fullmatch(head):
        res.bad(f"GitHub did not name a head commit for pull request #{pr} (got {head!r})",
                "run this again; a merge pinned to no commit is a merge of whatever is there")
        return None
    if expect and not head.startswith(expect.lower()):
        res.bad(f"the command pins {expect[:12]} and pull request #{pr}'s head is {head[:12]}",
                "somebody pushed since. Run this gate again and use the command IT prints")
    return head


def check_checks(view: dict, head: str | None, res: Result) -> dict[str, int]:
    """None pending, none failed, at least one passed -- on the newest run of each check."""
    counts = {"pass": 0, "skip": 0, "pending": 0, "fail": 0}
    rollup = view.get("statusCheckRollup")
    at = head[:12] if head else "the head"
    if not isinstance(rollup, list):
        res.bad(f"the check list for {at} is unreadable (statusCheckRollup is "
                f"{type(rollup).__name__})",
                "run this again; a list that cannot be read is not a list of passes")
        return counts
    if not rollup:
        res.bad(f"{at} has NO checks at all",
                "wait for CI to start, or find out why it did not. Zero checks is not zero "
                "failures")
        return counts
    named: dict[str, list[str]] = {"pending": [], "fail": []}
    for entry in latest_checks(rollup):
        verdict = judge(entry)
        counts[verdict] += 1
        if verdict in named:
            named[verdict].append(str(entry["_name"]))
    if named["pending"]:
        res.bad(f"{len(named['pending'])} check(s) on {at} have not finished: "
                + _some(named["pending"]),
                "wait: `gh run watch --exit-status`, then run this again. Never merge mid-run")
    if named["fail"]:
        res.bad(f"{len(named['fail'])} check(s) on {at} did not pass: " + _some(named["fail"]),
                "read the failing job, fix it, push, and run this again on the new head")
    if not counts["pass"]:
        res.bad(f"no check on {at} has PASSED ({counts['skip']} skipped, "
                f"{counts['pending']} pending, {counts['fail']} failed)",
                "a head nothing passed on is not a green head; wait for a real result")
    return counts


def _some(names: list[str], limit: int = 4) -> str:
    more = f" (+{len(names) - limit} more)" if len(names) > limit else ""
    return "; ".join(names[:limit]) + more


def check_merge_state(view: dict, res: Result) -> None:
    state = str(view.get("mergeStateStatus") or "").upper()
    if state == "CLEAN":
        return
    remedies = {
        "BEHIND": "bring the branch up to date with its base, push, wait for the checks",
        "DIRTY": "resolve the conflict with the base branch, push, wait for the checks",
        "BLOCKED": "a required check or review is missing; `gh pr checks` names it",
        "UNSTABLE": "a non-required check is failing; read it before deciding anything",
        "DRAFT": "mark the pull request ready for review first",
        "UNKNOWN": "GitHub is still computing it; run this again in a few seconds",
    }
    res.bad(f"GitHub's merge state is {state or 'unreadable'}, not CLEAN",
            remedies.get(state, "run this again; only CLEAN is a merge GitHub will not argue with"))


def check_state_date(inputs: Inputs, head: str, base: str, pr: int, res: Result) -> str:
    """The `Last updated` line at H against the date the squash commit will carry.

    Returns the sentence GREEN prints about it.
    """
    import check_coordination          # the SAME parser the gate on `main` uses, not a copy

    try:
        text = inputs.file_at(head, STATE_REL, pr)
    except GateError as exc:
        res.bad(f"{STATE_REL} at {head[:12]} could not be read: {exc}",
                "`git fetch origin`, then run this again")
        return ""
    claimed, problem = check_coordination._claimed_last_updated(text)
    if problem or claimed is None:
        res.bad(problem or f"{STATE_REL} at {head[:12]} carries no readable date",
                f"give {STATE_REL} a `**Last updated ...:** YYYY-MM-DD` line")
        return ""

    try:
        untouched = inputs.base_file(base, STATE_REL) == text
    except GateError:
        untouched = False              # cannot tell, so the rule applies
    if untouched:
        return (f"{STATE_REL} is identical to `{base}`'s, so the squash will not touch it "
                f"(its line says {claimed})")

    local, utc = inputs.today_local(), inputs.today_utc()
    needed = max(local, utc)
    remedy = (f"set the line to {needed} in {STATE_REL}, commit, push, wait for the checks "
              f"on the new head, then run this again")
    if claimed < local:
        res.bad(f"{STATE_REL} at {head[:12]} says `Last updated` {claimed}, and a squash made "
                f"now is dated {local} in this machine's zone -- `main` would go RED on "
                f"check_coordination the moment it lands", remedy)
    if claimed < utc:
        res.bad(f"{STATE_REL} at {head[:12]} says `Last updated` {claimed}, and a squash made "
                f"now is dated {utc} in UTC -- `main` would go RED on check_coordination "
                f"the moment it lands", remedy)
    return f"{STATE_REL} says {claimed}; today is {local} here and {utc} in UTC"


def merge_command(pr: int, head: str, repo: str | None = None) -> str:
    return (f"gh pr merge {pr} --squash --match-head-commit {head}"
            + (f" -R {repo}" if repo else ""))


def evaluate(pr: int, inputs: Inputs, expect: str | None = None) -> tuple[Result, dict]:
    res = Result()
    facts: dict = {"head": None, "counts": {}, "date": ""}
    try:
        view = inputs.pr_view(pr)
    except GateError as exc:
        res.bad(f"pull request #{pr} could not be read from GitHub: {exc}",
                "check `gh auth status` and the network, then run this again")
        return res, facts
    if not check_open(view, pr, res):
        # Nothing below means anything for a pull request that is merged or closed: GitHub
        # reports its merge state as UNKNOWN forever, and "run this again" would be a lie.
        return res, facts
    head = check_head(view, pr, expect, res)
    facts["head"] = head
    facts["counts"] = check_checks(view, head, res)
    check_merge_state(view, res)
    if head:
        base = str(view.get("baseRefName") or "main")
        facts["date"] = check_state_date(inputs, head, base, pr, res)
    return res, facts


def main(argv: list[str] | None = None, inputs: Inputs | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pr", type=int, required=True, help="the pull request number")
    ap.add_argument("--repo", default=None, help="owner/name, when it is not this clone's origin")
    ap.add_argument("--expect-head", default=None,
                    help="the commit a merge command pins; RED when the live head is another")
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)
    inputs = inputs or Inputs(pathlib.Path(args.root), args.repo)

    try:
        res, facts = evaluate(args.pr, inputs, args.expect_head)
    except Exception as exc:  # noqa: BLE001 - a gate that crashed has not said yes
        print(f"RED: pull request #{args.pr} must NOT be merged -- the gate itself failed\n")
        print(f"  1. {type(exc).__name__}: {exc}")
        print("     -> fix tools/check_merge_ready.py; a gate that could not run is not a pass")
        return 1

    if res.problems:
        print(f"RED: pull request #{args.pr} must NOT be merged now\n")
        for i, (what, remedy) in enumerate(res.problems, 1):
            print(f"  {i}. {what}")
            print(f"     -> {remedy}\n")
        print("Do these, then run this again. A merge on a head that is not GREEN here lands "
              "a commit\nnobody can fix without another merge.")
        return 1

    counts = facts["counts"]
    print(f"GREEN: pull request #{args.pr} may be merged now.\n")
    print(f"  head   : {facts['head']}")
    print(f"  checks : {counts['pass']} passed, {counts['skip']} skipped, none pending, "
          f"none failed")
    print("  state  : CLEAN")
    print(f"  date   : {facts['date']}")
    print("\nRun exactly this:")
    print(f"  {merge_command(args.pr, facts['head'], inputs.repo)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
