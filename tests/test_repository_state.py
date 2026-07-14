import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_repository_state import (
    RepositoryState,
    RepositoryStateError,
    verify_repository_binding,
)


class RepositoryStateTests(unittest.TestCase):
    def _task(self, root: pathlib.Path) -> dict:
        return {
            "task_id": "task-123",
            "repository": {
                "worktree": str(root),
                "branch": "task-123",
                "base_commit": "a" * 40,
                "tree_identity": "b" * 64,
            },
        }

    def _state(self, root: pathlib.Path) -> RepositoryState:
        return RepositoryState(
            root=root.resolve(),
            cwd=root.resolve(),
            branch="task-123",
            head_sha="a" * 40,
            tree_identity="b" * 64,
        )

    def _lock(self, root: pathlib.Path) -> dict:
        return {
            "task_id": "task-123",
            "worktree": str(root.resolve()),
            "branch": "task-123",
            "head_sha": "a" * 40,
            "tree_identity": "b" * 64,
            "status": "active",
        }

    def test_valid_exact_binding_passes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            with (
                patch("bro_repository_state.resolve_state", return_value=self._state(root)),
                patch(
                    "bro_repository_state.worktrees",
                    return_value=[{"worktree": str(root.resolve()), "branch": "refs/heads/task-123"}],
                ),
                patch("bro_repository_state._load_lock", return_value=self._lock(root)),
            ):
                state = verify_repository_binding(self._task(root), root=root)
            self.assertEqual(state.branch, "task-123")

    def test_wrong_worktree_is_denied(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as other:
            root = pathlib.Path(temp_dir)
            task = self._task(pathlib.Path(other))
            with patch("bro_repository_state.resolve_state", return_value=self._state(root)):
                with self.assertRaises(RepositoryStateError):
                    verify_repository_binding(task, root=root)

    def test_main_mutation_is_denied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            task = self._task(root)
            task["repository"]["branch"] = "main"
            state = self._state(root)
            state = RepositoryState(state.root, state.cwd, "main", state.head_sha, state.tree_identity)
            with (
                patch("bro_repository_state.resolve_state", return_value=state),
                patch("bro_repository_state.worktrees", return_value=[{"worktree": str(root.resolve())}]),
            ):
                with self.assertRaises(RepositoryStateError):
                    verify_repository_binding(task, root=root)

    def test_branch_head_and_tree_mismatches_are_denied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            base_task = self._task(root)
            cases = [
                RepositoryState(root.resolve(), root.resolve(), "wrong", "a" * 40, "b" * 64),
                RepositoryState(root.resolve(), root.resolve(), "task-123", "c" * 40, "b" * 64),
                RepositoryState(root.resolve(), root.resolve(), "task-123", "a" * 40, "d" * 64),
            ]
            for state in cases:
                with self.subTest(state=state):
                    with (
                        patch("bro_repository_state.resolve_state", return_value=state),
                        patch("bro_repository_state.worktrees", return_value=[{"worktree": str(root.resolve())}]),
                    ):
                        with self.assertRaises(RepositoryStateError):
                            verify_repository_binding(base_task, root=root)

    def test_unregistered_worktree_is_denied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            with (
                patch("bro_repository_state.resolve_state", return_value=self._state(root)),
                patch("bro_repository_state.worktrees", return_value=[]),
            ):
                with self.assertRaises(RepositoryStateError):
                    verify_repository_binding(self._task(root), root=root)

    def test_missing_or_conflicting_lock_is_denied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            common = [
                patch("bro_repository_state.resolve_state", return_value=self._state(root)),
                patch("bro_repository_state.worktrees", return_value=[{"worktree": str(root.resolve())}]),
            ]
            with common[0], common[1], patch(
                "bro_repository_state._load_lock",
                side_effect=RepositoryStateError("active task lock is missing"),
            ):
                with self.assertRaises(RepositoryStateError):
                    verify_repository_binding(self._task(root), root=root)

            bad_lock = self._lock(root)
            bad_lock["branch"] = "other"
            with (
                patch("bro_repository_state.resolve_state", return_value=self._state(root)),
                patch("bro_repository_state.worktrees", return_value=[{"worktree": str(root.resolve())}]),
                patch("bro_repository_state._load_lock", return_value=bad_lock),
            ):
                with self.assertRaises(RepositoryStateError):
                    verify_repository_binding(self._task(root), root=root)


if __name__ == "__main__":
    unittest.main()
