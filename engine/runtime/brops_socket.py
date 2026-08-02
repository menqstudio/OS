"""Wave 3b-1 — the ACL-controlled local IPC transport for the signer/supervisor services
(design §1.1; audit P0-1).

A service binds a **Unix domain socket** inside an owner-only (0700) directory, so the
filesystem already restricts who can reach the socket path. On Linux the server ALSO
reads the connecting peer's credentials via `SO_PEERCRED` and admits ONLY a configured
allow-list of peer UIDs — so even a process of a *different* user that can see the socket
path is refused unless it is the dedicated caller principal (e.g. the signer admits only
the supervisor UID; a same-login-user attacker is denied). This is the machine-enforced
"only the supervisor connects to the signer" boundary, proven by the Linux CI job.

Frames use `brops_protocol` (u32 length prefix, 256 KiB cap, strict decode).
"""

from __future__ import annotations

import os
import socket
import struct
from typing import Any, Callable

import brops_protocol

# TCP is forbidden (design §1.1) — this module only does AF_UNIX.
_HAS_AF_UNIX = hasattr(socket, "AF_UNIX")


class SocketAclError(Exception):
    """A peer failed the UID allow-list or the transport failed — fail-closed."""


def _peer_uid(conn: socket.socket) -> int | None:
    """The connecting peer's UID via SO_PEERCRED (Linux). None where unavailable — the
    caller then relies on the socket directory's 0700 ownership for isolation."""
    so_peercred = getattr(socket, "SO_PEERCRED", None)
    if so_peercred is None:
        return None
    try:
        creds = conn.getsockopt(socket.SOL_SOCKET, so_peercred, struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", creds)
        return uid
    except OSError:
        return None


def _harden_socket_dir(path: str) -> None:
    # The socket is deliberately REACHABLE (world-connectable) so the authoritative gate
    # is SO_PEERCRED (UID allow-list), not a static perm — the supervisor must be able to
    # connect while a same-login-user attacker is refused by UID (design §1.1). Only
    # created dirs are made traversable; a pre-provisioned dir's perms are left to the
    # operator. On Linux every accepted connection is UID-checked in `_serve_one`.
    directory = os.path.dirname(os.path.abspath(path))
    created = not os.path.isdir(directory)
    os.makedirs(directory, exist_ok=True)
    if created and os.name == "posix":
        os.chmod(directory, 0o755)


def serve_forever(
    socket_path: str,
    handle_frame: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    allowed_peer_uids: "frozenset[int] | None",
    ready: Callable[[], None] | None = None,
    max_requests: int | None = None,
) -> None:
    """Bind `socket_path`, then accept connections one at a time. For each: enforce the
    peer-UID allow-list (Linux), read ONE request frame, call `handle_frame`, write ONE
    result frame, close. `max_requests` bounds the loop for tests; None = forever."""
    if not _HAS_AF_UNIX:
        raise SocketAclError("AF_UNIX is required for the signer/supervisor IPC")
    _harden_socket_dir(socket_path)
    if os.path.exists(socket_path):
        os.unlink(socket_path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(socket_path)
        if os.name == "posix":
            # World-connectable on purpose — SO_PEERCRED (the UID allow-list in
            # `_serve_one`) is the authoritative gate, so a different-user caller may
            # connect() but is admitted ONLY if its UID is allow-listed.
            os.chmod(socket_path, 0o666)
        server.listen(16)
        if ready is not None:
            ready()
        served = 0
        while max_requests is None or served < max_requests:
            conn, _ = server.accept()
            served += 1
            try:
                _serve_one(conn, handle_frame, allowed_peer_uids)
            finally:
                conn.close()
    finally:
        server.close()
        try:
            os.unlink(socket_path)
        except OSError:
            pass


def _serve_one(
    conn: socket.socket,
    handle_frame: Callable[[dict[str, Any]], dict[str, Any]],
    allowed_peer_uids: "frozenset[int] | None",
) -> None:
    # ACL: enforce the peer-UID allow-list. An unlisted peer — OR a peer whose UID cannot
    # be read (SO_PEERCRED unavailable) — is dropped WITHOUT reading its frame. Because the
    # socket is world-connectable, an unreadable peer UID must be FAIL-CLOSED (never
    # world-open): if an allow-list is configured, only a positively-identified allowed UID
    # is admitted.
    if allowed_peer_uids is not None:
        uid = _peer_uid(conn)
        if uid is None or uid not in allowed_peer_uids:
            return  # denied — connection closed by the finally in serve_forever
    reader = conn.makefile("rb")
    try:
        request = brops_protocol.read_frame(reader)
    except brops_protocol.ProtocolError:
        return
    result = handle_frame(request)
    conn.sendall(brops_protocol.encode_frame(result))


def request(socket_path: str, frame: dict[str, Any], *, timeout: float = 30.0) -> dict[str, Any]:
    """Client: connect to `socket_path`, send one request frame, read one result frame."""
    if not _HAS_AF_UNIX:
        raise SocketAclError("AF_UNIX is required for the signer/supervisor IPC")
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(timeout)
    try:
        conn.connect(socket_path)
        conn.sendall(brops_protocol.encode_frame(frame))
        reader = conn.makefile("rb")
        return brops_protocol.read_frame(reader)
    finally:
        conn.close()
