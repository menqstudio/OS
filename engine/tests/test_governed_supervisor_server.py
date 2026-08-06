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

import hashlib
import hmac
import json
import pathlib
import sqlite3
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import governed_supervisor_ledger as gsl  # noqa: E402
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


def _call(request, *, config, ledger_conn, now=NOW):
    """Direct dispatch (no framing) with the durable ledger wired in."""
    return dispatch(
        request,
        config,
        _verify_sig,
        _recompute,
        _clock(now),
        conn=ledger_conn,
        publish_artifact=_publish,
        read_run_evidence=lambda attempt: _run_evidence("d" * 64),
        sign_attestation=_sign_attestation,
        supervisor_attestation_key_id=ATTEST_KEY_ID,
    )


# ---------------------------------------------------------------------------
# Peer authentication (allowlist ONLY the broker uid)
# ---------------------------------------------------------------------------


class PeerDenyTests(unittest.TestCase):
    def test_non_broker_peer_denied_before_any_frame(self):
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
        hostile = {"op": "" * 3_000}
        conn = FakeConn(BROKER_UID, inbound=_frame(hostile))
        reply = _handle(conn)
        self.assertFalse(reply["ok"])
        self.assertLessEqual(len(conn.out), MAX_FRAME_BYTES + LENGTH_PREFIX_BYTES)
        self.assertTrue(conn.out, "a reply was still written")


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


class AttestRunIsNotAnOracleTests(_LifecycleBase):
    def _completed_attempt(self):
        attempt = self._accept()
        self._to_executing(attempt)
        self._op({"op": OP_COMPLETE_RUN, "execution_attempt_id": attempt,
                  "produced": _produced()})
        return attempt

    def test_the_old_protocol_facts_object_is_a_HARD_ERROR(self):
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

    def test_a_fabricated_run_gets_no_attestation(self):
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


if __name__ == "__main__":
    unittest.main()
