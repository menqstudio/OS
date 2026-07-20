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

On Windows there are no POSIX process groups: `pgid` is the tree-root pid, the
tree is terminated with ``taskkill /T /F`` and liveness is confirmed against the
root pid via the Win32 process API. taskkill walks a parent-chain snapshot, so a
grandchild reparented after its parent died may escape it — the supervisor closes
that gap with a kill-on-close Job Object; here any group that cannot be confirmed
stopped is still reported un-stopped, never silently accepted. terminate_group
never raises: any OS/platform error is converted to "not confirmed stopped" so
stop_all always reaches the `unstopped-process` incident branch.

Machine-local registry; pure standard library.
"""
from __future__ import annotations

import json
import os
import pathlib
import signal
import subprocess
import time

from bro_audit_log import append as audit_append

_POSIX_GROUPS = hasattr(os, "killpg")


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


def _windows_pid_alive(pid: int) -> bool:
    """True unless the pid can be POSITIVELY confirmed exited.

    Win32 has no signal-0 probe (os.kill(pid, 0) on Windows unconditionally
    TerminateProcess-es the target), so liveness is read from the process object:
    a handle that cannot be opened means the pid is gone or already reaped; an
    exit code other than STILL_ACTIVE means it exited. Any query failure counts
    as alive — an unconfirmed stop must surface, not be assumed.
    """
    import ctypes

    process_query_limited_information = 0x1000
    error_access_denied = 5
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
    if not handle:
        # Access denied means the process exists but we may not query it — the
        # Windows analogue of killpg's PermissionError: alive and un-stoppable.
        # Every other open failure means the pid is gone.
        return ctypes.get_last_error() == error_access_denied
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True  # cannot prove it stopped
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _is_group_alive_posix(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but we cannot signal it: alive and, for our purposes, un-stoppable.
        return True
    return _group_has_live_member(pgid)


def is_group_alive(pgid: int) -> bool:
    """True if the group still has a live (non-zombie) member signallable by us.

    killpg(0) only proves the kernel still knows the group id — it also succeeds
    for a group whose sole survivor is an un-reaped zombie. A positive kernel check
    is therefore confirmed by scanning /proc for at least one live, non-zombie
    member of the group; a group with no live member counts as stopped.

    On Windows `pgid` is the tree-root pid and liveness is confirmed against that
    pid alone (grandchild coverage is the Job Object's task, see module docstring).
    """
    if _POSIX_GROUPS:
        return _is_group_alive_posix(pgid)
    return _windows_pid_alive(pgid)


def _terminate_group_posix(pgid: int, grace_seconds: float, poll: float) -> bool:
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


def _terminate_group_windows(pgid: int, grace_seconds: float, poll: float) -> bool:
    """Force-kill the tree rooted at `pgid` with taskkill /T /F and confirm it.

    There is no graceful phase: Windows has no SIGTERM analogue that a console
    child reliably observes, and STOP's contract is containment, not courtesy.
    taskkill exit code 128 ("no such process") is treated like ProcessLookupError,
    but the verdict is always the liveness probe, never taskkill's word for it.
    """
    subprocess.run(
        ["taskkill", "/T", "/F", "/PID", str(int(pgid))],
        capture_output=True, text=True,
    )
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if not is_group_alive(pgid):
            return True
        time.sleep(poll)
    return not is_group_alive(pgid)


def terminate_group(pgid: int, grace_seconds: float = 2.0, poll: float = 0.05) -> bool:
    """Terminate the tracked group/tree on any platform. Return True ONLY when the
    stop is positively confirmed.

    Never raises: an AttributeError on a platform without killpg, a missing
    taskkill, or any other OS error would previously escape before the caller's
    `unstopped-process` branch — the one moment the audit trail matters most. Any
    failure to stop OR to confirm is reported as False, so every caller's incident
    path fires instead of silently no-opping.
    """
    try:
        if _POSIX_GROUPS:
            return _terminate_group_posix(pgid, grace_seconds, poll)
        return _terminate_group_windows(pgid, grace_seconds, poll)
    except Exception:  # noqa: BLE001 — unconfirmed is un-stopped, never a crash
        return False


def stop_all(registry_path, audit_path, *, repo_root=None, grace_seconds: float = 2.0) -> dict:
    """Stop every registered process group; record every un-stopped one as an incident."""
    stopped, unstopped = [], []
    for entry in list_registered(registry_path):
        pgid = int(entry["pgid"])
        try:
            confirmed = terminate_group(pgid, grace_seconds=grace_seconds)
        except Exception:  # noqa: BLE001 — belt over terminate_group's own wrap
            confirmed = False
        if confirmed:
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
