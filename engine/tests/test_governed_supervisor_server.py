"""Offline tests for the AF_UNIX governed-supervisor server wiring (rev-30 §5).

No real socket, no OS trust chain: a ``FakeConn`` supplies the peer uid and a
byte buffer, the clock is a fixed int, signing/verification is a real ``hmac``
over the exact canonical bytes the supervisor reassembles, and lease/attempt
ids come from a deterministic counter. These exercise the normative wiring
behaviours (mirroring ``test_challenge_authority_server.py``):

  * a non-broker peer is DENIED before any frame is read (renderer/sidecar);
  * an oversize / short / truncated length-prefixed frame is refused (bounds);
  * a valid accept-open frame dispatches into the pure core and returns the REAL
    lease the supervisor minted (expiry = now + 210000, pinned digests);
  * a supervisor Refusal verdict (expired / mismatch / forged / malformed) is
    relayed as a fail-closed ok:false reply carrying the typed REFUSE_* reason —
    never a fabricated lease;
  * a launch-gate op re-checks a real lease budget through the pure gate;
  * an unknown op / malformed body / bad lease shape -> typed error reply.
"""

import hashlib
import hmac
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from governed_supervisor import (  # noqa: E402
    CHALLENGE_PROTOCOL,
    LEASE_DURATION_MS,
    MIN_LAUNCH_REMAINING_MS,
    REFUSE_CHALLENGE_EXPIRED,
    REFUSE_LEASE_EXPIRED,
    REFUSE_MALFORMED,
    REFUSE_REQUEST_SHA256_MISMATCH,
    REFUSE_SIGNATURE_INVALID,
    SupervisorConfig,
    recompute_request_sha256,
)
from governed_supervisor_server import (  # noqa: E402
    LENGTH_PREFIX_BYTES,
    MAX_FRAME_BYTES,
    OP_ACCEPT_OPEN,
    OP_LAUNCH_GATE,
    dispatch,
    handle_connection,
    read_frame,
    serve_forever,
)

BROKER_UID = 4001
RENDERER_UID = 1000
SIDECAR_UID = 4004

CHALLENGE_KEY = b"test-challenge-key-not-a-secret"
LAUNCHER_SHA = "1" * 64
EXECUTOR_SHA = "2" * 64
NOW = 1_000_000

_recompute = recompute_request_sha256


