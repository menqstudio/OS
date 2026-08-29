"""Tests for the handoff-readiness gate.

Each test builds a real git repository with a real upstream, because the thing under
test is whether a NEW session could clone this and continue — and a fixture that fakes
git proves nothing about that. The upstream is a bare repo on disk; nothing here
touches a network.

Every test names the mutation that turns it red. `unittest.main()` is the last
statement (ninth audit `I-05`).
"""
from __future__ import annotations

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
        return check_handoff_ready.main(self.work)

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
        self.assertEqual(check_handoff_ready.main(solo), 1)


class EntryPointRunsEverything(unittest.TestCase):
    def test_unittest_main_is_the_last_statement(self):
        source = pathlib.Path(__file__).read_text(encoding="utf-8").splitlines()
        classes = [i for i, ln in enumerate(source) if ln.startswith("class ")]
        guard = [i for i, ln in enumerate(source) if ln.startswith('if __name__')]
        self.assertEqual(len(guard), 1)
        self.assertGreater(guard[0], max(classes))


if __name__ == "__main__":
    unittest.main()
