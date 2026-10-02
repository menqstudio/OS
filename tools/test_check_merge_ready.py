"""Tests for the merge-readiness gate.

Every input the gate reads comes through `check_merge_ready.Inputs`, so `Fake` below
replaces GitHub, git and the clock, and nothing here touches a network. Each RED cause is
produced ON ITS OWN -- one problem, the others satisfied -- because a test that breaks two
things at once passes whichever check is deleted. `TheRealInputs` at the bottom drives the
REAL `Inputs` against a repository on disk, since a fake proves nothing about `git show`.

Every test names the mutation that turns it red. `unittest.main()` is the last statement
(ninth audit `I-05`).
"""
from __future__ import annotations

import contextlib
import copy
import datetime
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_merge_ready
from check_merge_ready import GateError

HEAD = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
D1 = datetime.date(2026, 10, 1)
D2 = datetime.date(2026, 10, 2)


def state(day: datetime.date, body: str = "the state of each part") -> str:
    return (f"# PROJECT_STATE\n\n**Last updated · Վերջին թարմացում:** {day} — {body}\n")


def run(name: str, status: str = "COMPLETED", conclusion: str = "SUCCESS",
        started: str = "2026-10-01T23:38:00Z") -> dict:
    return {"__typename": "CheckRun", "workflowName": "ci", "name": name, "status": status,
            "conclusion": conclusion, "startedAt": started}


def green_view() -> dict:
    return {"number": 5, "state": "OPEN", "headRefOid": HEAD, "baseRefName": "main",
            "mergeStateStatus": "CLEAN", "body": "What this changes, and why.\n",
            "changedFiles": 1,
            "statusCheckRollup": [run("frontend"), run("engine"), run("coordination")]}


ROADMAP = "MASTER_EXECUTION_ROADMAP.md"
REPORT = "apps/desktop/AUDIT/2026-10-03-architect-audit-of-the-wall.md"
RUNTIME = "engine/runtime/bro_security.py"
WAIVED = "2027-01-01"


def changed(*names: str) -> list[dict]:
    return [{"filename": name, "previous_filename": None} for name in names]


def roadmap(rule: str) -> str:
    """A roadmap whose §G.2 engine-security row ends in `rule`. The waiver it carries is
    dated a year after anything in this checkout's roadmap, and names pull requests this
    checkout's roadmap does not, so a gate that read the file on disk cannot pass."""
    return ("# Roadmap\n\n### G.1 Per-phase ownership\n| Phase | Rule |\n|---|---|\n"
            "| Any `engine/` security code | **OWNER WAIVER 2027-05-05:** `#5`, the section "
            "before. |\n\n### G.2 Task-class overrides\n"
            "| Task class | Builder | Audit | Approval | Rule |\n|---|---|---|---|---|\n"
            "| Any `engine/` security code (wall · leases) | builder | **mandatory** | "
            f"**before implementation** | Never rushed. {rule} |\n"
            "| Trust-boundary / key / secret handling | builder | **mandatory** | stop | As "
            "for the `engine/` security code row. **OWNER WAIVER 2027-03-03:** `#5`, "
            "another row. |\n\n## H. Registry\n\n| Artifact | Note |\n|---|---|\n"
            "| Any `engine/` security code | **OWNER WAIVER 2027-04-04:** `#5`, the section "
            "after. |\n")


def waived_view(line: str = f"Owner-Waiver: {WAIVED}") -> dict:
    view = green_view()
    view["body"] = f"Tightens the wall.\n\n{line}\n"
    return view


class Fake(check_merge_ready.Inputs):
    """GitHub, git and the clock, all answering from memory.

    The defaults are the night of #314: 00:05 here, 20:05 the day before in UTC. A line
    dated D2 is right in both zones; one dated D1 is right in UTC and wrong here.
    """

    def __init__(self, view=None, *, at_head=None, at_base=None, local=D2, utc=D1,
                 repo=None, files=None, tree=None, rule=None) -> None:
        super().__init__(ROOT, repo)
        self.view = green_view() if view is None else view
        self.at_head = state(D2) if at_head is None else at_head
        self.at_base = state(D1, "what main said yesterday") if at_base is None else at_base
        self.local, self.utc = local, utc
        self.asked: list[tuple] = []
        self.blobs: list[tuple] = []
        #: What the pull request changes. The default touches no engine security path.
        self.files = changed("tools/check_merge_ready.py") if files is None else files
        #: Every other path that exists AT the head: `rel` -> its text, or the error.
        self.tree = {} if tree is None else tree
        self.rule = rule
        if isinstance(files, list) and isinstance(self.view, dict):
            self.view["changedFiles"] = len(files)       # GitHub's count agrees by default

    def pr_view(self, pr):
        if isinstance(self.view, BaseException):
            raise self.view
        return self.view

    def _at(self, sha, rel):
        self.asked.append((sha, rel))
        if rel == check_merge_ready.STATE_REL:
            found = self.at_head
        else:
            found = self.tree.get(rel, GateError(f"path '{rel}' does not exist in '{sha}'"))
        if isinstance(found, BaseException):
            raise found
        return found

    def file_at(self, sha, rel, pr):
        return self._at(sha, rel)

    def blob_at(self, sha, rel, pr):
        self.blobs.append((sha, rel))            # read as a FILE, not as whatever is there
        return self._at(sha, rel)

    def changed_files(self, pr):
        if isinstance(self.files, BaseException):
            raise self.files
        return self.files

    def audit_rule(self):
        if self.rule is None:
            return super().audit_rule()          # the real file, drift check included
        if isinstance(self.rule, BaseException):
            raise self.rule
        return self.rule

    def base_file(self, base, rel):
        if isinstance(self.at_base, BaseException):
            raise self.at_base
        return self.at_base

    def today_local(self):
        return self.local

    def today_utc(self):
        return self.utc


