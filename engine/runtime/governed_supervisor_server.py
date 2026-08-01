"""AF_UNIX front door for the governed-supervisor (Wave 3b-1B, rev-30 §5).

The PURE acceptance/lease logic lives in ``governed_supervisor`` (``accept_open``
two-phase verify -> lease, and the ``launch_gate`` step-8a budget gate). This
module is the socket wiring ONLY: it binds a unix-domain socket, authenticates
each connecting peer by ``SO_PEERCRED`` uid, allowlists ONLY the broker uid
(the renderer and sidecar are DENIED, matching the challenge-authority front
door), then reads exactly one length-prefixed JSON frame, dispatches
``accept-open`` / ``launch-gate`` into the pure core, and writes the framed
reply.

Trust-boundary properties enforced here (all fail-closed):

  * peer authentication happens at accept time via the OS (``SO_PEERCRED``);
    a non-broker peer is refused BEFORE any frame is read.
  * the request frame is length-prefixed (4-byte big-endian) and hard-bounded
    to ``MAX_FRAME_BYTES`` (8192); an oversize/short/truncated frame is refused.
  * ``now_ms`` is NEVER taken from the wire — the supervisor's own clock
    (``clock_ms``) drives every expiry/budget check, so a caller cannot pick a
    favourable time. All other trust decisions stay inside ``governed_supervisor``:
    this module only marshals bytes and never fabricates a lease or a proceed.
  * the socket loop takes an injectable ``accept_one`` so the deny / bounds /
    dispatch behaviour is testable WITHOUT a real socket.

This is a THIN transport wrapper: it imports and calls the supervisor's real
logic and never re-decides authenticity, freshness, binding, or budget. A
:class:`governed_supervisor.Refusal` verdict is relayed as a fail-closed
``ok:false`` reply carrying the typed ``REFUSE_*`` reason; a supervisor-side
:class:`governed_supervisor.SupervisorError` (bad config / seam) and any framing
or request-shape fault likewise become fail-closed error replies.

Only the Python standard library is used. ``SO_PEERCRED`` is Linux-only and is
gated behind a platform check so importing this module never fails elsewhere.
The broker-allowlist predicate is reused from ``challenge_authority`` (the one
canonical, strict, fail-closed peer match) rather than reimplemented here.
"""

from __future__ import annotations

import json
import socket
import struct
import sys
from typing import Any, Callable, Dict, Mapping, Optional

from challenge_authority import peer_is_broker
from governed_supervisor import (
    Lease,
    LaunchProceed,
    Refusal,
    SupervisorConfig,
    SupervisorError,
    accept_open,
    launch_gate,
    recompute_request_sha256 as default_recompute_request_sha256,
)

# ---------------------------------------------------------------------------
# Wire framing constants (§5 supervisor front door — same shape as §2.1)
# ---------------------------------------------------------------------------

# 4-byte big-endian unsigned length prefix, then the JSON body.
LENGTH_PREFIX_BYTES = 4
# Hard upper bound on a single request/reply body. An accept-open (one signed
# challenge document) / launch-gate (one lease) request is small; anything
# larger is a malformed / hostile frame -> refuse.
MAX_FRAME_BYTES = 8192

OP_ACCEPT_OPEN = "accept-open"
OP_LAUNCH_GATE = "launch-gate"

# The exhaustive field set of a wire lease (mirrors governed_supervisor.Lease).
LEASE_FIELDS = (
    "lease_id",
    "execution_attempt_id",
    "lease_expires_at_ms",
    "launcher_executable_sha256",
    "executor_executable_sha256",
)


class ServerError(Exception):
    """A transport-level fault: malformed request body, bad lease shape, or an
    unknown op. Fail-closed, converted to an ``ok:false`` error reply — never a
    fabricated success."""


class FrameError(ServerError):
    """Raised on any framing violation (oversize, short, truncated, non-JSON)."""


# ---------------------------------------------------------------------------
# Peer credential resolution (Linux SO_PEERCRED; fail-closed elsewhere)
# ---------------------------------------------------------------------------


