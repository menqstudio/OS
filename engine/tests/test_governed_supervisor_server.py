"""Offline tests for the AF_UNIX governed-supervisor server wiring (rev-30 §5 v2).

No real socket, no OS trust chain: a ``FakeConn`` supplies the peer uid and a byte buffer,
the clock is a fixed int, signing/verification is a real ``hmac`` over the exact canonical
bytes the supervisor reassembles, lease/attempt ids come from a deterministic counter, and
the durable ledger is an in-memory SQLite database over the SHARED DDL.

These exercise the normative wiring behaviours:

  * a non-broker peer is DENIED before any frame is read (renderer/sidecar);
  * an oversize / short / truncated length-prefixed frame is refused (bounds);
  * a valid accept-open frame dispatches into the pure core, CASes a durable acceptance
    row, and returns the REAL lease the supervisor minted;
  * a replayed challenge returns the SAME lease — never a second execution attempt;
  * a supervisor Refusal verdict (expired / mismatch / forged / malformed) is relayed as a
    fail-closed ok:false reply carrying the typed REFUSE_* reason — never a fabricated lease;
  * the launch gate is driven BY ATTEMPT ID against the supervisor's own persisted window;
  * **F-01**: ``attest-run`` names only ``{run_id, execution_attempt_id}``, signs only over
    durable terminal state, refuses a fabricated run, and hard-errors on the old
    ``{facts: …}`` protocol rather than silently ignoring it.
"""

import contextlib
import hashlib
import hmac
import io
import json
import pathlib
import socket
import sqlite3
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import governed_supervisor_ledger as gsl  # noqa: E402
import governed_supervisor_server as gss  # noqa: E402
from governed_supervisor import (  # noqa: E402
    CHALLENGE_PROTOCOL,
    LEASE_DURATION_MS,
    REFUSE_CHALLENGE_EXPIRED,
    REFUSE_MALFORMED,
    REFUSE_REQUEST_SHA256_MISMATCH,
    REFUSE_SIGNATURE_INVALID,
    REFUSE_SUPERVISOR_MISMATCH,
    SupervisorConfig,
    recompute_request_sha256,
)
from governed_supervisor_server import (  # noqa: E402
    LENGTH_PREFIX_BYTES,
    MAX_ERROR_CHARS,
    MAX_FRAME_BYTES,
    OP_ACCEPT_OPEN,
    OP_ATTEST_RUN,
    OP_COMPLETE_RUN,
    OP_EXECUTION_STARTED,
    OP_LAUNCH_GATE,
    REFUSE_COMPLETION_CONFLICT,
    REFUSE_EVIDENCE_MISMATCH,
    REFUSE_ILLEGAL_STATE,
    REFUSE_NO_TERMINAL_RUN,
    REFUSE_UNKNOWN_ATTEMPT,
    FrameError,
    dispatch,
    handle_connection,
    _try_write,
    read_frame,
    recv_budget_s,
    recv_exactly_bounded,
    serve_forever,
)

BROKER_UID = 4001
RENDERER_UID = 1000
SIDECAR_UID = 4004

CHALLENGE_KEY = b"test-challenge-key-not-a-secret"
LAUNCHER_SHA = "1" * 64
EXECUTOR_SHA = "2" * 64
NOW = 1_000_000
ATTEST_KEY_ID = "sup-attest-key-1"

_recompute = recompute_request_sha256

_OPEN = []


def tearDownModule():
    while _OPEN:
        try:
            _OPEN.pop().close()
        except sqlite3.Error:
            pass


def _ledger():
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    gsl.apply_schema(conn)
    _OPEN.append(conn)
    return conn


