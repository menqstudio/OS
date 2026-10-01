#!/usr/bin/env python3
"""Tests for .claude/hooks/coordination_stop_guard.py -- the Stop hook.

Run: python -m unittest test_coordination_stop_guard   (from tools/)

CLAUDE.md says this hook "blocks a session from ending when source changed and the
coordination docs did not". Nothing tested that. And the hook is fail-open by design -- its
last line is `except Exception: sys.exit(0)` -- so a guard that had stopped working would
have looked exactly like a guard that allowed: no output, exit 0.

Every case drives the real hook as a subprocess, the way `.claude/settings.json` runs it, in
a scratch git repository with a `main` branch and a work branch.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = ROOT / ".claude" / "hooks" / "coordination_stop_guard.py"


def git(cwd: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
                   cwd=cwd, check=True, capture_output=True, text=True, timeout=60)


class StopGuardCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = pathlib.Path(tmp.name)
        git(self.repo, "init", "-q", "-b", "main")
        self.write("README.md", "seed\n")
        self.write("PROJECT_STATE.md", "state\n")
        self.write("apps/desktop/src/App.tsx", "export {};\n")
        self.commit("seed")
        git(self.repo, "checkout", "-q", "-b", "work")

    def write(self, rel: str, text: str) -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, message: str) -> None:
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", message)

    def stop(self, env: dict | None = None, cwd: pathlib.Path | None = None) -> tuple[int, dict]:
        """Run the hook; return its exit code and the one JSON object it printed (or {})."""
        environment = {k: v for k, v in os.environ.items() if k != "BRO_SKIP_DOC_SYNC"}
        environment.update(env or {})
        result = subprocess.run([sys.executable, "-X", "utf8", str(HOOK)],
                                input=json.dumps({"hook_event_name": "Stop"}),
                                cwd=cwd or self.repo, env=environment,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.stderr, "", "the hook wrote to stderr")
        out = result.stdout.strip()
        return result.returncode, (json.loads(out) if out else {})

    def assertBlocks(self, needle: str, **kwargs) -> None:
        code, said = self.stop(**kwargs)
        self.assertEqual(code, 0)
        self.assertEqual(said.get("decision"), "block", said)
        self.assertIn(needle, said["reason"])

    def assertAllows(self, **kwargs) -> None:
        code, said = self.stop(**kwargs)
        self.assertEqual(code, 0)
        self.assertEqual(said, {}, "the hook rendered a verdict where it should have allowed")


class TheBlock(StopGuardCase):
    def test_committed_code_with_no_coordination_doc_blocks(self):
        self.write("apps/desktop/src/App.tsx", "export const a = 1;\n")
        self.commit("code only")
        self.assertBlocks("apps/desktop/src/App.tsx")

    def test_uncommitted_code_blocks_too(self):
        """Unstaged and staged changes are both in the changed set, not only commits."""
        self.write("engine/runtime/thing.py", "x = 1\n")
        git(self.repo, "add", "-A")
        self.assertBlocks("engine/runtime/thing.py")
        git(self.repo, "reset", "-q")
        self.write("apps/desktop/src/App.tsx", "export const b = 2;\n")
        self.assertBlocks("apps/desktop/src/App.tsx")

    def test_every_code_directory_is_covered(self):
        for rel in ("apps/x.ts", "engine/x.py", "bridge/x.py", "contracts/x.schema.json"):
            with self.subTest(rel=rel):
                self.write(rel, "x\n")
                git(self.repo, "add", "-A")
                self.assertBlocks(rel)
                git(self.repo, "reset", "-q", "--hard")

    def test_the_message_names_both_ways_out(self):
        self.write("bridge/adapter.py", "x = 1\n")
        self.commit("code only")
        _, said = self.stop()
        self.assertIn("BRO_SKIP_DOC_SYNC=1", said["reason"])
        self.assertIn("[no-doc-sync]", said["reason"])

    def test_the_output_on_the_wire_is_ascii(self):
        """The hook promises ASCII-only output: a cp1252 console raises on anything else."""
        self.write("bridge/adapter.py", "x = 1\n")
        self.commit("code only")
        result = subprocess.run([sys.executable, str(HOOK)], input=b"{}", cwd=self.repo,
                                capture_output=True, timeout=60)
        self.assertTrue(result.stdout.isascii(), result.stdout)


class TheAllows(StopGuardCase):
    def test_nothing_changed_allows(self):
        self.assertAllows()

    def test_code_with_a_coordination_doc_in_the_same_branch_allows(self):
        for doc in ("PROJECT_STATE.md", "TASKS.md", "MASTER_EXECUTION_ROADMAP.md"):
            with self.subTest(doc=doc):
                self.write("apps/desktop/src/App.tsx", f"export const d = '{doc}';\n")
                self.write(doc, f"synced for {doc}\n")
                git(self.repo, "add", "-A")
                self.assertAllows()
                git(self.repo, "reset", "-q", "--hard")

    def test_a_change_that_is_not_source_allows(self):
        """Markdown, tests and lockfiles under a code directory, and anything outside one."""
        for rel in ("apps/desktop/README.md", "engine/tests/test_x.py",
                    "apps/desktop/package-lock.json", "apps/desktop/src-tauri/Cargo.lock",
                    "tools/check_x.py", "docs/NOTES.md"):
            with self.subTest(rel=rel):
                self.write(rel, "x\n")
                git(self.repo, "add", "-A")
                self.assertAllows()
                git(self.repo, "reset", "-q", "--hard")

    def test_the_environment_bypass_allows(self):
        self.write("apps/desktop/src/App.tsx", "export const a = 1;\n")
        self.commit("code only")
        for value in ("1", "true", "YES", "on"):
            with self.subTest(value=value):
                self.assertAllows(env={"BRO_SKIP_DOC_SYNC": value})
        self.assertBlocks("App.tsx", env={"BRO_SKIP_DOC_SYNC": "0"})

    def test_the_commit_tag_bypass_allows(self):
        self.write("apps/desktop/src/App.tsx", "export const a = 1;\n")
        self.commit("code only [no-doc-sync]")
        self.assertAllows()

    def test_outside_a_repository_it_fails_open(self):
        """git answers nothing, the changed set is empty, and the stop is allowed."""
        with tempfile.TemporaryDirectory() as elsewhere:
            self.assertAllows(cwd=pathlib.Path(elsewhere))


class TheHooksListAgainstTheLaw(unittest.TestCase):
    """Three lists say what a "substantive change" is. The law file declares its difference
    from check_coordination.py; this hook's list was declared nowhere and checked by nothing."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(HOOK.parent))
        try:
            import coordination_stop_guard
        finally:
            sys.path.pop(0)
        cls.hook = coordination_stop_guard
        cls.law = json.loads((ROOT / "config" / "canonical-update-law.json").read_text(
            encoding="utf-8"))

    def test_every_directory_the_hook_blocks_on_is_substantive_under_the_law(self):
        """The hook may be NARROWER than the law. It may not block on something the law does
        not call substantive, which is the only way the two could contradict each other."""
        import fnmatch

        for directory in self.hook.CODE_DIRS:
            with self.subTest(directory=directory):
                self.assertTrue(
                    any(fnmatch.fnmatch(directory + "some/file.py", glob)
                        for glob in self.law["substantive_globs"]),
                    f"the Stop hook blocks on {directory} and the update law does not name it")

    def test_every_document_the_hook_accepts_exists(self):
        for name in self.hook.COORDINATION_DOCS:
            with self.subTest(document=name):
                self.assertTrue((ROOT / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
