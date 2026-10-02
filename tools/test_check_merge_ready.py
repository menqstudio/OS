"""Tests for the merge-readiness gate.

Every input the gate reads comes through `check_merge_ready.Inputs`, so `Fake` below
replaces GitHub, git and the clock, and nothing here touches a network. Each RED cause is
produced ON ITS OWN -- one problem, the others satisfied -- because a test that breaks two
things at once passes whichever check is deleted. Two tests at the bottom drive the REAL
`Inputs` against a repository on disk, since a fake proves nothing about `git show`.

Every test names the mutation that turns it red. `unittest.main()` is the last statement
(ninth audit `I-05`).
"""
from __future__ import annotations

import contextlib
import datetime
import io
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
            "mergeStateStatus": "CLEAN",
            "statusCheckRollup": [run("frontend"), run("engine"), run("coordination")]}


class Fake(check_merge_ready.Inputs):
    """GitHub, git and the clock, all answering from memory.

    The defaults are the night of #314: 00:05 here, 20:05 the day before in UTC. A line
    dated D2 is right in both zones; one dated D1 is right in UTC and wrong here.
    """

    def __init__(self, view=None, *, at_head=None, at_base=None, local=D2, utc=D1,
                 repo=None) -> None:
        super().__init__(ROOT, repo)
        self.view = green_view() if view is None else view
        self.at_head = state(D2) if at_head is None else at_head
        self.at_base = state(D1, "what main said yesterday") if at_base is None else at_base
        self.local, self.utc = local, utc
        self.asked: list[tuple] = []

    def pr_view(self, pr):
        if isinstance(self.view, BaseException):
            raise self.view
        return self.view

    def file_at(self, sha, rel, pr):
        self.asked.append((sha, rel))
        if isinstance(self.at_head, BaseException):
            raise self.at_head
        return self.at_head

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


class MergeReady(unittest.TestCase):
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
                      "statusCheckRollup"):
            self.assertIn(field, check_merge_ready.VIEW_FIELDS.split(","))

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
