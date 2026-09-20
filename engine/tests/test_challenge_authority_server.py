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
    return AuthorityConfig(install_id="install-xyz", challenge_key_id="key-2026-07", supervisor_id="sup-1")


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
    def test_nm_ipc_02_non_broker_peer_denied_before_any_frame(self):
        """NM-IPC-02: a non-broker uid on the authority channel is refused before any frame."""
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
    def test_nm_frame_09_oversize_frame_refused(self):
        """NM-FRAME-09: a frame declared over MAX_FRAME_BYTES is refused before its body is read."""
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

    def test_foreign_install_id_in_create_pending_is_refused(self):
        """Audit A-01: the install_id scopes the evidence-head anti-rollback floor, so a
        caller that can choose it can bootstrap a fresh bucket and re-present a
        rolled-back head. The authority pins it from its own config and refuses.

        This is the negative that deleting the check cannot pass: the fields are
        otherwise VALID_FIELDS, so nothing else in the pipeline objects to them.
        """
        bad = {"op": OP_CREATE_PENDING, **VALID_FIELDS, "install_id": "install-SOMEONE-ELSE"}
        conn = FakeConn(BROKER_UID, inbound=_frame(bad))
        reply = handle_connection(conn, BROKER_UID, PendingStore(), _config(), _sign_fn, _clock)
        self.assertFalse(reply["ok"])
        self.assertIn("install_id", reply["error"])
        # The configured value is NOT disclosed: the caller learns that its own value was
        # refused, not what would have been accepted.
        self.assertNotIn("install-xyz", reply["error"])

    def test_matching_install_id_still_creates_a_pending_row(self):
        """The other half of the pair — the check refuses a foreign id without refusing
        the deployment's own. Without this, deleting `VALID_FIELDS` would pass the
        negative above by refusing everything."""
        conn = FakeConn(BROKER_UID, inbound=_frame({"op": OP_CREATE_PENDING, **VALID_FIELDS}))
        reply = handle_connection(conn, BROKER_UID, PendingStore(), _config(), _sign_fn, _clock)
        self.assertTrue(reply["ok"])
        self.assertIn("pending_challenge_id", reply)


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



class TheConnectionBudgetBoundsOneExchangeTests(unittest.TestCase):
    """A peer may not hold the challenge authority's serial accept loop (added 2026-09-20).

    Until that day ``SocketPeerConn.recv_exactly`` was an unbounded read loop with no timeout of any
    kind, so a peer that connected and never completed a frame stalled the loop forever.
    ``governed_supervisor_server`` had already refused that (the same total deadline, since audit R1)
    and ``floor_writer`` had its own 30 s version; this service and its sibling had nothing.

    The real class runs here. ``read_peercred_uid`` refuses off Linux, so that ONE attribute is
    stubbed — the uid read is a separate concern with its own tests in ``test_brops_socket`` — and
    everything else is the production object. Determinism comes from the BUDGET, not from a clock: a
    negative budget is already spent at construction.
    """

    class FakeSock:
        """Records every timeout armed and every byte asked for."""

        def __init__(self, chunks=()):
            self.chunks = list(chunks)
            self.armed = []
            self.recv_calls = []
            self.sent = []

        def settimeout(self, seconds):
            self.armed.append(seconds)

        def recv(self, n):
            self.recv_calls.append(n)
            return self.chunks.pop(0) if self.chunks else b""

        def sendall(self, data):
            self.sent.append(data)

        def close(self):
            pass

    def setUp(self):
        import challenge_authority_server as srv
        self.srv = srv
        original = srv.read_peercred_uid
        srv.read_peercred_uid = lambda _sock: 4242
        self.addCleanup(setattr, srv, "read_peercred_uid", original)

    def _conn(self, sock, budget_s):
        return self.srv.SocketPeerConn(sock, budget_s=budget_s)

    def test_a_spent_budget_never_reaches_the_socket(self):
        """THE assertion the previous code could not pass: it called `recv` unconditionally."""
        sock = self.FakeSock([b"xxxxxxxx"])
        got = self._conn(sock, -1.0).recv_exactly(8)
        self.assertEqual(got, b"")
        self.assertEqual(sock.recv_calls, [],
                         "a connection past its deadline must not read one more byte")

    def test_a_spent_budget_refuses_the_WRITE_in_this_services_own_vocabulary(self):
        """Writing under no timeout would hand back, on the write side, exactly the unbounded hold
        the read side just refused. The refusal is this module's `FrameError`, not a generic one."""
        sock = self.FakeSock()
        conn = self._conn(sock, -1.0)
        # `self.srv.FrameError`, not a bare name: the assertion is that THIS service's own class
        # is raised, and one of the two test files does not import the name into its namespace.
        with self.assertRaises(self.srv.FrameError):
            conn.send_all(b"reply")
        self.assertEqual(sock.sent, [], "nothing may be written after the budget is spent")

    def test_a_live_budget_reads_through_and_arms_a_POSITIVE_timeout(self):
        sock = self.FakeSock([b"hello ", b"world"])
        conn = self._conn(sock, 600.0)
        self.assertEqual(conn.recv_exactly(11), b"hello world")
        self.assertTrue(sock.armed, "a read must arm the remaining budget")
        self.assertTrue(all(t > 0 for t in sock.armed), sock.armed)

    def test_the_deadline_is_armed_ONCE_at_construction_and_not_per_read(self):
        """A per-read timeout restarts on every byte that arrives, so a drip peer never times out.
        Two successive reads on one connection must therefore arm a NON-INCREASING budget."""
        sock = self.FakeSock([b"ab", b"cd"])
        conn = self._conn(sock, 600.0)
        armed_at_construction = conn._deadline
        conn.recv_exactly(2)
        conn.recv_exactly(2)
        # The DIRECT assertion. Comparing armed timeouts is not enough: re-arming with the module
        # default would still shrink the number relative to a 600 s test budget, so a mutant that
        # reset the deadline on every read survived that comparison. The deadline itself may not move.
        self.assertEqual(conn._deadline, armed_at_construction,
                         "the deadline is armed ONCE, at construction, or a drip peer never expires")
        self.assertGreaterEqual(len(sock.armed), 2, sock.armed)
        self.assertLessEqual(sock.armed[-1], sock.armed[0],
                             "the budget must shrink across reads, never reset")

    def test_a_live_budget_writes_and_arms_the_remaining_time(self):
        sock = self.FakeSock()
        self._conn(sock, 600.0).send_all(b"reply")
        self.assertEqual(sock.sent, [b"reply"])
        self.assertTrue(all(t > 0 for t in sock.armed), sock.armed)

    def test_the_bound_comes_from_the_shared_module_rather_than_a_local_copy(self):
        """Five accept loops, two bounds, three of them unbounded — the divergence WAS the defect.
        One number, one place."""
        import brops_socket
        self.assertIs(self.srv.brops_socket.recv_exactly_bounded,
                      brops_socket.recv_exactly_bounded)
        self.assertEqual(self.srv.brops_socket.CONNECTION_BUDGET_S,
                         brops_socket.CONNECTION_BUDGET_S)


if __name__ == "__main__":
    unittest.main()
