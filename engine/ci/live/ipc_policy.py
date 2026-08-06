"""The per-service IPC peer-auth policy, loaded from a ROOT-OWNED file (audit F-10).

Every live service decides who may talk to it from ``allowed_broker_uid``, which used to be read
out of the shared ``config.json`` — the same world-readable file the broker reads its own knobs
from. That is also why the §2.5 TCB floor's ``*.ipc-policy`` artifacts had nothing to point at:
there was no IPC policy on disk to pin, only a field in a general config.

Each service now loads its own ``<service>.ipc-policy.json`` from the TCB directory. The file is
root-owned and non-writable, so the floor has a real artifact to measure and the peer-auth rule
has a custody story of its own. Fail-closed throughout: a missing, unreadable, malformed,
non-root-owned or writable policy raises, and a service with no policy does not serve.
"""

from __future__ import annotations

import json
import os
import stat


class IpcPolicyError(RuntimeError):
    pass


def load_allowed_peer_uid(path: str, service: str) -> int:
    """Return the single UID permitted to connect to ``service``.

    The §2.5 owner/mode floor is checked on the OPENED descriptor rather than by a second
    ``stat(path)``, so a swap between the check and the read cannot change what was measured.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise IpcPolicyError(f"{service}: cannot open the IPC policy {path}: {exc}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise IpcPolicyError(f"{service}: the IPC policy {path} is not a regular file")
        if info.st_uid != 0:
            raise IpcPolicyError(
                f"{service}: the IPC policy {path} is owned by uid {info.st_uid}, not root; a "
                "peer-auth rule a service account can rewrite authorizes whatever it likes")
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise IpcPolicyError(f"{service}: the IPC policy {path} is group/other-writable")
        with os.fdopen(fd, "r", encoding="utf-8") as f:
            fd = -1  # ownership moved to the file object
            document = json.load(f)
    except json.JSONDecodeError as exc:
        raise IpcPolicyError(f"{service}: the IPC policy {path} is malformed: {exc}") from exc
    finally:
        if fd >= 0:
            os.close(fd)

    if document.get("protocol") != "brops.ipc-policy.v1":
        raise IpcPolicyError(f"{service}: {path} is not a brops.ipc-policy.v1 document")
    if document.get("service") != service:
        raise IpcPolicyError(
            f"{service}: {path} names service {document.get('service')!r} — a policy issued for a "
            "different service must not authorize this one")
    peers = document.get("allowed_peer_uids")
    if not isinstance(peers, list) or len(peers) != 1 or not isinstance(peers[0], int) \
            or isinstance(peers[0], bool) or peers[0] < 0:
        raise IpcPolicyError(
            f"{service}: {path} must carry exactly one non-negative allowed_peer_uids entry")
    return peers[0]
