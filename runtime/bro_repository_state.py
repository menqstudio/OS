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


def current_tree_identity(root: pathlib.Path) -> str:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    digest = hashlib.sha256()
    for item in raw.split(b"\0"):
        if not item:
            continue
        rel = item.decode("utf-8")
        path = root / rel
        digest.update(
            rel.encode("utf-8") + b"\0" + hashlib.sha256(path.read_bytes()).digest()
        )
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


def _load_lock(task_id: str) -> dict[str, Any]:
    raw = os.getenv("BRO_TASK_LOCK_LEDGER")
    if not raw:
        raise RepositoryStateError("missing external BRO_TASK_LOCK_LEDGER")

    ledger = pathlib.Path(raw).expanduser()
    if not ledger.is_absolute():
        raise RepositoryStateError("BRO_TASK_LOCK_LEDGER must be absolute")

    path = ledger / f"{task_id}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RepositoryStateError("active task lock is missing") from exc
    except json.JSONDecodeError as exc:
        raise RepositoryStateError(f"active task lock is malformed: {exc}") from exc

    if not isinstance(value, dict):
        raise RepositoryStateError("active task lock must be an object")
    return value


def verify_repository_binding(
    task: dict[str, Any],
    *,
    root: pathlib.Path = ROOT,
    cwd: pathlib.Path | None = None,
) -> RepositoryState:
    repository = task.get("repository")
    if not isinstance(repository, dict):
        raise RepositoryStateError("task repository binding is missing")

    state = resolve_state(root, cwd)
    expected_root = pathlib.Path(str(repository.get("worktree") or "")).expanduser().resolve()
    if state.root != expected_root:
        raise RepositoryStateError("task worktree does not match runtime root")

    registered = {
        pathlib.Path(item["worktree"]).resolve(): item
        for item in worktrees(state.root)
        if item.get("worktree")
    }
    entry = registered.get(state.root)
    if entry is None:
        raise RepositoryStateError("runtime root is not a registered Git worktree")

    expected_branch = str(repository.get("branch") or "")
    if expected_branch in {"main", "master"}:
        raise RepositoryStateError("canonical main checkout is denied for mutation")
    if state.branch != expected_branch:
        raise RepositoryStateError("task branch does not match current worktree branch")

    expected_head = str(repository.get("base_commit") or "")
    if state.head_sha != expected_head:
        raise RepositoryStateError("task base_commit does not match current HEAD")

    expected_tree = str(repository.get("tree_identity") or "")
    if state.tree_identity != expected_tree:
        raise RepositoryStateError("task tree_identity does not match current tree")

    lock = _load_lock(str(task.get("task_id") or ""))
    required = {
        "task_id": task.get("task_id"),
        "worktree": str(state.root),
        "branch": state.branch,
        "head_sha": state.head_sha,
        "tree_identity": state.tree_identity,
        "status": "active",
    }
    for key, expected in required.items():
        if lock.get(key) != expected:
            raise RepositoryStateError(f"active task lock binding mismatch: {key}")

    return state
