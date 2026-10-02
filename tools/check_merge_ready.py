#!/usr/bin/env python3
"""May this pull request be merged right now -- and will `main` still be green after it?

    python3 tools/check_merge_ready.py --pr N
    python3 tools/check_merge_ready.py --pr N --explain-audit     # check (f) alone; see below

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

WHAT GREEN MEANS -- all six, each one refusable on its own
  a. the pull request is OPEN and its head commit H is known;
  b. every check on H has completed and passed: none pending, none failed, at least one
     present. A check list that is empty or unreadable is RED, never GREEN;
  c. GitHub's merge state is CLEAN;
  d. `PROJECT_STATE.md` AS IT IS AT H carries a `Last updated` date that is not earlier
     than the date the squash commit will get -- in BOTH this machine's local zone and UTC;
  e. the exact command is printed: `gh pr merge N --squash --match-head-commit H`;
  f. if the pull request changes engine security code, its body cites an Architect audit
     that exists at H AND ITSELF NAMES this pull request and the commit that was audited,
     with no engine security path changed since that commit (T-155) -- or a waiver the
     Owner wrote into the roadmap (T-154). Both below.

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

THE AUDIT RULE (f), and why it is a program
  `MASTER_EXECUTION_ROADMAP.md` §G.2, first row: any `engine/` security code -- wall,
  leases, gates, signatures, control-plane, root model -- needs a MANDATORY Architect audit
  BEFORE implementation, on its own audited branch, never parallelized. On 2026-10-01/02
  three changes went through without one (#313, #314, #321). The rule was written down and
  nothing refused the merge; the Builder noticed after two had landed, and the Owner then
  recorded a scoped waiver on that same row. A memory is not a solution, so this refuses.

  The files the pull request changes are read from GitHub -- every page, and the count is
  compared with the count GitHub reports, because a list cut at 100 entries is not the
  list (#314 changed 569). A file renamed OUT of the perimeter counts under its old name.
  If any of them matches `config/audit-required-paths.json`, the BODY must carry exactly
  one of two lines. A line counts only when it BEGINS with the key, case-sensitive; the
  key in the middle of a sentence, indented, or inside a quote is prose.

    Architect-Audit: <repo-relative path>
        The path must be a FILE that exists AT H, under `apps/desktop/AUDIT/` or
        `engine/AUDIT/`, and must not be empty. And THE REPORT ITSELF, as it is at H,
        must bind to this change (T-155; the Owner's decision of 2026-10-02, in its
        strongest form) by two lines. Each BEGINS its line, case-sensitive, exactly as
        the body's keys do:

            Audited-PR: #N                 N is this pull request's number
            Audited-Head: <40-hex sha>     the commit the auditor read

        A worked example -- for pull request 330, audited at the commit named, this is
        everything the gate reads in the report, and the rest of the file is the
        auditor's:

            Audited-PR: #330
            Audited-Head: 0123456789abcdef0123456789abcdef01234567

        Then git decides, not the report and not the body:
          * `Audited-Head` must be a commit this clone has, fetched when it is not here
            exactly as H is. One it cannot find is RED, never GREEN;
          * it must be H, or an ANCESTOR of H. A commit that is not in H's history -- a
            rebase, a force-push, another branch -- is RED, and nothing here tries to
            match a rebased commit to its original: an audit of a commit that is not in
            what merges is an audit of something else;
          * `git diff --name-only --no-renames <Audited-Head> H` must list NO path of the
            audit-required set, by the same matcher that decided the pull request needed
            an audit at all. That is the point of the head line: an audit of commit A
            does not cover engine security code pushed after A. Docs, tests and the canon
            may move after A; the audited code may not. `--no-renames`, so a file moved
            OUT of the perimeter after A is listed under the name it had.
        The report lives in the pull request, so its own commit comes AFTER the commit it
        names. That does not invalidate it: nothing under the two AUDIT directories is an
        audit-required path. Missing either line, a sha that is not 40 lowercase hex, an
        `Audited-PR` that is not `#N` or names another number, or either key carrying
        two different values: RED, each with its own message.

        WHAT THE TWO LINES ESTABLISH: that the report names THIS pull request and a
        commit in the history of the head that merges, and that the engine security
        content at that commit is, path for path, the engine security content being
        merged. An old report about something else no longer satisfies the rule.
        WHAT THEY DO NOT: THIS GATE STILL DOES NOT JUDGE THE AUDIT'S CONTENT OR ITS
        AUTHOR. Not its verdict -- a report that says RED and carries the two lines
        passes; not who wrote it -- nothing tells an Architect's file from one a Builder
        typed; not whether anyone read `Audited-Head` at all -- the line is a claim made
        by whoever wrote the file. Whether the report says GREEN is the reader's
        question.

        WHERE to file it, read from another gate rather than assumed:
        `tools/check_audit_reports.py` takes the newest `YYYY-MM-DD-*.md` DIRECTLY under
        `apps/desktop/AUDIT/` to be the round the ledger must call authoritative. A
        per-change audit filed there under such a name moves the ledger. File it as
        `engine/AUDIT/changes/pr-<N>-<what>.md`; a subdirectory of `apps/desktop/AUDIT/`
        does as well. That other gate lists `apps/desktop/AUDIT/*.md` and no deeper.

    Owner-Waiver: YYYY-MM-DD
        The §G.2 engine-security row AS IT IS AT H must contain the words `OWNER WAIVER`
        followed by that same date, and THAT waiver -- the text between it and the next
        `OWNER WAIVER` -- must name this pull request as `#N`. A waiver for another pull
        request, or a date that is not on the row, is RED. This is what makes a waiver
        something the Owner wrote into the roadmap rather than something a Builder typed
        into a pull-request body. (Nothing here can tell WHO typed the roadmap line; the
        roadmap's own change gate, `tools/test_roadmap_split.py`, is what makes an edit
        to that row a recorded one.)

  Neither line, both lines, or the same line twice: RED. An unreadable file list, body,
  rule or roadmap: RED.

  WHAT COUNTS AS ENGINE SECURITY CODE is not a list in this file. It is
  `config/audit-required-paths.json`, DERIVED from the engine's own statement of its
  perimeter -- the `protected_roots` of `engine/config/protected-control-plane.json`,
  prefixed `engine/`, minus the roots that file excludes by name with a reason (tests, and
  the secret-shaped name patterns and `.git/**`, which are not code paths).
  `perimeter_drift` compares the two on every run: a protected root this gate neither
  lists nor excludes is RED, not silence. The rule is read from the checkout that RUNS the
  gate, never from H -- a pull request cannot exempt itself by editing the list.

  `--explain-audit` prints ONLY this check's verdict, for the head GitHub records for the
  pull request -- merged, closed or open -- and exits 0/1 on this check alone. It exists
  so the rule can be read against history. It never prints a merge command, and its GREEN
  is not permission to merge: without the flag a merged pull request stays RED as before.
  For a pull request that is not OPEN it says, in either colour, that the verdict is the
  rule AS IT STANDS TODAY read against that head -- not the rule that was in force when
  the pull request merged. The two binding lines are newer than every pull request merged
  before them, so a RED there is not a finding that the merge broke the rule of its day.

WHAT THIS DOES NOT COVER -- listed, not implied
  * roadmap §G.2's SECOND row, trust-boundary / key / secret handling -- in practice
    `apps/desktop/src-tauri` (broker, key manifest, provisioning, launcher). It carries the
    same mandatory audit and this gate does not hold it, because the roadmap delimits that
    row by subject and not by path. RECOMMENDED: the Owner names those paths on the row,
    and they become a second declared list in `config/audit-required-paths.json`;
  * the audit's content, its author, and its timing. A report that names this pull
    request and an audited commit passes whatever its verdict and whoever typed it.
    "Before implementation" cannot be read off a merge: this refuses a merge with no
    audit on file, which is the latest moment the rule can still be held, not the moment
    it names;
  * what moves AFTER the audited commit outside the audit-required set: engine tests, the
    desktop's trust-boundary code, this gate. The head line holds still only the paths
    that made the audit mandatory;
  * a rebase after the audit, on purpose. The rebased commit is a different commit and the
    gate says RED rather than guess that it is the same change; the same holds when
    `main` is merged into the branch and brings engine security changes with it. Both
    cost a re-read by the auditor and a new `Audited-Head`, and that cost is the rule;
  * engine tests, security-relevant code outside `engine/`, and the rest of that file's
    `not_covered` list, each with its reason;
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
import fnmatch
import json
import pathlib
import posixpath
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

STATE_REL = "PROJECT_STATE.md"
VIEW_FIELDS = ("number,state,headRefOid,baseRefName,mergeStateStatus,statusCheckRollup,"
               "body,changedFiles")
SHA_RE = re.compile(r"[0-9a-f]{40}")

#: The audit rule (f). The path list is DECLARED in the first file and DERIVED from the
#: second; nothing below restates either.
AUDIT_PATHS_REL = "config/audit-required-paths.json"
PERIMETER_REL = "engine/config/protected-control-plane.json"
PERIMETER_PREFIX = "engine/"
ROADMAP_REL = "MASTER_EXECUTION_ROADMAP.md"
AUDIT_KEY = "Architect-Audit:"
WAIVER_KEY = "Owner-Waiver:"
#: Where audit reports live. A citation anywhere else is not a filed report.
AUDIT_DIRS = ("apps/desktop/AUDIT/", "engine/AUDIT/")
#: The two lines a cited report must carry ITSELF (T-155): which pull request it audited,
#: and which commit the auditor read.
AUDITED_PR_KEY = "Audited-PR:"
AUDITED_HEAD_KEY = "Audited-Head:"
#: `#5`, and only that: `#05` and `5` are not how a pull request is named.
PR_NUMBER_RE = re.compile(r"#([1-9][0-9]*)")
#: Where a per-change audit is filed so that `tools/check_audit_reports.py` stays green:
#: that gate takes the newest `YYYY-MM-DD-*.md` DIRECTLY under `apps/desktop/AUDIT/` for
#: the round the ledger must call authoritative, and lists nothing deeper or elsewhere.
PER_CHANGE_AUDIT_PATH = "engine/AUDIT/changes/pr-{pr}-<what>.md"
#: The sha in every worked example. Nothing a clone has, so pasting the example is RED.
EXAMPLE_SHA = "0123456789abcdef0123456789abcdef01234567"
G2_HEADING = re.compile(r"(?m)^### G\.2\b")
NEXT_HEADING = re.compile(r"(?m)^#{1,6} ")
#: What identifies §G.2's engine-security row: the words of its first cell.
G2_ROW_MARK = "`engine/` security code"
WAIVER_WORDS = "OWNER WAIVER"
WAIVER_DATED = re.compile(r"OWNER WAIVER\s+(\d{4}-\d{2}-\d{2})")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
#: `--jq` for the REST file list: one object per line, so pages concatenate into lines
#: and not into `[...][...]`, which is not JSON.
FILES_JQ = ".[] | {filename, previous_filename}"

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


def _exit(args: list[str], *, cwd: pathlib.Path, timeout: int = 40) -> tuple[int, str, str]:
    """Run one program: `(exit code, stdout, stderr)`. GateError when it could not run."""
    try:
        done = subprocess.run(args, cwd=str(cwd), capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise GateError(f"`{' '.join(args[:4])} ...` did not answer within {timeout}s") from None
    except OSError as exc:
        raise GateError(f"`{args[0]}` could not be run: {exc}") from None
    return (done.returncode, (done.stdout or b"").decode("utf-8", errors="replace"),
            (done.stderr or b"").decode("utf-8", errors="replace").strip())


def _failed(args: list[str], code: int, out: str, err: str) -> GateError:
    first = (err or out.strip() or "no output").splitlines()[0][:300]
    return GateError(f"`{' '.join(args[:4])} ...` exited {code}: {first}")


def _run(args: list[str], *, cwd: pathlib.Path, timeout: int = 40) -> str:
    """Run one program and return its stdout, or raise GateError saying why not."""
    code, out, err = _exit(args, cwd=cwd, timeout=timeout)
    if code != 0:
        raise _failed(args, code, out, err)
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

    def _ensure_commit(self, sha: str, pr: int) -> None:
        """Have `sha` in this clone, fetching it when it is not here."""
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

    def file_at(self, sha: str, rel: str, pr: int) -> str:
        """`rel` as it is AT `sha`, fetching the commit when this clone does not have it."""
        self._ensure_commit(sha, pr)
        return _run(["git", "show", f"{sha}:{rel}"], cwd=self.root)

    def blob_at(self, sha: str, rel: str, pr: int) -> str:
        """`rel` AT `sha`, and only if it is a FILE there.

        `git show H:dir` exits 0 and prints the directory's listing, so `file_at` alone
        would accept `apps/desktop/AUDIT/tickets` as a non-empty audit report.
        """
        self._ensure_commit(sha, pr)
        kind = _run(["git", "cat-file", "-t", f"{sha}:{rel}"], cwd=self.root).strip()
        if kind != "blob":
            raise GateError(f"{rel} at {sha[:12]} is a {kind or 'nothing readable'}, not a file")
        return _run(["git", "show", f"{sha}:{rel}"], cwd=self.root)

    def resolve_commit(self, sha: str, pr: int) -> None:
        """Have `sha` in this clone as a COMMIT, fetching it when it is not here; GateError
        when it cannot be had. The audited commit is read the way the head is."""
        self._ensure_commit(sha, pr)

    def is_ancestor(self, old: str, new: str) -> bool:
        """Whether `old` is `new` or in its history. Both must already be in this clone.

        `git merge-base --is-ancestor` answers with its exit code: 0 yes, 1 no. Anything
        else is git failing to answer, and that is neither.
        """
        args = ["git", "merge-base", "--is-ancestor", old, new]
        code, out, err = _exit(args, cwd=self.root)
        if code == 0:
            return True
        if code == 1:
            return False
        raise _failed(args, code, out, err)

    def commits_between(self, old: str, new: str) -> int:
        """How many commits `new` has that `old` does not."""
        raw = _run(["git", "rev-list", "--count", f"{old}..{new}"], cwd=self.root).strip()
        if not raw.isdigit():
            raise GateError(f"`git rev-list --count` printed {raw[:40]!r}, not a number")
        return int(raw)

    def paths_between(self, old: str, new: str) -> list[str]:
        """Every path whose content differs between the two commits' trees.

        `--no-renames`: a file moved after the audit is listed under BOTH names, so one
        moved out of the perimeter still counts under the name it had. `-z`: a path with
        a quote or a non-ASCII byte arrives as itself, not as git's quoted form of it.
        """
        raw = _run(["git", "diff", "--name-only", "--no-renames", "-z", old, new],
                   cwd=self.root, timeout=120)
        return [path for path in raw.split("\0") if path]

    def changed_files(self, pr: int) -> list[dict]:
        """Every file the pull request changes, as GitHub lists them -- all pages.

        The REST list, not `gh pr view --json files`: that one stops at 100 entries and
        says nothing about having stopped. #314 changed 569 files.
        """
        where = f"repos/{self.repo}" if self.repo else "repos/{owner}/{repo}"
        raw = _run(["gh", "api", "--paginate", f"{where}/pulls/{pr}/files?per_page=100",
                    "--jq", FILES_JQ], cwd=self.root, timeout=120)
        return parse_file_lines(raw)

    def audit_rule(self) -> dict:
        """`config/audit-required-paths.json`, from the checkout that RUNS this gate, and
        only while it still accounts for every root of the engine's own perimeter."""
        rule = _read_json(self.root / AUDIT_PATHS_REL)
        drift = perimeter_drift(rule, _read_json(self.root / PERIMETER_REL))
        if drift:
            raise GateError(f"{AUDIT_PATHS_REL} has drifted from {PERIMETER_REL}: "
                            + "; ".join(drift))
        return rule

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