def _canonical(payload) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _verify_sig(message: bytes, sig: str) -> bool:
    expected = hmac.new(CHALLENGE_KEY, message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def _sign(message: bytes) -> str:
    return hmac.new(CHALLENGE_KEY, message, hashlib.sha256).hexdigest()


def _sign_attestation(message: bytes) -> str:
    return "att:" + hashlib.sha256(message).hexdigest()


def _config():
    counter = {"n": 0}

    def id_fn():
        counter["n"] += 1
        return "id-%08d" % counter["n"]

    return SupervisorConfig(
        launcher_executable_sha256=LAUNCHER_SHA,
        executor_executable_sha256=EXECUTOR_SHA,
        id_fn=id_fn,
        supervisor_id="sup-1",
        executor_id="exec-1",
        builder_id="builder-1",
        policy_id="policy-1",
        policy_version="v1",
        policy_bundle_handle="e" * 64,
        challenge_registry_handle="reg-handle",
        challenge_registry_hash="reg-hash",
        challenge_registry_epoch=7,
        challenge_registry_root_key_id="root-1",
    )


def _valid_payload(issued=NOW, ttl=30_000, nonce="nonce-abc-123"):
    payload = {
        "protocol": CHALLENGE_PROTOCOL,
        "challenge_key_id": "chal-key-2026-07",
        "run_id": "run-1",
        "task_id": "task-1",
        "workspace_id": "ws-1",
        "install_id": "install-1",
        "supervisor_id": "sup-1",
        "request_nonce": nonce,
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


def _produced(**over):
    facts = dict(
        output_handle="d" * 64,
        containment_evidence_handle="e" * 64,
        completed_at_ms=NOW + 1_000,
    )
    facts.update(over)
    return facts

def _run_evidence(output_handle, *, head_sequence=12, event_count=3):
    """A recorder evidence chain the supervisor can derive the head from (audit F-01).

    Built around a given `output_handle` so a test can model both the honest case and a broker
    naming output the recorder never captured.
    """
    import hashlib as _h, json as _j

    def canon(payload):
        return _j.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def sha(data):
        return _h.sha256(data).hexdigest()

    payloads = [("lease-validated", {"n": i}) for i in range(1, event_count)]
    payloads.append(("output-captured", {"launcher_exit": 0, "output_sha256": output_handle}))
    previous, events = None, []
    for sequence, (event_type, payload) in enumerate(payloads, start=1):
        event = {
            "event_type": event_type,
            "payload": payload,
            "payload_sha256": sha(canon(payload)),
            "previous_event_hash": previous,
            "sequence": sequence,
        }
        previous = sha(canon(event))
        events.append(event)
    return _j.dumps({
        "event_count": len(events),
        "events": events,
        "final_event_hash": previous,
        "head_sequence": head_sequence,
        "last_sequence": len(events),
        "protocol": "brops.run-evidence-chain.v1",
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")



#: The supervisor publishes its own terminal artifacts (F-02); here the "store" is a dict, so
#: the content address is still real and a republish of identical bytes is still a no-op.
PUBLISHED = {}


def _publish(data: bytes) -> str:
    handle = hashlib.sha256(data).hexdigest()
    PUBLISHED[handle] = data
    return handle


def _clock(now=NOW):
    return lambda: now


def _frame(obj, *, ensure_ascii: bool = True) -> bytes:
    """Length-prefix a request the way a real peer would put it on the wire.

    `ensure_ascii` is EXPLICIT because it decides which check a test reaches.
    `json.dumps` defaults to True, expanding every non-ASCII character into a
    6-byte ``\\uXXXX`` escape — so a payload built to exercise a handler can
    silently balloon past MAX_FRAME_BYTES and be refused by `read_frame` before
    the handler is ever entered. (That is exactly what had happened to the
    amplified-error test below.) A peer that wants those bytes THROUGH the frame
    bound sends them as raw UTF-8, i.e. ensure_ascii=False.
    """
    body = json.dumps(obj, ensure_ascii=ensure_ascii).encode("utf-8")
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


def _handle(conn, config=None, now=NOW, ledger_conn=None):
    return handle_connection(
        conn,
        BROKER_UID,
        config or _config(),
        _verify_sig,
        _recompute,
        _clock(now),
        ledger_conn=ledger_conn if ledger_conn is not None else _ledger(),
        publish_artifact=_publish,
        read_run_evidence=lambda attempt: _run_evidence("d" * 64),
        sign_attestation=_sign_attestation,
        supervisor_attestation_key_id=ATTEST_KEY_ID,
    )


def _call(request, *, config, ledger_conn, now=NOW, publish=None, clock=None):
    """Direct dispatch (no framing) with the durable ledger wired in.

    `publish` and `clock` are seams a crash test injects. They default to the real ones, so a
    caller that does not name them cannot tell this signature ever changed."""
    return dispatch(
        request,
        config,
        _verify_sig,
        _recompute,
        clock if clock is not None else _clock(now),
        conn=ledger_conn,
        publish_artifact=publish if publish is not None else _publish,
        read_run_evidence=lambda attempt: _run_evidence("d" * 64),
        sign_attestation=_sign_attestation,
        supervisor_attestation_key_id=ATTEST_KEY_ID,
    )


# ---------------------------------------------------------------------------
# Peer authentication (allowlist ONLY the broker uid)
# ---------------------------------------------------------------------------


class PeerDenyTests(unittest.TestCase):
    def test_nm_ipc_04_non_broker_peer_denied_before_any_frame(self):
        """NM-IPC-04: an unknown uid at the supervisor socket is refused before any frame is read."""
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

    def test_an_amplified_error_reply_never_tears_down_the_connection(self):
        # A hostile op whose repr() expands ~4x used to produce a reply too large to frame,
        # and the FrameError escaped the handler and killed the supervisor (audit F-11).
        # The error text is bounded now, and _try_write degrades instead of raising.
        #
        # This test used to frame the payload with json.dumps' DEFAULT ensure_ascii=True,
        # which turned 3000 U+0080 characters into 18010 wire bytes against an 8192-byte
        # MAX_FRAME_BYTES. `read_frame` refused the length prefix, the bounds check alone
        # satisfied both assertions, and neither `_bounded_error` nor `_try_write`'s
        # FrameError branch was ever entered — it passed identically on the unfixed code.
        # To reach the amplifier the frame must be one the supervisor ACCEPTS: raw UTF-8.
        hostile = {"op": "" * 3_000}
        framed = _frame(hostile, ensure_ascii=False)

        # Guard 1 — the request really does get past the frame bound. Without this the
        # test can silently rot back into a length-prefix test that proves nothing.
        declared = int.from_bytes(framed[:LENGTH_PREFIX_BYTES], "big")
        self.assertLessEqual(
            declared, MAX_FRAME_BYTES,
            "the hostile frame must be ACCEPTED, or read_frame answers and the "
            "error-bounding path under test is never reached")

        # Guard 2 — un-bounded, this op's error text really would be un-framable, so the
        # bounding below is doing work rather than describing an already-small reply.
        unbounded = json.dumps({"ok": False, "error": "unknown op %r" % (hostile["op"],)},
                               separators=(",", ":")).encode("utf-8")
        self.assertGreater(
            len(unbounded), MAX_FRAME_BYTES,
            "premise of this test: the un-bounded error reply must exceed the frame bound")

        conn = FakeConn(BROKER_UID, inbound=framed)
        reply = _handle(conn)

        self.assertFalse(reply["ok"])
        # The refusal is about the OP — proof the frame was read and dispatch was entered,
        # not that the length prefix was rejected.
        self.assertIn("unknown op", reply["error"])
        self.assertNotIn("exceeds bound", reply["error"])
        # `_bounded_error` ran: the text is capped, and it says so.
        self.assertLessEqual(len(reply["error"]), MAX_ERROR_CHARS + 32)
        self.assertTrue(reply["error"].endswith("(truncated)"))
        # A real framed reply reached the peer and the connection survived.
        self.assertTrue(conn.out, "a reply was still written")
        self.assertLessEqual(len(conn.out), MAX_FRAME_BYTES + LENGTH_PREFIX_BYTES)
        self.assertEqual(conn.decoded_reply(), reply)

    def test_error_bounding_holds_at_the_largest_frame_a_peer_may_send(self):
        # The bound must hold at the WORST legal input, not one hand-picked size: a peer
        # may send a full MAX_FRAME_BYTES frame, and repr() expands non-printables ~4x.
        op = "" * ((MAX_FRAME_BYTES - 32) // 2)
        framed = _frame({"op": op}, ensure_ascii=False)
        self.assertLessEqual(int.from_bytes(framed[:LENGTH_PREFIX_BYTES], "big"),
                             MAX_FRAME_BYTES)
        conn = FakeConn(BROKER_UID, inbound=framed)
        reply = _handle(conn)
        self.assertFalse(reply["ok"])
        self.assertIn("unknown op", reply["error"])
        self.assertTrue(reply["error"].endswith("(truncated)"))
        self.assertTrue(conn.out)
        self.assertLessEqual(len(conn.out), MAX_FRAME_BYTES + LENGTH_PREFIX_BYTES)

    def test_try_write_degrades_instead_of_raising_on_an_unframable_reply(self):
        # The F-11 belt itself, driven directly. If a reply is over-bound for ANY reason,
        # `_try_write` must emit the minimal typed refusal rather than let FrameError
        # escape `handle_connection` and kill the process that mints every lease. Nothing
        # else in this suite enters that branch.
        conn = FakeConn(BROKER_UID)
        _try_write(conn, {"ok": False, "error": "x" * (MAX_FRAME_BYTES * 2)})
        self.assertTrue(conn.out, "_try_write must still answer the peer")
        self.assertLessEqual(len(conn.out), MAX_FRAME_BYTES + LENGTH_PREFIX_BYTES)
        self.assertEqual(conn.decoded_reply(),
                         {"ok": False, "error": "reply exceeded frame bound"})

    def test_try_write_swallows_a_dead_peer(self):
        # The other half of the belt: a peer that has gone away must not raise either.
        class DeadConn(FakeConn):
            def send_all(self, data):
                raise OSError("peer gone")

        _try_write(DeadConn(BROKER_UID), {"ok": True})  # must not raise


# ---------------------------------------------------------------------------
# accept-open dispatch (relays the REAL lease AND persists the acceptance)
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
        self.assertEqual(lease["lease_expires_at_ms"], NOW + LEASE_DURATION_MS)
        self.assertEqual(lease["launcher_executable_sha256"], LAUNCHER_SHA)
        self.assertEqual(lease["executor_executable_sha256"], EXECUTOR_SHA)
        self.assertTrue(lease["lease_id"])
        self.assertNotEqual(lease["lease_id"], lease["execution_attempt_id"])
        self.assertEqual(conn.decoded_reply(), reply)

    def test_accept_open_persists_the_attempt_in_LEASE_READY(self):
        ledger_conn = _ledger()
        reply = _call(
            {"op": OP_ACCEPT_OPEN, "challenge_doc": _signed_doc(_valid_payload())},
            config=_config(), ledger_conn=ledger_conn,
        )
        attempt = reply["lease"]["execution_attempt_id"]
        self.assertEqual(gsl._current_state(ledger_conn, attempt), gsl.LEASE_READY)

    def test_a_replayed_challenge_returns_the_SAME_lease_not_a_second_attempt(self):
        # The core F-09/F-01 property at the wire: one signed challenge, one attempt.
        ledger_conn = _ledger()
        config = _config()
        doc = _signed_doc(_valid_payload())
        first = _call({"op": OP_ACCEPT_OPEN, "challenge_doc": doc},
                      config=config, ledger_conn=ledger_conn)
        second = _call({"op": OP_ACCEPT_OPEN, "challenge_doc": doc},
                       config=config, ledger_conn=ledger_conn)
        self.assertTrue(first["ok"] and second["ok"])
        self.assertEqual(first["lease"], second["lease"])
        rows = ledger_conn.execute(
            "SELECT COUNT(*) FROM governed_turn_acceptance"
        ).fetchone()[0]
        self.assertEqual(rows, 1)

    def test_now_ms_comes_from_server_clock_not_the_wire(self):
        # A smuggled now_ms is now a hard shape error rather than a silently ignored field.
        conn = FakeConn(
            BROKER_UID,
            inbound=_frame({"op": OP_ACCEPT_OPEN,
                            "challenge_doc": _signed_doc(_valid_payload()), "now_ms": 42}),
        )
        reply = _handle(conn, now=NOW)
        self.assertFalse(reply["ok"])
        self.assertIn("now_ms", reply["error"])

    def test_expired_challenge_relayed_as_typed_refusal(self):
        payload = _valid_payload(issued=NOW - 30_001)
        conn = FakeConn(
            BROKER_UID,
            inbound=_frame({"op": OP_ACCEPT_OPEN, "challenge_doc": _signed_doc(payload)}),
        )
        reply = _handle(conn, now=NOW)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REFUSE_CHALLENGE_EXPIRED)
        self.assertNotIn("lease", reply)

    def test_challenge_for_another_supervisor_is_refused(self):
        payload = _valid_payload()
        payload["supervisor_id"] = "sup-OTHER"
        payload["request_sha256"] = _recompute(payload)
        conn = FakeConn(
            BROKER_UID,
            inbound=_frame({"op": OP_ACCEPT_OPEN, "challenge_doc": _signed_doc(payload)}),
        )
        reply = _handle(conn)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REFUSE_SUPERVISOR_MISMATCH)

    def test_forged_signature_relayed_as_signature_invalid(self):
        doc = _signed_doc(_valid_payload())
        doc["sig"] = "0" * 64
        conn = FakeConn(BROKER_UID, inbound=_frame({"op": OP_ACCEPT_OPEN, "challenge_doc": doc}))
        reply = _handle(conn)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REFUSE_SIGNATURE_INVALID)

    def test_request_sha256_mismatch_relayed(self):
        payload = _valid_payload()
        payload["request_sha256"] = "f" * 64
        conn = FakeConn(
            BROKER_UID,
            inbound=_frame({"op": OP_ACCEPT_OPEN, "challenge_doc": _signed_doc(payload)}),
        )
        reply = _handle(conn)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REFUSE_REQUEST_SHA256_MISMATCH)

    def test_malformed_challenge_relayed_as_malformed(self):
        payload = _valid_payload()
        payload["evil_bytes"] = "attacker-controlled"
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
# The lifecycle ops: launch-gate -> execution-started -> complete-run
# ---------------------------------------------------------------------------


class _LifecycleBase(unittest.TestCase):
    def setUp(self):
        self.ledger_conn = _ledger()
        self.config = _config()

    def _accept(self, payload=None, now=NOW):
        reply = _call(
            {"op": OP_ACCEPT_OPEN, "challenge_doc": _signed_doc(payload or _valid_payload())},
            config=self.config, ledger_conn=self.ledger_conn, now=now,
        )
        self.assertTrue(reply["ok"], reply)
        return reply["lease"]["execution_attempt_id"]

    def _op(self, request, now=NOW):
        return _call(request, config=self.config, ledger_conn=self.ledger_conn, now=now)

    def _wire(self, request, now=NOW):
        """Drive the request through the framed front door, which converts a shape
        violation into a fail-closed reply (``dispatch`` alone raises it)."""
        conn = FakeConn(BROKER_UID, inbound=_frame(request))
        return _handle(conn, config=self.config, now=now, ledger_conn=self.ledger_conn)

    def _to_executing(self, attempt, now=NOW):
        gate = self._op({"op": OP_LAUNCH_GATE, "execution_attempt_id": attempt}, now=now)
        self.assertTrue(gate["ok"], gate)
        started = self._op({
            "op": OP_EXECUTION_STARTED, "execution_attempt_id": attempt,
            "process_group_id": "pg-1", "cgroup_id": "cg-1",
            "execution_started_marker": None,
        }, now=now)
        self.assertTrue(started["ok"], started)


class LaunchGateDispatchTests(_LifecycleBase):
    def test_launch_gate_takes_only_an_attempt_id_and_proceeds(self):
        attempt = self._accept()
        reply = self._op({"op": OP_LAUNCH_GATE, "execution_attempt_id": attempt})
        self.assertTrue(reply["ok"])
        self.assertTrue(reply["proceed"])
        self.assertEqual(reply["execution_attempt_id"], attempt)
        self.assertEqual(gsl._current_state(self.ledger_conn, attempt), gsl.EXECUTION_STARTING)

    def test_a_caller_supplied_lease_is_a_hard_error(self):
        # The old wire let the caller hand back the lease it was judged against (F-23).
        attempt = self._accept()
        reply = self._wire({
            "op": OP_LAUNCH_GATE, "execution_attempt_id": attempt,
            "lease": {"lease_expires_at_ms": 9_999_999_999_999},
        })
        self.assertFalse(reply["ok"])
        self.assertIn("lease", reply["error"])
        # And the attempt was not moved by the refused request.
        self.assertEqual(gsl._current_state(self.ledger_conn, attempt), gsl.LEASE_READY)

    def test_gate_judges_the_supervisors_own_window_and_expires_the_attempt(self):
        attempt = self._accept()
        too_late = NOW + LEASE_DURATION_MS + 1
        reply = self._op({"op": OP_LAUNCH_GATE, "execution_attempt_id": attempt}, now=too_late)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], "lease_expired")
        self.assertEqual(gsl._current_state(self.ledger_conn, attempt), gsl.EXPIRED)

    def test_gate_on_a_fabricated_attempt_is_unknown_attempt(self):
        reply = self._op({"op": OP_LAUNCH_GATE, "execution_attempt_id": "att-fabricated"})
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REFUSE_UNKNOWN_ATTEMPT)

    def test_gating_twice_is_an_illegal_state_move(self):
        attempt = self._accept()
        self._op({"op": OP_LAUNCH_GATE, "execution_attempt_id": attempt})
        again = self._op({"op": OP_LAUNCH_GATE, "execution_attempt_id": attempt})
        self.assertFalse(again["ok"])
        self.assertEqual(again["reason"], REFUSE_ILLEGAL_STATE)


