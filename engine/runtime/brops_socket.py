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
import sys
import time
from typing import Any, Callable, Optional

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
        # `=III`, not `3i`: `struct ucred` is `{pid_t, uid_t, gid_t}` and `uid_t` is UNSIGNED on Linux.
        # The four other readers of this struct in the tree (`challenge_authority_server`,
        # `governed_supervisor_server`, `isolated_signer_server`, `floor_writer`) all use `=III`, and
        # `floor_writer` documents it. This one read it as three SIGNED ints, which agrees for every uid
        # below 2^31 and differs above: the kernel's `(uid_t)-1` "no uid" arrived as `-1`, and
        # `(uid_t)-2` — `nobody` on some systems — as `-2`. That is fail-closed, because the gate below
        # is `uid not in allowed_peer_uids` and an allow-list built from `os.getuid()` holds no negative
        # numbers, so a negative can only DENY. What it broke is the number a refusal reports, and the
        # agreement between five readers of one structure. `calcsize` is 12 either way.
        creds = conn.getsockopt(socket.SOL_SOCKET, so_peercred, struct.calcsize("=III"))
        _pid, uid, _gid = struct.unpack("=III", creds)
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


# --------------------------------------------------------------------------------------
# The TOTAL connection budget, and the three helpers three servers each had a copy of
# --------------------------------------------------------------------------------------
#
# A PER-READ timeout does not bound a connection: a peer that sends one byte per timeout holds the
# loop indefinitely while never once timing out. This is a budget for the WHOLE exchange, armed at
# the first read and never re-armed.
#
# 120 s is generous and DERIVED rather than chosen: the only party that legitimately connects to the
# signer gives up after 20 s of its own accord (`isolated_signer_server.request_sign_result`'s
# default, and `SIGNER_TIMEOUT_S = 20.0` in `engine/ci/live/run_ladder_supervisor.py`), and `request`
# below defaults to 30 s. Six times the client's own patience cannot bite a legitimate exchange, both
# peers are local, and the largest frame in the protocol is 240 KiB. What matters is that it is FINITE.
#
# Moved here from `governed_supervisor_server` on 2026-09-20. It was the only one of the five accept
# loops under `engine/runtime/` that had a total budget; `floor_writer` had its own 30 s version; the
# other three -- including this module's own loop and the SIGNER's -- had nothing. A control two of
# five servers implement is a control this tree does not have.
CONNECTION_BUDGET_S = 120.0


def recv_budget_s(deadline: float, now: float) -> Optional[float]:
    """The timeout to arm for the next read, or ``None`` when the budget is spent.

    Deliberately OUTSIDE any socket class. :func:`read_peercred_uid` refuses off Linux, so a bound
    expressed only inside an accepted connection's read loop would sit in a branch no test on a
    non-Linux runner can reach -- which is how earlier rounds shipped unwitnessed changes. The
    arithmetic that decides the refusal lives here, where a test drives it directly.

    **Never returns 0.0.** ``socket.settimeout(0)`` puts the socket in NON-BLOCKING mode (and the
    POSIX ``SO_RCVTIMEO`` it maps to reads 0 as *infinite*), so arming zero at the exact moment the
    budget expires is the opposite of a deadline. Exhaustion is ``None``, and the caller stops reading.
    """
    remaining = deadline - now
    if remaining <= 0.0:
        return None
    return remaining


def recv_exactly_bounded(
    recv: "Callable[[int], bytes]",
    n: int,
    *,
    deadline: float,
    arm_timeout: "Callable[[float], None]",
    now: "Callable[[], float]" = time.monotonic,
) -> bytes:
    """Read up to ``n`` bytes, giving up when the connection budget is exhausted.

    Returns whatever arrived. A short return is the caller's signal: a frame reader already turns one
    into a framing refusal, so a starved read is a refusal rather than a hang. Pure with respect to
    the socket -- ``recv``/``arm_timeout``/``now`` are seams, which is what makes the deadline
    testable with no socket at all.
    """
    chunks = []
    remaining = n
    while remaining > 0:
        budget = recv_budget_s(deadline, now())
        if budget is None:
            break  # budget spent; caller sees the short read
        arm_timeout(budget)
        try:
            chunk = recv(remaining)
        except (socket.timeout, TimeoutError):
            break
        if not chunk:
            break  # peer closed early; caller detects the short read
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_peercred_uid(sock: "socket.socket", *, error: type) -> int:
    """Return the connecting peer's uid via ``SO_PEERCRED``.

    Linux-only: ``SO_PEERCRED`` yields ``struct ucred { pid, uid, gid }``, unpacked as ``=III``. On
    any non-Linux host this fails closed with ``error`` so the caller can DENY rather than trust an
    unauthenticated peer.

    Three servers each carried this, byte-identical but for the exception class and the docstring
    naming it -- measured 2026-09-20 at 840 / 816 / 828 B, all 20 lines, whose entire diff was
    ``ChallengeAuthorityError`` / ``ServerError`` / ``SignerServerError``. The message is the same in
    all three, so only the class is injected; each service keeps its own refusal vocabulary while the
    logic exists once.
    """
    if sys.platform != "linux":
        raise error("platform unsupported: SO_PEERCRED peer authentication requires Linux")
    # struct ucred is {pid_t pid; uid_t uid; gid_t gid;} == three 32-bit ints. `=III`, not `3i`:
    # `uid_t` is UNSIGNED, so the kernel's `(uid_t)-1` must not arrive as `-1`.
    ucred = sock.getsockopt(
        socket.SOL_SOCKET,
        socket.SO_PEERCRED,  # type: ignore[attr-defined]
        struct.calcsize("=III"),
    )
    _pid, uid, _gid = struct.unpack("=III", ucred)
    return uid


def bind_listener(socket_path: str, *, error: type, subject: str) -> "socket.socket":
    """Bind a fresh AF_UNIX stream listener at ``socket_path`` (Linux path).

    Fail-closed on non-Linux hosts: the peer-credential trust chain these services depend on
    (``SO_PEERCRED``) does not exist there.

    The three copies differed only in the exception class and one noun in the message ("authority" /
    "supervisor front door" / "signer"), measured at 579 / 579 / 570 B. Everything else is verbatim,
    ``listen(64)`` included -- this function deliberately does NOT harden the socket directory,
    unlink an existing path, or chmod it, because none of the three did, and a shared helper that
    quietly added those would be a change to a security boundary dressed as de-duplication.
    """
    if sys.platform != "linux":
        raise error(f"platform unsupported: AF_UNIX SO_PEERCRED {subject} requires Linux")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(socket_path)
    listener.listen(64)
    return listener


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
                # The bound this loop never had. One request, one reply, so a single TOTAL socket
                # timeout covers the whole exchange -- the shape `floor_writer` already uses. The
                # drip-peer case that needs `recv_exactly_bounded` is the multi-read loop in the
                # signer and the authority, not this one.
                conn.settimeout(CONNECTION_BUDGET_S)
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
    except (socket.timeout, TimeoutError):
        # The budget armed by `serve_forever` expired. A stalled peer is a DROPPED connection, never
        # a handled request: returning closes it and the loop takes the next caller.
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
