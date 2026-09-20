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
import time
import traceback
import brops_socket
from typing import Any, Callable, Dict, Mapping, Optional

from challenge_authority import (
    AuthorityConfig,
    ChallengeAuthorityError,
    PendingStore,
    issue_challenge_document,
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
    # Moved to `brops_socket.read_peercred_uid` on 2026-09-20. Three servers carried this
    # byte-identically but for the exception class -- measured at 840 / 816 / 828 B, all 20 lines,
    # whose entire diff was that class and the docstring naming it. The wrapper stays because the
    # NAME is this service's surface: `accept_socket_conn` and its tests reach it here.
    return brops_socket.read_peercred_uid(sock, error=ChallengeAuthorityError)


# ---------------------------------------------------------------------------
# Connection abstraction (real socket + injectable fake share this shape)
# ---------------------------------------------------------------------------


class SocketPeerConn:
    """Adapter around a live accepted socket exposing the duck-typed shape the
    server loop consumes: ``peer_uid``, ``recv_exactly``, ``send_all``,
    ``close``.

    The peer uid is captured ONCE, at accept time, from the kernel — it is not
    caller-supplied and cannot be spoofed over the wire.

    The connection also carries a TOTAL deadline (:data:`brops_socket.CONNECTION_BUDGET_S`), armed
    at construction and shared by both directions, so no peer can hold the serial accept loop.

    **Added 2026-09-20, and it was missing.** This class read `while remaining > 0: recv(remaining)`
    with no timeout of any kind, so a peer that connected and never completed a frame stalled the
    accept loop forever. `governed_supervisor_server` had already decided that may not happen (the
    same deadline, since audit R1) and `floor_writer` had decided it too (30 s); this file and the
    challenge authority had nothing — and this one is the SIGNER, whose own `serve_forever`
    docstring promises that "nothing a single peer can do may end" the loop. That promise was about
    an EXCEPTION; a stall is the same outcome by another road. A per-read timeout would not have
    been enough either: a peer sending one byte per timeout never times out, which is why the bound
    is a budget for the whole exchange rather than for one read.
    """

    def __init__(self, sock: "socket.socket", *,
                 budget_s: float = brops_socket.CONNECTION_BUDGET_S) -> None:
        self._sock = sock
        self.peer_uid = read_peercred_uid(sock)
        self._deadline = time.monotonic() + budget_s

    def recv_exactly(self, n: int) -> bytes:
        return brops_socket.recv_exactly_bounded(
            self._sock.recv, n,
            deadline=self._deadline, arm_timeout=self._sock.settimeout)

    def send_all(self, data: bytes) -> None:
        budget = brops_socket.recv_budget_s(self._deadline, time.monotonic())
        if budget is None:
            # The budget is spent. Writing under no timeout here would hand back, on the write
            # side, exactly the unbounded hold the read side just refused.
            raise FrameError("connection budget exhausted before the reply could be written")
        self._sock.settimeout(budget)
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
        # validator: an arbitrary/extra field (including a caller-supplied
        # request_sha256) is REJECTED, never silently dropped, so hostile bytes
        # cannot ride in past the trust door (§2.1).
        fields = {k: v for k, v in request.items() if k != "op"}
        validated = validate_create_pending(fields)
        # The install_id is CHECKED against the authority's own trusted config, not
        # taken on trust (audit A-01, 2026-08-14). It scopes the evidence-head
        # anti-rollback floor, so a caller that can choose it can bootstrap a fresh
        # bucket and re-present a rolled-back head.
        #
        # VALIDATED, not substituted. Overwriting the caller's value would keep the
        # floor honest and break something else: the supervisor recomputes
        # request_sha256 over the payload and `governed_turn_open` refuses when the
        # request's install_id differs from the signed one (`:487-488`), so a silent
        # substitution turns a deployment misconfiguration into a confusing failure
        # three hops away. This refuses at the door, by name, with the two values
        # withheld from the message -- the caller already knows what it sent, and the
        # configured value is not a fact it is entitled to learn by probing.
        if validated["install_id"] != config.install_id:
            raise ChallengeAuthorityError(
                "create-pending install_id does not match this deployment's configured install_id"
            )
        now = clock_ms()
        pending_id, pending_expires_at_ms = store.create_pending(validated, now)
        return {
            "ok": True,
            "op": OP_CREATE_PENDING,
            "pending_challenge_id": pending_id,
            "pending_expires_at_ms": pending_expires_at_ms,
        }
    if op == OP_ISSUE:
        pending_id = request.get("pending_challenge_id")
        if not isinstance(pending_id, str) or not pending_id:
            raise ChallengeAuthorityError("issue requires a pending_challenge_id string")
        # The authority resolves + issues from its OWN store: it signs a live
        # PENDING row ONCE (persisting the exact document) or replays a live
        # ISSUED row's stored document byte-for-byte (§2.1.1(d)/(f)).
        challenge = issue_challenge_document(store, pending_id, config, sign_fn, clock_ms)
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
        # Surface the typed §2.1 refusal reason (e.g. no_pending_row vs
        # pending_expired vs retry_conflict) when the core supplied one.
        reason = getattr(exc, "reason", None)
        if isinstance(reason, str) and reason:
            reply["reason"] = reason
    except Exception:  # noqa: BLE001 - the fail-closed backstop
        # Every EXPLICIT raise in ``challenge_authority`` is a
        # ``ChallengeAuthorityError`` (and ``FrameError`` subclasses it), so —
        # unlike ``isolated_signer_server`` — no sibling exception class of the
        # core is missing from the tuple above. What the tuple still cannot
        # promise is the docstring's "never raises": the INJECTED seams
        # (``sign_fn``, ``clock_ms``, ``id_fn``) may raise anything at all, and a
        # latent ``TypeError``/``KeyError`` would escape the same way. Either
        # tears down ``serve_forever`` with no refusal frame written, which is a
        # denial of service on the challenge authority. So anything else becomes
        # a fail-closed reply, with the detail going to the operator's stderr and
        # NOT to the broker.
        traceback.print_exc(file=sys.stderr)
        reply = {"ok": False, "error": "internal authority fault"}

    _try_write(conn, reply)
    return reply


def _try_write(conn: Any, reply: Mapping[str, Any]) -> None:
    try:
        write_frame(conn, _encode_reply(reply))
    except (OSError, FrameError, TypeError, ValueError):
        # peer already gone, or a reply we could not frame/encode. Either way the
        # connection is closed by the loop; never let the write path raise back
        # into ``handle_connection``'s contract.
        pass


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
        except Exception:  # noqa: BLE001 - one connection must never kill the loop
            # Belt to ``handle_connection``'s braces: the accept loop IS the
            # availability of the challenge authority, so nothing a single peer
            # can do may end it.
            traceback.print_exc(file=sys.stderr)
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - a failing close must not end the loop
                pass


def bind_listener(socket_path: str) -> "socket.socket":
    """Bind a fresh AF_UNIX stream listener at ``socket_path`` (Linux path).

    Fail-closed on non-Linux hosts: the peer-credential trust chain this service
    depends on (``SO_PEERCRED``) does not exist there.
    """
    # Moved to `brops_socket.bind_listener` on 2026-09-20; the three copies differed only in the
    # exception class and the noun in this message. `listen(64)` and the deliberate absence of any
    # directory hardening travelled with it unchanged.
    return brops_socket.bind_listener(
        socket_path, error=ChallengeAuthorityError, subject="authority")


def accept_socket_conn(listener: "socket.socket") -> SocketPeerConn:
    """Accept one connection and resolve its peer uid from the kernel."""
    sock, _addr = listener.accept()
    return SocketPeerConn(sock)
