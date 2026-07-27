"""Offline tests for the AF_UNIX challenge-authority server wiring (rev-30 §2.1).

No real socket, no keys, no OS trust chain: a ``FakeConn`` supplies the peer uid
and a byte buffer, the store is a plain dict, the clock is fixed, and signing is
a stub. These exercise the three normative wiring behaviours:

  * a non-broker peer is DENIED before any frame is read (renderer/sidecar);
  * an oversize length-prefixed frame is refused (fail-closed on bounds);
  * a valid create-pending frame dispatches into the pure core and returns the
    minted pending_challenge_id.
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import json  # noqa: E402

from challenge_authority import (  # noqa: E402
    AuthorityConfig,
    PendingStore,
)
from challenge_authority_server import (  # noqa: E402
    LENGTH_PREFIX_BYTES,
    MAX_FRAME_BYTES,
    OP_CREATE_PENDING,
    dispatch,
    handle_connection,
    read_frame,
    serve_forever,
)

BROKER_UID = 4001
RENDERER_UID = 1000
SIDECAR_UID = 4004

VALID_FIELDS = {
    "request_nonce": "550e8400-e29b-41d4-a716-446655440000",
    "request_sha256": "a" * 64,
    "conversation_id": "conv-123",
    "install_id": "install-xyz",
}


def _config():
    return AuthorityConfig(
        challenge_key_id="key-2026-07",
        workspace_id="ws-1",
        supervisor_id="sup-1",
    )


def _frame(obj) -> bytes:
    body = json.dumps(obj).encode("utf-8")
    return len(body).to_bytes(LENGTH_PREFIX_BYTES, "big") + body


class FakeConn:
    """A socket stand-in: fixed peer_uid, an inbound byte buffer, and a capture
    of everything written back. No OS involved."""

    def __init__(self, peer_uid, inbound: bytes = b""):
        self.peer_uid = peer_uid
        self._in = inbound
        self.out = b""
        self.closed = False

    def recv_exactly(self, n: int) -> bytes:
        chunk = self._in[:n]
        self._in = self._in[n:]
        return chunk

    def send_all(self, data: bytes) -> None:
        self.out += data

    def close(self) -> None:
        self.closed = True

    def decoded_reply(self):
        length = int.from_bytes(self.out[:LENGTH_PREFIX_BYTES], "big")
        body = self.out[LENGTH_PREFIX_BYTES:LENGTH_PREFIX_BYTES + length]
        return json.loads(body.decode("utf-8"))


def _sign_fn(_data: bytes) -> str:
    return "sig-deadbeef"


def _clock():
    return 1_000_000


class PeerDenyTests(unittest.TestCase):
    def test_non_broker_peer_denied_before_any_frame(self):
        store = PendingStore()
        # A valid create-pending frame is queued, but the renderer peer must be
        # refused BEFORE it is ever read.
        conn = FakeConn(RENDERER_UID, inbound=_frame({"op": OP_CREATE_PENDING, **VALID_FIELDS}))
        reply = handle_connection(conn, BROKER_UID, store, _config(), _sign_fn, _clock)
        self.assertFalse(reply["ok"])
        self.assertIn("peer", reply["error"])
        # The store was never touched: the frame was not dispatched.
        self.assertEqual(len(list(store._rows)), 0)  # type: ignore[attr-defined]
        self.assertEqual(conn.decoded_reply(), reply)

    def test_sidecar_peer_denied(self):
        store = PendingStore()
        conn = FakeConn(SIDECAR_UID, inbound=_frame({"op": OP_CREATE_PENDING, **VALID_FIELDS}))
        reply = handle_connection(conn, BROKER_UID, store, _config(), _sign_fn, _clock)
        self.assertFalse(reply["ok"])


class FrameBoundTests(unittest.TestCase):
    def test_oversize_frame_refused(self):
        # Declare a length past the hard bound; the body is never even read.
        header = (MAX_FRAME_BYTES + 1).to_bytes(LENGTH_PREFIX_BYTES, "big")
        conn = FakeConn(BROKER_UID, inbound=header)
        store = PendingStore()
        reply = handle_connection(conn, BROKER_UID, store, _config(), _sign_fn, _clock)
        self.assertFalse(reply["ok"])
        self.assertIn("exceeds", reply["error"])
        self.assertEqual(len(list(store._rows)), 0)  # type: ignore[attr-defined]

    def test_short_header_refused(self):
        conn = FakeConn(BROKER_UID, inbound=b"\x00\x01")  # only 2 of 4 bytes
        reply = handle_connection(conn, BROKER_UID, PendingStore(), _config(), _sign_fn, _clock)
        self.assertFalse(reply["ok"])

    def test_truncated_body_refused(self):
        # Header promises 100 bytes; only 3 are present.
        conn = FakeConn(BROKER_UID, inbound=(100).to_bytes(LENGTH_PREFIX_BYTES, "big") + b"abc")
        reply = handle_connection(conn, BROKER_UID, PendingStore(), _config(), _sign_fn, _clock)
        self.assertFalse(reply["ok"])

    def test_read_frame_rejects_zero_length(self):
        from challenge_authority_server import FrameError

        conn = FakeConn(BROKER_UID, inbound=(0).to_bytes(LENGTH_PREFIX_BYTES, "big"))
        with self.assertRaises(FrameError):
            read_frame(conn)


class DispatchTests(unittest.TestCase):
    def test_valid_create_pending_dispatch(self):
        store = PendingStore(id_fn=lambda: "pending-abc")
        conn = FakeConn(BROKER_UID, inbound=_frame({"op": OP_CREATE_PENDING, **VALID_FIELDS}))
        reply = handle_connection(conn, BROKER_UID, store, _config(), _sign_fn, _clock)
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["op"], OP_CREATE_PENDING)
        self.assertEqual(reply["pending_challenge_id"], "pending-abc")
        # The row landed in the store with the broker-supplied nonce verbatim.
        stored = store.get("pending-abc")
        self.assertEqual(stored["request_nonce"], VALID_FIELDS["request_nonce"])
        self.assertEqual(conn.decoded_reply(), reply)

    def test_create_then_issue_roundtrip(self):
        store = PendingStore(id_fn=lambda: "pending-xyz")
        created = dispatch(
            {"op": OP_CREATE_PENDING, **VALID_FIELDS},
            store, _config(), _sign_fn, _clock,
        )
        pid = created["pending_challenge_id"]
        issued = dispatch(
            {"op": "issue", "pending_challenge_id": pid},
            store, _config(), _sign_fn, _clock,
        )
        self.assertTrue(issued["ok"])
        challenge = issued["challenge"]
        self.assertEqual(challenge["payload"]["request_nonce"], VALID_FIELDS["request_nonce"])
        self.assertEqual(challenge["sig"], "sig-deadbeef")

    def test_unknown_op_rejected(self):
        conn = FakeConn(BROKER_UID, inbound=_frame({"op": "delete-everything"}))
        reply = handle_connection(conn, BROKER_UID, PendingStore(), _config(), _sign_fn, _clock)
        self.assertFalse(reply["ok"])

    def test_arbitrary_field_in_create_pending_rejected(self):
        bad = {"op": OP_CREATE_PENDING, **VALID_FIELDS, "evil_bytes": "attacker"}
        conn = FakeConn(BROKER_UID, inbound=_frame(bad))
        reply = handle_connection(conn, BROKER_UID, PendingStore(), _config(), _sign_fn, _clock)
        self.assertFalse(reply["ok"])


class ServeLoopTests(unittest.TestCase):
    def test_serve_forever_drives_injected_acceptor(self):
        store = PendingStore(id_fn=lambda: "pending-loop")
        conns = [FakeConn(BROKER_UID, inbound=_frame({"op": OP_CREATE_PENDING, **VALID_FIELDS}))]
        served = list(conns)

        def accept_one():
            return conns.pop(0) if conns else None

        serve_forever(accept_one, BROKER_UID, store, _config(), _sign_fn, _clock)

        # The single connection was handled, replied to, and closed.
        self.assertTrue(served[0].closed)
        self.assertTrue(served[0].decoded_reply()["ok"])
        self.assertIsNotNone(store.get("pending-loop"))


if __name__ == "__main__":
    unittest.main()
