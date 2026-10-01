"""The skip counter, tested — because an unenforced guard is worse than none.

`_prerequisites.require()` lets a handful of tests skip on a deployed tree, where the
thing they assert about (a git worktree, `apps/`, `bridge/`) genuinely is not present.
That is only safe while the same call REFUSES to skip on a CI runner, which always has
all three. If that half ever broke, the skips would spread silently and the suite would
keep printing OK -- the exact failure mode this file exists to make impossible.

So: the guard is exercised in both directions, and every prerequisite's own probe is driven to
both answers -- the sibling-tree ones (`_prerequisites.SIBLING_TREE`) over a tree laid out here,
the git one over every reply git can give -- rather than left as a probe that could answer True
to anything.
"""
from __future__ import annotations

import os
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import _prerequisites  # noqa: E402
from _prerequisites import Prerequisite, require, requires  # noqa: E402

ABSENT = Prerequisite("fixture prerequisite", lambda: False, "deliberately absent")
PRESENT = Prerequisite("fixture prerequisite", lambda: True, "deliberately present")


def _raise(exc):
    def raiser(*args, **kwargs):
        raise exc
    return raiser


class PrerequisiteGuardTests(unittest.TestCase):
    def test_a_present_prerequisite_lets_the_test_run(self):
        require(PRESENT)  # must not raise

    def test_an_absent_prerequisite_skips_by_name_off_the_runner(self):
        with patch.object(_prerequisites, "running_under_ci", return_value=False):
            with self.assertRaises(unittest.SkipTest) as raised:
                require(ABSENT)
        # The reason must NAME the missing thing: "skipped" with no cause is how a hole
        # gets read as a pass.
        self.assertIn("fixture prerequisite", str(raised.exception))
        self.assertIn("deliberately absent", str(raised.exception))

    def test_an_absent_prerequisite_is_a_failure_under_ci(self):
        with patch.object(_prerequisites, "running_under_ci", return_value=True):
            with self.assertRaises(AssertionError) as raised:
                require(ABSENT)
        self.assertNotIsInstance(raised.exception, unittest.SkipTest)
        self.assertIn("deliberately absent", str(raised.exception))

    def test_the_runner_is_detected_from_the_runner_s_own_variables(self):
        for env, expected in (
            ({"GITHUB_ACTIONS": "true"}, True),
            ({"CI": "true"}, True),
            ({"CI": "1"}, True),
            ({"GITHUB_ACTIONS": "false", "CI": ""}, False),
            ({}, False),
            # BRO_ENV=ci is NOT a runner signal: the deployment runbook tells an
            # operator to export it, and their skips are the honest answer.
            ({"BRO_ENV": "ci"}, False),
        ):
            with self.subTest(env=env):
                clean = {k: v for k, v in os.environ.items()
                         if k not in {"GITHUB_ACTIONS", "CI", "BRO_ENV"}}
                clean.update(env)
                with patch.dict(os.environ, clean, clear=True):
                    self.assertEqual(_prerequisites.running_under_ci(), expected)

    def test_the_decorator_runs_the_body_when_the_prerequisite_holds(self):
        ran = []

        class Fixture(unittest.TestCase):
            @requires(PRESENT)
            def test_gated(self):
                ran.append(self)

        result = unittest.TestResult()
        Fixture("test_gated").run(result)
        # A decorator that swallowed the body would report a pass just the same, so the pass is
        # not the evidence: the body's own side effect is.
        self.assertEqual(len(ran), 1)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(result.skipped, [])

    def test_the_decorator_reports_through_the_normal_channels(self):
        class Fixture(unittest.TestCase):
            @requires(ABSENT)
            def test_gated(self):  # pragma: no cover - the body must not run
                raise AssertionError("the gated body ran with its prerequisite absent")

        for ci, counter in ((False, "skipped"), (True, "failures")):
            with self.subTest(ci=ci):
                with patch.object(_prerequisites, "running_under_ci", return_value=ci):
                    result = unittest.TestResult()
                    Fixture("test_gated").run(result)
                self.assertEqual(result.testsRun, 1)
                self.assertEqual(len(getattr(result, counter)), 1)

    def test_the_sibling_tree_probes_answer_both_ways(self):
        """A probe stuck on one answer would make either the skip or the test unreachable.

        Both answers are taken from a tree this test lays out, never from the checkout
        it happens to run in: asserting "present" against the real repository would be
        a fresh red on the very deployed box this whole change exists to keep quiet.

        The probes asked are the REAL ones, pointed at that tree by moving the one name
        they all resolve against. A probe rebuilt here from a prerequisite's name would
        answer for itself and say nothing about the one the gated tests call.
        """
        import tempfile
        for prerequisite in _prerequisites.SIBLING_TREE:
            with self.subTest(prerequisite=prerequisite.name), \
                    tempfile.TemporaryDirectory(prefix="bro-prereq-sib-") as tmp:
                repo = pathlib.Path(tmp)
                self.assertTrue(prerequisite.files, "a sibling-tree prerequisite names its files")
                paths = [repo / relative for relative in prerequisite.files]
                with patch.object(_prerequisites, "REPO_ROOT", repo):
                    self.assertFalse(prerequisite.present())
                    for path in paths:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text("x", encoding="utf-8")
                    self.assertTrue(prerequisite.present())
                    # Every file it names is needed, and a directory of the same name is
                    # not the file the tests read.
                    for path in paths:
                        with self.subTest(replaced_by_a_directory=path.name):
                            path.unlink()
                            path.mkdir()
                            self.assertFalse(prerequisite.present())
                            path.rmdir()
                            path.write_text("x", encoding="utf-8")
                    self.assertTrue(prerequisite.present())

    def test_every_sibling_tree_prerequisite_is_in_the_set_this_file_drives(self):
        """A prerequisite added to the module and not to `SIBLING_TREE` would be a probe no test
        ever asked for its other answer."""
        declared = {value.name for value in vars(_prerequisites).values()
                    if isinstance(value, Prerequisite)}
        driven = {p.name for p in _prerequisites.SIBLING_TREE} | {_prerequisites.GIT_WORKTREE.name}
        self.assertEqual(declared, driven)
        self.assertEqual(len(driven), len(_prerequisites.SIBLING_TREE) + 1, "two share a name")

    def test_the_git_probe_believes_git_and_nothing_else(self):
        """Every answer git can give, mapped to the verdict it must produce.

        The probe is cached, so each case clears the cache first — and the cache is
        cleared once more at the end so the rest of the suite sees the real tree.
        """
        import subprocess as sp

        def answer(**kwargs):
            return lambda *a, **kw: SimpleNamespace(**kwargs)

        cases = (
            ("inside a worktree", answer(returncode=0, stdout="true\n"), True),
            # `git rev-parse` says "false" inside a bare repo / GIT_DIR: usable for
            # plumbing, but not a worktree whose files can be hashed.
            ("bare repository", answer(returncode=0, stdout="false\n"), False),
            ("not a repository (the deployed tree, exit 128)",
             answer(returncode=128, stdout=""), False),
            ("git not installed", _raise(FileNotFoundError("git")), False),
            ("git hung", _raise(sp.TimeoutExpired("git", 60)), False),
        )
        self.addCleanup(_prerequisites._inside_git_worktree.cache_clear)
        for label, behaviour, expected in cases:
            with self.subTest(case=label):
                _prerequisites._inside_git_worktree.cache_clear()
                with patch.object(_prerequisites.subprocess, "run", behaviour):
                    self.assertIs(_prerequisites._inside_git_worktree(), expected)

    def test_the_git_probe_asks_from_the_engine_tree_and_writes_nothing(self):
        seen = {}

        def record(argv, **kwargs):
            seen["argv"] = argv
            seen["cwd"] = kwargs.get("cwd")
            return SimpleNamespace(returncode=0, stdout="true\n")

        _prerequisites._inside_git_worktree.cache_clear()
        self.addCleanup(_prerequisites._inside_git_worktree.cache_clear)
        with patch.object(_prerequisites.subprocess, "run", record):
            _prerequisites._inside_git_worktree()
        self.assertEqual(seen["argv"], ["git", "rev-parse", "--is-inside-work-tree"])
        self.assertEqual(seen["cwd"], str(_prerequisites.ENGINE_ROOT))
        # A read-only question. Anything that could mutate a tree shared with other
        # work does not belong in a probe that runs on every test process.
        self.assertNotIn(seen["argv"][1], {"init", "add", "stash", "checkout", "reset"})


if __name__ == "__main__":
    unittest.main()
