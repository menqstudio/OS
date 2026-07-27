"""AF_UNIX front door for the desktop-challenge-authority (Wave 3b-1B, rev-30 §2.1).

The PURE authority logic lives in ``challenge_authority`` (PendingStore,
validate_create_pending, peer_is_broker, issue_challenge). This module is the
socket wiring ONLY: it binds a unix-domain socket, authenticates each connecting
peer by ``SO_PEERCRED`` uid, allowlists ONLY the broker uid (§2.1: renderer and
sidecar are DENIED on both messages), then reads exactly one length-prefixed
JSON frame, dispatches ``create-pending`` / ``issue`` into the pure core, and
writes the framed reply.

Trust-boundary properties enforced here (all fail-closed):

  * peer authentication happens at accept time via the OS (``SO_PEERCRED``);
    a non-broker peer is refused BEFORE any frame is read.
  * the request frame is length-prefixed (4-byte big-endian) and hard-bounded
    to ``MAX_FRAME_BYTES`` (8192); an oversize/short/truncated frame is refused.
  * the socket loop takes an injectable ``accept_one`` so the deny / bounds /
    dispatch behaviour is testable WITHOUT a real socket.

Only the Python standard library is used. ``SO_PEERCRED`` is Linux-only and is
gated behind a platform check so importing this module never fails elsewhere.
"""

from __future__ import annotations

import json
import socket
import struct
import sys
from typing import Any, Callable, Dict, Mapping, Optional

from challenge_authority import (
    AuthorityConfig,
    ChallengeAuthorityError,
    PendingStore,
    issue_challenge,
    peer_is_broker,
    validate_create_pending,
)

# ---------------------------------------------------------------------------
# Wire framing constants (§2.1 creation channel)
# ---------------------------------------------------------------------------

# 4-byte big-endian unsigned length prefix, then the JSON body.
LENGTH_PREFIX_BYTES = 4
# Hard upper bound on a single request/reply body. A create-pending / issue
# request is tiny; anything larger is a malformed / hostile frame -> refuse.
MAX_FRAME_BYTES = 8192

OP_CREATE_PENDING = "create-pending"
OP_ISSUE = "issue"


class FrameError(ChallengeAuthorityError):
    """Raised on any framing violation (oversize, short, truncated, non-JSON)."""


# ---------------------------------------------------------------------------
# Peer credential resolution (Linux SO_PEERCRED; fail-closed elsewhere)
# ---------------------------------------------------------------------------


def read_peercred_uid(sock: "socket.socket") -> int:
    """Return the connecting peer's uid via ``SO_PEERCRED``.

    Linux-only: ``SO_PEERCRED`` yields ``struct ucred { pid, uid, gid }`` which
    we unpack as ``=III``. On any non-Linux host this fails closed with a
    ``ChallengeAuthorityError`` so the caller can DENY rather than trust an
    unauthenticated peer.
    """
    if sys.platform != "linux":
        raise ChallengeAuthorityError(
            "platform unsupported: SO_PEERCRED peer authentication requires Linux"
        )
    # struct ucred is {pid_t pid; uid_t uid; gid_t gid;} == three 32-bit ints.
    ucred = sock.getsockopt(
        socket.SOL_SOCKET,
        socket.SO_PEERCRED,  # type: ignore[attr-defined]
        struct.calcsize("=III"),
    )
    _pid, uid, _gid = struct.unpack("=III", ucred)
    return uid


# ---------------------------------------------------------------------------
# Connection abstraction (real socket + injectable fake share this shape)
# ---------------------------------------------------------------------------


class SocketPeerConn:
    """Adapter around a live accepted socket exposing the duck-typed shape the
    server loop consumes: ``peer_uid``, ``recv_exactly``, ``send_all``,
    ``close``.

    The peer uid is captured ONCE, at accept time, from the kernel — it is not
    caller-supplied and cannot be spoofed over the wire.
    """

    def __init__(self, sock: "socket.socket") -> None:
        self._sock = sock
        self.peer_uid = read_peercred_uid(sock)

    def recv_exactly(self, n: int) -> bytes:
        chunks = []
        remaining = n
        while remaining > 0:
            chunk = self._sock.recv(remaining)
            if not chunk:
                break  # peer closed early; caller detects the short read
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def send_all(self, data: bytes) -> None:
        self._sock.sendall(data)

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Framing (length-prefixed, bounded)
# ---------------------------------------------------------------------------


def read_frame(conn: Any) -> bytes:
    """Read exactly one length-prefixed frame, bounded to ``MAX_FRAME_BYTES``.

    Fail-closed on a short header, a zero/oversize declared length, or a
    truncated body.
    """
    header = conn.recv_exactly(LENGTH_PREFIX_BYTES)
    if len(header) != LENGTH_PREFIX_BYTES:
        raise FrameError("short length prefix")
    length = int.from_bytes(header, "big")
    if length == 0:
        raise FrameError("empty frame rejected")
    if length > MAX_FRAME_BYTES:
        raise FrameError(
            "frame length %d exceeds bound %d" % (length, MAX_FRAME_BYTES)
        )
    body = conn.recv_exactly(length)
    if len(body) != length:
        raise FrameError("truncated frame body")
    return body


