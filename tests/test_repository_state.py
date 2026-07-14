import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_repository_state import (
    RepositoryState,
    RepositoryStateError,
    _normal,
    _worktree_lock_path,
    current_tree_identity,
    verify_repository_binding,
)


class RepositoryStateTests(unittest.TestCase):
    agent_id = "agt-p01-r01"
    session_id = "session-123"

    def _task(self, root: pathlib.Path) -> dict:
        return {
            "task_id": "task-123",
            "agent_id": self.agent_id,
            "repository": {
                "worktree": str(root),
                "branch": "task-123",
                "base_commit": "a" * 40,
                "tree_identity": "b" * 64,
            },
        }

    def _state(self, root: pathlib.Path) -> RepositoryState:
        return RepositoryState(root.resolve(), root.resolve(), "task-123", "a" * 40, "b" * 64)

    def _lock(self, root: pathlib.Path) -> dict:
        return {
            "schema": 1,
            "status": "active",
            "task_id": "task-123",
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "worktree": _normal(root),
            "branch": "task-123",
            "head_sha": "a" * 40,
            "tree_identity": "b" * 64,
        }

    def _verify(self, task, root):
        return verify_repository_binding(task, agent_id=self.agent_id, session_id=self.session_id, root=root)

    def test_valid_exact_binding_passes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            with (
                patch("bro_repository_state.resolve_state", return_value=self._state(root)),
                patch("bro_repository_state.worktrees", return_value=[{"worktree": str(root.resolve())}]),
                patch("bro_repository_state._load_lock", return_value=self._lock(root)),
            ):
                self.assertEqual(self._verify(self._task(root), root).branch, "task-123")

    def test_wrong_worktree_is_denied(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as other:
            root = pathlib.Path(temp_dir)
            with patch("bro_repository_state.resolve_state", return_value=self._state(root)):
                with self.assertRaises(RepositoryStateError):
                    self._verify(self._task(pathlib.Path(other)), root)

    def test_main_mutation_is_denied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            task = self._task(root)
            task["repository"]["branch"] = "main"
            state = RepositoryState(root.resolve(), root.resolve(), "main", "a" * 40, "b" * 64)
            with patch("bro_repository_state.resolve_state", return_value=state), patch(
                "bro_repository_state.worktrees", return_value=[{"worktree": str(root.resolve())}]
            ):
                with self.assertRaises(RepositoryStateError):
                    self._verify(task, root)

    def test_branch_head_and_tree_mismatches_are_denied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            cases = [
                RepositoryState(root.resolve(), root.resolve(), "wrong", "a" * 40, "b" * 64),
                RepositoryState(root.resolve(), root.resolve(), "task-123", "c" * 40, "b" * 64),
                RepositoryState(root.resolve(), root.resolve(), "task-123", "a" * 40, "d" * 64),
            ]
            for state in cases:
                with self.subTest(state=state), patch(
                    "bro_repository_state.resolve_state", return_value=state
                ), patch(
                    "bro_repository_state.worktrees", return_value=[{"worktree": str(root.resolve())}]
                ):
                    with self.assertRaises(RepositoryStateError):
                        self._verify(self._task(root), root)

    def test_unregistered_worktree_is_denied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            with patch("bro_repository_state.resolve_state", return_value=self._state(root)), patch(
                "bro_repository_state.worktrees", return_value=[]
            ):
                with self.assertRaises(RepositoryStateError):
                    self._verify(self._task(root), root)

    def test_lock_binds_agent_session_and_single_worktree_slot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            bad = self._lock(root)
            bad["session_id"] = "other"
            with patch("bro_repository_state.resolve_state", return_value=self._state(root)), patch(
                "bro_repository_state.worktrees", return_value=[{"worktree": str(root.resolve())}]
            ), patch("bro_repository_state._load_lock", return_value=bad):
                with self.assertRaises(RepositoryStateError):
                    self._verify(self._task(root), root)

    def test_lock_filename_is_derived_from_worktree_not_task(self):
        with tempfile.TemporaryDirectory() as ledger_dir, tempfile.TemporaryDirectory() as root_dir:
            os.environ["BRO_TASK_LOCK_LEDGER"] = ledger_dir
            try:
                path1 = _worktree_lock_path(pathlib.Path(root_dir))
                path2 = _worktree_lock_path(pathlib.Path(root_dir))
                self.assertEqual(path1, path2)
                self.assertNotIn("task-123", path1.name)
            finally:
                os.environ.pop("BRO_TASK_LOCK_LEDGER", None)

    def test_tree_identity_includes_untracked_but_ignores_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / ".gitignore").write_text("ignored.tmp\n", encoding="utf-8")
            (root / "tracked.txt").write_text("tracked", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=root, check=True, capture_output=True)
            baseline = current_tree_identity(root)
            (root / "ignored.tmp").write_text("ignored", encoding="utf-8")
            self.assertEqual(current_tree_identity(root), baseline)
            (root / "untracked.txt").write_text("untracked", encoding="utf-8")
            self.assertNotEqual(current_tree_identity(root), baseline)


if __name__ == "__main__":
    unittest.main()