class CompleteRunDispatchTests(_LifecycleBase):
    def test_complete_run_records_once(self):
        attempt = self._accept()
        self._to_executing(attempt)
        reply = self._op({"op": OP_COMPLETE_RUN, "execution_attempt_id": attempt,
                          "produced": _produced()})
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["recorded"], gsl.CREATED)
        self.assertEqual(gsl._current_state(self.ledger_conn, attempt), gsl.COMPLETED)

    def test_a_second_completion_with_different_facts_is_refused(self):
        attempt = self._accept()
        self._to_executing(attempt)
        self._op({"op": OP_COMPLETE_RUN, "execution_attempt_id": attempt,
                  "produced": _produced()})
        # Differ in a field the recorder's evidence does NOT govern, so the write-once conflict
        # is what refuses this — a differing `output_handle` is now caught earlier and harder
        # (see the F-01 test below), which would have masked the property under test.
        reply = self._op({"op": OP_COMPLETE_RUN, "execution_attempt_id": attempt,
                          "produced": _produced(completed_at_ms=NOW + 9_000)})
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REFUSE_COMPLETION_CONFLICT)

    def test_naming_output_the_recorder_never_captured_is_refused(self):
        """audit **F-01**: `output_handle` is the digest of the exact reply the desktop commits.
        It is still reported by the executing chain, but the supervisor now checks it against the
        `output-captured` digest in the recorder's own chain — which the broker cannot write."""
        attempt = self._accept()
        self._to_executing(attempt)
        reply = self._op({"op": OP_COMPLETE_RUN, "execution_attempt_id": attempt,
                          "produced": _produced(output_handle="9" * 64)})
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REFUSE_EVIDENCE_MISMATCH)

    def test_completion_without_execution_is_an_illegal_state_move(self):
        attempt = self._accept()  # LEASE_READY, never launched
        reply = self._op({"op": OP_COMPLETE_RUN, "execution_attempt_id": attempt,
                          "produced": _produced()})
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REFUSE_ILLEGAL_STATE)

    def test_completion_cannot_smuggle_ids_the_supervisor_owns(self):
        attempt = self._accept()
        self._to_executing(attempt)
        facts = _produced()
        facts["run_id"] = "run-ATTACKER"
        reply = self._op({"op": OP_COMPLETE_RUN, "execution_attempt_id": attempt,
                          "produced": facts})
        self.assertFalse(reply["ok"])