def gate(inputs: Fake, *extra: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = check_merge_ready.main(["--pr", "5", *extra], inputs)
    return code, out.getvalue()


class GateCase(unittest.TestCase):
    """What both suites below assert about a RED. It holds no test of its own."""

    def red(self, inputs: Fake, *needles: str, problems: int = 1) -> str:
        """RED, with exactly `problems` problems, each needle present, and no traceback."""
        code, out = gate(inputs)
        self.assertEqual(code, 1, out)
        self.assertTrue(out.startswith("RED:"), out)
        self.assertNotIn("Traceback", out)
        self.assertNotIn("gh pr merge 5 --squash", out, "a RED gate printed the command")
        self.assertIn(f"  {problems}. ", out)
        self.assertNotIn(f"  {problems + 1}. ", out, out)
        self.assertEqual(out.count("     -> "), problems, "a problem without its remedy")
        for needle in needles:
            self.assertIn(needle, out)
        return out


class MergeReady(GateCase):
    # --- GREEN ---------------------------------------------------------------------

    def test_green_prints_the_exact_command(self):
        """The positive control. Without it every RED below could be a gate that never
        says yes. Mutant: print the command without the head ⇒ red."""
        inputs = Fake()
        code, out = gate(inputs)
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("GREEN:"), out)
        self.assertIn(f"gh pr merge 5 --squash --match-head-commit {HEAD}\n", out)
        self.assertIn("3 passed", out)
        self.assertEqual(inputs.asked, [(HEAD, "PROJECT_STATE.md")],
                         "PROJECT_STATE.md was not read AT the head that will merge")

    def test_green_names_the_repository_it_was_asked_about(self):
        code, out = gate(Fake(repo="menqstudio/OS"))
        self.assertEqual(code, 0, out)
        self.assertIn(f"gh pr merge 5 --squash --match-head-commit {HEAD} -R menqstudio/OS", out)

    # --- a. open, and a known head ---------------------------------------------------

    def test_a_closed_or_merged_pull_request_is_red(self):
        """Mutant: drop check_open ⇒ green -- everything else about a merged pull request
        can still look fine, and #317 read exactly so the minute after it merged."""
        for value in ("CLOSED", "MERGED", "", None):
            with self.subTest(state=value):
                view = green_view()
                view["state"] = value
                self.red(Fake(view), "not OPEN")

    def test_a_pull_request_with_no_head_is_red(self):
        """Mutant: drop the head check ⇒ the command is printed pinning nothing."""
        for value in (None, "", "abc123", 7):
            with self.subTest(head=value):
                view = green_view()
                view["headRefOid"] = value
                self.red(Fake(view), "did not name a head commit")

    def test_a_pin_that_is_not_the_live_head_is_red(self):
        """Mutant: ignore --expect-head ⇒ green on a head nobody typed."""
        code, out = gate(Fake(), "--expect-head", "f" * 40)
        self.assertEqual(code, 1, out)
        self.assertIn("somebody pushed since", out)
        self.assertEqual(gate(Fake(), "--expect-head", HEAD)[0], 0)
        self.assertEqual(gate(Fake(), "--expect-head", HEAD[:12])[0], 0)

    # --- b. every check completed and passed -------------------------------------------

    def test_a_pending_check_is_red(self):
        """Mutant: drop the pending arm ⇒ green mid-run, which is how #85 and #86 merged."""
        for status in ("IN_PROGRESS", "QUEUED", "PENDING", "WAITING"):
            with self.subTest(status=status):
                view = green_view()
                view["statusCheckRollup"].append(run("windows engine", status, ""))
                self.red(Fake(view), "have not finished", "windows engine")

    def test_a_failed_check_is_red(self):
        """Mutant: drop the failed arm ⇒ green on a red head, which is how #84 merged."""
        for conclusion in ("FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STALE", ""):
            with self.subTest(conclusion=conclusion):
                view = green_view()
                view["statusCheckRollup"].append(run("bundle budget", "COMPLETED", conclusion))
                self.red(Fake(view), "did not pass", "bundle budget")

    def test_no_checks_at_all_is_red(self):
        """Mutant: treat an empty list as nothing-failed ⇒ green before CI has started."""
        view = green_view()
        view["statusCheckRollup"] = []
        self.red(Fake(view), "NO checks at all")

    def test_an_unreadable_check_list_is_red(self):
        """Mutant: default a missing rollup to [] and skip ⇒ green on no information."""
        for value in (None, "", {"nodes": []}, 3):
            with self.subTest(rollup=value):
                view = green_view()
                view["statusCheckRollup"] = value
                self.red(Fake(view), "unreadable")
        view = green_view()
        del view["statusCheckRollup"]
        self.red(Fake(view), "unreadable")

    def test_an_entry_that_is_not_a_check_is_red(self):
        view = green_view()
        view["statusCheckRollup"].append("not an object")
        self.red(Fake(view), "did not pass", "unreadable entry")
        view = green_view()
        view["statusCheckRollup"].append({"name": "shapeless"})
        self.red(Fake(view), "did not pass", "shapeless")

    def test_skipped_checks_alone_are_not_a_pass(self):
        """Mutant: drop the at-least-one-SUCCESS arm ⇒ green on a head nothing passed on."""
        view = green_view()
        view["statusCheckRollup"] = [run("a", conclusion="SKIPPED"), run("b", conclusion="NEUTRAL")]
        self.red(Fake(view), "no check on", "has PASSED")

    def test_a_skipped_check_beside_passes_is_not_a_failure(self):
        view = green_view()
        view["statusCheckRollup"].append(run("release preflight", conclusion="SKIPPED"))
        code, out = gate(Fake(view))
        self.assertEqual(code, 0, out)
        self.assertIn("3 passed, 1 skipped", out)

    def test_a_superseded_cancelled_run_does_not_fail_a_green_head(self):
        """Mutant: judge every rollup entry ⇒ red. #317's rollup held 62 entries for 39
        checks: 23 CANCELLED runs, each beside the run that replaced it."""
        view = green_view()
        view["statusCheckRollup"] = [
            run("engine", conclusion="CANCELLED", started="2026-10-01T23:32:54Z"),
            run("frontend", conclusion="CANCELLED", started="2026-10-01T23:32:54Z"),
            run("engine", started="2026-10-01T23:38:00Z"),
            run("frontend", started="2026-10-01T23:38:01Z"),
        ]
        code, out = gate(Fake(view))
        self.assertEqual(code, 0, out)
        self.assertIn("2 passed", out)

    def test_a_stale_success_does_not_hide_a_newer_failure(self):
        """Mutant: keep the LAST-LISTED run of each name ⇒ green. Listed newest-first on
        purpose, so list order cannot stand in for the timestamp. (Keep-the-first is the
        other mutant, and the cancelled-run test above is what it turns red.)"""
        view = green_view()
        view["statusCheckRollup"] = [
            run("frontend"),
            run("engine", conclusion="FAILURE", started="2026-10-01T23:50:00Z"),
            run("engine", conclusion="SUCCESS", started="2026-10-01T23:38:00Z"),
        ]
        self.red(Fake(view), "did not pass", "engine")

    def test_a_status_context_is_judged_too(self):
        context = {"__typename": "StatusContext", "context": "external/scan"}
        for value, needle in (("PENDING", "have not finished"), ("FAILURE", "did not pass"),
                              ("ERROR", "did not pass")):
            with self.subTest(state=value):
                view = green_view()
                view["statusCheckRollup"].append(dict(context, state=value))
                self.red(Fake(view), needle, "external/scan")
        view = green_view()
        view["statusCheckRollup"].append(dict(context, state="SUCCESS"))
        self.assertEqual(gate(Fake(view))[0], 0)

    # --- c. merge state -----------------------------------------------------------------

    def test_a_merge_state_that_is_not_CLEAN_is_red(self):
        """Mutant: drop check_merge_state ⇒ green on a branch that is BEHIND its base."""
        for value in ("BLOCKED", "BEHIND", "DIRTY", "UNSTABLE", "DRAFT", "UNKNOWN", "HAS_HOOKS",
                      "", None):
            with self.subTest(state=value):
                view = green_view()
                view["mergeStateStatus"] = value
                self.red(Fake(view), "not CLEAN")

    # --- d. the date the squash commit will get ------------------------------------------

    def test_a_date_one_day_behind_in_LOCAL_time_is_red(self):
        """#314, exactly: 00:05 here, 20:05 the day before in UTC, the line dated the day
        before. UTC alone accepts it. Mutant: drop the local arm ⇒ green."""
        out = self.red(Fake(at_head=state(D1), local=D2, utc=D1),
                       "this machine's zone", f"says `Last updated` {D1}", f"dated {D2}")
        self.assertIn(f"set the line to {D2}", out)

    def test_a_date_behind_ONLY_in_UTC_is_red(self):
        """The mirror image: a machine west of UTC in its evening. The local date accepts
        the line and the commit GitHub stamps in UTC does not. Mutant: drop the UTC arm ⇒
        green."""
        out = self.red(Fake(at_head=state(D1), local=D1, utc=D2),
                       "in UTC", f"says `Last updated` {D1}", f"dated {D2}")
        self.assertNotIn("this machine's zone", out)
        self.assertIn(f"set the line to {D2}", out)

    def test_a_date_behind_in_both_zones_says_so_twice(self):
        self.red(Fake(at_head=state(D1), local=D2, utc=D2),
                 "this machine's zone", "in UTC", problems=2)

    def test_a_date_that_holds_in_both_zones_is_green(self):
        for local, utc in ((D2, D1), (D1, D2), (D2, D2)):
            with self.subTest(local=local, utc=utc):
                self.assertEqual(gate(Fake(at_head=state(D2), local=local, utc=utc))[0], 0)

    def test_the_date_is_read_at_the_head_not_from_this_checkout(self):
        """Mutant: read ROOT/PROJECT_STATE.md ⇒ the head's own line is never consulted. The
        fake's line is dated a year ahead of anything on disk, and it is what must decide."""
        ahead = datetime.date(2027, 10, 2)
        self.assertEqual(gate(Fake(at_head=state(ahead), local=ahead, utc=ahead))[0], 0)
        self.red(Fake(at_head=state(D2), local=ahead, utc=ahead), "in UTC", problems=2)

    def test_a_squash_that_will_not_touch_the_file_is_exempt(self):
        """If PROJECT_STATE.md at the head is byte-identical to the base's, the squash
        commit does not touch it and cannot redden the rule. Mutant: drop the exemption ⇒
        red, demanding an edit that changes nothing."""
        same = state(D1)
        code, out = gate(Fake(at_head=same, at_base=same, local=D2, utc=D2))
        self.assertEqual(code, 0, out)
        self.assertIn("the squash will not touch it", out)

    def test_the_exemption_is_not_taken_when_the_base_cannot_be_read(self):
        """Mutant: treat an unreadable base as 'identical' ⇒ green on no information."""
        self.red(Fake(at_head=state(D1), at_base=GateError("no network"), local=D2, utc=D1),
                 "this machine's zone")

    def test_a_state_file_that_cannot_be_read_at_the_head_is_red(self):
        """Mutant: skip the date rule when the file is unreadable ⇒ green."""
        self.red(Fake(at_head=GateError("commit a1b2c3d4e5f6 is not in this clone")),
                 "could not be read", "not in this clone")

    def test_a_state_file_with_no_date_is_red(self):
        for text in ("# PROJECT_STATE\n\nno line at all\n",
                     "**Last updated:** recently, honestly\n",
                     "**Last updated:** 2026-13-45 — not a day\n"):
            with self.subTest(text=text):
                self.red(Fake(at_head=text), "Last updated")

    # --- failing inputs -------------------------------------------------------------------

    def test_an_unreadable_gh_is_red_with_the_reason(self):
        """Mutant: catch the failure and carry on with an empty view ⇒ a different RED, or
        worse. The reason gh gave must reach the reader."""
        self.red(Fake(GateError("`gh pr view 5 ...` exited 1: HTTP 401: Bad credentials")),
                 "could not be read from GitHub", "HTTP 401: Bad credentials")

    def test_an_unexpected_exception_is_red_and_never_a_traceback(self):
        """Mutant: drop the outer except ⇒ a traceback, which the hook reads as 'no
        verdict' and a person reads as 'broken, ignore it'."""
        for boom in (RuntimeError("the unexpected"), KeyError("headRefOid"), OSError(5, "io")):
            with self.subTest(boom=boom):
                code, out = gate(Fake(boom))
                self.assertEqual(code, 1, out)
                self.assertTrue(out.startswith("RED:"), out)
                self.assertIn(type(boom).__name__, out)
                self.assertNotIn("Traceback", out)


