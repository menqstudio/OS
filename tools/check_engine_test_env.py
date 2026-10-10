#!/usr/bin/env python3
"""Does the counted engine-suite claim apply to the environment this is run in?

`config/counted-claims.json` says the engine suite runs 2741 tests, and names the machines it was
measured on. The eleventh audit (K-10) ran the documented command in a managed sandbox and got 14
failures and 70 errors — not 84 regressions, but an environment in which the suite cannot pass:
`AF_UNIX` bind returned EPERM and the temporary directory belonged to uid 65534. Nothing said so
before the run, so a true count read as a false claim.

This probes the facts that separated the two environments, before anyone runs the suite:

  0. Python finds a temporary directory it can write at all;
  1. an `AF_UNIX` stream socket can be bound, listened on and connected to in a fresh directory;
  2. a directory this process creates is owned by its effective uid and takes mode 0700;
  3. the system temporary directory is owned by root or by this process's uid — the custody code
     reads a sticky parent's owner (`bro_custody`), and a foreign owner changes its verdicts.

GREEN: the count is expected here. RED: it is NOT expected here, and each line names the fact;
failures in this environment are about the environment until shown otherwise. Either way the
verdict is printed beside the uid and platform, so a count can be quoted with where it holds.

What this does NOT establish: that these three are the ONLY environmental facts the suite needs.
They are the ones the audit observed. On Windows facts 1 and 3 are not what custody rests on, and
this reports that it has nothing to say rather than a verdict it has not earned.
"""

from __future__ import annotations

import os
import socket
import stat
import sys
import tempfile


def probe_unix_socket(directory: str) -> str | None:
    """None when an AF_UNIX stream socket works end to end in `directory`; else why not."""
    if not hasattr(socket, "AF_UNIX"):
        return "this Python has no AF_UNIX"
    path = os.path.join(directory, "probe.sock")
    server = client = None
    try:
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(1)
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(5)
        client.connect(path)
    except OSError as exc:
        return f"AF_UNIX bind/listen/connect failed: {exc.__class__.__name__}: {exc}"
    finally:
        for sock in (client, server):
            if sock is not None:
                sock.close()
    return None


def probe_owned_directory(directory: str, euid: int) -> str | None:
    """None when `directory`, which this process created, is ours and takes mode 0700."""
    try:
        os.chmod(directory, 0o700)
        info = os.stat(directory)
    except OSError as exc:
        return f"cannot chmod/stat a directory this process created: {exc}"
    if info.st_uid != euid:
        return f"a directory this process created is owned by uid {info.st_uid}, not its euid {euid}"
    mode = stat.S_IMODE(info.st_mode)
    if mode != 0o700:
        return f"a directory this process created reads back mode {mode:04o}, not 0700"
    return None


def probe_temp_owner(temp_root: str, euid: int) -> str | None:
    """None when the system temporary directory is owned by root or by this process."""
    try:
        owner = os.stat(temp_root).st_uid
    except OSError as exc:
        return f"cannot stat the temporary directory {temp_root}: {exc}"
    if owner not in (0, euid):
        return (f"the temporary directory {temp_root} is owned by uid {owner}, neither root nor "
                f"this process ({euid}); custody verdicts that read a parent's owner differ here")
    return None


def usable_temp_root() -> tuple[str | None, str | None]:
    """(directory, None), or (None, why) when Python finds no temporary directory it can write.

    Seen in the reviewer's read-only sandbox: `tempfile.gettempdir()` RAISES there, so the first
    version of this probe crashed in the one environment it was written to describe.
    """
    try:
        return tempfile.gettempdir(), None
    except OSError as exc:
        return None, f"no usable temporary directory: {exc}"


def problems(temp_root: str | None = None) -> list[str]:
    if temp_root is None:
        temp_root, why = usable_temp_root()
        if temp_root is None:
            return [why or "no usable temporary directory"]
    euid = os.geteuid()
    found: list[str] = []
    try:
        with tempfile.TemporaryDirectory(dir=temp_root) as fresh:
            for problem in (probe_unix_socket(fresh), probe_owned_directory(fresh, euid)):
                if problem:
                    found.append(problem)
    except OSError as exc:
        found.append(f"cannot create a directory under {temp_root}: {exc}")
    problem = probe_temp_owner(temp_root, euid)
    if problem:
        found.append(problem)
    return found


def main() -> int:
    if os.name != "posix":
        print(f"ENGINE TEST ENVIRONMENT: NOT JUDGED on {sys.platform} — this probe reads POSIX "
              "ownership and AF_UNIX, which are not what custody rests on here.")
        return 0
    where = f"{sys.platform}, uid {os.geteuid()}, temp {usable_temp_root()[0] or 'none'}"
    found = problems()
    if not found:
        print(f"ENGINE TEST ENVIRONMENT: GREEN — the counted engine-suite claim is expected here ({where}).")
        return 0
    print(f"ENGINE TEST ENVIRONMENT: RED — the counted engine-suite claim is NOT expected here ({where}).")
    for line in found:
        print(f"  - {line}")
    print("  Failures of the engine suite in this environment are about the environment until "
          "shown otherwise; see config/counted-claims.json for where the count was measured.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