def read_peercred_uid(sock: "socket.socket") -> int:
    """Return the connecting peer's uid via ``SO_PEERCRED``.

    Linux-only: ``SO_PEERCRED`` yields ``struct ucred { pid, uid, gid }`` which
    we unpack as ``=III``. On any non-Linux host this fails closed with a
    ``ServerError`` so the caller can DENY rather than trust an unauthenticated
    peer.
    """
    if sys.platform != "linux":
        raise ServerError(
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
    """Write one length-prefixed frame. The reply is supervisor-built and small;
    an over-bound reply is a programming error, not attacker input, so we still
    refuse it rather than emit an un-framable blob."""
    if len(payload) > MAX_FRAME_BYTES:
        raise FrameError("reply exceeds frame bound")
    conn.send_all(len(payload).to_bytes(LENGTH_PREFIX_BYTES, "big") + payload)


def _encode_reply(reply: Mapping[str, Any]) -> bytes:
    return json.dumps(reply, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# Result marshalling (supervisor verdict -> fail-closed reply, never invented)
# ---------------------------------------------------------------------------


def _lease_to_dict(lease: Lease) -> Dict[str, Any]:
    return {
        "lease_id": lease.lease_id,
        "execution_attempt_id": lease.execution_attempt_id,
        "lease_expires_at_ms": lease.lease_expires_at_ms,
        "launcher_executable_sha256": lease.launcher_executable_sha256,
        "executor_executable_sha256": lease.executor_executable_sha256,
    }


def _refusal_reply(op: str, refusal: Refusal) -> Dict[str, Any]:
    # A refusal is a fail-closed verdict, NOT a success. It surfaces as ok:false
    # with the typed REFUSE_* reason so the broker sees the exact denial cause.
    return {
        "ok": False,
        "op": op,
        "reason": refusal.reason,
        "detail": refusal.detail,
        "error": refusal.detail,
    }


def _parse_lease(obj: Any) -> Lease:
    """Rebuild a :class:`Lease` from the wire ``lease`` object for a launch-gate
    re-check. Enforces the exhaustive fixed shape (extra/missing/mistyped ->
    ``ServerError``) BEFORE constructing, so a malformed lease can never reach
    the gate as a partially-typed object. The gate itself (in the pure core)
    still owns the budget decision — this only marshals bytes into the type it
    expects.
    """
    if not isinstance(obj, Mapping):
        raise ServerError("launch-gate requires a lease object")
    keys = set(obj.keys())
    allowed = set(LEASE_FIELDS)
    extra = keys - allowed
    if extra:
        raise ServerError("lease has unexpected field(s) %s" % sorted(extra))
    missing = allowed - keys
    if missing:
        raise ServerError("lease is missing field(s) %s" % sorted(missing))

    expires = obj["lease_expires_at_ms"]
    if not isinstance(expires, int) or isinstance(expires, bool):
        raise ServerError("lease_expires_at_ms must be an int (epoch ms)")
    for name in (
        "lease_id",
        "execution_attempt_id",
        "launcher_executable_sha256",
        "executor_executable_sha256",
    ):
        if not isinstance(obj[name], str) or not obj[name]:
            raise ServerError("%s must be a non-empty string" % name)

    return Lease(
        lease_id=obj["lease_id"],
        execution_attempt_id=obj["execution_attempt_id"],
        lease_expires_at_ms=expires,
        launcher_executable_sha256=obj["launcher_executable_sha256"],
        executor_executable_sha256=obj["executor_executable_sha256"],
    )


# ---------------------------------------------------------------------------
# Dispatch (thin adapter onto the pure core; no new trust logic)
# ---------------------------------------------------------------------------


def dispatch(
    request: Any,
    config: SupervisorConfig,
    verify_sig: Callable[[bytes, str], bool],
    recompute_request_sha256: Callable[[Mapping[str, Any]], str],
    clock_ms: Callable[[], int],
) -> Dict[str, Any]:
    """Route one decoded request into the pure supervisor core.

    ``accept-open`` runs the two-phase challenge verify and, on success, mints a
    lease; ``launch-gate`` re-checks a lease's remaining budget. The supervisor's
    own clock (``clock_ms``) supplies ``now_ms`` for BOTH — it is never read from
    the wire, so a caller cannot pick a favourable time. The signed challenge
    document and the lease enter ONLY through the typed ops, never as free bytes
    used for a trust decision.
    """
    if not isinstance(request, Mapping):
        raise ServerError("request body must be a JSON object")
    op = request.get("op")

    if op == OP_ACCEPT_OPEN:
        challenge_doc = request.get("challenge_doc")
        if not isinstance(challenge_doc, Mapping):
            raise ServerError("accept-open requires a challenge_doc object")
        # now_ms is the SUPERVISOR's clock, not the caller's (fail-closed).
        result = accept_open(
            challenge_doc,
            clock_ms(),
            config=config,
            verify_sig=verify_sig,
            recompute_request_sha256=recompute_request_sha256,
        )
        if isinstance(result, Lease):
            return {"ok": True, "op": OP_ACCEPT_OPEN, "lease": _lease_to_dict(result)}
        if isinstance(result, Refusal):
            return _refusal_reply(OP_ACCEPT_OPEN, result)
        # The pure core only ever returns Lease | Refusal; anything else is a
        # contract breach -> fail closed rather than relay an unknown object.
        raise SupervisorError("accept_open returned an unexpected result type")

    if op == OP_LAUNCH_GATE:
        lease = _parse_lease(request.get("lease"))
        result = launch_gate(lease, clock_ms())
        if isinstance(result, LaunchProceed):
            return {
                "ok": True,
                "op": OP_LAUNCH_GATE,
                "proceed": True,
                "lease": _lease_to_dict(result.lease),
            }
        if isinstance(result, Refusal):
            return _refusal_reply(OP_LAUNCH_GATE, result)
        raise SupervisorError("launch_gate returned an unexpected result type")

    raise ServerError("unknown op %r" % (op,))


# ---------------------------------------------------------------------------
# Per-connection handling (peer-auth -> frame -> dispatch -> framed reply)
# ---------------------------------------------------------------------------


def handle_connection(
    conn: Any,
    allowed_broker_uid: int,
    config: SupervisorConfig,
    verify_sig: Callable[[bytes, str], bool],
    recompute_request_sha256: Callable[[Mapping[str, Any]], str],
    clock_ms: Callable[[], int],
) -> Dict[str, Any]:
    """Authenticate the peer, read one bounded frame, dispatch, and write the
    framed reply. Returns the reply object (also useful for tests). Never raises
    on hostile input — every failure becomes a fail-closed error reply.
    """
    peer_uid = getattr(conn, "peer_uid", None)
    # Allowlist ONLY the broker uid; refuse BEFORE reading any frame.
    if not peer_is_broker(peer_uid, allowed_broker_uid):
        reply = {"ok": False, "error": "peer not authorized"}
        _try_write(conn, reply)
        return reply

    try:
        raw = read_frame(conn)
        request = json.loads(raw.decode("utf-8"))
        reply = dispatch(request, config, verify_sig, recompute_request_sha256, clock_ms)
    except (FrameError, ServerError, SupervisorError, ValueError, UnicodeDecodeError) as exc:
        reply = {"ok": False, "error": str(exc)}
        # Surface a typed refusal reason if the exception carried one (a Refusal
        # verdict is relayed via dispatch, not raised — this is for completeness).
        reason = getattr(exc, "reason", None)
        if isinstance(reason, str) and reason:
            reply["reason"] = reason

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
    config: SupervisorConfig,
    verify_sig: Callable[[bytes, str], bool],
    recompute_request_sha256: Callable[[Mapping[str, Any]], str],
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
            handle_connection(
                conn,
                allowed_broker_uid,
                config,
                verify_sig,
                recompute_request_sha256,
                clock_ms,
            )
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
        raise ServerError(
            "platform unsupported: AF_UNIX SO_PEERCRED supervisor front door requires Linux"
        )
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(socket_path)
    listener.listen(64)
    return listener


def accept_socket_conn(listener: "socket.socket") -> SocketPeerConn:
    """Accept one connection and resolve its peer uid from the kernel."""
    sock, _addr = listener.accept()
    return SocketPeerConn(sock)


# ``default_recompute_request_sha256`` is re-exported as the natural default
# binding seam for a real deployment (the supervisor's OWN canonical recompute).
__all__ = [
    "LENGTH_PREFIX_BYTES",
    "MAX_FRAME_BYTES",
    "OP_ACCEPT_OPEN",
    "OP_LAUNCH_GATE",
    "FrameError",
    "ServerError",
    "SocketPeerConn",
    "accept_socket_conn",
    "bind_listener",
    "default_recompute_request_sha256",
    "dispatch",
    "handle_connection",
    "read_frame",
    "serve_forever",
    "write_frame",
]