# ---------------------------------------------------------------------------
# F-01: attest-run is no longer a sign-arbitrary-facts oracle.
# ---------------------------------------------------------------------------


class CrashCutsInsideCompletionTests(_LifecycleBase):
    """NM-CRASH-12, -13 and -14 — three cuts inside `complete_governed_run`, three properties.

    The function does every store write first (lease, terminal record, execution receipt, into one
    dict literal) and only then calls `record_completion`, which holds the completion INSERT, the
    evidence-head floor CAS and the advance to `COMPLETED` in one transaction. So there are exactly
    three places a crash can land with different consequences, and each row below is one of them.

    A crash is modelled the only way a test honestly can: raise from the seam the supervisor was
    inside, then look at what SURVIVED in the store and the ledger, and then RETRY — because durable
    state is only half the claim. A supervisor that recorded the right state and could not finish the
    turn has still lost it.

    `KeyboardInterrupt` rather than a `RuntimeError`: the completion path converts typed refusals
    into wire replies, and a row about a CRASH must not be answered by the refusal path.
    """

    def _crash_on_publish(self, nth):
        """A publish seam that writes to the store and THEN crashes, on its nth call.

        After the store write, deliberately: the interesting state is "the bytes are addressable and
        the ledger has never heard of them", which is the orphan a retry has to tolerate."""
        calls = []

        def publish(data):
            calls.append(bytes(data))
            handle = _publish(data)
            if len(calls) == nth:
                raise KeyboardInterrupt("crash AFTER store write %d" % nth)
            return handle

        return publish, calls

    def _crash_after_all_publishes(self):
        """A (publish, clock) pair that cuts between the last store write and `record_completion`.

        `record_completion` is called with `clock_ms()` as an argument, so arming a raising clock on
        the third publish puts the cut exactly there: three artifacts durable, ledger untouched."""
        armed = {"yes": False}
        calls = []

        def publish(data):
            calls.append(bytes(data))
            handle = _publish(data)
            if len(calls) == 3:
                armed["yes"] = True
            return handle

        def clock():
            if armed["yes"]:
                raise KeyboardInterrupt("crash after the last publish, before record_completion")
            return NOW

        return publish, clock, calls

    def _completion_row(self, attempt):
        return self.ledger_conn.execute(
            "SELECT * FROM governed_turn_completion WHERE execution_attempt_id = ?",
            (attempt,)).fetchone()

    def _floor_rows(self):
        return [tuple(r) for r in self.ledger_conn.execute(
            "SELECT * FROM governed_evidence_head_floor ORDER BY install_id, task_id").fetchall()]

    # ---- NM-CRASH-12 ----------------------------------------------------------------

    def test_nm_crash_12_a_cut_among_the_terminal_artifacts_leaves_orphan_bytes_and_no_completion(self):
        """NM-CRASH-12 — the supervisor dies with some terminal artifacts published.

        The design phrases this cut as "after receipt/evidence, before terminal record". In the
        implementation all three artifacts are published into one dict literal before any ledger
        write, so the order among them is not observable to anything; what IS observable, and what
        this row is about, is a store holding addressable bytes the ledger has never heard of. The
        cut is taken on the third publish, so two blobs are durable and the ledger is untouched.

        What must be true: orphan store bytes cost nothing. `publish_artifact` is create-if-absent
        and the artifacts are built from the supervisor's own durable row, so the retry republishes
        the SAME bytes, derives the SAME content addresses, and the blobs left by the crash turn out
        to have been the answer rather than waste. If the handles differed, the store would be
        accumulating near-duplicates and the crash would have cost a real leak.
        """
        case = "NM-CRASH-12"
        attempt = self._accept()
        self._to_executing(attempt)
        publish, calls = self._crash_on_publish(3)

        with self.assertRaises(KeyboardInterrupt):
            self._op_publishing({"op": OP_COMPLETE_RUN, "execution_attempt_id": attempt,
                                 "produced": _produced()}, publish)
        self.assertEqual(len(calls), 3, f"{case}: the cut was not on the third publish")
        for blob in calls:
            self.assertIn(hashlib.sha256(blob).hexdigest(), PUBLISHED,
                          f"{case}: a published blob is not addressable")
        self.assertIsNone(self._completion_row(attempt),
                          f"{case}: a completion survived a cut before record_completion")
        self.assertEqual(gsl._current_state(self.ledger_conn, attempt), gsl.EXECUTING, case)
        self.assertEqual(self._floor_rows(), [], f"{case}: the floor moved before the completion")

        reply = self._op({"op": OP_COMPLETE_RUN, "execution_attempt_id": attempt,
                          "produced": _produced()})
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["recorded"], gsl.CREATED, case)
        self.assertEqual(gsl._current_state(self.ledger_conn, attempt), gsl.COMPLETED, case)
        row = self._completion_row(attempt)
        for blob in calls:
            handle = hashlib.sha256(blob).hexdigest()
            self.assertIn(handle, (row["lease_handle"], row["record_handle"],
                                   row["execution_receipt_handle"]),
                          f"{case}: the retry re-derived a handle the crashed attempt had published, "
                          f"so those bytes were a leak rather than the answer")

    # ---- NM-CRASH-13 ----------------------------------------------------------------

    def test_nm_crash_13_a_cut_after_the_last_publish_leaves_executing_not_completed(self):
        """NM-CRASH-13 — the terminal record is in the store and the ledger has not moved.

        `record_completion` receives `clock_ms()` as an argument, so a clock armed by the third
        publish cuts exactly between "all three artifacts durable" and "the ledger knows". The state
        must still be `EXECUTING`: `COMPLETED` is reached only through `record_completion`, and a
        store that holds a terminal record is not a claim that the turn completed. Anything else
        would mean a reader could take a published record as a completion.

        The retry then completes the SAME attempt rather than starting another, and the floor moves
        for the first time here — which is what makes NM-CRASH-14 a different row.
        """
        case = "NM-CRASH-13"
        attempt = self._accept()
        self._to_executing(attempt)
        publish, clock, calls = self._crash_after_all_publishes()

        with self.assertRaises(KeyboardInterrupt):
            self._op_publishing({"op": OP_COMPLETE_RUN, "execution_attempt_id": attempt,
                                 "produced": _produced()}, publish, clock=clock)
        self.assertEqual(len(calls), 3, f"{case}: not all three artifacts were published")
        self.assertIsNone(self._completion_row(attempt), case)
        self.assertEqual(gsl._current_state(self.ledger_conn, attempt), gsl.EXECUTING,
                         f"{case}: a published terminal record moved the ledger by itself")
        self.assertEqual(self._floor_rows(), [], case)

        reply = self._op({"op": OP_COMPLETE_RUN, "execution_attempt_id": attempt,
                          "produced": _produced()})
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["recorded"], gsl.CREATED, case)
        self.assertEqual(gsl._current_state(self.ledger_conn, attempt), gsl.COMPLETED, case)
        self.assertEqual(len(self._floor_rows()), 1,
                         f"{case}: the completion did not move the evidence-head floor")

    # ---- NM-CRASH-14 ----------------------------------------------------------------

    def test_nm_crash_14_a_lost_reply_after_the_floor_commit_retries_without_touching_the_floor(self):
        """NM-CRASH-14 — the completion committed, including the floor, and the reply never arrived.

        This is the cut with nothing left to repair, and it is the one most easily got wrong. The
        floor CAS runs inside `record_completion`'s transaction and only `if inserted`; the source
        says why in as many words — "an idempotent retry must not re-run the CAS (its head is by
        definition the one already accepted)". So a byte-identical retry must answer `IDEMPOTENT` and
        leave the floor row **byte for byte** as it was.

        Re-running the CAS on a retry would not be a harmless duplicate: the floor is the
        anti-rollback and anti-fork record, and a second pass over it on the same head is a write
        nobody can distinguish from an advance. Comparing the whole row, not a count, is the point.
        """
        case = "NM-CRASH-14"
        attempt = self._accept()
        self._to_executing(attempt)

        first = self._op({"op": OP_COMPLETE_RUN, "execution_attempt_id": attempt,
                          "produced": _produced()})
        self.assertTrue(first["ok"], first)
        self.assertEqual(first["recorded"], gsl.CREATED, case)
        floor_before = self._floor_rows()
        row_before = tuple(self._completion_row(attempt))
        self.assertEqual(len(floor_before), 1, f"{case}: the floor did not commit")

        # The reply is lost; the caller re-sends the byte-identical request.
        again = self._op({"op": OP_COMPLETE_RUN, "execution_attempt_id": attempt,
                          "produced": _produced()})
        self.assertTrue(again["ok"], again)
        self.assertEqual(again["recorded"], gsl.IDEMPOTENT,
                         f"{case}: a re-sent completion was treated as a new one")
        self.assertEqual(self._floor_rows(), floor_before,
                         f"{case}: the idempotent retry touched the evidence-head floor")
        self.assertEqual(tuple(self._completion_row(attempt)), row_before,
                         f"{case}: the completion row was rewritten by a retry")
        self.assertEqual(gsl._current_state(self.ledger_conn, attempt), gsl.COMPLETED, case)

    def _op_publishing(self, request, publish, now=NOW, clock=None):
        return _call(request, config=self.config, ledger_conn=self.ledger_conn, now=now,
                     publish=publish, clock=clock)


