"""STOP Controller v2 (Execution Surface kind=recovery).

Audit gap: the only halt mechanism was a per-builder timeout SIGKILL that reaped
just the direct child, leaving orphaned grandchildren alive and recording nothing
about what could not be stopped.

This controller tracks Bro-started processes by process GROUP (pgid). A supervised
process launched with start_new_session=True becomes its own group leader, so
signalling the group terminates the whole descendant tree, not only the direct
child. Any process that cannot be confirmed stopped is written as an incident to
the append-only audit ledger (L16) — un-stopped state is recorded, never silently
dropped.

Machine-local registry; pure standard library.
"""
from __future__ import annotations

import json
import os
import pathlib
import signal
import time

from bro_audit_log import append as audit_append


class StopError(ValueError):
    pass


def register(registry_path, task_id: str, pid: int, pgid: int) -> None:
    p = pathlib.Path(registry_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"task_id": task_id, "pid": int(pid), "pgid": int(pgid)}) + "\n")


def list_registered(registry_path) -> list[dict]:
    p = pathlib.Path(registry_path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _leader_state(pid: int) -> str | None:
    """Process state char from /proc, or None if the pid is gone. 'Z'/'X' == dead."""
    try:
        data = pathlib.Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    # /proc/<pid>/stat: "<pid> (<comm>) <state> ...". comm may contain spaces/parens,
    # so split on the LAST ') '.
    try:
        return data.rsplit(") ", 1)[1].split(" ", 1)[0]
    except IndexError:
        return None


def is_group_alive(pgid: int) -> bool:
    """True if the group still has a live (non-zombie) leader signallable by us.

    A reaped or zombie/defunct leader counts as stopped: killpg(0) still succeeds for
    an un-reaped zombie, so the kernel check alone would falsely report it alive.
    """
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but we cannot signal it: alive and, for our purposes, un-stoppable.
        return True
    state = _leader_state(pgid)  # pgid == group-leader pid by construction
    if state in (None, "Z", "X", "x"):
        return False
    return True


def terminate_group(pgid: int, grace_seconds: float = 2.0, poll: float = 0.05) -> bool:
    """SIGTERM the group, wait for graceful exit, then SIGKILL. Return True if stopped."""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return True  # already gone
    except PermissionError:
        return False  # cannot signal it
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if not is_group_alive(pgid):
            return True
        time.sleep(poll)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if not is_group_alive(pgid):
            return True
        time.sleep(poll)
    return not is_group_alive(pgid)


def stop_all(registry_path, audit_path, *, repo_root=None, grace_seconds: float = 2.0) -> dict:
    """Stop every registered process group; record every un-stopped one as an incident."""
    stopped, unstopped = [], []
    for entry in list_registered(registry_path):
        pgid = int(entry["pgid"])
        if terminate_group(pgid, grace_seconds=grace_seconds):
            stopped.append(entry)
        else:
            unstopped.append(entry)
            audit_append(
                audit_path,
                "unstopped-process",
                {"task_id": entry.get("task_id"), "pid": entry.get("pid"), "pgid": pgid,
                 "detail": "process group could not be confirmed stopped"},
                repo_root=repo_root,
            )
    return {"stopped": stopped, "unstopped": unstopped}