class AuditRule(GateCase):
    """f. Engine security code merges with a cited audit or a waiver the Owner wrote.

    Roadmap §G.2's first row was a sentence while #313, #314 and #321 went through with no
    Architect audit. Every RED below is produced on its own, on a pull request that is
    green in every other respect.
    """

    def green(self, inputs: Fake, line: str) -> str:
        code, out = gate(inputs)
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("GREEN:"), out)
        self.assertIn(f"  audit  : {line}\n", out)
        self.assertIn(f"gh pr merge 5 --squash --match-head-commit {HEAD}\n", out)
        return out

    def cited(self, path: str = REPORT) -> dict:
        view = green_view()
        view["body"] = f"Tightens the wall.\n\nArchitect-Audit: {path}\n\nMore prose.\n"
        return view

    # --- which pull requests the rule applies to ---------------------------------------

    def test_no_engine_security_path_changed_is_not_required(self):
        """The control for every RED below: the rule does not fire on what it does not
        cover. Mutant: require a declaration of every pull request ⇒ red."""
        files = changed("tools/check_merge_ready.py", "apps/desktop/src/App.tsx",
                        "engine/docs/OPERATOR_RUNBOOK.md", "engine/AUDIT/README.md",
                        "docs/engine/runtime/notes.md")
        self.green(Fake(files=files), "not required (no engine security path changed)")

    def test_an_engine_runtime_path_with_no_line_is_red_and_names_the_path(self):
        """#313, #314 and #321, exactly. Mutant: drop the neither-line arm, or drop the
        call to check_audit ⇒ green."""
        out = self.red(Fake(files=changed("README.md", RUNTIME)),
                       "1 engine security path(s)", RUNTIME, "neither",
                       "get an Architect audit and cite it, or have the Owner record a "
                       "scoped waiver on roadmap §G.2 naming this pull request")
        self.assertNotIn("README.md", out)

    def test_many_engine_paths_are_counted_and_the_first_few_named(self):
        names = [f"engine/runtime/bro_{i:02}.py" for i in range(9)]
        out = self.red(Fake(files=changed(*names)), "9 engine security path(s)",
                       "engine/runtime/bro_00.py", "(+5 more)")
        self.assertNotIn("engine/runtime/bro_08.py", out)

    def test_every_listed_root_asks_for_an_audit(self):
        """One path under each kind of glob the config carries: a `dir/**`, an exact file,
        and a dotted directory. Mutant: match only `engine/runtime/` ⇒ red."""
        for path in ("engine/tools/broctl.py", "engine/config/protected-control-plane.json",
                     "engine/requirements-ci.txt", "engine/.bro/policy.json",
                     "engine/laws/registry.json", "engine/ci/live/run_live_turn.sh",
                     "engine/.claude/settings.json", "engine/schemas/a/b/deep.json"):
            with self.subTest(path=path):
                self.red(Fake(files=changed(path)), path, "neither")

    def test_only_engine_tests_changed_is_not_required(self):
        """`tests/**` is a protected root and is excluded by name: a test is not security
        code. Mutant: derive the globs from EVERY protected root ⇒ red."""
        files = changed("engine/tests/test_bro_security.py", "engine/tests/fixtures/a.json")
        self.green(Fake(files=files), "not required (no engine security path changed)")

    def test_a_file_renamed_out_of_the_perimeter_counts_under_its_old_name(self):
        """Moving `engine/runtime/x.py` to `docs/` deletes security code. Mutant: read
        only `filename` ⇒ green."""
        files = [{"filename": "docs/old_wall.py", "previous_filename": RUNTIME}]
        self.red(Fake(files=files), RUNTIME, "neither")

    def test_case_does_not_move_a_path_out_of_the_perimeter(self):
        """Mutant: match case-sensitively ⇒ green."""
        self.red(Fake(files=changed("engine/Runtime/BRO_Security.py")), "neither")

    # --- Architect-Audit ---------------------------------------------------------------

    def test_a_cited_audit_that_exists_at_the_head_is_green(self):
        """The positive control for the four REDs after it."""
        for path in (REPORT, "engine/AUDIT/2026-10-03-wall.md"):
            with self.subTest(path=path):
                inputs = Fake(self.cited(path), files=changed(RUNTIME),
                              tree={path: "# Architect audit\n\nVerdict: GREEN.\n"})
                self.green(inputs, f"Architect-Audit {path}")
                self.assertIn((HEAD, path), inputs.asked,
                              "the report was not read AT the head that will merge")
                self.assertEqual(inputs.blobs, [(HEAD, path)],
                                 "the report was not read as a FILE: `git show H:dir` "
                                 "prints a directory's listing, and that is not empty")

    def test_a_cited_audit_that_does_not_exist_at_the_head_is_red(self):
        """Mutant: accept the line without reading the file ⇒ green."""
        self.red(Fake(self.cited(), files=changed(RUNTIME)),
                 f"`Architect-Audit: {REPORT}` does not exist at", "does not exist in")

    def test_a_cited_audit_outside_the_two_AUDIT_directories_is_red(self):
        """Every path here EXISTS at the head and is not empty, so only where it lives
        refuses it. Mutant: drop the directory rule ⇒ green."""
        for path in ("docs/architect-audit.md", "AUDIT/report.md", "apps/desktop/AUDITS/a.md",
                     "engine/AUDIT", "/apps/desktop/AUDIT/a.md", "./engine/AUDIT/a.md",
                     "apps/desktop/AUDIT/../../../tools/check_merge_ready.py",
                     "apps/desktop/AUDIT/", "engine/AUDIT//a.md", "engine\\AUDIT\\a.md",
                     "`apps/desktop/AUDIT/a.md`"):
            with self.subTest(path=path):
                inputs = Fake(self.cited(path), files=changed(RUNTIME),
                              tree={path: "# a report\n", path.strip("`"): "# a report\n"})
                self.red(inputs, "is not a file under apps/desktop/AUDIT/ or engine/AUDIT/")

    def test_an_empty_cited_audit_is_red(self):
        """Mutant: drop the emptiness rule ⇒ green on a file created to satisfy the gate."""
        for text in ("", "\n", "   \n\t\n"):
            with self.subTest(text=text):
                self.red(Fake(self.cited(), files=changed(RUNTIME), tree={REPORT: text}),
                         f"`Architect-Audit: {REPORT}` is empty at")

    def test_an_audit_line_that_names_no_path_is_red(self):
        view = green_view()
        view["body"] = "Tightens the wall.\nArchitect-Audit:\n"
        self.red(Fake(view, files=changed(RUNTIME)), "names no path")

    # --- Owner-Waiver ------------------------------------------------------------------

    def test_a_waiver_on_the_row_that_names_this_pull_request_is_green(self):
        """The positive control, and the proof the roadmap is read AT THE HEAD: the fake
        row carries a date and a number this checkout's roadmap does not. Mutant: read
        ROOT/MASTER_EXECUTION_ROADMAP.md ⇒ red."""
        text = roadmap(f"**OWNER WAIVER {WAIVED}, scoped:** `#4` and `#5` had no audit.")
        inputs = Fake(waived_view(), files=changed(RUNTIME), tree={ROADMAP: text})
        self.green(inputs, f"Owner-Waiver {WAIVED} (roadmap §G.2 names #5)")
        self.assertIn((HEAD, ROADMAP), inputs.asked)

    def test_a_waiver_whose_date_is_not_on_the_row_is_red(self):
        """Three dates the fixture carries with `#5` beside each: on ANOTHER row of §G.2,
        and on a row with the same first cell in the section before and the section after.
        Mutant: search the whole section ⇒ green. Mutant: drop either bound of the section,
        or look for the row's words in any cell ⇒ two rows answer, and the control above
        goes red."""
        text = roadmap(f"**OWNER WAIVER {WAIVED}, scoped:** `#5` had no audit.")
        for line in ("Owner-Waiver: 2027-03-03", "Owner-Waiver: 2027-04-04",
                     "Owner-Waiver: 2027-05-05", "Owner-Waiver: 2027-01-02"):
            with self.subTest(line=line):
                self.red(Fake(waived_view(line), files=changed(RUNTIME), tree={ROADMAP: text}),
                         "carries no `OWNER WAIVER 2027-", f"waivers on the row: {WAIVED}")

    def test_a_row_with_no_waiver_at_all_is_red(self):
        """Mutant: accept the line on the Builder's word ⇒ green. This is the whole
        point: a waiver is something on the roadmap, not something in a body."""
        inputs = Fake(waived_view(), files=changed(RUNTIME), tree={ROADMAP: roadmap("")})
        self.red(inputs, f"carries no `OWNER WAIVER {WAIVED}`", "waivers on the row: none")

    def test_a_waiver_that_does_not_name_this_pull_request_is_red(self):
        """Each waiver names something that CONTAINS `#5`, or a 5, and is not pull request
        5. Mutant: drop the look-ahead ⇒ green on the first. Mutant: drop the look-behind
        ⇒ green on the second. Mutant: drop the naming rule ⇒ green on all three."""
        for named in ("`#50` and `#555`", "another/repo#5", "`#4`, `#15` and `T-5`"):
            with self.subTest(named=named):
                text = roadmap(f"**OWNER WAIVER {WAIVED}, scoped:** {named} had no audit.")
                self.red(Fake(waived_view(), files=changed(RUNTIME), tree={ROADMAP: text}),
                         "does not name `#5`", "a waiver for other pull requests")

    def test_a_pull_request_named_under_another_waivers_date_is_red(self):
        """Two waivers on one row. `#5` is under the second; the body cites the first.
        Mutant: look for `#N` anywhere on the row ⇒ green."""
        text = roadmap(f"**OWNER WAIVER {WAIVED}:** `#4` had no audit. "
                       f"**OWNER WAIVER 2027-02-02:** `#5` had none either.")
        self.red(Fake(waived_view(), files=changed(RUNTIME), tree={ROADMAP: text}),
                 "does not name `#5`")
        self.green(Fake(waived_view("Owner-Waiver: 2027-02-02"), files=changed(RUNTIME),
                        tree={ROADMAP: text}),
                   "Owner-Waiver 2027-02-02 (roadmap §G.2 names #5)")

    def test_an_undated_waiver_ends_the_dated_one_before_it(self):
        """Mutant: end a waiver's text only at the next DATED one ⇒ green: `#5` would be
        waived by a date written for `#4`."""
        text = roadmap(f"**OWNER WAIVER {WAIVED}:** `#4` had no audit. "
                       f"**OWNER WAIVER, date pending:** `#5`.")
        self.red(Fake(waived_view(), files=changed(RUNTIME), tree={ROADMAP: text}),
                 "does not name `#5`")

    def test_a_waiver_line_that_is_not_a_date_is_red(self):
        """`20270101` is a date to `fromisoformat` and not to the row; `2027-13-45` has the
        shape and is no day. Mutant: drop the shape ⇒ red on the first. Mutant: drop the
        calendar ⇒ red on the second. Either way a different RED: the reader is told the
        row lacks a waiver when the line was never a date."""
        text = roadmap(f"**OWNER WAIVER {WAIVED}:** `#5` had no audit.")
        for value in ("20270101", "2027-13-45", "", "yes", "2027-1-1",
                      f"{WAIVED} by the Owner", "01-01-2027"):
            with self.subTest(value=value):
                self.red(Fake(waived_view(f"Owner-Waiver: {value}"), files=changed(RUNTIME),
                              tree={ROADMAP: text}), "is not a date")

    def test_a_roadmap_that_cannot_be_read_at_the_head_is_red(self):
        """Mutant: treat an unreadable roadmap as 'no objection' ⇒ green."""
        inputs = Fake(waived_view(), files=changed(RUNTIME),
                      tree={ROADMAP: GateError("commit a1b2c3d4e5f6 is not in this clone")})
        self.red(inputs, f"{ROADMAP} at", "could not be read", "not in this clone")

    def test_a_roadmap_without_the_row_is_red(self):
        """No such row, no §G.2 at all, and TWO rows. Mutant: take the first row found ⇒
        green on the last, where the Owner's row has a twin somebody added below it."""
        row = f"| Any `engine/` security code | OWNER WAIVER {WAIVED} `#5` |\n"
        head = "# Roadmap\n\n### G.2 Task-class overrides\n| Task class | Rule |\n|---|---|\n"
        for text in (head + f"| UI/copy | OWNER WAIVER {WAIVED} `#5` |\n\n## H\n",
                     "# Roadmap\n\n### G.1 Ownership\n| Task class | Rule |\n|---|---|\n" + row,
                     head + "| Any `engine/` security code | Never rushed. |\n" + row):
            with self.subTest(text=text):
                self.red(Fake(waived_view(), files=changed(RUNTIME), tree={ROADMAP: text}),
                         "has no single §G.2 row")

    # --- one declaration, and only at the start of a line ------------------------------

    def test_both_lines_are_red(self):
        """Each line on its own would pass here. Mutant: take the first declaration found
        ⇒ green."""
        text = roadmap(f"**OWNER WAIVER {WAIVED}:** `#5` had no audit.")
        tree = {ROADMAP: text, REPORT: "# Architect audit\n"}
        both = green_view()
        both["body"] = f"Architect-Audit: {REPORT}\nOwner-Waiver: {WAIVED}\n"
        self.red(Fake(both, files=changed(RUNTIME), tree=tree),
                 "1 `Architect-Audit:` and 1 `Owner-Waiver:` line(s)", "ambiguous")
        for line in (f"Architect-Audit: {REPORT}", f"Owner-Waiver: {WAIVED}"):
            with self.subTest(twice=line):
                twice = green_view()
                twice["body"] = f"{line}\nprose\n{line}\n"
                self.red(Fake(twice, files=changed(RUNTIME), tree=tree), "ambiguous")

    def test_a_key_that_does_not_begin_a_line_is_not_a_declaration(self):
        """Every body here would be GREEN if the key counted where it stands. Mutant:
        search for the key anywhere in the line, or ignore case ⇒ green."""
        text = roadmap(f"**OWNER WAIVER {WAIVED}:** `#5` had no audit.")
        tree = {ROADMAP: text, REPORT: "# Architect audit\n"}
        for line in (f"See Architect-Audit: {REPORT}", f"  Architect-Audit: {REPORT}",
                     f"> Architect-Audit: {REPORT}", f"`Architect-Audit: {REPORT}`",
                     f"architect-audit: {REPORT}", f"ARCHITECT-AUDIT: {REPORT}",
                     f"Architect-Audit {REPORT}", f"- Owner-Waiver: {WAIVED}",
                     f"The Owner-Waiver: {WAIVED} is on the row", f"owner-waiver: {WAIVED}",
                     f"\tOwner-Waiver: {WAIVED}"):
            with self.subTest(line=line):
                view = green_view()
                view["body"] = f"Tightens the wall.\n{line}\n"
                self.red(Fake(view, files=changed(RUNTIME), tree=tree), "neither")

    def test_prose_about_the_other_key_does_not_make_a_declaration_ambiguous(self):
        view = green_view()
        view["body"] = (f"No Owner-Waiver: line here, this one was audited.\r\n\r\n"
                        f"Architect-Audit: {REPORT}\r\n")
        self.green(Fake(view, files=changed(RUNTIME), tree={REPORT: "# Architect audit\n"}),
                   f"Architect-Audit {REPORT}")

    # --- inputs that cannot be read ----------------------------------------------------

    def test_an_unreadable_file_list_is_red(self):
        """On a pull request whose body would otherwise be irrelevant. Mutant: treat a
        failed or shapeless list as 'no engine path' ⇒ green."""
        self.red(Fake(files=GateError("`gh api --paginate ...` exited 1: HTTP 502")),
                 "could not be read", "HTTP 502")
        for value in ([], 7, None, "engine/runtime/x.py", {"filename": "a"}, ["a.py"],
                      [{"path": "a.py"}], [{"filename": ""}], [{"filename": None}]):
            with self.subTest(files=value):
                inputs = Fake()
                inputs.files = value
                self.red(inputs, "unreadable or empty")

    def test_a_file_list_shorter_than_GitHub_says_is_red(self):
        """A list cut at a page boundary. #314 changed 569 files, and its 61 engine paths
        were not all in the first hundred. Mutant: drop the count comparison ⇒ green."""
        for claimed in (2, 569, 0, None, "1", True):
            with self.subTest(claimed=claimed):
                view = green_view()
                inputs = Fake(view)
                view["changedFiles"] = claimed
                self.red(inputs, "the list is incomplete")
        view = green_view()
        inputs = Fake(view)
        del view["changedFiles"]
        self.red(inputs, "the list is incomplete")

    def test_an_unreadable_body_is_red_when_a_declaration_is_needed(self):
        """Mutant: drop the body check ⇒ the gate crashes on a body that is not text, and
        the reader is told the gate is broken instead of what it could not read."""
        for value in (None, 7, ["Architect-Audit: x"]):
            with self.subTest(body=value):
                view = green_view()
                view["body"] = value
                self.red(Fake(view, files=changed(RUNTIME)), "its body could not be read")

    def test_an_unreadable_rule_is_red(self):
        """Mutant: fall back to an empty glob list ⇒ green, every change exempt."""
        self.red(Fake(files=changed(RUNTIME), rule=GateError("audit-required-paths.json "
                                                             "could not be read: gone")),
                 "the audit rule could not be read", "gone")
        for globs in ([], None, "engine/runtime/**", [""], [7]):
            with self.subTest(globs=globs):
                self.red(Fake(files=changed(RUNTIME), rule={"globs": globs, "not_covered": []}),
                         "the audit rule could not be read", "non-empty list")

    # --- --explain-audit ----------------------------------------------------------------

    def merged(self, body: str) -> dict:
        """A pull request nothing about which is mergeable, except possibly its audit."""
        view = green_view()
        view.update(state="MERGED", mergeStateStatus="UNKNOWN", body=body)
        view["statusCheckRollup"] = [run("engine", conclusion="FAILURE")]
        return view

    def test_explain_audit_judges_a_MERGED_pull_request_on_the_audit_check_alone(self):
        """Mutant: route --explain-audit through the whole gate ⇒ 'not OPEN', which says
        nothing about the audit."""
        inputs = Fake(self.merged("no declaration\n"), files=changed(RUNTIME))
        code, out = gate(inputs, "--explain-audit")
        self.assertEqual(code, 1, out)
        self.assertTrue(out.startswith("RED: pull request #5 does NOT meet the audit rule"), out)
        self.assertIn(RUNTIME, out)
        self.assertIn("     -> get an Architect audit and cite it", out)
        self.assertNotIn("not OPEN", out)
        self.assertNotIn("did not pass", out)
        self.assertNotIn("gh pr merge", out)

    def test_explain_audit_green_is_not_a_merge_command(self):
        """Exit 0 on the audit alone, with a failed check and no merge state beside it --
        and no command, because GREEN here is not permission. Mutant: print the command
        ⇒ red."""
        inputs = Fake(self.merged(f"Architect-Audit: {REPORT}\n"), files=changed(RUNTIME),
                      tree={REPORT: "# Architect audit\n"})
        code, out = gate(inputs, "--explain-audit")
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("GREEN: pull request #5 meets the audit rule"), out)
        self.assertIn(f"  audit  : Architect-Audit {REPORT}\n", out)
        self.assertIn("  state  : MERGED\n", out)
        self.assertIn("NOT permission to merge", out)
        self.assertNotIn("gh pr merge", out)
        self.assertEqual(inputs.asked, [(HEAD, REPORT)], "it read more than the audit check")

    def test_without_the_flag_a_MERGED_pull_request_stays_red(self):
        """The flag must not have opened a second way to GREEN. Mutant: let the audit
        verdict stand in for the gate ⇒ green on a merged pull request."""
        inputs = Fake(self.merged(f"Architect-Audit: {REPORT}\n"), files=changed(RUNTIME),
                      tree={REPORT: "# Architect audit\n"})
        self.red(inputs, "is MERGED, not OPEN")

    def test_explain_audit_says_not_required_when_nothing_in_the_perimeter_changed(self):
        code, out = gate(Fake(self.merged("")), "--explain-audit")
        self.assertEqual(code, 0, out)
        self.assertIn("  audit  : not required (no engine security path changed)\n", out)

    def test_explain_audit_is_red_on_what_it_cannot_read(self):
        """A GitHub that did not answer is a reason with a remedy; anything else is the
        gate's own failure, said as such. Mutant: drop the inner except ⇒ the 401 is
        reported as a broken gate. Mutant: narrow the outer one ⇒ a traceback."""
        for view, needles in (
                (GateError("HTTP 401: Bad credentials"),
                 ("could not be read from GitHub: HTTP 401", "check `gh auth status`")),
                (RuntimeError("the unexpected"), ("RuntimeError", "the gate itself failed"))):
            with self.subTest(view=view):
                code, out = gate(Fake(view), "--explain-audit")
                self.assertEqual(code, 1, out)
                self.assertTrue(out.startswith("RED:"), out)
                for needle in needles:
                    self.assertIn(needle, out)
                self.assertNotIn("Traceback", out)

    def test_explain_audit_reads_nothing_at_a_head_GitHub_did_not_name(self):
        """Mutant: run the audit check with no head ⇒ a report is 'read' at None."""
        view = self.merged(f"Architect-Audit: {REPORT}\n")
        view["headRefOid"] = None
        inputs = Fake(view, files=changed(RUNTIME), tree={REPORT: "# Architect audit\n"})
        code, out = gate(inputs, "--explain-audit")
        self.assertEqual(code, 1, out)
        self.assertIn("did not name a head commit", out)
        self.assertEqual(inputs.asked, [])