class AttestRunIsNotAnOracleTests(_LifecycleBase):
    def _completed_attempt(self):
        attempt = self._accept()
        self._to_executing(attempt)
        self._op({"op": OP_COMPLETE_RUN, "execution_attempt_id": attempt,
                  "produced": _produced()})
        return attempt

    def test_nm_oracle_01_the_old_protocol_facts_object_is_a_HARD_ERROR(self):
        """NM-ORACLE-01: a caller `facts` object at attest-run is a hard error, never attested."""
        # THE regression. Previously this exact request signed whatever arrived. It must not
        # be silently ignored either — an old caller has to learn its evidence was refused.
        attempt = self._completed_attempt()
        fabricated = {
            "op": OP_ATTEST_RUN, "run_id": "run-1", "execution_attempt_id": attempt,
            "facts": {"output_handle": "9" * 64, "receipt_id": "attacker-chosen"},
        }
        reply = self._wire(fabricated)
        self.assertFalse(reply["ok"])
        self.assertIn("facts", reply["error"])
        self.assertNotIn("attestation", reply)

    def test_nm_oracle_02_a_fabricated_run_gets_no_attestation(self):
        """NM-ORACLE-02: a fabricated run/attempt id gets no attestation (no_terminal_run_state)."""
        reply = self._op({"op": OP_ATTEST_RUN, "run_id": "run-ghost",
                          "execution_attempt_id": "att-ghost"})
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REFUSE_NO_TERMINAL_RUN)
        self.assertNotIn("attestation", reply)

    def test_an_accepted_but_unfinished_run_gets_no_attestation(self):
        attempt = self._accept()
        self._to_executing(attempt)  # EXECUTING, never completed
        reply = self._op({"op": OP_ATTEST_RUN, "run_id": "run-1",
                          "execution_attempt_id": attempt})
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REFUSE_NO_TERMINAL_RUN)

    def test_a_mismatched_run_id_gets_no_attestation(self):
        attempt = self._completed_attempt()
        reply = self._op({"op": OP_ATTEST_RUN, "run_id": "run-OTHER",
                          "execution_attempt_id": attempt})
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REFUSE_NO_TERMINAL_RUN)

    def test_a_real_completed_run_is_attested_over_supervisor_state(self):
        attempt = self._completed_attempt()
        reply = self._op({"op": OP_ATTEST_RUN, "run_id": "run-1",
                          "execution_attempt_id": attempt})
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["attestation"]["supervisor_key_id"], ATTEST_KEY_ID)
        self.assertTrue(reply["attestation"]["sig"])
        evidence = json.loads(
            __import__("base64").urlsafe_b64decode(
                reply["evidence_jcs_b64"] + "=" * (-len(reply["evidence_jcs_b64"]) % 4)
            ).decode("utf-8")
        )
        # Every value traces to the ledger or to supervisor config — none to this request.
        self.assertEqual(evidence["decision"], "completed")
        self.assertEqual(evidence["run_id"], "run-1")
        self.assertEqual(evidence["execution_attempt_id"], attempt)
        self.assertEqual(evidence["request_nonce"], "nonce-abc-123")
        self.assertEqual(evidence["output_handle"], "d" * 64)
        self.assertEqual(evidence["executor_id"], "exec-1")
        self.assertEqual(evidence["builder_id"], "builder-1")
        self.assertEqual(evidence["supervisor_id"], "sup-1")
        # The receipt_id was minted by the supervisor at acceptance, not supplied.
        self.assertTrue(evidence["receipt_id"])

    def test_attest_run_is_idempotent_over_the_same_terminal_state(self):
        attempt = self._completed_attempt()
        a = self._op({"op": OP_ATTEST_RUN, "run_id": "run-1", "execution_attempt_id": attempt})
        b = self._op({"op": OP_ATTEST_RUN, "run_id": "run-1", "execution_attempt_id": attempt})
        self.assertEqual(a["evidence_jcs_b64"], b["evidence_jcs_b64"])
        self.assertEqual(a["attestation"]["sig"], b["attestation"]["sig"])

    def test_a_full_governed_lifecycle_produces_exactly_one_attestable_run(self):
        # End-to-end over the wire: one challenge, one attempt, one attestation. A replay of
        # the challenge does not add a second attestable run.
        attempt = self._completed_attempt()
        replay = self._op({"op": OP_ACCEPT_OPEN,
                           "challenge_doc": _signed_doc(_valid_payload())})
        self.assertEqual(replay["lease"]["execution_attempt_id"], attempt)
        rows = self.ledger_conn.execute(
            "SELECT COUNT(*) FROM governed_turn_completion"
        ).fetchone()[0]
        self.assertEqual(rows, 1)


