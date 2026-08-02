"""AF_UNIX front door for the isolated receipt-signer (Wave 3b-1B, rev-30 §7 / §4.9).

The PURE signer logic lives in ``isolated_signer`` (``IsolatedSigner.sign_result``:
recompute-then-sign the flat ``brops.governed-receipt-envelope.v1`` payload after
verifying the supervisor attestation ITSELF). This module is the socket wiring
ONLY — the exact mirror of ``challenge_authority_server``: it binds a
unix-domain socket, authenticates each connecting peer by ``SO_PEERCRED`` uid,
allowlists ONLY the broker uid (renderer/sidecar are DENIED), reads exactly one
length-prefixed bounded JSON frame, dispatches the single ``sign-result`` op into
the signer, and writes the framed reply.

Crucially this stays a RECOMPUTE-then-sign authority, never a
``sign(arbitrary_bytes)`` oracle: the server passes the received verified inputs
straight to ``IsolatedSigner.sign_result``, which recomputes every store-derived
``*_sha256`` (``output_sha256``/``output_bytes``/``request_sha256``) from the
content-addressed store bytes and verifies the supervisor attestation over
``JCS(evidence)`` before it signs. The server invents NO signing logic and holds
NO key; it only frames the request and relays the signer's own
envelope-or-refusal.

Trust-boundary properties enforced here (all fail-closed):

  * peer authentication happens at accept time via the OS (``SO_PEERCRED``);
    a non-broker peer is refused BEFORE any frame is read.
  * the request frame is length-prefixed (4-byte big-endian) and hard-bounded
    to ``MAX_FRAME_BYTES``; an oversize/short/truncated frame is refused.
  * an unknown op, a malformed body, or ANY signer refusal (typed
    ``brops.governed-receipt-refusal.v1``) becomes a fail-closed error reply
    carrying the fixed reason — never a partial or unsigned success.
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
from typing import Any, Dict, Mapping, Optional

from isolated_signer import IsolatedSigner

# ---------------------------------------------------------------------------
# Wire framing constants (§7 signing channel)
# ---------------------------------------------------------------------------

# 4-byte big-endian unsigned length prefix, then the JSON body.
LENGTH_PREFIX_BYTES = 4
# Hard upper bound on a single request/reply body. A sign-request carries only
# content-addressed handles + small facts (the signer's own whole-request cap is
# 256 KiB); this outer frame bound sits comfortably above it so a well-formed
# request always reaches the signer's own oversize gate, while a truly gigantic
# frame is refused here before the body is ever read.
MAX_FRAME_BYTES = 512 * 1024

OP_SIGN_RESULT = "sign-result"


class SignerServerError(Exception):
    """Raised for server wiring faults (platform/peer-cred resolution)."""


class FrameError(SignerServerError):
    """Raised on any framing violation (oversize, short, truncated, non-JSON)."""


# ---------------------------------------------------------------------------
# Peer credential resolution (Linux SO_PEERCRED; fail-closed elsewhere)
# ---------------------------------------------------------------------------


def read_peercred_uid(sock: "socket.socket") -> int:
    """Return the connecting peer's uid via ``SO_PEERCRED``.

    Linux-only: ``SO_PEERCRED`` yields ``struct ucred { pid, uid, gid }`` which
    we unpack as ``=III``. On any non-Linux host this fails closed with a
    ``SignerServerError`` so the caller can DENY rather than trust an
    unauthenticated peer.
    """
    if sys.platform != "linux":
        raise SignerServerError(
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


def peer_is_broker(peer_uid: Any, allowed_broker_uid: Any) -> bool:
    """Return True IFF the connecting peer is the trusted broker UID.

    The signer's only accepted peer is the broker UID; every other peer
    (renderer/login uid, sidecar uid) is DENIED. A strict, fail-closed identity
    match — no ranges, no group membership. ``bool`` is excluded explicitly
    (it is an ``int`` subclass) so a stray ``True`` can never masquerade as a
    uid.
    """
    if not isinstance(peer_uid, int) or isinstance(peer_uid, bool):
        return False
    if not isinstance(allowed_broker_uid, int) or isinstance(allowed_broker_uid, bool):
        return False
    return peer_uid == allowed_broker_uid


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
    """Write one length-prefixed frame. The reply is signer-built and small; an
    over-bound reply is a programming error, not attacker input, so we still
    refuse it rather than emit an un-framable blob."""
    if len(payload) > MAX_FRAME_BYTES:
        raise FrameError("reply exceeds frame bound")
    conn.send_all(len(payload).to_bytes(LENGTH_PREFIX_BYTES, "big") + payload)


def _encode_reply(reply: Mapping[str, Any]) -> bytes:
    return json.dumps(reply, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# Dispatch (thin adapter onto the pure signer; no new signing logic)
# ---------------------------------------------------------------------------


def dispatch(request: Any, signer: IsolatedSigner) -> Dict[str, Any]:
    """Route one decoded request into ``IsolatedSigner.sign_result``.

    The single op ``sign-result`` carries the verified inputs as
    ``{"op": "sign-result", "sign_request": {protocol, attestation, evidence}}``.
    The nested ``sign_request`` is handed VERBATIM to the signer, which
    strict-validates it, verifies the supervisor attestation, recomputes every
    store-derived digest, and signs ``JCS(recomputed_payload)`` — the server adds
    no signing logic and never sees the private key.

    On a signed result the reply carries the flat 23-key ``payload`` and its
    ``signature`` exactly as the signer produced them. A typed signer refusal
    (``brops.governed-receipt-refusal.v1``) becomes a fail-closed error reply
    carrying the fixed ``reason``. An unknown op or non-object body is refused.
    """
    if not isinstance(request, Mapping):
        raise SignerServerError("request body must be a JSON object")
    op = request.get("op")
    if op != OP_SIGN_RESULT:
        raise SignerServerError("unknown op %r" % (op,))

    # The verified inputs enter ONLY as the nested sign_request; the signer's
    # own strict validator is the sole door for turn facts. We do not merge the
    # routing key into it (the signer rejects unknown top-level keys), and we
    # pass whatever the broker sent so the signer — not this wiring — decides
    # what is well-formed and attested.
    sign_request = request.get("sign_request")

    result = signer.sign_result(sign_request)

    if result.get("status") == "signed":
        return {
            "ok": True,
            "op": OP_SIGN_RESULT,
            "artifact_type": result["artifact_type"],
            "payload": result["payload"],
            "signature": result["signature_b64"],
        }

    # Any non-signed outcome is a typed fail-closed refusal — never a partial
    # success. Surface the fixed refusal reason + artifact_type to the broker.
    return {
        "ok": False,
        "op": OP_SIGN_RESULT,
        "error": "signer refused",
        "reason": result.get("reason"),
        "artifact_type": result.get("artifact_type"),
    }


# ---------------------------------------------------------------------------
# Per-connection handling (peer-auth -> frame -> dispatch -> framed reply)
# ---------------------------------------------------------------------------


def handle_connection(
    conn: Any,
    allowed_broker_uid: int,
    signer: IsolatedSigner,
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
        reply = dispatch(request, signer)
    except (FrameError, SignerServerError, ValueError, UnicodeDecodeError) as exc:
        reply = {"ok": False, "error": str(exc)}
        # Surface a typed reason if the raised error carried one.
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
    accept_one,
    allowed_broker_uid: int,
    signer: IsolatedSigner,
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
            handle_connection(conn, allowed_broker_uid, signer)
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
        raise SignerServerError(
            "platform unsupported: AF_UNIX SO_PEERCRED signer requires Linux"
        )
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(socket_path)
    listener.listen(64)
    return listener


def accept_socket_conn(listener: "socket.socket") -> SocketPeerConn:
    """Accept one connection and resolve its peer uid from the kernel."""
    sock, _addr = listener.accept()
    return SocketPeerConn(sock)
