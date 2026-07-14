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
        digest.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(path.read_bytes()).digest())
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


def resolve_state(root: pathlib.Path = ROOT, cwd: pathlib.Path | None = None) -> RepositoryState:
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
    ledger = os.getenv("BRO_TASK_LOCK_LEDGER")
    if not ledger:
        raise RepositoryStateError("missing external BRO_TASK_LOCK_LEDGER