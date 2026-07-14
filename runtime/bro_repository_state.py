from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
from dataclasses import dataclass
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]


class RepositoryStateError(ValueError):
    pass


@dataclass(frozen=True)
class RepositoryState:
    root: pathlib.Path
    cwd: pathlib.Path
    branch: str
    head_sha: str
    tree_identity: str


def _git(root: pathlib.Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=root, text=True, encoding="utf-8"
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RepositoryStateError(f"git command failed: git {' '.join(args)}") from exc


def _normal(path: pathlib.Path) -> str:
    return os.path.normcase(str(path.expanduser().resolve()))


def current_tree_identity(root: pathlib.Path) -> str:
    """Hash every tracked and untracked non-ignored file in the worktree."""
    try:
        raw = subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RepositoryStateError("cannot enumerate current repository tree") from exc

    digest = hashlib.sha256()
    for item in sorted(part for part in raw.split(b"\0") if part):
        rel = os.fsdecode(item)
        path = root / rel
        try:
            if path.is_symlink():
                payload = b"L\0" + os.fsencode(os.readlink(path))
            elif path.is_file():
                payload = b"F\0" + hashlib.sha256(path.read_bytes()).digest()
            else:
                raise RepositoryStateError(f"tree entry is missing or unsupported: {rel}")
        except OSError as exc:
            raise RepositoryStateError(f"cannot hash tree entry: {rel}") from exc
        digest.update(os.fsencode(rel) + b"\0" + payload)
    return digest.hexdigest()


def worktrees(root: pathlib.Path) -> list[dict[str, str]]:
    raw = _git(root, "worktree", "list", "--porcelain")
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in raw.splitlines() + [""]:
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    return entries


def resolve_state(
    root: pathlib.Path = ROOT,
    cwd: pathlib.Path | None = None,
) -> RepositoryState:
    resolved_root = root.resolve()
    resolved_cwd = (cwd or pathlib.Path.cwd()).resolve()
    try:
        resolved_cwd.relative_to(resolved_root)
    except ValueError as exc:
        raise RepositoryStateError("process CWD is outside the bound worktree") from exc

    branch = _git(resolved_root, "branch", "--show-current")
    if not branch:
        raise RepositoryStateError("detached HEAD is not allowed for mutation")

    return RepositoryState(
        root=resolved_root,
        cwd=resolved_cwd,
        branch=branch,
        head_sha=_git(resolved_root, "rev-parse", "HEAD"),
        tree_identity=current_tree_identity(resolved_root),
    )


def _lock_ledger(root: pathlib.Path) -> pathlib.Path:
    raw = os.getenv("BRO_TASK_LOCK_LEDGER")
    if not raw:
        raise RepositoryStateError("missing external BRO_TASK_LOCK_LEDGER")
    path = pathlib.Path(raw).expanduser()
    if not path.is_absolute():
        raise RepositoryStateError("BRO_TASK_LOCK_LEDGER must be absolute")
    if path.exists() and path.is_symlink():
        raise RepositoryStateError("BRO_TASK_LOCK_LEDGER may not be a symlink")
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return resolved
    raise RepositoryStateError("BRO_TASK_LOCK_LEDGER must be outside repository")


def _worktree_lock_path(root: pathlib.Path) -> pathlib.Path:
    ledger = _lock_ledger(root)
    key = hashlib.sha256(_normal(root).encode("utf-8")).hexdigest()
    path = ledger / f"{key}.json"
    if path.exists() and path.is_symlink():
        raise RepositoryStateError("active task lock may not be a symlink")
    if path.resolve(strict=False).parent != ledger:
        raise RepositoryStateError("active task lock escaped ledger")
    return path


def _load_lock(root: pathlib.Path) -> dict[str, Any]:
    path = _worktree_lock_path(root)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RepositoryStateError("active worktree lock is missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RepositoryStateError(f"active worktree lock is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise RepositoryStateError("active worktree lock must be an object")
    return value


def verify_repository_binding(
    task: dict[str, Any],
    *,
    agent_id: str,
    session_id: str,
    root: pathlib.Path = ROOT,
    cwd: pathlib.Path | None = None,
) -> RepositoryState:
    repository = task.get("repository")
    if not isinstance(repository, dict):
        raise RepositoryStateError("task repository binding is missing")
    if not agent_id or not session_id:
        raise RepositoryStateError("agent/session binding is required")

    state = resolve_state(root, cwd)
    expected_root = pathlib.Path(str(repository.get("worktree") or "")).expanduser().resolve()
    if _normal(state.root) != _normal(expected_root):
        raise RepositoryStateError("task worktree does not match runtime root")

    registered = {
        _normal(pathlib.Path(item["worktree"])): item
        for item in worktrees(state.root)
        if item.get("worktree")
    }
    if _normal(state.root) not in registered:
        raise RepositoryStateError("runtime root is not a registered Git worktree")

    expected_branch = str(repository.get("branch") or "")
    if expected_branch in {"main", "master"}:
        raise RepositoryStateError("canonical main checkout is denied for mutation")
    if state.branch != expected_branch:
        raise RepositoryStateError("task branch does not match current worktree branch")

    if state.head_sha != str(repository.get("base_commit") or ""):
        raise RepositoryStateError("task base_commit does not match current HEAD")
    if state.tree_identity != str(repository.get("tree_identity") or ""):
        raise RepositoryStateError("task tree_identity does not match current tree")

    lock = _load_lock(state.root)
    required = {
        "schema": 1,
        "status": "active",
        "task_id": task.get("task_id"),
        "agent_id": task.get("agent_id"),
        "session_id": session_id,
        "worktree": _normal(state.root),
        "branch": state.branch,
        "head_sha": state.head_sha,
        "tree_identity": state.tree_identity,
    }
    if agent_id != task.get("agent_id"):
        raise RepositoryStateError("runtime agent does not match task agent")
    for key, expected in required.items():
        actual = lock.get(key)
        if key == "worktree" and isinstance(actual, str):
            actual = _normal(pathlib.Path(actual))
        if actual != expected:
            raise RepositoryStateError(f"active worktree lock binding mismatch: {key}")
    return state