# ---------------------------------------------------------------------------
# Unknown op / malformed body / missing durable ledger
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

    def test_a_supervisor_with_no_durable_ledger_refuses_to_serve(self):
        # Running stateless is exactly the condition F-01 exploited, so it is not a
        # degraded mode — it is a refusal.
        conn = FakeConn(
            BROKER_UID,
            inbound=_frame({"op": OP_ACCEPT_OPEN, "challenge_doc": _signed_doc(_valid_payload())}),
        )
        reply = handle_connection(
            conn, BROKER_UID, _config(), _verify_sig, _recompute, _clock(NOW),
            ledger_conn=None, publish_artifact=_publish,
            read_run_evidence=lambda attempt: _run_evidence("d" * 64),
        )
        self.assertFalse(reply["ok"])
        self.assertNotIn("lease", reply)

    def test_dispatch_never_fabricates_success_on_supervisor_error(self):
        conn = FakeConn(
            BROKER_UID,
            inbound=_frame({"op": OP_ACCEPT_OPEN, "challenge_doc": _signed_doc(_valid_payload())}),
        )
        reply = handle_connection(
            conn, BROKER_UID, _config(), _verify_sig, _recompute, lambda: "not-an-int",
            ledger_conn=_ledger(), publish_artifact=_publish,
            read_run_evidence=lambda attempt: _run_evidence("d" * 64),
        )
        self.assertFalse(reply["ok"])
        self.assertNotIn("lease", reply)

    def test_attest_run_without_the_signing_seam_is_a_config_fault(self):
        # A deployment that never injected the attestation key must not serve attest-run at
        # all — the fault surfaces as a fail-closed error reply, never a fabricated one.
        conn = FakeConn(
            BROKER_UID,
            inbound=_frame({"op": OP_ATTEST_RUN, "run_id": "r", "execution_attempt_id": "a"}),
        )
        reply = handle_connection(
            conn, BROKER_UID, _config(), _verify_sig, _recompute, _clock(NOW),
            ledger_conn=_ledger(),
        )
        self.assertFalse(reply["ok"])
        self.assertNotIn("attestation", reply)