def _canonical(payload) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _verify_sig(message: bytes, sig: str) -> bool:
    expected = hmac.new(CHALLENGE_KEY, message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def _sign(message: bytes) -> str:
    return hmac.new(CHALLENGE_KEY, message, hashlib.sha256).hexdigest()


def _config():
    counter = {"n": 0}

    def id_fn():
        counter["n"] += 1
        return "id-%08d" % counter["n"]

    return SupervisorConfig(
        launcher_executable_sha256=LAUNCHER_SHA,
        executor_executable_sha256=EXECUTOR_SHA,
        id_fn=id_fn,
    )


def _valid_payload(issued=NOW, ttl=30_000):
    payload = {
        "protocol": CHALLENGE_PROTOCOL,
        "challenge_key_id": "chal-key-2026-07",
        "run_id": "run-1",
        "task_id": "task-1",
        "workspace_id": "ws-1",
        "install_id": "install-1",
        "supervisor_id": "sup-1",
        "request_nonce": "nonce-abc-123",
        "system_sha256": "a" * 64,
        "history_sha256": "b" * 64,
        "generation_config_sha256": "c" * 64,
        "request_sha256": "",
        "requested_at_ms": 1_700_000_000_000,
        "challenge_issued_at_ms": issued,
        "challenge_expires_at_ms": issued + ttl,
    }
    payload["request_sha256"] = _recompute(payload)
    return payload


def _signed_doc(payload):
    return {"payload": payload, "sig": _sign(_canonical(payload))}


def _clock(now=NOW):
    return lambda: now


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


def _handle(conn, config=None, now=NOW):
    return handle_connection(
        conn,
        BROKER_UID,
        config or _config(),
        _verify_sig,
        _recompute,
        _clock(now),
    )


# ---------------------------------------------------------------------------
# Peer authentication (allowlist ONLY the broker uid)
# ---------------------------------------------------------------------------


class PeerDenyTests(unittest.TestCase):
    def test_non_broker_peer_denied_before_any_frame(self):
        # A valid accept-open frame is queued, but the renderer peer must be
        # refused BEFORE it is ever read (no lease, no dispatch).
        conn = FakeConn(
            RENDERER_UID,
            inbound=_frame({"op": OP_ACCEPT_OPEN, "challenge_doc": _signed_doc(_valid_payload())}),
        )
        reply = _handle(conn)
        self.assertFalse(reply["ok"])
        self.assertIn("peer", reply["error"])
        self.assertNotIn("lease", reply)
        self.assertEqual(conn.decoded_reply(), reply)

    def test_sidecar_peer_denied(self):
        conn = FakeConn(
            SIDECAR_UID,
            inbound=_frame({"op": OP_ACCEPT_OPEN, "challenge_doc": _signed_doc(_valid_payload())}),
        )
        reply = _handle(conn)
        self.assertFalse(reply["ok"])
        self.assertIn("peer", reply["error"])


# ---------------------------------------------------------------------------
# Frame bounds (fail-closed on oversize / short / truncated)
# ---------------------------------------------------------------------------


class FrameBoundTests(unittest.TestCase):
    def test_oversize_frame_refused(self):
        header = (MAX_FRAME_BYTES + 1).to_bytes(LENGTH_PREFIX_BYTES, "big")
        conn = FakeConn(BROKER_UID, inbound=header)
        reply = _handle(conn)
        self.assertFalse(reply["ok"])
        self.assertIn("exceeds", reply["error"])

    def test_short_header_refused(self):
        conn = FakeConn(BROKER_UID, inbound=b"\x00\x01")  # only 2 of 4 bytes
        reply = _handle(conn)
        self.assertFalse(reply["ok"])

    def test_truncated_body_refused(self):
        conn = FakeConn(BROKER_UID, inbound=(100).to_bytes(LENGTH_PREFIX_BYTES, "big") + b"abc")
        reply = _handle(conn)
        self.assertFalse(reply["ok"])

    def test_read_frame_rejects_zero_length(self):
        from governed_supervisor_server import FrameError

        conn = FakeConn(BROKER_UID, inbound=(0).to_bytes(LENGTH_PREFIX_BYTES, "big"))
        with self.assertRaises(FrameError):
            read_frame(conn)


# ---------------------------------------------------------------------------
# accept-open dispatch (happy path relays the REAL lease; verdicts relayed)
# ---------------------------------------------------------------------------


class AcceptOpenDispatchTests(unittest.TestCase):
    def test_valid_accept_open_yields_real_lease(self):
        conn = FakeConn(
            BROKER_UID,
            inbound=_frame({"op": OP_ACCEPT_OPEN, "challenge_doc": _signed_doc(_valid_payload())}),
        )
        reply = _handle(conn)
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["op"], OP_ACCEPT_OPEN)
        lease = reply["lease"]
        # Expiry is the SUPERVISOR's clock + the fixed 210000 duration.
        self.assertEqual(lease["lease_expires_at_ms"], NOW + LEASE_DURATION_MS)
        # Pinned digests come from the supervisor's OWN config, not the wire.
        self.assertEqual(lease["launcher_executable_sha256"], LAUNCHER_SHA)
        self.assertEqual(lease["executor_executable_sha256"], EXECUTOR_SHA)
        self.assertTrue(lease["lease_id"])
        self.assertNotEqual(lease["lease_id"], lease["execution_attempt_id"])
        self.assertEqual(conn.decoded_reply(), reply)

    def test_now_ms_comes_from_server_clock_not_the_wire(self):
        # Even if the caller smuggles a now_ms, the server's own clock drives
        # expiry (the wire value is ignored).
        payload = _signed_doc(_valid_payload())
        conn = FakeConn(
            BROKER_UID,
            inbound=_frame({"op": OP_ACCEPT_OPEN, "challenge_doc": payload, "now_ms": 42}),
        )
        reply = _handle(conn, now=NOW)
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["lease"]["lease_expires_at_ms"], NOW + LEASE_DURATION_MS)

    def test_expired_challenge_relayed_as_typed_refusal(self):
        payload = _valid_payload(issued=NOW - 30_001)  # expired by 1 ms at NOW
        conn = FakeConn(
            BROKER_UID,
            inbound=_frame({"op": OP_ACCEPT_OPEN, "challenge_doc": _signed_doc(payload)}),
        )
        reply = _handle(conn, now=NOW)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REFUSE_CHALLENGE_EXPIRED)
        self.assertNotIn("lease", reply)

    def test_forged_signature_relayed_as_signature_invalid(self):
        doc = _signed_doc(_valid_payload())
        doc["sig"] = "0" * 64
        conn = FakeConn(BROKER_UID, inbound=_frame({"op": OP_ACCEPT_OPEN, "challenge_doc": doc}))
        reply = _handle(conn)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REFUSE_SIGNATURE_INVALID)

    def test_request_sha256_mismatch_relayed(self):
        payload = _valid_payload()
        payload["request_sha256"] = "f" * 64  # valid shape, wrong digest; re-signed
        conn = FakeConn(
            BROKER_UID,
            inbound=_frame({"op": OP_ACCEPT_OPEN, "challenge_doc": _signed_doc(payload)}),
        )
        reply = _handle(conn)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REFUSE_REQUEST_SHA256_MISMATCH)

    def test_malformed_challenge_relayed_as_malformed(self):
        payload = _valid_payload()
        payload["evil_bytes"] = "attacker-controlled"  # extra field
        conn = FakeConn(
            BROKER_UID,
            inbound=_frame({"op": OP_ACCEPT_OPEN, "challenge_doc": _signed_doc(payload)}),
        )
        reply = _handle(conn)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REFUSE_MALFORMED)

    def test_accept_open_missing_challenge_doc_is_error(self):
        conn = FakeConn(BROKER_UID, inbound=_frame({"op": OP_ACCEPT_OPEN}))
        reply = _handle(conn)
        self.assertFalse(reply["ok"])
        self.assertIn("challenge_doc", reply["error"])