def write_frame(conn: Any, payload: bytes) -> None:
    """Write one length-prefixed frame. The reply is authority-built and small;
    an over-bound reply is a programming error, not attacker input, so we still
    refuse it rather than emit an un-framable blob."""
    if len(payload) > MAX_FRAME_BYTES:
        raise FrameError("reply exceeds frame bound")
    conn.send_all(len(payload).to_bytes(LENGTH_PREFIX_BYTES, "big") + payload)


def _encode_reply(reply: Mapping[str, Any]) -> bytes:
    return json.dumps(reply, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# Dispatch (thin adapter onto the pure core; no new authority logic)
# ---------------------------------------------------------------------------


def dispatch(
    request: Any,
    store: PendingStore,
    config: AuthorityConfig,
    sign_fn: Callable[[bytes], str],
    clock_ms: Callable[[], int],
) -> Dict[str, Any]:
    """Route one decoded request into the pure authority core.

    ``create-pending`` validates the fixed shape and stores a row; ``issue``
    one-time-consumes the row and returns the signed challenge. Turn facts enter
    ONLY through ``validate_create_pending`` — never as arbitrary bytes.
    """
    if not isinstance(request, Mapping):
        raise ChallengeAuthorityError("request body must be a JSON object")
    op = request.get("op")
    if op == OP_CREATE_PENDING:
        # Pass the wire body (minus the routing key) straight to the fixed-shape
        # validator: an arbitrary/extra field is REJECTED, never silently
        # dropped, so hostile bytes cannot ride in past the trust door (§2.1).
        fields = {k: v for k, v in request.items() if k != "op"}
        validated = validate_create_pending(fields)
        pending_id = store.create_pending(validated)
        return {"ok": True, "op": OP_CREATE_PENDING, "pending_challenge_id": pending_id}
    if op == OP_ISSUE:
        pending_id = request.get("pending_challenge_id")
        if not isinstance(pending_id, str) or not pending_id:
            raise ChallengeAuthorityError("issue requires a pending_challenge_id string")
        row = store.consume(pending_id)
        challenge = issue_challenge(row, config, sign_fn, clock_ms)
        return {"ok": True, "op": OP_ISSUE, "challenge": challenge}
    raise ChallengeAuthorityError("unknown op %r" % (op,))


# ---------------------------------------------------------------------------
# Per-connection handling (peer-auth -> frame -> dispatch -> framed reply)
# ---------------------------------------------------------------------------


def handle_connection(
    conn: Any,
    allowed_broker_uid: int,
    store: PendingStore,
    config: AuthorityConfig,
    sign_fn: Callable[[bytes], str],
    clock_ms: Callable[[], int],
) -> Dict[str, Any]:
    """Authenticate the peer, read one bounded frame, dispatch, and write the
    framed reply. Returns the reply object (also useful for tests). Never raises
    on hostile input — every failure becomes a fail-closed error reply.
    """
    peer_uid = getattr(conn, "peer_uid", None)
    # §2.1: allowlist ONLY the broker uid; refuse BEFORE reading any frame.
    if not peer_is_broker(peer_uid, allowed_broker_uid):
        reply = {"ok": False, "error": "peer not authorized"}
        _try_write(conn, reply)
        return reply

    try:
        raw = read_frame(conn)
        request = json.loads(raw.decode("utf-8"))
        reply = dispatch(request, store, config, sign_fn, clock_ms)
    except (FrameError, ChallengeAuthorityError, ValueError, UnicodeDecodeError) as exc:
        reply = {"ok": False, "error": str(exc)}

    _try_write(conn, reply)
    return reply


def _try_write(conn: Any, reply: Mapping[str, Any]) -> None:
    try:
        write_frame(conn, _encode_reply(reply))
    except OSError:
        pass  # peer already gone; nothing to do, connection is closed by loop


# ---------------------------------------------------------------------------
# Socket loop (injectable accept_one -> testable without a real socket)
# ---------------------------------------------------------------------------


def serve_forever(
    accept_one: Callable[[], Optional[Any]],
    allowed_broker_uid: int,
    store: PendingStore,
    config: AuthorityConfig,
    sign_fn: Callable[[bytes], str],
    clock_ms: Callable[[], int],
) -> None:
    """Drive the accept loop. ``accept_one`` returns the next connection (any
    object with ``peer_uid`` / ``recv_exactly`` / ``send_all`` / ``close``) or
    ``None`` to stop. A real deployment passes a socket-backed acceptor; a test
    passes a fake that yields ``SocketPeerConn``-shaped stand-ins.

    A single hostile connection never tears down the loop: each is handled in
    isolation and always closed.
    """
    while True:
        conn = accept_one()
        if conn is None:
            return
        try:
            handle_connection(conn, allowed_broker_uid, store, config, sign_fn, clock_ms)
        finally:
            try:
                conn.close()
            except OSError:
                pass


def bind_listener(socket_path: str) -> "socket.socket":
    """Bind a fresh AF_UNIX stream listener at ``socket_path`` (Linux path).

    Fail-closed on non-Linux hosts: the peer-credential trust chain this service
    depends on (``SO_PEERCRED``) does not exist there.
    """
    if sys.platform != "linux":
        raise ChallengeAuthorityError(
            "platform unsupported: AF_UNIX SO_PEERCRED authority requires Linux"
        )
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(socket_path)
    listener.listen(64)
    return listener


def accept_socket_conn(listener: "socket.socket") -> SocketPeerConn:
    """Accept one connection and resolve its peer uid from the kernel."""
    sock, _addr = listener.accept()
    return SocketPeerConn(sock)
