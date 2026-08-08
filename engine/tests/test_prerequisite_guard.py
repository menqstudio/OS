"""The skip counter, tested — because an unenforced guard is worse than none.

`_prerequisites.require()` lets a handful of tests skip on a deployed tree, where the
thing they assert about (a git worktree, `apps/`, `bridge/`) genuinely is not present.
That is only safe while the same call REFUSES to skip on a CI runner, which always has
all three. If that half ever broke, the skips would spread silently and the suite would
keep printing OK -- the exact failure mode this file exists to make impossible.

So: the guard is exercised in both directions, and the three prerequisites are asserted
to be real facts about this checkout rather than probes that answer True to anything.
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
from _prerequisites import (BRIDGE_SIDECAR, DESKTOP_TCB_SOURCE,  # noqa: E402
                            Prerequisite, require, requires)

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

    @requires(PRESENT)
    def test_the_decorator_runs_the_body_when_the_prerequisite_holds(self):
        self.assertTrue(True)

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
        """
        import tempfile
        with tempfile.TemporaryDirectory(prefix="bro-prereq-sib-") as tmp:
            repo = pathlib.Path(tmp)
            for name, relative in (
                (DESKTOP_TCB_SOURCE.name,
                 ("apps", "desktop", "src-tauri", "core", "src", "tcb_integrity.rs")),
                (BRIDGE_SIDECAR.name, ("bridge", "engine_sidecar.py")),
            ):
                with self.subTest(prerequisite=name):
                    path = repo.joinpath(*relative)
                    probe = Prerequisite(name, path.is_file, "fixture")
                    self.assertFalse(probe.present())
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("x", encoding="utf-8")
                    self.assertTrue(probe.present())
                    # A directory of the same name is not the file the tests import.
                    path.unlink()
                    path.mkdir()
                    self.assertFalse(probe.present())

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