def _read_json(path: pathlib.Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError(f"{path.name} could not be read: {exc}") from None
    if not isinstance(data, dict):
        raise GateError(f"{path.name} is {type(data).__name__}, not an object")
    return data


def parse_file_lines(raw: str) -> list[dict]:
    """The REST file list as `--jq` prints it: one JSON object per line."""
    entries: list[dict] = []
    for number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GateError(f"line {number} of the file list is not JSON: {exc}") from None
        entries.append(entry)
    return entries


def audit_globs(rule: dict) -> list[str]:
    """The declared globs. A rule that names no path would call every change exempt."""
    globs = rule.get("globs")
    if (not isinstance(globs, list) or not globs
            or not all(isinstance(g, str) and g.strip() for g in globs)):
        raise GateError(f"{AUDIT_PATHS_REL} must carry `globs`: a non-empty list of paths")
    return globs


def excluded_roots(rule: dict) -> dict[str, str]:
    """`protected_root` -> reason, for every root the rule excludes by name."""
    listed = rule.get("not_covered")
    if not isinstance(listed, list):
        raise GateError(f"{AUDIT_PATHS_REL} must carry `not_covered`: a list")
    out: dict[str, str] = {}
    for entry in listed:
        if isinstance(entry, dict) and "protected_root" in entry:
            out[str(entry["protected_root"])] = str(entry.get("reason") or "").strip()
    return out


def perimeter_drift(rule: dict, manifest: dict) -> list[str]:
    """Every way the declared globs and the engine's own perimeter disagree; [] if none.

    Each protected root must be accounted for exactly once: listed as a glob (prefixed
    `engine/`), or excluded under `not_covered` with a reason. A root the engine gained
    and this file never heard of is the silent drift this exists to refuse; a glob or an
    exclusion for a root the engine no longer has is a stale line that reads as coverage.
    """
    roots = manifest.get("protected_roots")
    if (not isinstance(roots, list) or not roots
            or not all(isinstance(r, str) and r for r in roots)):
        return [f"{PERIMETER_REL} carries no readable `protected_roots`"]
    problems: list[str] = []
    listed: set[str] = set()
    for glob in audit_globs(rule):
        if glob.startswith(PERIMETER_PREFIX):
            listed.add(glob[len(PERIMETER_PREFIX):])
        else:
            problems.append(f"glob `{glob}` is not under `{PERIMETER_PREFIX}`, so it was not "
                            f"derived from the engine's perimeter")
    excluded = excluded_roots(rule)
    for root in roots:
        if root not in listed and root not in excluded:
            problems.append(f"protected root `{root}` is neither listed as "
                            f"`{PERIMETER_PREFIX}{root}` nor excluded with a reason")
    for root in sorted(listed - set(roots)):
        problems.append(f"glob `{PERIMETER_PREFIX}{root}` is not a protected root any more")
    for root in sorted(set(excluded) - set(roots)):
        problems.append(f"`{root}` is excluded and is not a protected root any more")
    for root in sorted(listed & set(excluded)):
        problems.append(f"`{root}` is both listed and excluded")
    for root, reason in sorted(excluded.items()):
        if not reason:
            problems.append(f"`{root}` is excluded with no reason")
    return problems


def needs_audit(path: str, globs: list[str]) -> bool:
    """Whether `path` is engine security code under the declared globs.

    The engine's own matcher (`engine/runtime/bro_workspace.py::matches_pattern`): fnmatch,
    where `*` crosses `/`, plus "a bare directory covers what is under it". Always
    case-insensitive, which is the engine's rule on the platform where case does not
    distinguish paths; here it is the stricter answer, and `engine/Runtime/x.py` asking
    for an audit it did not need costs less than the reverse.
    """
    rel = path.replace("\\", "/").lower()
    for glob in globs:
        pat = glob.replace("\\", "/").lower()
        if fnmatch.fnmatchcase(rel, pat):
            return True
        if not any(ch in pat for ch in "*?[") and rel.startswith(pat + "/"):
            return True
    return False


def declarations(body: str) -> tuple[list[str], list[str]]:
    """`(audit values, waiver values)`: the lines of `body` that BEGIN with a key.

    Begins, at column 0, case-sensitive. "see the Architect-Audit: line below" is a
    sentence, and so is the same key indented or quoted.
    """
    audits: list[str] = []
    waivers: list[str] = []
    for line in body.splitlines():
        if line.startswith(AUDIT_KEY):
            audits.append(line[len(AUDIT_KEY):].strip())
        elif line.startswith(WAIVER_KEY):
            waivers.append(line[len(WAIVER_KEY):].strip())
    return audits, waivers


def g2_engine_row(roadmap: str) -> str | None:
    """§G.2's engine-security row, or None unless there is EXACTLY one."""
    start = G2_HEADING.search(roadmap)
    if not start:
        return None
    rest = roadmap[start.end():]
    end = NEXT_HEADING.search(rest)
    section = rest[:end.start()] if end else rest
    rows = [line for line in section.splitlines()
            if line.startswith("|") and G2_ROW_MARK in (line.split("|") + ["", ""])[1]]
    return rows[0] if len(rows) == 1 else None


def waivers_on(row: str) -> list[tuple[str, str]]:
    """`(date, that waiver's own text)` for every dated `OWNER WAIVER` on the row.

    A waiver's text runs to the next `OWNER WAIVER`, dated or not, so a pull request
    named under one waiver is not covered by the date of another.
    """
    starts = [m.start() for m in re.finditer(re.escape(WAIVER_WORDS), row)]
    found: list[tuple[str, str]] = []
    for match in WAIVER_DATED.finditer(row):
        later = [s for s in starts if s > match.start()]
        found.append((match.group(1), row[match.end():later[0] if later else len(row)]))
    return found


def names_pull_request(text: str, pr: int) -> bool:
    """`#N` as a whole number, of THIS repository: `#5` is not named by `#50`, and not by
    `another/repo#5`."""
    return re.search(rf"(?<!\w)#{pr}(?!\d)", text) is not None


def audit_bindings(report: str) -> tuple[list[str], list[str]]:
    """`(Audited-PR values, Audited-Head values)`: the DISTINCT values of the report's
    lines that BEGIN with each key, in the order they appear.

    Begins, at column 0, case-sensitive -- the rule `declarations` applies to the body.
    A key said twice with one value is one statement; said with two, it is two.
    """
    prs: list[str] = []
    heads: list[str] = []
    for line in report.splitlines():
        for key, found in ((AUDITED_PR_KEY, prs), (AUDITED_HEAD_KEY, heads)):
            if line.startswith(key):
                value = line[len(key):].strip()
                if value not in found:
                    found.append(value)
    return prs, heads


def binding_format(pr: int) -> str:
    """The whole format, with a worked example and where to file the report -- written so
    that a RED's remedy alone is enough to produce a report that passes."""
    return (f"the report must carry two lines, each BEGINNING its line: `{AUDITED_PR_KEY} "
            f"#{pr}` and `{AUDITED_HEAD_KEY} <the 40-hex commit the auditor read, as `git "
            f"rev-parse HEAD` printed it on the audited checkout>` -- for example "
            f"`{AUDITED_PR_KEY} #{pr}` and, on the next line, `{AUDITED_HEAD_KEY} "
            f"{EXAMPLE_SHA}`. File it as `{PER_CHANGE_AUDIT_PATH.format(pr=pr)}` (or in a "
            f"subdirectory of apps/desktop/AUDIT/) and NOT as a `YYYY-MM-DD-*.md` directly "
            f"under apps/desktop/AUDIT/, which tools/check_audit_reports.py takes for the "
            f"round the ledger must call authoritative. Commit it on this branch after the "
            f"audited commit -- a file under an AUDIT directory is not an audit-required "
            f"path, so adding the report does not outdate it -- then push, wait for the "
            f"checks on the new head, and run this again")


def check_audit_binding(inputs: Inputs, value: str, report: str, head: str, pr: int,
                        globs: list[str], res: Result) -> str:
    """The report names THIS pull request and a commit of its history, and no
    audit-required path differs between that commit and H (T-155).

    Returns what GREEN says in brackets after the report's path; "" when it added a problem.
    """
    fmt = binding_format(pr)
    prs, heads = audit_bindings(report)
    before = len(res.problems)

    if not prs:
        res.bad(f"the report `{value}` at {head[:12]} carries no `{AUDITED_PR_KEY}` line: it "
                f"does not say which pull request it audited", fmt)
    elif len(prs) > 1:
        res.bad(f"the report `{value}` at {head[:12]} carries {len(prs)} different "
                f"`{AUDITED_PR_KEY}` values ({_some(prs)}): which pull request it audited is "
                f"ambiguous", f"leave ONE. A report is an audit of one pull request; {fmt}")
    else:
        named = PR_NUMBER_RE.fullmatch(prs[0])
        if not named:
            res.bad(f"`{AUDITED_PR_KEY} {prs[0]}` in the report `{value}` is not a pull "
                    f"request number", f"write it as `#` and the number, nothing else on the "
                    f"line; {fmt}")
        elif int(named.group(1)) != pr:
            res.bad(f"the report `{value}` says `{AUDITED_PR_KEY} {prs[0]}`, and this is pull "
                    f"request #{pr}: it is an audit of another pull request",
                    f"cite the report that audited THIS pull request, or have this one "
                    f"audited. A report is not transferable; {fmt}")

    audited = ""
    if not heads:
        res.bad(f"the report `{value}` at {head[:12]} carries no `{AUDITED_HEAD_KEY}` line: it "
                f"does not say which commit the auditor read", fmt)
    elif len(heads) > 1:
        res.bad(f"the report `{value}` at {head[:12]} carries {len(heads)} different "
                f"`{AUDITED_HEAD_KEY}` values ({_some([h[:12] for h in heads])}): which commit "
                f"was audited is ambiguous", f"leave ONE: the commit the auditor read; {fmt}")
    elif not SHA_RE.fullmatch(heads[0]):
        res.bad(f"`{AUDITED_HEAD_KEY} {heads[0]}` in the report `{value}` is not a commit id: "
                f"it must be exactly 40 lowercase hex characters",
                f"a short id, a branch name or a tag can come to mean another commit. {fmt}")
    else:
        audited = heads[0]
    if len(res.problems) != before:
        return ""

    redo = (f"the audit must be redone or extended to the new head; then update "
            f"`Audited-Head` in {value} to the commit the auditor read, commit, push, wait "
            f"for the checks on the new head, and run this again")
    try:
        inputs.resolve_commit(audited, pr)
    except GateError as exc:
        res.bad(f"`{AUDITED_HEAD_KEY} {audited}` in the report `{value}` names no commit this "
                f"repository has, even after a fetch: {exc}",
                f"the line must name a commit that is pushed and is in this pull request's "
                f"history. {fmt}")
        return ""
    try:
        ancestor = inputs.is_ancestor(audited, head)
        later = inputs.commits_between(audited, head) if ancestor else 0
        moved = inputs.paths_between(audited, head) if ancestor else []
    except GateError as exc:
        res.bad(f"what changed between the audited {audited[:12]} and the head {head[:12]} "
                f"could not be read: {exc}",
                "`git fetch origin`, then run this again; a history that cannot be read is "
                "not a history in which nothing moved")
        return ""
    if not ancestor:
        res.bad(f"`{AUDITED_HEAD_KEY} {audited[:12]}` in the report `{value}` is not in the "
                f"history of pull request #{pr}'s head {head[:12]}: the report audited a "
                f"commit this pull request does not contain (a rebase, a force-push, or "
                f"another branch)",
                f"an audit of a commit that is not in what merges is an audit of something "
                f"else, and this gate does not guess that a rebased commit is the same "
                f"change. So {redo}")
        return ""
    hits = sorted(p for p in moved if needs_audit(p, globs))
    if hits:
        res.bad(f"{len(hits)} audit-required path(s) changed after the audit -- "
                f"{_some(hits)} -- between the audited {audited[:12]} and the head "
                f"{head[:12]}, {later} commit(s) later: the report did not read what would "
                f"merge", redo)
        return ""
    if audited == head:
        return f"names #{pr} and was audited at this head"
    return (f"names #{pr} and was audited at {audited[:12]}; the head is {later} commit(s) "
            f"later and no audit-required path moved")


def check_audit_citation(inputs: Inputs, value: str, head: str, pr: int, globs: list[str],
                         res: Result) -> str:
    """`Architect-Audit: <path>` -- a non-empty FILE at H under an AUDIT directory, which
    itself names this pull request and the commit that was audited."""
    cite = (f"write the line as `{AUDIT_KEY} <path>`, the path repo-relative and under "
            f"{' or '.join(AUDIT_DIRS)}, with the report committed on this branch")
    if not value:
        res.bad(f"the `{AUDIT_KEY}` line names no path", cite)
        return ""
    if not value.startswith(AUDIT_DIRS) or posixpath.normpath(value) != value:
        res.bad(f"`{AUDIT_KEY} {value}` is not a file under {' or '.join(AUDIT_DIRS)}",
                f"an audit report is filed where audit reports live. Move it there and "
                f"{cite}")
        return ""
    try:
        text = inputs.blob_at(head, value, pr)
    except GateError as exc:
        res.bad(f"`{AUDIT_KEY} {value}` does not exist at {head[:12]}: {exc}",
                "commit the report on this branch and push, wait for the checks on the new "
                "head, then run this again. A report that is not at the head that merges is "
                "not in what merges")
        return ""
    if not text.strip():
        res.bad(f"`{AUDIT_KEY} {value}` is empty at {head[:12]}",
                "an empty file is not a report. File the Architect's audit there, push, wait "
                "for the checks, then run this again")
        return ""
    bound = check_audit_binding(inputs, value, text, head, pr, globs, res)
    if not bound:
        return ""
    return (f"Architect-Audit {value} ({bound}). Its verdict and its author are NOT read "
            f"by this gate")


def check_waiver(inputs: Inputs, value: str, head: str, pr: int, res: Result) -> str:
    """`Owner-Waiver: YYYY-MM-DD` -- on §G.2's row AT H, and naming this pull request."""
    owner = (f"only the Owner records a waiver: on roadmap §G.2's engine-security row, as "
             f"`{WAIVER_WORDS} <date>` naming `#{pr}`. Or get an Architect audit and cite it "
             f"with `{AUDIT_KEY} <path>` instead")
    try:
        if not DATE_RE.fullmatch(value):
            raise ValueError(value)
        datetime.date.fromisoformat(value)
    except ValueError:
        res.bad(f"`{WAIVER_KEY} {value}` is not a date",
                f"write the line as `{WAIVER_KEY} YYYY-MM-DD`: the date of the waiver on "
                f"roadmap §G.2's engine-security row")
        return ""
    try:
        roadmap = inputs.file_at(head, ROADMAP_REL, pr)
    except GateError as exc:
        res.bad(f"{ROADMAP_REL} at {head[:12]} could not be read: {exc}",
                "`git fetch origin`, then run this again")
        return ""
    row = g2_engine_row(roadmap)
    if row is None:
        res.bad(f"{ROADMAP_REL} at {head[:12]} has no single §G.2 row for "
                f"{G2_ROW_MARK}, so there is no row a waiver could be on",
                "restore §G.2's engine-security row; a waiver nobody can find is not one")
        return ""
    found = waivers_on(row)
    mine = [text for date, text in found if date == value]
    if not mine:
        dates = ", ".join(sorted({date for date, _ in found})) or "none"
        res.bad(f"roadmap §G.2's engine-security row at {head[:12]} carries no "
                f"`{WAIVER_WORDS} {value}` (waivers on the row: {dates})", owner)
        return ""
    if not any(names_pull_request(text, pr) for text in mine):
        res.bad(f"the `{WAIVER_WORDS} {value}` on roadmap §G.2's engine-security row at "
                f"{head[:12]} does not name `#{pr}`: it is a waiver for other pull requests",
                owner)
        return ""
    return f"Owner-Waiver {value} (roadmap §G.2 names #{pr})"


def check_audit(inputs: Inputs, view: dict, head: str, pr: int, res: Result) -> str:
    """Engine security code merges with a cited audit, or a waiver the Owner wrote.

    Returns the sentence GREEN prints about it; "" when it added a problem.
    """
    try:
        globs = audit_globs(inputs.audit_rule())
    except GateError as exc:
        res.bad(f"the audit rule could not be read: {exc}",
                f"repair {AUDIT_PATHS_REL} so it accounts for every root of {PERIMETER_REL}; "
                f"a rule that cannot be read exempts nothing")
        return ""
    again = "run this again; a file list that cannot be read is not a list of safe files"
    try:
        entries = inputs.changed_files(pr)
    except GateError as exc:
        res.bad(f"the files pull request #{pr} changes could not be read: {exc}", again)
        return ""
    if (not isinstance(entries, list) or not entries
            or not all(isinstance(e, dict) and isinstance(e.get("filename"), str)
                       and e["filename"] for e in entries)):
        res.bad(f"the list of files pull request #{pr} changes is unreadable or empty", again)
        return ""
    claimed = view.get("changedFiles")
    if type(claimed) is not int or claimed != len(entries):
        res.bad(f"GitHub says pull request #{pr} changes {claimed!r} file(s) and listed "
                f"{len(entries)}: the list is incomplete", again)
        return ""
    paths = {e["filename"] for e in entries}
    paths |= {e["previous_filename"] for e in entries
              if isinstance(e.get("previous_filename"), str) and e["previous_filename"]}
    hits = sorted(p for p in paths if needs_audit(p, globs))
    if not hits:
        return "not required (no engine security path changed)"

    changed = f"{len(hits)} engine security path(s) -- {_some(hits)}"
    body = view.get("body")
    if not isinstance(body, str):
        res.bad(f"pull request #{pr} changes {changed} -- and its body could not be read "
                f"(got {type(body).__name__})",
                "run this again; a body that cannot be read carries no declaration")
        return ""
    audits, waivers = declarations(body)
    if not audits and not waivers:
        res.bad(f"pull request #{pr} changes {changed} -- and its body carries neither an "
                f"`{AUDIT_KEY}` nor an `{WAIVER_KEY}` line. Roadmap §G.2: an Architect audit "
                f"is mandatory for engine security code",
                f"get an Architect audit and cite it, or have the Owner record a scoped "
                f"waiver on roadmap §G.2 naming this pull request. Then ONE line in the "
                f"body, beginning the line: `{AUDIT_KEY} <path under "
                f"{' or '.join(AUDIT_DIRS)}>` or `{WAIVER_KEY} YYYY-MM-DD`. For an audit: "
                f"{binding_format(pr)}")
        return ""
    if len(audits) + len(waivers) != 1:
        res.bad(f"pull request #{pr}'s body carries {len(audits)} `{AUDIT_KEY}` and "
                f"{len(waivers)} `{WAIVER_KEY}` line(s); which one it stands on is ambiguous",
                "leave exactly ONE of them. An audit and a waiver are different claims, and "
                "a pull request rests on one")
        return ""
    if audits:
        return check_audit_citation(inputs, audits[0], head, pr, globs, res)
    return check_waiver(inputs, waivers[0], head, pr, res)


def merge_command(pr: int, head: str, repo: str | None = None) -> str:
    return (f"gh pr merge {pr} --squash --match-head-commit {head}"
            + (f" -R {repo}" if repo else ""))


def evaluate(pr: int, inputs: Inputs, expect: str | None = None) -> tuple[Result, dict]:
    res = Result()
    facts: dict = {"head": None, "counts": {}, "date": "", "audit": ""}
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
        facts["audit"] = check_audit(inputs, view, head, pr, res)
    return res, facts


def evaluate_audit_only(pr: int, inputs: Inputs) -> tuple[Result, dict]:
    """Check (f) alone, for whatever head GitHub records -- merged, closed or open."""
    res = Result()
    facts: dict = {"head": None, "state": "", "audit": ""}
    try:
        view = inputs.pr_view(pr)
    except GateError as exc:
        res.bad(f"pull request #{pr} could not be read from GitHub: {exc}",
                "check `gh auth status` and the network, then run this again")
        return res, facts
    facts["state"] = str(view.get("state") or "").upper() or "in no readable state"
    head = check_head(view, pr, None, res)
    facts["head"] = head
    if head:
        facts["audit"] = check_audit(inputs, view, head, pr, res)
    return res, facts


def explain_audit(pr: int, inputs: Inputs) -> int:
    """Print the audit check's verdict and nothing else. Never prints a merge command."""
    try:
        res, facts = evaluate_audit_only(pr, inputs)
    except Exception as exc:  # noqa: BLE001 - a gate that crashed has not said yes
        print(f"RED: the audit rule could NOT be checked for pull request #{pr} -- the gate "
              f"itself failed\n")
        print(f"  1. {type(exc).__name__}: {exc}")
        print("     -> fix tools/check_merge_ready.py; a gate that could not run is not a pass")
        return 1
    at = f" at {facts['head'][:12]}" if facts["head"] else ""
    # A pull request that is no longer open was merged, or closed, under the rule of ITS
    # day. What is printed here is today's rule, and saying so is the difference between
    # "this would be refused now" and "this broke the rule when it merged".
    then = ""
    if facts["state"] and facts["state"] != "OPEN":
        then = (f"Pull request #{pr} is {facts['state']}. The verdict above is the rule AS IT "
                f"STANDS TODAY read against the head GitHub records for it -- not the rule "
                f"that was in force when it was {facts['state'].lower()}. The audit rule is "
                f"T-154 and the `{AUDITED_PR_KEY}` / `{AUDITED_HEAD_KEY}` lines a cited "
                f"report must carry are T-155, both of 2026-10-02: a pull request settled "
                f"before either was never asked.")
    if res.problems:
        print(f"RED: pull request #{pr} does NOT meet the audit rule{at}\n")
        for i, (what, remedy) in enumerate(res.problems, 1):
            print(f"  {i}. {what}")
            print(f"     -> {remedy}\n")
        print("This is the audit check alone (roadmap §G.2, first row). It was run to "
              "explain, not to merge.")
        if then:
            print(then)
        return 1
    print(f"GREEN: pull request #{pr} meets the audit rule{at}.\n")
    print(f"  state  : {facts['state']}")
    print(f"  audit  : {facts['audit']}")
    print("\nThis is the audit check alone. It is NOT permission to merge: run without "
          "--explain-audit for that.")
    if then:
        print(then)
    return 0


def main(argv: list[str] | None = None, inputs: Inputs | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pr", type=int, required=True, help="the pull request number")
    ap.add_argument("--repo", default=None, help="owner/name, when it is not this clone's origin")
    ap.add_argument("--expect-head", default=None,
                    help="the commit a merge command pins; RED when the live head is another")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--explain-audit", action="store_true",
                    help="print ONLY the audit check's verdict for this pull request's head, "
                         "merged or not, and exit on that check alone. Never a merge command")
    args = ap.parse_args(argv)
    inputs = inputs or Inputs(pathlib.Path(args.root), args.repo)

    if args.explain_audit:
        return explain_audit(args.pr, inputs)

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
    print(f"  audit  : {facts['audit']}")
    print("\nRun exactly this:")
    print(f"  {merge_command(args.pr, facts['head'], inputs.repo)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
