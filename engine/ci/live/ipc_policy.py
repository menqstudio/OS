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


def read_root_owned_json(path: str, *, error: type, what: str, label: str = ""):
    """Parse a ROOT-OWNED, non-group/other-writable JSON file, checked on the OPEN descriptor.

    The ONE implementation of that rule in the live kits. ``run_ladder_supervisor.load_tcb_json``
    carried a second copy "with the same rule and the same reasoning" (its words), and the two
    had already diverged: this one named ``os.O_NOFOLLOW`` and wrapped a failed open and a
    malformed document in its own error, that one looked the flag up and let ``OSError`` and
    ``JSONDecodeError`` escape raw.

    The §2.5 owner/mode floor is measured with ``fstat`` on the descriptor rather than by a
    second ``stat(path)``, so a swap between the check and the read cannot change what was
    measured. ``O_NOFOLLOW``/``O_CLOEXEC`` are looked up rather than named so the module stays
    importable off Linux, where the services can still be constructed and driven directly; on
    the only platform they SERVE on, both always exist. Every refusal is ``error``; ``what``
    describes the file ("the IPC policy") and ``label`` is the caller's prefix ("supervisor: ").
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise error(f"{label}cannot open {what} {path}: {exc}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise error(f"{label}{what} {path} is not a regular file")
        if info.st_uid != 0:
            raise error(
                f"{label}{what} {path} is owned by uid {info.st_uid}, not root; a document a service "
                "account can rewrite authorizes whatever it likes")
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise error(f"{label}{what} {path} is group/other-writable")
        with os.fdopen(fd, "r", encoding="utf-8") as f:
            fd = -1  # ownership moved to the file object
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise error(f"{label}{what} {path} is malformed: {exc}") from exc
    finally:
        if fd >= 0:
            os.close(fd)


def load_allowed_peer_uid(path: str, service: str) -> int:
    """Return the single UID permitted to connect to ``service``.

    Custody is :func:`read_root_owned_json`'s; what is decided here is the document's meaning.
    """
    document = read_root_owned_json(path, error=IpcPolicyError, what="the IPC policy",
                                    label=f"{service}: ")
    if not isinstance(document, dict):
        raise IpcPolicyError(f"{service}: {path} is not a brops.ipc-policy.v1 document")
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
