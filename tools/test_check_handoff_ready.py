"""Tests for the handoff-readiness gate.

Each test builds a real git repository with a real upstream, because the thing under
test is whether a NEW session could clone this and continue — and a fixture that fakes
git proves nothing about that. The upstream is a bare repo on disk; nothing here
touches a network.

Every test names the mutation that turns it red. `unittest.main()` is the last
statement (ninth audit `I-05`).
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_handoff_ready


def git(cwd: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


def build_repo(tmp: pathlib.Path) -> pathlib.Path:
    """A repository that is ready to hand over: committed, pushed, in budget, and
    whose NEXT_CHAT.md names the branch, the head and a next action."""
    origin = tmp / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True)
    work = tmp / "work"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
    git(work, "config", "user.name", "Test")
    git(work, "config", "user.email", "test@example.invalid")

    (work / "config").mkdir(parents=True, exist_ok=True)
    (work / "NEXT_CHAT.md").write_text("placeholder\n", encoding="utf-8")
    (work / "config" / "canonical-read-manifest.json").write_text(
        json.dumps({"paths": ["NEXT_CHAT.md"]}), encoding="utf-8")
    (work / "config" / "canon-budget.json").write_text(json.dumps({
        "per_file_bytes": {"NEXT_CHAT.md": 10_000},
        "total_bytes_max": 10_000, "max_shared_fraction": 0.2}), encoding="utf-8")
    (work / "config" / "current_state.json").write_text(
        json.dumps({"settled_at_main_head": "0" * 40}), encoding="utf-8")

    git(work, "add", "-A")
    git(work, "commit", "-qm", "first")
    git(work, "push", "-q", "-u", "origin", "HEAD")

    # Now that a commit exists, write the handoff that names it, and push again.
    head = subprocess.run(["git", "-C", str(work), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    branch = subprocess.run(["git", "-C", str(work), "rev-parse", "--abbrev-ref", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    settle(work, head, branch)
    return work


def head_of(work: pathlib.Path) -> str:
    return subprocess.run(["git", "-C", str(work), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def branch_of(work: pathlib.Path) -> str:
    return subprocess.run(["git", "-C", str(work), "rev-parse", "--abbrev-ref", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def write_handoff(work: pathlib.Path, *, head: str, branch: str, next_action: bool = True) -> None:
    """Write the handoff naming `head`. Called BEFORE committing, so the head it names
    becomes HEAD^ once the commit lands — which is what the gate accepts, because a
    document cannot contain its own hash."""
    body = f"# NEXT_CHAT\n\nBranch `{branch}` settled at `{head[:7]}`.\n"
    if next_action:
        body += "\n**Next:** continue with the thing after this one.\n"
    (work / "NEXT_CHAT.md").write_text(body, encoding="utf-8")
    (work / "config" / "current_state.json").write_text(
        json.dumps({"settled_at_main_head": head}), encoding="utf-8")


def commit(work: pathlib.Path, message: str, *, push: bool = True) -> None:
    git(work, "add", "-A")
    git(work, "commit", "-qm", message)
    if push:
        git(work, "push", "-q", "origin", "HEAD")


def settle(work: pathlib.Path, head: str, branch: str) -> None:
    write_handoff(work, head=head, branch=branch)
    commit(work, "settle")


class HandoffReady(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="handoff-"))
        self.work = build_repo(self.tmp)

    def gate(self) -> int:
        # `env={}` explicitly, never the ambient environment. These tests are about an
        # ordinary checkout, and when the suite itself runs INSIDE GitHub Actions the
        # ambient GITHUB_* variables describe a completely different repository -- the gate
        # then judged this fixture against the real PR's head and went red. That is how a
        # suite passes on a developer's disk and fails in CI, which is the failure mode this
        # whole file exists to close, arriving through the test rather than the code.
        return check_handoff_ready.main(self.work, env={})

    def test_a_settled_repository_is_green(self):
        """The positive control. Without it every RED below could be a gate that
        simply never says yes."""
        self.assertEqual(self.gate(), 0)

    def test_an_uncommitted_file_is_red(self):
        """Mutant: drop check_tree_clean ⇒ green. An uncommitted file does not exist
        for a session that clones the remote.

        The dirty file is untracked and unrelated on purpose. Editing NEXT_CHAT.md
        would also break the head and branch assertions, and the test would then pass
        whether or not the clean-tree check existed — which is what it did until the
        mutation run said so."""
        (self.work / "scratch.txt").write_text("not committed\n", encoding="utf-8")
        self.assertEqual(self.gate(), 1)

    def test_an_unpushed_commit_is_red(self):
        """Mutant: drop check_pushed ⇒ green.

        The commit re-settles the handoff first, so the head and branch assertions
        still pass and the ONLY thing wrong is that the remote does not have it."""
        (self.work / "note.txt").write_text("local only\n", encoding="utf-8")
        write_handoff(self.work, head=head_of(self.work), branch=branch_of(self.work))
        commit(self.work, "local only", push=False)
        self.assertEqual(self.gate(), 1)

    def test_a_handoff_that_does_not_name_the_head_is_red(self):
        """The defect this repository has had repeatedly: START_HERE.md sat at a head
        seven merges stale and nothing checked it."""
        text = (self.work / "NEXT_CHAT.md").read_text(encoding="utf-8")
        (self.work / "NEXT_CHAT.md").write_text(
            text.replace("at `", "at `deadbee` not `"), encoding="utf-8")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-qm", "stale head")
        git(self.work, "push", "-q", "origin", "HEAD")
        self.assertEqual(self.gate(), 1)

    def test_a_handoff_naming_the_merge_base_is_green(self):
        """The fix for the failure that recurred on five consecutive merges.

        This repository squash-merges, so a branch commit stops existing the moment
        the pull request lands. A handoff naming the branch head therefore names a
        DEAD object on `main` -- and `check_doc_claims` refuses it there, after the
        merge, where no pull request can show it. #193, #194, #195 and #196 all failed
        that way; #197 settled it by hand and #198 reproduced it, because the settle
        fixed the instance and not the mechanism.

        The merge base is a commit on `main`. It survives the squash. Nothing is lost
        by naming it: the branch's exact head still travels in the pull request body as
        `AUDIT_CANDIDATE_HEAD`, compared against the live head on every push.
        """
        # `main` is where the branch is cut from, and the fixture's default branch is
        # whatever `git init` chose -- so name it explicitly and push it, the way the
        # real repository has an origin/main to measure against.
        git(self.work, "branch", "-f", "main", "HEAD")
        git(self.work, "push", "-q", "origin", "main")
        base = head_of(self.work)          # the commit `main` and this branch share

        git(self.work, "checkout", "-q", "-b", "feature")
        git(self.work, "push", "-q", "-u", "origin", "feature")
        for n in ("one", "two"):           # two commits, so neither head nor PARENT is the base
            (self.work / f"{n}.txt").write_text(n + "\n", encoding="utf-8")
            git(self.work, "add", "-A")
            git(self.work, "commit", "-qm", n)
        self.assertNotEqual(head_of(self.work), base)

        write_handoff(self.work, head=base, branch="feature")
        commit(self.work, "handoff names the merge base")
        self.assertEqual(self.gate(), 0)

    def test_a_handoff_that_does_not_name_the_branch_is_red(self):
        """Mutant: drop the branch check ⇒ green. Head and next-action stay correct,
        so only the branch is missing — a handoff that says WHAT but not WHERE sends
        the next session to look on the wrong branch.

        This test did not exist until a mutation run reported the branch check as
        tested by nothing; three of the six checks here passed that way at first,
        all of them riding on the head assertion."""
        head = head_of(self.work)
        (self.work / "NEXT_CHAT.md").write_text(
            f"# NEXT_CHAT\n\nSettled at `{head[:7]}`.\n\n"
            f"**Next:** continue with the thing after this one.\n", encoding="utf-8")
        (self.work / "config" / "current_state.json").write_text(
            json.dumps({"settled_at_main_head": head}), encoding="utf-8")
        commit(self.work, "handoff naming no branch")
        self.assertEqual(self.gate(), 1)

    def test_a_handoff_with_no_next_action_is_red(self):
        """Mutant: drop the next-action check ⇒ green. A handoff that says where you
        are and not what to do is where the last session\'s intent goes missing.

        Head and branch stay correct so this test can only fail for its own reason."""
        write_handoff(self.work, head=head_of(self.work), branch=branch_of(self.work),
                      next_action=False)
        commit(self.work, "handoff without a next action")
        self.assertEqual(self.gate(), 1)

    def test_a_mirror_pointing_at_a_commit_that_does_not_exist_is_red(self):
        """Mutant: delete check_machine_mirror ⇒ green."""
        (self.work / "config" / "current_state.json").write_text(
            json.dumps({"settled_at_main_head": "f" * 40}), encoding="utf-8")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "--amend", "--no-edit")
        git(self.work, "push", "-qf", "origin", "HEAD")
        self.assertEqual(self.gate(), 1)

    def test_an_over_budget_canon_is_red(self):
        """The two gates are joined on purpose: a canon the next session cannot be
        handed is not a handoff, however current its prose."""
        (self.work / "config" / "canon-budget.json").write_text(json.dumps({
            "per_file_bytes": {"NEXT_CHAT.md": 10},
            "total_bytes_max": 10, "max_shared_fraction": 0.2}), encoding="utf-8")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "--amend", "--no-edit")
        git(self.work, "push", "-qf", "origin", "HEAD")
        self.assertEqual(self.gate(), 1)

    def test_a_repository_with_no_upstream_at_all_is_red(self):
        solo = self.tmp / "solo"
        subprocess.run(["git", "init", "-q", str(solo)], check=True)
        git(solo, "config", "user.name", "Test")
        git(solo, "config", "user.email", "test@example.invalid")
        (solo / "NEXT_CHAT.md").write_text("x\n", encoding="utf-8")
        git(solo, "add", "-A")
        git(solo, "commit", "-qm", "only")
        self.assertEqual(check_handoff_ready.main(solo, env={}), 1)


class CiCheckout(unittest.TestCase):
    """The gate ran in CI from the day it was written and was never green there.

    `actions/checkout` on a `pull_request` builds a throwaway merge commit and checks it
    out detached. Asked naively, git then reports no upstream, a branch called "HEAD" and a
    first parent that is `main` — so the gate said "nothing of it is on GitHub" about a
    checkout GitHub had just made, and demanded that NEXT_CHAT.md name a commit that exists
    only inside that one job. Unsatisfiable, and red for a reason unconnected to its subject,
    which is how a gate gets ignored.

    These build the real shape: a base commit, a PR head that settles the handoff, and a
    merge commit whose parents are (base, pr-head), checked out detached.
    """

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="handoff-ci-"))
        self.work = build_repo(self.tmp)
        self.branch = branch_of(self.work)
        self.base = head_of(self.work)
        # A PR head on top of the base, settling the handoff the way a session would.
        git(self.work, "checkout", "-q", "-b", "pr/topic")
        (self.work / "work.txt").write_text("the change\n", encoding="utf-8")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-qm", "the change")
        write_handoff(self.work, head=head_of(self.work), branch="pr/topic")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-qm", "settle")
        git(self.work, "push", "-q", "-u", "origin", "pr/topic")
        self.pr_head = head_of(self.work)
        # The merge commit actions/checkout leaves behind: parents (base, pr head).
        git(self.work, "checkout", "-q", self.base)
        git(self.work, "merge", "-q", "--no-ff", "-m", "merge", self.pr_head)
        self.merge = head_of(self.work)

    def env(self, **over: str) -> dict[str, str]:
        e = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request",
             "GITHUB_HEAD_REF": "pr/topic", "GITHUB_SHA": self.merge}
        e.update(over)
        return e

    def test_a_pull_request_checkout_of_a_settled_branch_is_green(self):
        """Mutant: pass ci=None into check_pushed and the handoff check ⇒ red, with two
        problems that are both artefacts of the merge commit."""
        self.assertEqual(check_handoff_ready.main(self.work, env=self.env()), 0)

    def test_the_same_checkout_is_red_without_the_ci_environment(self):
        """The control that proves the test above is not green for a general reason: the
        identical detached merge commit, judged as an ordinary checkout, still fails."""
        self.assertEqual(check_handoff_ready.main(self.work, env={}), 1)

    def test_a_handoff_naming_the_base_instead_of_the_pr_head_is_red(self):
        """Mutant: accept HEAD^ (the base branch) as well as the PR head ⇒ green. The gate
        must still catch a stale handoff in CI, or it is CI-aware by being blind."""
        git(self.work, "checkout", "-q", "pr/topic")
        write_handoff(self.work, head=self.base, branch="pr/topic")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-qm", "stale")
        git(self.work, "push", "-q", "origin", "HEAD")
        pr_head = head_of(self.work)
        git(self.work, "checkout", "-q", self.base)
        git(self.work, "merge", "-q", "--no-ff", "-m", "merge", pr_head)
        env = self.env()
        env["GITHUB_SHA"] = head_of(self.work)
        self.assertEqual(check_handoff_ready.main(self.work, env=env), 1)

    def test_a_handoff_naming_a_different_branch_is_red_in_ci(self):
        """The branch comes from GITHUB_HEAD_REF, not from git — so it must still be
        compared, not merely defaulted away."""
        self.assertEqual(
            check_handoff_ready.main(self.work, env=self.env(GITHUB_HEAD_REF="pr/other")), 1)

    def test_a_head_this_checkout_does_not_contain_is_red(self):
        """Mutant: drop the cat-file test in check_pushed's CI branch ⇒ green. A shallow or
        misconfigured checkout must not read as GREEN.

        The handoff is written to name the unreachable sha, and the branch is left correct,
        so the head-and-branch assertions all PASS and the only thing wrong is that CI is
        naming a commit this clone does not have. Without that the test was red because
        NEXT_CHAT.md did not name `0000000`, and it passed with the check deleted — which
        the mutation run said out loud."""
        missing = "0" * 40
        git(self.work, "checkout", "-q", "pr/topic")
        # Written by hand rather than through write_handoff, which would also point the
        # machine mirror at the missing commit and make check_machine_mirror the thing that
        # turns this red. Only ONE assertion may be failing, or the test proves nothing
        # about check_pushed.
        (self.work / "NEXT_CHAT.md").write_text(
            f"# NEXT_CHAT\n\nBranch `pr/topic` settled at `{missing[:7]}`.\n"
            f"\n**Next:** continue with the thing after this one.\n", encoding="utf-8")
        (self.work / "config" / "current_state.json").write_text(
            json.dumps({"settled_at_main_head": self.base}), encoding="utf-8")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-qm", "names a head that is not here")
        git(self.work, "push", "-q", "origin", "HEAD")
        pr_head = head_of(self.work)
        git(self.work, "checkout", "-q", self.base)
        git(self.work, "merge", "-q", "--no-ff", "-m", "merge", pr_head)
        payload = self.tmp / "event.json"
        payload.write_text(json.dumps({"pull_request": {"head": {"sha": missing}}}),
                           encoding="utf-8")
        env = self.env(GITHUB_EVENT_PATH=str(payload), GITHUB_SHA=head_of(self.work))
        self.assertEqual(check_handoff_ready.main(self.work, env=env), 1)

    def test_a_ci_run_that_cannot_resolve_its_head_at_all_is_red(self):
        """Mutant: drop the empty-head guard ⇒ green, and a run that does not know what it
        is testing then passes silently.

        A `pull_request` event with no payload, no GITHUB_SHA and a HEAD that is not a merge
        commit: nothing can say which commit is under test. "I could not check" and "it is
        fine" are different answers."""
        git(self.work, "checkout", "-q", "pr/topic")
        env = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request",
               "GITHUB_HEAD_REF": "pr/topic"}
        self.assertEqual(check_handoff_ready.ci_checkout(self.work, env)["head"], "")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = check_handoff_ready.main(self.work, env=env)
        self.assertEqual(code, 1)
        # The MESSAGE is the assertion. Without the guard the run is still red -- `git
        # cat-file -e ^{commit}` on an empty sha fails -- but it reports a checkout that is
        # missing a commit, which is a different and misleading diagnosis of a run that
        # simply does not know what it is testing.
        self.assertIn("the head under test could not be resolved", buf.getvalue())

    def test_the_pr_head_is_read_from_the_event_payload_when_present(self):
        payload = self.tmp / "event.json"
        payload.write_text(json.dumps({"pull_request": {"head": {"sha": self.pr_head}}}),
                           encoding="utf-8")
        got = check_handoff_ready.ci_checkout(
            self.work, self.env(GITHUB_EVENT_PATH=str(payload)))
        self.assertEqual(got, {"head": self.pr_head, "branch": "pr/topic"})

    def test_the_pr_head_falls_back_to_the_merge_commits_second_parent(self):
        """No payload on disk: the second parent IS the PR head, and reading it is what
        keeps this working when the event file is unavailable."""
        got = check_handoff_ready.ci_checkout(self.work, self.env())
        self.assertEqual(got, {"head": self.pr_head, "branch": "pr/topic"})

    def test_a_push_run_uses_the_sha_and_ref_github_gives(self):
        got = check_handoff_ready.ci_checkout(self.work, {
            "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "push",
            "GITHUB_SHA": self.pr_head, "GITHUB_REF_NAME": "main"})
        self.assertEqual(got, {"head": self.pr_head, "branch": "main"})

    def test_outside_github_actions_there_is_no_ci_checkout(self):
        """Mutant: return a dict unconditionally ⇒ every local run stops checking the push.
        This is the guard that keeps CI-awareness from leaking onto a developer's disk."""
        self.assertIsNone(check_handoff_ready.ci_checkout(self.work, {}))
        self.assertIsNone(check_handoff_ready.ci_checkout(self.work, {"GITHUB_ACTIONS": "false"}))


class EntryPointRunsEverything(unittest.TestCase):
    def test_unittest_main_is_the_last_statement(self):
        source = pathlib.Path(__file__).read_text(encoding="utf-8").splitlines()
        classes = [i for i, ln in enumerate(source) if ln.startswith("class ")]
        guard = [i for i, ln in enumerate(source) if ln.startswith('if __name__')]
        self.assertEqual(len(guard), 1)
        self.assertGreater(guard[0], max(classes))


if __name__ == "__main__":
    unittest.main()