# ---------------------------------------------------------------------------
# Serve loop (injectable acceptor -> no real socket)
# ---------------------------------------------------------------------------


class ServeLoopTests(unittest.TestCase):
    def test_serve_forever_drives_injected_acceptor(self):
        conns = [
            FakeConn(
                BROKER_UID,
                inbound=_frame({"op": OP_ACCEPT_OPEN,
                                "challenge_doc": _signed_doc(_valid_payload())}),
            )
        ]
        served = list(conns)

        def accept_one():
            return conns.pop(0) if conns else None

        serve_forever(
            accept_one, BROKER_UID, _config(), _verify_sig, _recompute, _clock(NOW),
            ledger_conn=_ledger(), publish_artifact=_publish,
            read_run_evidence=lambda attempt: _run_evidence("d" * 64),
        )

        self.assertTrue(served[0].closed)
        reply = served[0].decoded_reply()
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["lease"]["lease_expires_at_ms"], NOW + LEASE_DURATION_MS)

    def test_dispatch_direct_valid_accept_open(self):
        reply = _call(
            {"op": OP_ACCEPT_OPEN, "challenge_doc": _signed_doc(_valid_payload())},
            config=_config(), ledger_conn=_ledger(),
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["lease"]["lease_expires_at_ms"], NOW + LEASE_DURATION_MS)


# ---------------------------------------------------------------------------
# The front door must survive its peers (audit R1 `governed_supervisor_server.py:626`
# and `:183`). This loop IS the availability of every governed turn on the install.
# ---------------------------------------------------------------------------


def _deeply_nested_frame(depth: int) -> bytes:
    """A syntactically valid JSON body that fits the 8 KiB frame bound and nests far past
    CPython's recursion limit. ``[[[[…]]]]`` costs 2 bytes per level."""
    body = (b"[" * depth) + (b"]" * depth)
    assert len(body) <= MAX_FRAME_BYTES, "the attack must fit inside the legal frame bound"
    return len(body).to_bytes(LENGTH_PREFIX_BYTES, "big") + body