#: The roots of the engine's perimeter this gate deliberately does not ask an audit for.
#: Pinned HERE as well as in the config, so that excluding one more is an edit to a test
#: that names it and not only a line of JSON with a plausible reason.
EXCLUDED_BY_NAME = {"tests/**", ".git/**", "**/.env", "**/*secret*", "**/*credential*",
                    "**/*private-key*"}


class ThePathListIsTheEnginesOwn(unittest.TestCase):
    """`config/audit-required-paths.json` against `engine/config/protected-control-plane.json`.

    The first is derived from the second. These fail when the derivation stops being true.
    """

    def setUp(self):
        self.rule = json.loads((ROOT / check_merge_ready.AUDIT_PATHS_REL)
                               .read_text(encoding="utf-8"))
        self.manifest = json.loads((ROOT / check_merge_ready.PERIMETER_REL)
                                   .read_text(encoding="utf-8"))

    def drift(self, rule=None, manifest=None) -> list[str]:
        return check_merge_ready.perimeter_drift(self.rule if rule is None else rule,
                                                 self.manifest if manifest is None else manifest)

    def test_the_declared_globs_account_for_every_protected_root(self):
        """THE DRIFT GUARD, on the files as committed. It fails the day the engine's
        manifest gains or loses a root this config neither lists nor excludes."""
        self.assertEqual(self.drift(), [])

    def test_the_globs_are_the_protected_roots_minus_the_named_exclusions(self):
        """The derivation, recomputed. Mutant: hand-edit one glob ⇒ red."""
        derived = [f"engine/{root}" for root in self.manifest["protected_roots"]
                   if root not in EXCLUDED_BY_NAME]
        self.assertEqual(self.rule["globs"], derived)

    def test_a_root_the_manifest_GAINS_is_drift(self):
        """Mutant: drop the unaccounted-root arm of perimeter_drift ⇒ green."""
        grown = copy.deepcopy(self.manifest)
        grown["protected_roots"].append("deploy/**")
        problems = self.drift(manifest=grown)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("`deploy/**` is neither listed", problems[0])

    def test_a_root_the_manifest_LOSES_is_drift(self):
        """A listed root and an excluded one. Mutant: drop either stale-line arm ⇒ green."""
        for gone, needle in (("laws/**", "glob `engine/laws/**` is not a protected root"),
                             ("tests/**", "`tests/**` is excluded and is not a protected")):
            with self.subTest(gone=gone):
                shrunk = copy.deepcopy(self.manifest)
                shrunk["protected_roots"].remove(gone)
                problems = self.drift(manifest=shrunk)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(needle, problems[0])

    def test_a_glob_dropped_from_the_config_is_drift(self):
        """The edit that would quietly exempt the wall. Mutant: as for a gained root."""
        rule = copy.deepcopy(self.rule)
        rule["globs"].remove("engine/runtime/**")
        self.assertTrue(any("`runtime/**` is neither listed" in p for p in self.drift(rule)))

    def test_an_exclusion_needs_a_reason_and_cannot_also_be_listed(self):
        """Mutant: drop the reason arm, or the both-listed arm ⇒ green."""
        rule = copy.deepcopy(self.rule)
        for entry in rule["not_covered"]:
            if entry.get("protected_root") == "tests/**":
                entry["reason"] = "  "
        self.assertTrue(any("`tests/**` is excluded with no reason" in p
                            for p in self.drift(rule)))
        rule = copy.deepcopy(self.rule)
        rule["globs"].append("engine/tests/**")
        self.assertTrue(any("`tests/**` is both listed and excluded" in p
                            for p in self.drift(rule)))

    def test_a_glob_that_is_not_under_engine_is_drift(self):
        """`globs` is DERIVED. A path somebody typed in is a second list, and it would
        belong in a field of its own. Mutant: drop the prefix arm ⇒ green."""
        rule = copy.deepcopy(self.rule)
        rule["globs"].append("apps/desktop/src-tauri/broker/**")
        self.assertTrue(any("was not derived" in p for p in self.drift(rule)))

    def test_an_unreadable_manifest_is_drift_not_agreement(self):
        for manifest in ({}, {"protected_roots": []}, {"protected_roots": "runtime/**"},
                         {"protected_roots": [""]}):
            with self.subTest(manifest=manifest):
                self.assertTrue(any("no readable `protected_roots`" in p
                                    for p in self.drift(manifest=manifest)))

    def test_the_gate_refuses_to_run_on_a_drifted_rule(self):
        """`Inputs.audit_rule` is where drift becomes RED at merge time and not only in
        this suite. Mutant: return the rule without comparing ⇒ no GateError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "config").mkdir()
            (root / "engine" / "config").mkdir(parents=True)
            grown = copy.deepcopy(self.manifest)
            grown["protected_roots"].append("deploy/**")
            (root / check_merge_ready.AUDIT_PATHS_REL).write_text(json.dumps(self.rule),
                                                                 encoding="utf-8")
            (root / check_merge_ready.PERIMETER_REL).write_text(json.dumps(grown),
                                                               encoding="utf-8")
            with self.assertRaises(GateError) as caught:
                check_merge_ready.Inputs(root).audit_rule()
            self.assertIn("deploy/**", str(caught.exception))
            (root / check_merge_ready.PERIMETER_REL).write_text(json.dumps(self.manifest),
                                                               encoding="utf-8")
            self.assertEqual(check_merge_ready.Inputs(root).audit_rule(), self.rule)

    def test_a_config_that_cannot_be_read_is_a_GateError(self):
        """Missing, not JSON, not an object, and no `not_covered` list. Mutant: answer {}
        or [] for any of them ⇒ no GateError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "config").mkdir()
            (root / "engine" / "config").mkdir(parents=True)
            rule_path = root / check_merge_ready.AUDIT_PATHS_REL
            (root / check_merge_ready.PERIMETER_REL).write_text(json.dumps(self.manifest),
                                                               encoding="utf-8")
            inputs = check_merge_ready.Inputs(root)
            with self.assertRaises(GateError) as caught:
                inputs.audit_rule()
            self.assertIn("could not be read", str(caught.exception))
            for text, needle in (("{not json", "could not be read"), ("[]", "not an object"),
                                 (json.dumps({"globs": self.rule["globs"]}), "`not_covered`")):
                with self.subTest(text=text[:20]):
                    rule_path.write_text(text, encoding="utf-8")
                    with self.assertRaises(GateError) as caught:
                        inputs.audit_rule()
                    self.assertIn(needle, str(caught.exception))

    def test_the_matcher_is_the_engines_own(self):
        """`engine/runtime/bro_workspace.py::matches_pattern`, restated as cases: `*`
        crosses `/`, an exact file is itself, a bare directory covers what is under it,
        and a prefix is not a match. Mutant: drop the bare-directory arm, the separator
        fold or the case fold ⇒ red, each on its own path."""
        needs = check_merge_ready.needs_audit
        globs = ["engine/runtime/**", "engine/requirements-ci.txt", "engine/laws",
                 "Engine\\Schemas\\**"]
        for path in ("engine/runtime/a.py", "engine/runtime/a/b/c.py",
                     "engine/requirements-ci.txt", "engine/laws/L5.md",
                     "engine\\runtime\\a.py", "ENGINE/RUNTIME/A.PY", "engine/schemas/x.json"):
            with self.subTest(path=path):
                self.assertTrue(needs(path, globs))
        for path in ("engine/runtime", "engine/runtime_old/a.py",
                     "engine/requirements-ci.txt.bak", "engine/lawsuit.md", "runtime/a.py",
                     "apps/engine/runtime/a.py", "engine/tests/a.py"):
            with self.subTest(path=path):
                self.assertFalse(needs(path, globs))

    def test_only_the_roots_named_here_are_excluded(self):
        """Mutant: move `runtime/**` under `not_covered` with a reason ⇒ the drift guard
        stays green, and this is what goes red."""
        self.assertEqual(set(check_merge_ready.excluded_roots(self.rule)), EXCLUDED_BY_NAME)

    def test_the_purpose_quotes_the_row_the_roadmap_actually_carries(self):
        """Mutant: reword the roadmap's first cell ⇒ red here, before a waiver is refused
        for want of a row."""
        text = (ROOT / ROADMAP).read_text(encoding="utf-8")
        row = check_merge_ready.g2_engine_row(text)
        self.assertIsNotNone(row, "this checkout's roadmap has no single §G.2 engine row")
        cells = [cell.strip() for cell in row.split("|")]
        self.assertIn(cells[1], self.rule["purpose"])
        self.assertIn("Never rushed, never parallelized (§E serialization rule).",
                      self.rule["purpose"])
        self.assertIn("Never rushed, never parallelized (§E serialization rule).", row)

    def test_what_is_not_covered_says_so(self):
        """The second row of §G.2 carries the same audit and no path. A gate that did not
        say so would read as covering it."""
        said = " ".join(f"{e.get('what', '')} {e.get('reason', '')}"
                        for e in self.rule["not_covered"])
        for needle in ("Trust-boundary / key / secret handling", "apps/desktop/src-tauri",
                       "NOT covered", "Tests are not security code"):
            self.assertIn(needle, said)
        for entry in self.rule["not_covered"]:
            self.assertTrue(str(entry.get("what") or "").strip(), entry)
            self.assertTrue(str(entry.get("reason") or "").strip(), entry)


