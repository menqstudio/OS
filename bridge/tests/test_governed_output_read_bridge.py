"""The §4.10(f) BRIDGE hop — `bridge.governed-turn-output-read.v1`, desktop → sidecar.

The supervisor half of the output pull landed first and stopped at the supervisor's edge.
This file is about the other half of the same round trip: what the sidecar does with a
desktop's read request, and — more to the point — the four things it must be structurally
unable to do.

No socket, no key material, no network, no real clock. The supervisor behind the injected
transport seam is the REAL `governed_output_read.handle_output_read`, over a real
`governed_output_streams` row in an in-memory ledger carrying the canonical
`supervisor_ledger.sql`, over real bytes in a content-addressed store stand-in. So when a
test here says `stream_binding_mismatch` reached the desktop, a real supervisor decided it.

What the file is organized around
---------------------------------

  * **The sidecar originates NO verdict.** Every one of the five closed §4.10(f) reasons —
    including `malformed` — is produced by the SUPERVISOR and relayed verbatim. The proxy
    forwards the caller's fields unchanged rather than validating them, precisely so that
    it never has to answer for a shape it is not the authority on. `ClosedSetRelayTests`
    is the roll call and fails if any reason stops being reachable through this hop.

  * **A LOCAL failure produces NO §4.10(f) frame.** §4.10(f)'s P1-5 NOTE: a spawn/connect/
    timeout/oversize-or-malformed-reply failure "is NOT one of these reasons and produces
    NO reply frame". `OutOfBandTests` proves each of those degrades to the protocol-less
    `bridge.op.v1` document, which carries no `reason` a desktop could mistake for a
    supervisor's.

  * **The arithmetic is in a test, not in a comment.** `FrameArithmeticTests` CONSTRUCTS
    the literal maximum reply on both legs and asserts the byte counts (245940 supervisor,
    245941 bridge) against the bounds that must admit them — and against the two bounds
    that must NOT, which is why this hop is a subprocess stdio hop at all.

  * **A read still never touches the execution path.** `test_sidecar_ops.py`'s
    `ExecutionIsolationTests` pins that for ops; §4.10(f) is the first request in this file
    that legitimately reaches the supervisor SOCKET, so the same trip-wires are re-armed
    here to prove it still reaches neither `_real_callables` nor `run_governed_turn`.

No prerequisite here is optional. Everything is stdlib plus repo modules imported at module
scope, with no `try`/`except` and no `skipIf`, so a missing prerequisite is an unmissable
hard error rather than a green run with a quiet skip. (There is no
`BROPS_TEST_MISSING_PREREQUISITES` declaration anywhere in this tree, so nothing is declared
in it and nothing here may be softened.)
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import pathlib
import sqlite3
import sys
import unittest

import engine_sidecar

_ENGINE_RUNTIME = pathlib.Path(engine_sidecar.__file__).resolve().parents[1] / "engine" / "runtime"
if str(_ENGINE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_ENGINE_RUNTIME))

import brops_protocol as bp  # noqa: E402
import governed_output_read as gor  # noqa: E402
import governed_output_stream as gos  # noqa: E402
import governed_supervisor_ledger as gsl  # noqa: E402
import governed_supervisor_server as gss  # noqa: E402

SIDECAR_UID = 4004
NOW = 1_700_000_000_000
SOCKET = "/run/brops/supervisor.sock"


# ---------------------------------------------------------------------------
# A real supervisor, minus the socket
# ---------------------------------------------------------------------------


class Store(dict):
    """The content-addressed store reduced to the one operation §4.10(f) needs.

    `read` re-derives the digest and refuses a mismatch — what the real
    `brops_evidence_store.EvidenceStore.read` does, and the property the supervisor's
    handler relies on when it says it never serves a byte it has not just re-hashed.
    """

    def publish(self, data: bytes) -> str:
        handle = hashlib.sha256(data).hexdigest()
        self[handle] = data
        return handle

    def read(self, handle: str) -> bytes:
        if handle not in self:
            raise KeyError("evidence handle not in store: %s" % handle)
        data = self[handle]
        if hashlib.sha256(data).hexdigest() != handle:
            raise ValueError("store corruption at %s" % handle)
        return data


class Supervisor:
    """One accepted, completed turn with a real stream row, answering real reads.

    `serve` is exactly what the socket would deliver: the handler's own reply object. It is
    installed as `engine_sidecar._supervisor_request`, so the bridge hop below runs against
    a supervisor that can genuinely refuse rather than against a canned dictionary.
    """

    def __init__(self, output: bytes = b"hello governed world", *, attempt="attempt-1",
                 receipt_id="rcpt-1", install_id="inst-1", now_ms=NOW):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        gsl.apply_schema(self.conn)
        self.store = Store()
        self.output = output
        self.attempt = attempt
        self.receipt_id = receipt_id
        self.now_ms = now_ms
        self.seen: list = []
        handle = self.store.publish(output)
        gsl.accept_prepare(self.conn, gsl.NewAcceptance(
            install_id=install_id, request_nonce="nonce-1", challenge_handle="c" * 64,
            run_id="run-1", task_id="task-1", workspace_id="ws-1",
            execution_attempt_id=attempt, challenge_accepted_at_ms=now_ms,
            challenge_registry_handle="d" * 64, challenge_registry_hash="e" * 64,
            challenge_registry_epoch=7, challenge_registry_root_key_id="root-1",
            lease_payload_bytes=b"{}", lease_id="lease-1",
            lease_issued_at_ms=now_ms, lease_expires_at_ms=now_ms + 210_000,
            receipt_id=receipt_id, supervisor_id="sup-1", requested_at_ms=now_ms - 10,
            request_sha256="f" * 64, system_handle="1" * 64, history_handle="2" * 64,
            generation_config_handle="3" * 64,
        ), now_ms)
        _outcome, self.row = gos.mint_stream(self.conn, gos.NewStream(
            install_id=install_id, receipt_id=receipt_id, execution_attempt_id=attempt,
            output_handle=handle, output_bytes=len(output)), now_ms)
        self.token = self.row["output_stream_id"]

    def serve(self, socket_path: str, frame: dict) -> dict:
        self.seen.append((socket_path, frame))
        return gor.handle_output_read(
            frame, peer_uid=SIDECAR_UID, allowed_sidecar_uid=SIDECAR_UID,
            conn=self.conn, now_ms=self.now_ms, read_output=self.store.read)


def drive(request, argv=()) -> dict:
    """Run the sidecar entry over an in-memory pipe; return the parsed reply.

    Deliberately the process entry point and not `_bridge_output_read`: the dispatch order
    (protocol before op before task-request) is part of what these tests are about, and a
    call straight to the handler would step over it.
    """
    stdin = io.StringIO(request if isinstance(request, str) else json.dumps(request))
    stdout = io.StringIO()
    code = engine_sidecar.run(list(argv), stdin, stdout)
    assert code == 0, "the sidecar must always exit 0 (the verdict travels in the payload)"
    return json.loads(stdout.getvalue())


class _Hop(unittest.TestCase):
    """A provisioned socket path and a real supervisor behind the transport seam."""

    def setUp(self) -> None:
        self.saved_socket = os.environ.get(engine_sidecar._SUPERVISOR_SOCKET_ENV)
        os.environ[engine_sidecar._SUPERVISOR_SOCKET_ENV] = SOCKET
        self.supervisor = Supervisor()
        self.transport(self.supervisor.serve)

    def tearDown(self) -> None:
        if self.saved_socket is None:
            os.environ.pop(engine_sidecar._SUPERVISOR_SOCKET_ENV, None)
        else:
            os.environ[engine_sidecar._SUPERVISOR_SOCKET_ENV] = self.saved_socket

    def transport(self, fn) -> None:
        original = engine_sidecar._supervisor_request
        engine_sidecar._supervisor_request = fn
        self.addCleanup(setattr, engine_sidecar, "_supervisor_request", original)

    def unprovision(self) -> None:
        os.environ.pop(engine_sidecar._SUPERVISOR_SOCKET_ENV, None)

    def request(self, seq=0, **overrides) -> dict:
        req = {
            "protocol": engine_sidecar.BRIDGE_OUTPUT_READ_PROTOCOL,
            "output_stream_id": self.supervisor.token,
            "receipt_id": self.supervisor.receipt_id,
            "execution_attempt_id": self.supervisor.attempt,
            "seq": seq,
        }
        req.update(overrides)
        return req

    def read(self, seq=0, **overrides) -> dict:
        return drive(self.request(seq, **overrides))

    def refused(self, reply: dict) -> str:
        self.assertEqual(reply["protocol"],
                         engine_sidecar.BRIDGE_OUTPUT_READ_RESULT_PROTOCOL, reply)
        self.assertIs(reply["ok"], False, reply)
        return reply["error"]["reason"]

    def out_of_band(self, reply: dict) -> str:
        """Assert this is NOT a §4.10(f) frame, and hand back its human reason.

        Three properties, and each is a different way the distinction could be lost: it names a
        different protocol; it carries no `reason` at any depth, so nothing in it can be read as
        one of the five closed literals; and its `error` is prose rather than an object. A desktop
        that parsed this as a governed verdict would be reading a supervisor's decision out of a
        socket its sidecar never opened.
        """
        self.assertEqual(reply["protocol"], engine_sidecar.BRIDGE_OP_PROTOCOL, reply)
        self.assertIs(reply["ok"], False, reply)
        self.assertNotIn("reason", json.dumps(reply), reply)
        self.assertIsInstance(reply["error"], str)
        return reply["error"]


# ---------------------------------------------------------------------------
# The happy path, and what it relays
# ---------------------------------------------------------------------------


class RelayTests(_Hop):
    """One request, one supervisor round trip, one reframed reply."""

    def test_a_served_read_returns_the_exact_bytes_under_the_bridge_protocol(self) -> None:
        reply = self.read()
        self.assertEqual(reply["protocol"],
                         engine_sidecar.BRIDGE_OUTPUT_READ_RESULT_PROTOCOL)
        self.assertIs(reply["ok"], True)
        self.assertIs(reply["eof"], True)
        self.assertIsNone(reply["error"])
        self.assertEqual(bp.decode_base64url(reply["bytes_b64"]), self.supervisor.output)

    def test_exactly_one_supervisor_round_trip_at_the_provisioned_socket(self) -> None:
        # One-request/one-response, both directions: the loop lives in the desktop, and a
        # sidecar that retried or prefetched would be holding per-turn state it must not have.
        self.read()
        self.assertEqual(len(self.supervisor.seen), 1)
        socket_path, _frame = self.supervisor.seen[0]
        self.assertEqual(socket_path, SOCKET)

    def test_the_supervisor_receives_the_callers_fields_under_its_own_protocol(self) -> None:
        self.read(seq=0)
        _socket, frame = self.supervisor.seen[0]
        self.assertEqual(frame, {
            "protocol": gor.OUTPUT_READ_PROTOCOL,
            "output_stream_id": self.supervisor.token,
            "receipt_id": self.supervisor.receipt_id,
            "execution_attempt_id": self.supervisor.attempt,
            "seq": 0,
        })

    def test_every_field_but_the_protocol_is_relayed_byte_for_byte(self) -> None:
        # The one edit this hop is allowed to make is the discriminator. A re-shaped verdict
        # is an originated verdict, and the sidecar originates none.
        served = {}

        def spy(socket_path, frame):
            served.update(self.supervisor.serve(socket_path, frame))
            return dict(served)

        self.transport(spy)
        reply = self.read()
        self.assertEqual({k: v for k, v in reply.items() if k != "protocol"},
                         {k: v for k, v in served.items() if k != "protocol"})
        self.assertEqual(served["protocol"], gor.OUTPUT_READ_RESULT_PROTOCOL)

    def test_a_zero_byte_output_is_a_contract_not_an_absence(self) -> None:
        # §4.10(f): `output_bytes == 0` still has a row and exactly one legal read.
        self.supervisor = Supervisor(output=b"", attempt="attempt-empty",
                                     receipt_id="rcpt-empty")
        self.transport(self.supervisor.serve)
        reply = self.read(0)
        self.assertIs(reply["ok"], True)
        self.assertEqual(reply["bytes_b64"], "")
        self.assertIs(reply["eof"], True)
        self.assertEqual(self.refused(self.read(1)), gor.REFUSE_SEQ_OUT_OF_RANGE)

    def test_a_re_read_of_the_same_seq_returns_identical_bytes(self) -> None:
        # Idempotent by construction: the range is a pure function of `seq`, so a lost reply
        # is retried rather than resumed and there is no cursor to consume.
        self.assertEqual(self.read(0), self.read(0))


# ---------------------------------------------------------------------------
# The closed set, relayed rather than invented
# ---------------------------------------------------------------------------


class ClosedSetRelayTests(_Hop):
    """Each of the five §4.10(f) reasons, reaching the desktop through this hop.

    Every one of them is decided by the real supervisor handler. That is the point of the
    file: the sidecar has no branch that can produce any of these words.
    """

    def test_stream_unknown(self) -> None:
        self.assertEqual(self.refused(self.read(output_stream_id="U" * 43)),
                         gor.REFUSE_STREAM_UNKNOWN)

    def test_stream_expired(self) -> None:
        self.supervisor.now_ms = self.supervisor.row["expires_at_ms"] + 1
        self.assertEqual(self.refused(self.read()), gor.REFUSE_STREAM_EXPIRED)

    def test_stream_binding_mismatch(self) -> None:
        # A VALID token presented with another turn's receipt: caught server-side, which is
        # the whole of the P1-3 change, and never by this proxy.
        self.assertEqual(self.refused(self.read(receipt_id="rcpt-someone-else")),
                         gor.REFUSE_STREAM_BINDING_MISMATCH)

    def test_seq_out_of_range(self) -> None:
        self.assertEqual(self.refused(self.read(seq=9)), gor.REFUSE_SEQ_OUT_OF_RANGE)

    def test_malformed_is_the_supervisors_word_not_the_sidecars(self) -> None:
        # The proxy forwards a broken frame UNCHANGED. If it validated instead, this reason
        # would be manufactured locally — and a desktop would be told a supervisor refused
        # a stream no supervisor ever looked at.
        for broken in (self.request(seq=-1),
                       self.request(output_stream_id="short"),
                       self.request(seq="0"),
                       {k: v for k, v in self.request().items() if k != "receipt_id"},
                       dict(self.request(), extra="smuggled")):
            with self.subTest(broken=sorted(broken)):
                self.assertEqual(self.refused(drive(broken)), gor.REFUSE_MALFORMED)
        self.assertEqual(len(self.supervisor.seen), 5,
                         "every malformed frame must have reached the supervisor")

    def test_the_bridge_reason_set_is_identical_to_the_supervisors_not_a_superset(self) -> None:
        # §4.10(f): "this reason enum is IDENTICAL to the supervisor's (NOT a superset)".
        # There is no second tuple in the bridge to compare against — which IS the property,
        # so what is asserted is that no reason outside the engine's set can be relayed.
        self.transport(lambda _s, _f: {
            "protocol": gor.OUTPUT_READ_RESULT_PROTOCOL, "ok": False,
            "output_stream_id": self.supervisor.token, "seq": 0, "bytes_b64": None,
            "eof": None, "error": {"reason": "peer_denied"}})
        self.assertIn("peer_denied", self.out_of_band(self.read()))

    def test_an_unauthorized_peer_is_the_supervisors_least_informative_literal(self) -> None:
        # §4.10(f) publishes no `peer_denied`, so a peer the supervisor does not serve gets
        # `malformed` — and a stranger learns nothing about whether the stream exists.
        self.transport(lambda socket_path, frame: gor.handle_output_read(
            frame, peer_uid=SIDECAR_UID + 1, allowed_sidecar_uid=SIDECAR_UID,
            conn=self.supervisor.conn, now_ms=NOW, read_output=self.supervisor.store.read))
        self.assertEqual(self.refused(self.read()), gor.REFUSE_MALFORMED)


# ---------------------------------------------------------------------------
# Local failure: no §4.10(f) frame at all
# ---------------------------------------------------------------------------


class OutOfBandTests(_Hop):
    """§4.10(f) P1-5 — a local transport failure is not a stream verdict.

    The distinction is the whole reason the desktop can trust a `stream_expired`: if this
    process could emit one for a socket it never opened, the word would mean nothing.
    """

    def test_an_unprovisioned_socket_emits_no_governed_frame(self) -> None:
        self.unprovision()
        reason = self.out_of_band(self.read())
        self.assertIn(engine_sidecar._SUPERVISOR_SOCKET_ENV, reason)
        self.assertEqual(self.supervisor.seen, [])

    def test_a_connect_failure_emits_no_governed_frame(self) -> None:
        def boom(_socket_path, _frame):
            raise OSError("connection refused")

        self.transport(boom)
        self.assertIn("connection refused", self.out_of_band(self.read()))

    def test_a_reply_that_is_not_a_frame_emits_no_governed_frame(self) -> None:
        # The first entry is the one that isolates the FIELD-SET check, and it is here because
        # mutation testing said so: deleting that check left every other case in this list still
        # failing — on a `KeyError` from a missing key, not on the shape rule — so the test passed
        # for the wrong reason and the check read as covered while being deletable. A reply that is
        # a perfectly good §4.10(f) frame PLUS one extra key satisfies every other check in the
        # function, so only the exhaustive field set can refuse it.
        for bad in ({"protocol": gor.OUTPUT_READ_RESULT_PROTOCOL, "ok": True,
                     "output_stream_id": "x", "seq": 0, "bytes_b64": "", "eof": True,
                     "error": None, "extra": "smuggled"},
                    "not a dict",
                    {"protocol": gor.OUTPUT_READ_RESULT_PROTOCOL},
                    {"protocol": "brops.something-else.v1", "ok": True,
                     "output_stream_id": "x", "seq": 0, "bytes_b64": "", "eof": True,
                     "error": None},
                    {"protocol": gor.OUTPUT_READ_RESULT_PROTOCOL, "ok": "yes",
                     "output_stream_id": "x", "seq": 0, "bytes_b64": "", "eof": True,
                     "error": None},
                    {"protocol": gor.OUTPUT_READ_RESULT_PROTOCOL, "ok": True,
                     "output_stream_id": "x", "seq": 0, "bytes_b64": "!!not-b64!!",
                     "eof": True, "error": None},
                    {"protocol": gor.OUTPUT_READ_RESULT_PROTOCOL, "ok": False,
                     "output_stream_id": "x", "seq": 0, "bytes_b64": "AA", "eof": None,
                     "error": {"reason": gor.REFUSE_STREAM_UNKNOWN}}):
            with self.subTest(bad=bad):
                self.transport(lambda _s, _f, bad=bad: bad)
                self.out_of_band(self.read())

    def test_an_oversize_chunk_reply_emits_no_governed_frame(self) -> None:
        # The one size check this leg has, and it CAN fire: a reply carrying more than the
        # §4.10(f) stride is not a reply the frame arithmetic below admits.
        over = base64.urlsafe_b64encode(b"x" * (gor.OUTPUT_CHUNK_BYTES + 1)).decode().rstrip("=")
        self.transport(lambda _s, _f: {
            "protocol": gor.OUTPUT_READ_RESULT_PROTOCOL, "ok": True,
            "output_stream_id": self.supervisor.token, "seq": 0, "bytes_b64": over,
            "eof": True, "error": None})
        self.assertIn(str(gor.OUTPUT_CHUNK_BYTES), self.out_of_band(self.read()))

    def test_a_non_canonical_base64url_chunk_is_refused_rather_than_re_encoded(self) -> None:
        # `base64.urlsafe_b64decode` tolerates a padded value; `decode_base64url` does not.
        # A value that decodes only under the lenient decoder must never reach a desktop
        # that might decode it differently.
        padded = base64.urlsafe_b64encode(b"abcd").decode()  # keeps its '=' padding
        self.assertTrue(padded.endswith("="))
        self.transport(lambda _s, _f: {
            "protocol": gor.OUTPUT_READ_RESULT_PROTOCOL, "ok": True,
            "output_stream_id": self.supervisor.token, "seq": 0, "bytes_b64": padded,
            "eof": True, "error": None})
        self.assertIn("canonical", self.out_of_band(self.read()))


# ---------------------------------------------------------------------------
# Dispatch, isolation, drift
# ---------------------------------------------------------------------------


class DispatchTests(_Hop):
    """Which request reaches this hop — and which must never."""

    def test_a_task_request_is_still_a_task_request(self) -> None:
        # The frozen path, untouched: no `protocol` key, so it cannot be re-read as a pull.
        reply = drive({"task_id": "t-1", "task_class": "standard-builder",
                       "rationale": "reply", "system": "s", "history": [], "request": {}})
        self.assertEqual(set(reply), {"ok", "result", "receipt", "error"})
        self.assertEqual(self.supervisor.seen, [])

    def test_the_task_request_contract_cannot_grow_a_protocol_key(self) -> None:
        # The disjointness is structural, not conventional — assert the schema still says so.
        schema = json.loads((pathlib.Path(engine_sidecar.__file__).resolve().parent
                             / "contracts" / "task-request.schema.json")
                            .read_text(encoding="utf-8"))
        self.assertIs(schema["additionalProperties"], False)
        self.assertNotIn("protocol", schema["properties"])

    def test_an_op_still_reaches_its_op_and_not_this_hop(self) -> None:
        self.assertEqual(drive({"op": "governance.read"})["protocol"],
                         engine_sidecar.GOVERNANCE_PROTOCOL)
        self.assertEqual(self.supervisor.seen, [])

    def test_an_op_smuggled_alongside_the_protocol_reaches_the_supervisor_as_junk(self) -> None:
        # The sidecar's grant on that socket is a closed tuple of protocol NAMES. An `op`
        # written here is forwarded as the extra field it is and refused by shape — it can
        # never become a §5 lifecycle call.
        self.assertEqual(self.refused(self.read(op="accept-open")), gor.REFUSE_MALFORMED)
        _socket, frame = self.supervisor.seen[0]
        self.assertEqual(frame["protocol"], gor.OUTPUT_READ_PROTOCOL)

    def test_the_callers_own_protocol_value_cannot_relabel_the_forwarded_frame(self) -> None:
        # `protocol` is written first and the caller's is dropped, so there is no request
        # that makes this hop speak anything but the one protocol it is allowed to speak.
        frame = engine_sidecar._forwarded_output_read(
            {"protocol": "brops.governed-turn-open.v1", "seq": 0}, gor.OUTPUT_READ_PROTOCOL)
        self.assertEqual(frame, {"protocol": gor.OUTPUT_READ_PROTOCOL, "seq": 0})


class ExecutionIsolationTests(_Hop):
    """A pull is the egress of a turn that is already over. It executes nothing.

    `test_sidecar_ops.py` pins this for the read OPS. §4.10(f) is the first request in the
    sidecar that legitimately reaches the supervisor socket, so the same trip-wires are
    re-armed against the same two doors.
    """

    def _trip_wires(self) -> dict:
        calls = {"real_callables": 0, "run_governed_turn": 0}

        def real_callables(_request):
            calls["real_callables"] += 1
            raise AssertionError("an output read reached the execution provisioning path")

        def governed_turn(*_args, **_kwargs):
            calls["run_governed_turn"] += 1
            raise AssertionError("an output read reached run_governed_turn")

        for name, replacement in (("_real_callables", real_callables),
                                  ("run_governed_turn", governed_turn)):
            original = getattr(engine_sidecar, name)
            setattr(engine_sidecar, name, replacement)
            self.addCleanup(setattr, engine_sidecar, name, original)
        return calls

    def test_a_served_read_never_touches_the_execution_path(self) -> None:
        calls = self._trip_wires()
        self.assertIs(self.read()["ok"], True)
        self.assertEqual(calls, {"real_callables": 0, "run_governed_turn": 0})

    def test_an_unprovisioned_read_never_touches_the_execution_path(self) -> None:
        calls = self._trip_wires()
        self.unprovision()
        self.out_of_band(self.read())
        self.assertEqual(calls, {"real_callables": 0, "run_governed_turn": 0})

    def test_a_self_test_flag_cannot_fabricate_a_chunk(self) -> None:
        # The canned self-test callables answer the TURN path only. A pull carrying the flag
        # must still reach a supervisor — or fail out of band — never canned bytes.
        self.unprovision()
        self.out_of_band(drive(self.request(), argv=["--self-test", "--self-test-signed"]))


class ProtocolDriftTests(unittest.TestCase):
    """The bridge literals and the engine constants, held apart by exactly one prefix."""

    def test_the_two_hops_name_the_same_protocol_under_two_prefixes(self) -> None:
        self.assertEqual(engine_sidecar.BRIDGE_OUTPUT_READ_PROTOCOL,
                         gor.OUTPUT_READ_PROTOCOL.replace("brops.", "bridge.", 1))
        self.assertEqual(engine_sidecar.BRIDGE_OUTPUT_READ_RESULT_PROTOCOL,
                         gor.OUTPUT_READ_RESULT_PROTOCOL.replace("brops.", "bridge.", 1))

    def test_the_bridge_frames_are_disjoint_from_every_other_bridge_document(self) -> None:
        # §4.6/Appendix B: every `bridge.governed-*` schema is disjoint from `bridge.result`
        # via its REQUIRED top-level `protocol` const — never via a shared field.
        for other in (engine_sidecar.BRIDGE_OP_PROTOCOL, engine_sidecar.GOVERNANCE_PROTOCOL,
                      "bridge.result", "bridge.task-request"):
            self.assertNotEqual(engine_sidecar.BRIDGE_OUTPUT_READ_PROTOCOL, other)
            self.assertNotEqual(engine_sidecar.BRIDGE_OUTPUT_READ_RESULT_PROTOCOL, other)

    def test_the_hop_restates_none_of_the_engines_output_read_contract(self) -> None:
        """Reuse, never copy — asserted over the sidecar's CODE, not its prose.

        The reply field set, the closed reason set, the chunk stride and the supervisor's
        own protocol consts are the engine's values, so the two hops cannot drift into
        accepting different frames. A plain text scan would fail on the module comment that
        EXPLAINS the arithmetic, which is the opposite of what this rule is for, so the
        source is parsed and only real constants are examined. Docstrings are excluded for
        the same reason comments are: writing a number down is not restating it.
        """
        import ast

        tree = ast.parse(pathlib.Path(engine_sidecar.__file__).read_text(encoding="utf-8"))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                body = getattr(node, "body", None) or []
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    docstrings.add(id(body[0].value))
        constants = {node.value for node in ast.walk(tree)
                     if isinstance(node, ast.Constant) and id(node) not in docstrings}
        forbidden = set(gor.OUTPUT_READ_REFUSAL_REASONS)
        forbidden |= {gor.OUTPUT_READ_PROTOCOL, gor.OUTPUT_READ_RESULT_PROTOCOL,
                      gor.OUTPUT_CHUNK_BYTES, gor.OUTPUT_STREAM_ID_LEN}
        # The reply FIELD NAMES are deliberately not in this set. `OUTPUT_READ_REPLY_FIELDS`
        # is imported and used for the set-equality check that decides whether a reply is a
        # §4.10(f) frame at all; naming `reply["eof"]` afterwards is navigating the object
        # that check already accepted, not a second copy of the contract. What must never be
        # restated is anything a DECISION turns on: the closed reason set (an unpublished
        # literal would travel into a desktop Block), the two protocol consts, the stride
        # and the token length.
        restated = sorted(str(v) for v in (constants & forbidden))
        self.assertEqual(restated, [],
                         "the sidecar restates engine contract values instead of importing "
                         "them: %s" % restated)


# ---------------------------------------------------------------------------
# The arithmetic — every bound that has to admit a full chunk, and the two that cannot
# ---------------------------------------------------------------------------


class FrameArithmeticTests(unittest.TestCase):
    """Done first, and in a test rather than in a comment.

    §4.10(f) is the only governed protocol whose reply is genuinely large: 184320 decoded
    bytes ride as 245760 base64url characters. Steps 3, 4 and 5 each declined to write a
    check the numbers proved could never fire; this class is the other half of that
    discipline — it names the bounds that DO decide, including the two that decide this hop
    must be a subprocess stdio hop and not a framed-IPC one.
    """

    @staticmethod
    def _max_supervisor_reply() -> bytes:
        reply = gor.output_read_ok("A" * gor.OUTPUT_STREAM_ID_LEN, 44,
                                   b"x" * gor.OUTPUT_CHUNK_BYTES, False)
        return json.dumps(reply, separators=(",", ":")).encode("utf-8")

    @classmethod
    def _max_bridge_reply(cls) -> bytes:
        reply = json.loads(cls._max_supervisor_reply())
        reply["protocol"] = engine_sidecar.BRIDGE_OUTPUT_READ_RESULT_PROTOCOL
        return json.dumps(reply, separators=(",", ":")).encode("utf-8")

    def test_the_literal_maximum_reply_fits_the_socket_on_the_supervisor_leg(self) -> None:
        body = self._max_supervisor_reply()
        self.assertEqual(len(body), 245_940)
        self.assertLessEqual(len(body), bp.MAX_FRAME_BYTES)
        self.assertEqual(bp.MAX_FRAME_BYTES - len(body), 16_204)
        # And it really does encode: `encode_frame` is the transport's own bound, so this is
        # the check the whole pull rests on rather than a restatement of it.
        self.assertEqual(len(bp.encode_frame(json.loads(body))), len(body) + 4)

    def test_the_reframed_reply_is_one_byte_longer_and_still_fits(self) -> None:
        # `bridge.` is one character longer than `brops.`; nothing else changes.
        self.assertEqual(len(self._max_bridge_reply()), 245_941)
        self.assertEqual(len(self._max_bridge_reply()) - len(self._max_supervisor_reply()), 1)

    def test_the_desktop_stdout_bound_admits_a_full_chunk_with_room_to_spare(self) -> None:
        # `ai.rs::MAX_STDOUT_BYTES`, the bound on the sidecar→desktop leg. Asserted from the
        # Rust source so the number cannot drift silently on the other side of the pipe.
        ai_rs = (pathlib.Path(engine_sidecar.__file__).resolve().parents[1]
                 / "apps" / "desktop" / "src-tauri" / "src" / "ai.rs")
        line = next(l for l in ai_rs.read_text(encoding="utf-8").splitlines()
                    if "const MAX_STDOUT_BYTES" in l)
        self.assertIn("9 * 1024 * 1024", line)
        self.assertLess(len(self._max_bridge_reply()), 9 * 1024 * 1024)

    def test_neither_framed_ipc_bound_could_ever_carry_a_chunk(self) -> None:
        # This is why the pull is a stdio hop. The supervisor's BROKER-facing frame bound and
        # the desktop's own IPC payload cap are both 8192 — 30x too small — so a future
        # "simplification" onto either would fail at the first full chunk rather than at the
        # first empty one.
        self.assertEqual(gss.MAX_FRAME_BYTES, 8192)
        self.assertGreater(len(self._max_supervisor_reply()), gss.MAX_FRAME_BYTES)
        ipc_rs = (pathlib.Path(engine_sidecar.__file__).resolve().parents[1]
                  / "apps" / "desktop" / "src-tauri" / "core" / "src" / "ipc_framing.rs")
        line = next(l for l in ipc_rs.read_text(encoding="utf-8").splitlines()
                    if "MAX_FRAME_PAYLOAD_BYTES" in l and "pub const" in l)
        self.assertIn("8192", line)
        self.assertGreater(len(self._max_bridge_reply()), 8192)

    def test_the_largest_legal_request_is_a_few_hundred_bytes(self) -> None:
        # Why there is no request-side cap in the sidecar: the largest frame this shape
        # accepts is 422 bytes against 262144, so a cap here could never fire.
        request = {"protocol": engine_sidecar.BRIDGE_OUTPUT_READ_PROTOCOL,
                   "output_stream_id": "A" * gor.OUTPUT_STREAM_ID_LEN,
                   "receipt_id": "r" * 128, "execution_attempt_id": "e" * 128, "seq": 45}
        self.assertEqual(len(json.dumps(request, separators=(",", ":")).encode()), 422)
        self.assertLess(422, bp.MAX_FRAME_BYTES)

    def test_a_full_size_chunk_survives_the_whole_hop(self) -> None:
        # The arithmetic, exercised rather than only computed: a maximum-stride chunk goes
        # through the real supervisor handler, the real reframing, and the real stdout write.
        supervisor = Supervisor(output=b"z" * gor.OUTPUT_CHUNK_BYTES, attempt="attempt-max",
                                receipt_id="rcpt-max")
        original = engine_sidecar._supervisor_request
        engine_sidecar._supervisor_request = supervisor.serve
        saved = os.environ.get(engine_sidecar._SUPERVISOR_SOCKET_ENV)
        os.environ[engine_sidecar._SUPERVISOR_SOCKET_ENV] = SOCKET
        try:
            reply = drive({"protocol": engine_sidecar.BRIDGE_OUTPUT_READ_PROTOCOL,
                           "output_stream_id": supervisor.token,
                           "receipt_id": supervisor.receipt_id,
                           "execution_attempt_id": supervisor.attempt, "seq": 0})
        finally:
            engine_sidecar._supervisor_request = original
            if saved is None:
                os.environ.pop(engine_sidecar._SUPERVISOR_SOCKET_ENV, None)
            else:
                os.environ[engine_sidecar._SUPERVISOR_SOCKET_ENV] = saved
        self.assertIs(reply["ok"], True)
        self.assertEqual(len(reply["bytes_b64"]), gor.MAX_OUTPUT_CHUNK_B64_LEN)
        self.assertEqual(bp.decode_base64url(reply["bytes_b64"]), supervisor.output)


if __name__ == "__main__":
    unittest.main()