class HostileFrameDoesNotKillTheSupervisorTests(unittest.TestCase):
    """One frame from an authorized peer must not end the process that issues every lease.

    The defect was that `handle_connection` listed its exception classes explicitly and
    `serve_forever` had no `except` at all, so any class nobody remembered — `RecursionError`
    is a `RuntimeError`, reachable from a deeply nested body inside the legal 8 KiB frame —
    escaped both and killed the process.

    WHICH exception a hostile body produces is a platform fact, not a property. The first
    version of this class asserted `RecursionError` by name; it passed on Windows and failed
    on Linux CI with an **empty** stderr, meaning the same body was refused there by the
    listed-exception branch, which does not log. The backstop is correct on both. So the
    backstop is now witnessed deterministically by injection, and the real hostile frame is
    asserted only on what holds everywhere.
    """

    def test_an_unlisted_exception_is_caught_logged_and_bounded(self):
        """The backstop itself, with no dependence on how any parser behaves.

        `MemoryError` stands in for "a class nobody listed": it is not in the explicit tuple,
        and unlike `RecursionError` it is raised identically on every platform.
        """
        conn = FakeConn(BROKER_UID, inbound=_deeply_nested_frame(8))

        def explode(*_args, **_kwargs):
            raise MemoryError("in no explicit except tuple")

        with mock.patch.object(gss, "read_frame", explode):
            with contextlib.redirect_stderr(io.StringIO()) as logged:
                reply = _handle(conn)

        # The operator DOES get the detail...
        self.assertIn("MemoryError", logged.getvalue())
        # ...and the peer does not: nothing about the fault beyond that there was one.
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["error"], "internal supervisor fault")
        self.assertEqual(conn.decoded_reply(), reply)

    def test_deeply_nested_json_becomes_a_refusal_not_an_escape(self):
        """The real hostile frame, asserted on what is true on every platform.

        Deliberately silent about which branch catches it: on Windows it is the backstop
        (`RecursionError`), on Linux CI it was the listed branch. Both are refusals, and
        pinning the mechanism is what made this test platform-dependent.
        """
        conn = FakeConn(BROKER_UID, inbound=_deeply_nested_frame(3900))
        with contextlib.redirect_stderr(io.StringIO()):
            reply = _handle(conn)

        self.assertFalse(reply["ok"])
        self.assertEqual(conn.decoded_reply(), reply)
        # Whatever the branch, the reply stays framable and leaks no internals.
        self.assertLessEqual(len(reply["error"]), MAX_ERROR_CHARS + 32)
        self.assertNotIn("Traceback", reply["error"])
        self.assertNotIn("engine/runtime", reply["error"])

    def test_serve_forever_survives_the_frame_and_keeps_serving(self):
        hostile = FakeConn(BROKER_UID, inbound=_deeply_nested_frame(3900))
        healthy = FakeConn(
            BROKER_UID,
            inbound=_frame({"op": OP_ACCEPT_OPEN,
                            "challenge_doc": _signed_doc(_valid_payload())}),
        )
        conns = [hostile, healthy]
        served = list(conns)

        def accept_one():
            return conns.pop(0) if conns else None

        with contextlib.redirect_stderr(io.StringIO()):
            serve_forever(
                accept_one, BROKER_UID, _config(), _verify_sig, _recompute, _clock(NOW),
                ledger_conn=_ledger(), publish_artifact=_publish,
                read_run_evidence=lambda attempt: _run_evidence("d" * 64),
            )

        # The loop reached the SECOND connection at all, and answered it correctly.
        self.assertTrue(served[0].closed)
        self.assertTrue(served[1].closed)
        self.assertTrue(served[1].decoded_reply()["ok"])

    def test_an_exploding_handler_does_not_end_the_accept_loop(self):
        """The backstop in ``serve_forever`` is separate from the one in
        ``handle_connection``, so it needs its own witness: a connection whose very first
        attribute access raises is not inside the handler's try block at all."""

        class Exploding:
            closed = False

            @property
            def peer_uid(self):
                raise MemoryError("in no explicit except tuple")

            def close(self):
                type(self).closed = True

        healthy = FakeConn(
            BROKER_UID,
            inbound=_frame({"op": OP_ACCEPT_OPEN,
                            "challenge_doc": _signed_doc(_valid_payload())}),
        )
        conns = [Exploding(), healthy]

        def accept_one():
            return conns.pop(0) if conns else None

        with contextlib.redirect_stderr(io.StringIO()):
            serve_forever(
                accept_one, BROKER_UID, _config(), _verify_sig, _recompute, _clock(NOW),
                ledger_conn=_ledger(), publish_artifact=_publish,
                read_run_evidence=lambda attempt: _run_evidence("d" * 64),
            )

        self.assertTrue(Exploding.closed)
        self.assertTrue(healthy.decoded_reply()["ok"])


class ConnectionBudgetTests(unittest.TestCase):
    """The TOTAL deadline that bounds one connection (audit R1 `:183`).

    ``SocketPeerConn`` cannot be constructed on a non-Linux host (``read_peercred_uid``
    refuses), so the arithmetic that decides the refusal is tested where it lives — a pure
    function plus a seam-driven read loop — rather than in a branch no runner here reaches.
    """

    def test_budget_is_the_remaining_time(self):
        self.assertEqual(recv_budget_s(100.0, 40.0), 60.0)

    def test_an_exhausted_budget_is_none_and_never_zero(self):
        # settimeout(0) is NON-BLOCKING, and the POSIX SO_RCVTIMEO it maps to reads 0 as
        # INFINITE. Returning 0.0 as the deadline lands would arm the opposite of a
        # deadline at exactly the moment it matters most.
        self.assertIsNone(recv_budget_s(100.0, 100.0))
        self.assertIsNone(recv_budget_s(100.0, 100.5))

    def test_a_drip_peer_is_cut_off_by_the_total_budget(self):
        """One byte per call, forever. A per-recv timeout would never fire — it restarts on
        every byte that arrives — so only a TOTAL budget can end this."""
        clock = {"t": 0.0}
        armed = []

        def now():
            return clock["t"]

        def arm(seconds):
            armed.append(seconds)

        def recv(_n):
            clock["t"] += 10.0  # each byte costs ten seconds of the budget
            return b"x"

        got = recv_exactly_bounded(recv, 1000, deadline=100.0, arm_timeout=arm, now=now)

        self.assertEqual(len(got), 10)          # 100 s of budget at 10 s per byte
        self.assertLess(len(got), 1000)         # the read did NOT complete
        self.assertTrue(all(t > 0 for t in armed), armed)

    def test_a_prompt_peer_is_unaffected(self):
        payload = [b"hello ", b"world"]

        def recv(_n):
            return payload.pop(0) if payload else b""

        got = recv_exactly_bounded(
            recv, 11, deadline=100.0, arm_timeout=lambda _s: None, now=lambda: 0.0)
        self.assertEqual(got, b"hello world")

    def test_a_socket_timeout_ends_the_read_instead_of_escaping(self):
        def recv(_n):
            raise socket.timeout("timed out")

        got = recv_exactly_bounded(
            recv, 8, deadline=100.0, arm_timeout=lambda _s: None, now=lambda: 0.0)
        self.assertEqual(got, b"")

    def test_read_frame_turns_a_starved_read_into_a_framing_refusal(self):
        """The budget's OUTCOME, not only its arithmetic: a short read is already a
        ``FrameError``, so a starved connection is refused rather than hung."""

        class Starved:
            def recv_exactly(self, n):
                return b""

        with self.assertRaises(FrameError):
            read_frame(Starved())


if __name__ == "__main__":
    unittest.main()