class TheRealInputs(unittest.TestCase):
    """`Inputs` itself, against programs and a repository that exist."""

    def test_a_program_that_fails_is_a_GateError_carrying_its_own_words(self):
        with self.assertRaises(GateError) as caught:
            check_merge_ready._run([sys.executable, "-c",
                                    "import sys; sys.stderr.write('HTTP 502\\n'); sys.exit(3)"],
                                   cwd=ROOT)
        self.assertIn("exited 3", str(caught.exception))
        self.assertIn("HTTP 502", str(caught.exception))

    def test_a_program_that_does_not_exist_is_a_GateError(self):
        with self.assertRaises(GateError):
            check_merge_ready._run(["definitely-not-a-program-t150"], cwd=ROOT)

    def test_a_program_that_hangs_is_a_GateError(self):
        with self.assertRaises(GateError) as caught:
            check_merge_ready._run([sys.executable, "-c", "import time; time.sleep(30)"],
                                   cwd=ROOT, timeout=1)
        self.assertIn("did not answer", str(caught.exception))

    def test_the_view_asks_for_every_field_the_gate_decides_on(self):
        for field in ("state", "headRefOid", "baseRefName", "mergeStateStatus",
                      "statusCheckRollup", "body", "changedFiles"):
            self.assertIn(field, check_merge_ready.VIEW_FIELDS.split(","))

    def test_the_file_list_is_parsed_one_object_per_line(self):
        """What `gh api --paginate --jq` prints: pages run together as LINES. Mutant:
        `json.loads` the whole output ⇒ a GateError on every pull request over one file."""
        raw = ('{"filename":"engine/runtime/a.py","previous_filename":null}\n'
               '{"filename":"docs/b.md","previous_filename":"engine/tools/b.py"}\n\n')
        self.assertEqual(check_merge_ready.parse_file_lines(raw),
                         [{"filename": "engine/runtime/a.py", "previous_filename": None},
                          {"filename": "docs/b.md", "previous_filename": "engine/tools/b.py"}])
        self.assertEqual(check_merge_ready.parse_file_lines(""), [])
        with self.assertRaises(GateError) as caught:
            check_merge_ready.parse_file_lines('{"filename":"a"}\n<html>502</html>\n')
        self.assertIn("line 2", str(caught.exception))

    def test_the_file_list_asks_GitHub_for_every_page(self):
        """`gh pr view --json files` stops at 100. Mutant: drop --paginate ⇒ red."""
        seen: list[list[str]] = []
        real = check_merge_ready._run

        def spy(args, *, cwd, timeout=40):
            seen.append(list(args))
            return '{"filename":"a.py","previous_filename":null}\n'

        check_merge_ready._run = spy
        try:
            listed = check_merge_ready.Inputs(ROOT, "menqstudio/OS").changed_files(314)
        finally:
            check_merge_ready._run = real
        self.assertEqual(listed, [{"filename": "a.py", "previous_filename": None}])
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][:3], ["gh", "api", "--paginate"])
        self.assertIn("repos/menqstudio/OS/pulls/314/files?per_page=100", seen[0])
        check_merge_ready._run = spy
        try:
            check_merge_ready.Inputs(ROOT).changed_files(7)
        finally:
            check_merge_ready._run = real
        self.assertIn("repos/{owner}/{repo}/pulls/7/files?per_page=100", seen[1],
                      "with no --repo, gh fills the placeholders from this clone's origin")

    def _repo(self, tmp: pathlib.Path) -> tuple[pathlib.Path, str, str]:
        def git(*args: str) -> str:
            return subprocess.run(
                ["git", "-C", str(tmp), "-c", "user.name=t", "-c", "user.email=t@t",
                 "-c", "commit.gpgsign=false", *args],
                check=True, capture_output=True, text=True).stdout.strip()

        git("init", "-q")
        (tmp / "PROJECT_STATE.md").write_text(state(D1), encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", "yesterday")
        first = git("rev-parse", "HEAD")
        (tmp / "PROJECT_STATE.md").write_text(state(D2), encoding="utf-8")
        git("commit", "-qam", "today")
        return tmp, first, git("rev-parse", "HEAD")

    def test_file_at_reads_the_file_AS_IT_IS_AT_the_named_commit(self):
        """Mutant: read the working tree ⇒ both commits return today's line."""
        with tempfile.TemporaryDirectory() as tmp:
            root, first, second = self._repo(pathlib.Path(tmp))
            inputs = check_merge_ready.Inputs(root)
            self.assertIn(str(D1), inputs.file_at(first, "PROJECT_STATE.md", 5))
            self.assertIn(str(D2), inputs.file_at(second, "PROJECT_STATE.md", 5))

    def test_blob_at_refuses_a_directory_and_a_path_that_is_not_there(self):
        """`git show H:dir` exits 0 and prints a listing -- a non-empty 'report'. Mutant:
        read the citation with file_at ⇒ the directory is returned as text."""
        with tempfile.TemporaryDirectory() as tmp:
            root, _, second = self._repo(pathlib.Path(tmp))
            audit = root / "engine" / "AUDIT"
            (audit / "tickets").mkdir(parents=True)
            # Bytes, not text: `write_text` would make these CRLF on the Windows runner.
            (audit / "tickets" / "T-1.md").write_bytes(b"a ticket\n")
            (audit / "report.md").write_bytes(b"# the audit\n")
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c",
                            "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-qm",
                            "audit"], check=True)
            third = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                                   capture_output=True, text=True).stdout.strip()
            inputs = check_merge_ready.Inputs(root)
            self.assertEqual(inputs.blob_at(third, "engine/AUDIT/report.md", 5), "# the audit\n")
            self.assertIn("T-1.md", inputs.file_at(third, "engine/AUDIT/tickets", 5),
                          "the premise: file_at returns a directory's listing")
            with self.assertRaises(GateError) as caught:
                inputs.blob_at(third, "engine/AUDIT/tickets", 5)
            self.assertIn("not a file", str(caught.exception))
            with self.assertRaises(GateError):
                inputs.blob_at(third, "engine/AUDIT/absent.md", 5)
            with self.assertRaises(GateError):
                inputs.blob_at(second, "engine/AUDIT/report.md", 5)
            with self.assertRaises(GateError) as caught:
                inputs.blob_at("f" * 40, "engine/AUDIT/report.md", 5)
            self.assertIn("could not be fetched", str(caught.exception),
                          "a head this clone lacks must be FETCHED before it is read")

    def test_a_commit_this_clone_does_not_have_and_cannot_fetch_is_a_GateError(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _, _ = self._repo(pathlib.Path(tmp))
            with self.assertRaises(GateError) as caught:
                check_merge_ready.Inputs(root).file_at("f" * 40, "PROJECT_STATE.md", 5)
            self.assertIn("could not be fetched", str(caught.exception))

    def test_the_parser_is_the_one_the_gate_on_main_uses(self):
        """One parser, not a copy: if the two ever disagreed about what the line says,
        this gate would pass a head `check_coordination` then refuses on `main`."""
        import check_coordination
        claimed, problem = check_coordination._claimed_last_updated(state(D2))
        self.assertEqual((claimed, problem), (D2, None))


if __name__ == "__main__":
    unittest.main()
