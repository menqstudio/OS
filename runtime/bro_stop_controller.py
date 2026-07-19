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


def _iter_proc_pids():
    """Yield the numeric pids currently under /proc; nothing if /proc is absent."""
    try:
        names = os.listdir("/proc")
    except OSError:
        return
    for name in names:
        if name.isdigit():
            yield int(name)


def _proc_state_and_pgrp(pid: int) -> tuple[str, int] | None:
    """(state_char, pgrp) from /proc/<pid>/stat, or None if the pid is gone."""
    try:
        data = pathlib.Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    # /proc/<pid>/stat: "<pid> (<comm>) <state> <ppid> <pgrp> ...". comm may contain
    # spaces and parens, so split on the LAST ') ' and index the numeric tail.
    try:
        tail = data.rsplit(") ", 1)[1].split()
        return tail[0], int(tail[2])
    except (IndexError, ValueError):
        return None


def _group_has_live_member(pgid: int) -> bool:
    """True if any process in group `pgid` is present and not a zombie/dead.

    Scanning every process — not only the leader pid — is what closes the liveness
    false negative. A process group outlives its leader: once the leader exits and
    is reaped, /proc/<pgid> is gone, yet a surviving child still carries the group
    and killpg(0) still succeeds. Checking the leader's /proc entry alone would
    then report the group dead while orphaned grandchildren keep running — exactly
    the un-stopped state STOP exists to prevent.
    """
    for pid in _iter_proc_pids():
        info = _proc_state_and_pgrp(pid)
        if info is None:
            continue
        state, pgrp = info
        if pgrp == pgid and state not in ("Z", "X", "x"):
            return True
    return False


def is_group_alive(pgid: int) -> bool:
    """True if the group still has a live (non-zombie) member signallable by us.

    killpg(0) only proves the kernel still knows the group id — it also succeeds
    for a group whose sole survivor is an un-reaped zombie. A positive kernel check
    is therefore confirmed by scanning /proc for at least one live, non-zombie
    member of the group; a group with no live member counts as stopped.
    """
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but we cannot signal it: alive and, for our purposes, un-stoppable.
        return True
    return _group_has_live_member(pgid)


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
