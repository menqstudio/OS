"""Minimal FD-only governed executor launcher.

The production deployment may replace this with the pinned privileged launcher.  This
reference launcher enforces the same process contract for tests and local packaging:
exact input descriptors become read-only FDs 3/4/5, stdout is FD 1 (the recorder's
bounded pipe), and no artifact bytes are placed in argv or environment.
"""
from __future__ import annotations

import fcntl
import os
import stat
import sys


def _source_fd(name: str) -> int:
    raw = os.environ.pop(name, None)
    if raw is None or not raw.isdecimal():
        raise SystemExit(f"missing {name}")
    fd = int(raw)
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        raise SystemExit(f"{name} is not a regular file")
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    if flags & os.O_ACCMODE != os.O_RDONLY:
        raise SystemExit(f"{name} is not read-only")
    os.lseek(fd, 0, os.SEEK_SET)
    return fd


def main(argv: list[str]) -> int:
    if not argv:
        raise SystemExit("executor command required")
    sources = [_source_fd(n) for n in ("BROPS_LAUNCH_SYSTEM_FD", "BROPS_LAUNCH_HISTORY_FD", "BROPS_LAUNCH_CONFIG_FD")]
    for source, target in zip(sources, (3, 4, 5)):
        if source != target:
            os.dup2(source, target, inheritable=True)
        else:
            os.set_inheritable(target, True)
        os.lseek(target, 0, os.SEEK_SET)
    # The executor receives only the canonical input FDs and output/stderr.  Close the
    # original duplicate descriptors after installing 3/4/5.
    for source in sources:
        if source not in (3, 4, 5):
            try:
                os.close(source)
            except OSError:
                pass
    os.execvpe(argv[0], argv, os.environ)
    return 127


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