# ---------------------------------------------------------------------------
# launch-gate dispatch (re-checks a real lease budget through the pure gate)
# ---------------------------------------------------------------------------


class LaunchGateDispatchTests(unittest.TestCase):
    def _lease_obj(self, expires):
        return {
            "lease_id": "l-1",
            "execution_attempt_id": "a-1",
            "lease_expires_at_ms": expires,
            "launcher_executable_sha256": LAUNCHER_SHA,
            "executor_executable_sha256": EXECUTOR_SHA,
        }

    def test_launch_gate_proceeds_at_budget_boundary(self):
        lease = self._lease_obj(expires=NOW + MIN_LAUNCH_REMAINING_MS)
        conn = FakeConn(BROKER_UID, inbound=_frame({"op": OP_LAUNCH_GATE, "lease": lease}))
        reply = _handle(conn, now=NOW)
        self.assertTrue(reply["ok"])
        self.assertTrue(reply["proceed"])
        self.assertEqual(reply["lease"]["lease_id"], "l-1")

    def test_launch_gate_refuses_below_boundary(self):
        lease = self._lease_obj(expires=NOW + MIN_LAUNCH_REMAINING_MS - 1)
        conn = FakeConn(BROKER_UID, inbound=_frame({"op": OP_LAUNCH_GATE, "lease": lease}))
        reply = _handle(conn, now=NOW)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REFUSE_LEASE_EXPIRED)

    def test_launch_gate_bad_lease_shape_is_error(self):
        bad = self._lease_obj(expires=NOW + MIN_LAUNCH_REMAINING_MS)
        bad["smuggled"] = "x"  # extra field
        conn = FakeConn(BROKER_UID, inbound=_frame({"op": OP_LAUNCH_GATE, "lease": bad}))
        reply = _handle(conn, now=NOW)
        self.assertFalse(reply["ok"])
        self.assertIn("unexpected", reply["error"])

    def test_launch_gate_non_int_expiry_is_error(self):
        bad = self._lease_obj(expires="soon")
        conn = FakeConn(BROKER_UID, inbound=_frame({"op": OP_LAUNCH_GATE, "lease": bad}))
        reply = _handle(conn, now=NOW)
        self.assertFalse(reply["ok"])
        self.assertIn("lease_expires_at_ms", reply["error"])


# ---------------------------------------------------------------------------
# Unknown op / malformed body
# ---------------------------------------------------------------------------


class UnknownOpTests(unittest.TestCase):
    def test_unknown_op_rejected(self):
        conn = FakeConn(BROKER_UID, inbound=_frame({"op": "delete-everything"}))
        reply = _handle(conn)
        self.assertFalse(reply["ok"])
        self.assertIn("unknown op", reply["error"])

    def test_non_object_body_rejected(self):
        conn = FakeConn(BROKER_UID, inbound=_frame(["not", "an", "object"]))
        reply = _handle(conn)
        self.assertFalse(reply["ok"])

    def test_dispatch_never_fabricates_success_on_supervisor_error(self):
        # A bad clock seam (non-int now) is a supervisor-side fault -> the pure
        # core raises SupervisorError, which the server relays as an error reply,
        # never a lease.
        conn = FakeConn(
            BROKER_UID,
            inbound=_frame({"op": OP_ACCEPT_OPEN, "challenge_doc": _signed_doc(_valid_payload())}),
        )
        reply = handle_connection(
            conn, BROKER_UID, _config(), _verify_sig, _recompute, lambda: "not-an-int"
        )
        self.assertFalse(reply["ok"])
        self.assertNotIn("lease", reply)


# ---------------------------------------------------------------------------
# Serve loop (injectable acceptor -> no real socket)
# ---------------------------------------------------------------------------


class ServeLoopTests(unittest.TestCase):
    def test_serve_forever_drives_injected_acceptor(self):
        conns = [
            FakeConn(
                BROKER_UID,
                inbound=_frame({"op": OP_ACCEPT_OPEN, "challenge_doc": _signed_doc(_valid_payload())}),
            )
        ]
        served = list(conns)

        def accept_one():
            return conns.pop(0) if conns else None

        serve_forever(accept_one, BROKER_UID, _config(), _verify_sig, _recompute, _clock(NOW))

        self.assertTrue(served[0].closed)
        reply = served[0].decoded_reply()
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["lease"]["lease_expires_at_ms"], NOW + LEASE_DURATION_MS)

    def test_dispatch_direct_valid_accept_open(self):
        # Direct dispatch (no framing) also returns the real lease.
        reply = dispatch(
            {"op": OP_ACCEPT_OPEN, "challenge_doc": _signed_doc(_valid_payload())},
            _config(),
            _verify_sig,
            _recompute,
            _clock(NOW),
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["lease"]["lease_expires_at_ms"], NOW + LEASE_DURATION_MS)


if __name__ == "__main__":
    unittest.main()
