"""Offline tests for the AF_UNIX challenge-authority server wiring (rev-30 §2.1 / §2.1.1).

No real socket, no keys, no OS trust chain: a ``FakeConn`` supplies the peer uid
and a byte buffer, the store is a plain dict, the clock is fixed, and signing is
a stub. These exercise the normative wiring behaviours:

  * a non-broker peer is DENIED before any frame is read (renderer/sidecar);
  * an oversize length-prefixed frame is refused (fail-closed on bounds);
  * a valid create-pending frame dispatches into the pure core and returns the
    minted pending_challenge_id + pending_expires_at_ms;
  * a caller-supplied request_sha256 is refused as malformed;
  * an issue replays a live ISSUED row byte-for-byte; an unknown id surfaces
    ``no_pending_row`` and an expired row ``pending_expired`` in the reply.
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402

from challenge_authority import (  # noqa: E402
    PENDING_TTL_MS,
    REASON_NO_PENDING_ROW,
    REASON_PENDING_EXPIRED,
    AuthorityConfig,
    PendingStore,
)
from challenge_authority_server import (  # noqa: E402
    LENGTH_PREFIX_BYTES,
    MAX_FRAME_BYTES,
    OP_CREATE_PENDING,
    OP_ISSUE,
    dispatch,
    handle_connection,
    read_frame,
    serve_forever,
)

BROKER_UID = 4001
RENDERER_UID = 1000
SIDECAR_UID = 4004

VALID_FIELDS = {
    "run_id": "run-1",
    "task_id": "task-1",
    "workspace_id": "ws-1",
    "install_id": "install-xyz",
    "request_nonce": "550e8400-e29b-41d4-a716-446655440000",
    "system_sha256": "a" * 64,
    "history_sha256": "b" * 64,
    "generation_config_sha256": "c" * 64,
    "requested_at_ms": 1_700_000_000_000,
}

NOW = 1_000_000


def _config():
    return AuthorityConfig(challenge_key_id="key-2026-07", supervisor_id="sup-1")


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
    return NOW


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
        self.assertEqual(reply["pending_expires_at_ms"], NOW + PENDING_TTL_MS)
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
            {"op": OP_ISSUE, "pending_challenge_id": pid},
            store, _config(), _sign_fn, _clock,
        )
        self.assertTrue(issued["ok"])
        challenge = issued["challenge"]
        self.assertEqual(challenge["payload"]["request_nonce"], VALID_FIELDS["request_nonce"])
        self.assertEqual(challenge["payload"]["run_id"], "run-1")
        self.assertEqual(challenge["sig"], "sig-deadbeef")

    def test_issue_replays_stored_document_byte_for_byte(self):
        store = PendingStore(id_fn=lambda: "pending-replay")
        dispatch({"op": OP_CREATE_PENDING, **VALID_FIELDS}, store, _config(), _sign_fn, _clock)
        first = dispatch(
            {"op": OP_ISSUE, "pending_challenge_id": "pending-replay"},
            store, _config(), _sign_fn, lambda: NOW,
        )
        replay = dispatch(
            {"op": OP_ISSUE, "pending_challenge_id": "pending-replay"},
            store, _config(), _sign_fn, lambda: NOW + 20_000,
        )
        self.assertEqual(
            json.dumps(first["challenge"], sort_keys=True),
            json.dumps(replay["challenge"], sort_keys=True),
        )

    def test_issue_unknown_id_surfaces_no_pending_row(self):
        conn = FakeConn(
            BROKER_UID, inbound=_frame({"op": OP_ISSUE, "pending_challenge_id": "ghost"})
        )
        reply = handle_connection(conn, BROKER_UID, PendingStore(), _config(), _sign_fn, _clock)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REASON_NO_PENDING_ROW)

    def test_issue_expired_pending_surfaces_pending_expired(self):
        store = PendingStore(id_fn=lambda: "pending-exp")
        dispatch({"op": OP_CREATE_PENDING, **VALID_FIELDS}, store, _config(), _sign_fn, lambda: NOW)
        late = NOW + PENDING_TTL_MS + 1
        conn = FakeConn(
            BROKER_UID, inbound=_frame({"op": OP_ISSUE, "pending_challenge_id": "pending-exp"})
        )
        reply = handle_connection(conn, BROKER_UID, store, _config(), _sign_fn, lambda: late)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REASON_PENDING_EXPIRED)

    def test_unknown_op_rejected(self):
        conn = FakeConn(BROKER_UID, inbound=_frame({"op": "delete-everything"}))
        reply = handle_connection(conn, BROKER_UID, PendingStore(), _config(), _sign_fn, _clock)
        self.assertFalse(reply["ok"])

    def test_arbitrary_field_in_create_pending_rejected(self):
        bad = {"op": OP_CREATE_PENDING, **VALID_FIELDS, "evil_bytes": "attacker"}
        conn = FakeConn(BROKER_UID, inbound=_frame(bad))
        reply = handle_connection(conn, BROKER_UID, PendingStore(), _config(), _sign_fn, _clock)
        self.assertFalse(reply["ok"])

    def test_caller_request_sha256_in_create_pending_rejected(self):
        bad = {"op": OP_CREATE_PENDING, **VALID_FIELDS, "request_sha256": "a" * 64}
        conn = FakeConn(BROKER_UID, inbound=_frame(bad))
        reply = handle_connection(conn, BROKER_UID, PendingStore(), _config(), _sign_fn, _clock)
        self.assertFalse(reply["ok"])
        self.assertIn("request_sha256", reply["error"])


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


class NeverRaisesTests(unittest.TestCase):
    """The same "never raises / never tears down the loop" promise the sibling
    ``isolated_signer_server`` carries.

    The audit question was whether this core has the SAME defect the signer had —
    an exception class of the core module that is a sibling of, rather than a
    subclass of, the class named in the ``except`` tuple. It does not: every
    explicit ``raise`` in ``challenge_authority`` is a ``ChallengeAuthorityError``
    and ``FrameError`` subclasses it, so the core's own refusals are all caught.

    What was NOT covered is the injected seams. ``sign_fn``, ``clock_ms`` and
    ``id_fn`` are supplied by the deployment and may raise anything at all; a real
    signer that cannot reach its key raises ``RuntimeError``/``OSError``, which
    escaped the front door and killed the accept loop with no refusal frame
    written.
    """

    def _seeded_store(self):
        store = PendingStore(id_fn=lambda: "pending-boom")
        dispatch({"op": OP_CREATE_PENDING, **VALID_FIELDS}, store, _config(), _sign_fn, _clock)
        return store

    @staticmethod
    def _boom_sign(_data: bytes) -> str:
        raise RuntimeError("HSM slot 3 unreachable at /run/pkcs11/token")

    def test_raising_sign_fn_becomes_a_reply_not_an_exception(self):
        store = self._seeded_store()
        conn = FakeConn(
            BROKER_UID, inbound=_frame({"op": OP_ISSUE, "pending_challenge_id": "pending-boom"})
        )
        with contextlib.redirect_stderr(io.StringIO()) as captured:
            reply = handle_connection(conn, BROKER_UID, store, _config(), self._boom_sign, _clock)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["error"], "internal authority fault")
        # The internal detail goes to the operator, never to the broker.
        self.assertNotIn("HSM slot 3", json.dumps(reply))
        self.assertIn("HSM slot 3", captured.getvalue())
        self.assertEqual(conn.decoded_reply(), reply)

    def test_raising_sign_fn_does_not_kill_the_accept_loop(self):
        store = self._seeded_store()
        conns = [
            FakeConn(BROKER_UID, inbound=_frame({"op": OP_ISSUE, "pending_challenge_id": "pending-boom"}))
            for _ in range(2)
        ]
        served = list(conns)

        def accept_one():
            return conns.pop(0) if conns else None

        with contextlib.redirect_stderr(io.StringIO()):
            serve_forever(accept_one, BROKER_UID, store, _config(), self._boom_sign, _clock)

        # BOTH connections were served: the loop survived the first one.
        for conn in served:
            self.assertTrue(conn.closed)
            self.assertFalse(conn.decoded_reply()["ok"])


if __name__ == "__main__":
    unittest.main()
