"""The sidecar's op dispatch — and the shape of every answer it can give.

The sidecar used to have exactly one thing it could be asked. A well-formed
governance read went down the governed-turn path, came back as the execution path's
fail-closed answer, and the cockpit rendered a blocked mirror forever — not because
the engine had nothing to say, but because nothing was listening for a question.
These tests pin the dispatch that fixes that, and they are mostly about REFUSALS,
because a read surface is only worth trusting if it cannot lie about what it does
not know.

Two properties carry the file:

**A refusal never wears a read's clothes.** No refusal this sidecar emits carries a
`records` key. `ok:true` + `records:[]` means "I looked and there is nothing";
`ok:false` means "I could not look". Collapse those and a blind engine renders as a
calm, empty page, which is strictly worse than an error.

**An unimplemented op is refused by name.** Not ignored, not answered with an empty
list. The reply says which op was asked for and which ops this build serves.
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import tempfile
import unittest

import engine_sidecar

_GOVERNANCE_ENV = (
    engine_sidecar._GOVERNANCE_STATE_DIR_ENV,
    engine_sidecar._GOVERNANCE_EVIDENCE_STORE_ENV,
    engine_sidecar._GOVERNANCE_REGISTRY_ROOT_ENV,
)

_TASK_REQUEST = {
    "task_id": "t-0001", "task_class": "standard-builder", "rationale": "reply",
    "system": "you are a specialist",
    "history": [{"role": "user", "content": "hello"}],
    "request": {
        "protocol": "brops.request.v1", "workspace_id": "ws", "install_id": "in",
        "request_nonce": "nonce-1", "system_sha256": "aa" * 32, "history_sha256": "bb" * 32,
        "generation_config_sha256": "cc" * 32, "requested_at": "1000",
    },
}


def read_request(surface: str = "decisionLedger", task_id=None, **overrides) -> dict:
    body = {
        "protocol": engine_sidecar.GOVERNANCE_PROTOCOL,
        "op": engine_sidecar.GOVERNANCE_READ_OP,
        "surface": surface,
        "task_id": task_id,
        "read_only": True,
    }
    body.update(overrides)
    return body


def drive(request, argv=()) -> dict:
    """Run the sidecar entry over an in-memory pipe; return the parsed reply."""
    stdin = io.StringIO(request if isinstance(request, str) else json.dumps(request))
    stdout = io.StringIO()
    code = engine_sidecar.run(list(argv), stdin, stdout)
    assert code == 0, "the sidecar must always exit 0 (the verdict travels in the payload)"
    return json.loads(stdout.getvalue())


class _CleanEnv(unittest.TestCase):
    """Every test starts from an unprovisioned, non-self-test environment."""

    def setUp(self) -> None:
        self._saved = {
            k: os.environ.pop(k, None)
            for k in (*_GOVERNANCE_ENV, *engine_sidecar._PROVISION_ENV,
                      engine_sidecar._SUPERVISOR_SOCKET_ENV, "BRIDGE_SIDECAR_FAKE")
        }

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def set_env(self, key: str, value: str) -> None:
        os.environ[key] = value
        self.addCleanup(lambda: os.environ.pop(key, None))

    def refusal(self, reply: dict) -> dict:
        self.assertFalse(reply["ok"], reply)
        self.assertIsInstance(reply["error"], str)
        self.assertTrue(reply["error"])
        # The load-bearing assertion of this whole file.
        self.assertNotIn("records", reply)
        return reply


class DispatchTests(_CleanEnv):
    """Which request reaches which handler."""

    def test_a_request_without_an_op_still_runs_the_governed_turn_path(self) -> None:
        # The original contract, byte-for-byte: a bridge-result, fail-closed because
        # nothing is provisioned. If the dispatch swallowed this the whole desktop
        # chat path would go dark.
        reply = drive(_TASK_REQUEST)
        self.assertEqual(set(reply), {"ok", "result", "receipt", "error"})
        self.assertFalse(reply["ok"])
        self.assertIsNone(reply["result"])
        self.assertIn("not provisioned", reply["error"])

    def test_the_self_test_path_still_answers_through_the_dispatch(self) -> None:
        reply = drive(_TASK_REQUEST, argv=["--self-test"])
        self.assertTrue(reply["ok"], reply)
        self.assertIn("SELF-TEST", reply["result"])

    def test_an_unknown_op_is_refused_by_name(self) -> None:
        reply = self.refusal(drive({"op": "probe.integration"}))
        self.assertEqual(reply["protocol"], engine_sidecar.BRIDGE_OP_PROTOCOL)
        self.assertEqual(reply["op"], "probe.integration")
        # Named: the reply says what was asked for AND what this build serves, so an
        # operator can tell "not built yet" from "you spelled it wrong".
        self.assertIn("probe.integration", reply["error"])
        self.assertIn(engine_sidecar.GOVERNANCE_READ_OP, reply["error"])

    def test_an_unknown_op_is_never_answered_as_an_empty_success(self) -> None:
        for op in ("probe.integration", "governance.write", "", "GOVERNANCE.READ"):
            reply = self.refusal(drive({"op": op}))
            self.assertNotIn("result", reply)

    def test_a_non_string_op_is_refused_not_coerced(self) -> None:
        for op in (None, 7, True, ["governance.read"], {"op": "governance.read"}):
            reply = self.refusal(drive({"op": op}))
            # Nothing caller-shaped is echoed into the typed `op` field.
            self.assertIsNone(reply["op"])

    def test_an_op_whose_handler_raises_becomes_that_ops_own_refusal(self) -> None:
        # Defence in depth: a handler is not trusted to be total. A crash must land as
        # a refusal in the protocol the caller was speaking, never as a traceback on
        # stderr and an empty pipe on stdout.
        def boom(_request):
            raise RuntimeError("handler exploded")

        original = engine_sidecar._OPS[engine_sidecar.GOVERNANCE_READ_OP]
        engine_sidecar._OPS[engine_sidecar.GOVERNANCE_READ_OP] = (
            boom, engine_sidecar._governance_refusal)
        self.addCleanup(
            engine_sidecar._OPS.__setitem__, engine_sidecar.GOVERNANCE_READ_OP, original)
        reply = self.refusal(drive(read_request()))
        self.assertEqual(reply["protocol"], engine_sidecar.GOVERNANCE_PROTOCOL)
        self.assertIn("handler exploded", reply["error"])

    def test_an_unserializable_reply_is_a_refusal_not_a_half_written_pipe(self) -> None:
        # An op relays a far richer document than a bridge-result's four flat fields.
        # A value that will not encode must not leave a truncated JSON object on the
        # pipe for the desktop to parse as a short success.
        original = engine_sidecar._dispatch
        engine_sidecar._dispatch = lambda request, argv: {"ok": True, "records": [object()]}
        self.addCleanup(setattr, engine_sidecar, "_dispatch", original)
        self.refusal(drive({"op": engine_sidecar.GOVERNANCE_READ_OP}))


class ExecutionIsolationTests(_CleanEnv):
    """A read must not be able to knock on the door that executes."""

    def _trip_wires(self) -> dict:
        calls: dict[str, int] = {"real_callables": 0, "run_governed_turn": 0}

        def real_callables(_request):
            calls["real_callables"] += 1
            raise AssertionError("a read op reached the execution provisioning path")

        def governed_turn(*_args, **_kwargs):
            calls["run_governed_turn"] += 1
            raise AssertionError("a read op reached run_governed_turn")

        for name, replacement in (("_real_callables", real_callables),
                                  ("run_governed_turn", governed_turn)):
            original = getattr(engine_sidecar, name)
            setattr(engine_sidecar, name, replacement)
            self.addCleanup(setattr, engine_sidecar, name, original)
        return calls

    def test_an_unprovisioned_read_never_touches_the_execution_path(self) -> None:
        calls = self._trip_wires()
        self.refusal(drive(read_request()))
        self.assertEqual(calls, {"real_callables": 0, "run_governed_turn": 0})

    def test_a_served_read_never_touches_the_execution_path(self) -> None:
        calls = self._trip_wires()
        with tempfile.TemporaryDirectory() as state:
            self.set_env(engine_sidecar._GOVERNANCE_STATE_DIR_ENV, state)
            reply = drive(read_request())
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(calls, {"real_callables": 0, "run_governed_turn": 0})

    def test_a_self_test_flag_cannot_fabricate_a_read(self) -> None:
        # The canned self-test callables answer the TURN path only. A read carrying
        # the flag must still reach the engine — or refuse — never canned data.
        self.refusal(drive(read_request(), argv=["--self-test", "--self-test-signed"]))


class GovernanceProvisioningTests(_CleanEnv):
    """Each way the mirror can be un-servable is a distinct, named refusal."""

    def test_an_unprovisioned_mirror_refuses_and_names_the_variable(self) -> None:
        reply = self.refusal(drive(read_request()))
        self.assertEqual(reply["protocol"], engine_sidecar.GOVERNANCE_PROTOCOL)
        self.assertIn(engine_sidecar._GOVERNANCE_STATE_DIR_ENV, reply["error"])
        # It says which of the two "nothing here" answers this is.
        self.assertIn("not an empty mirror", reply["error"])

    def test_a_state_directory_that_does_not_exist_is_never_created(self) -> None:
        with tempfile.TemporaryDirectory() as base:
            absent = pathlib.Path(base) / "never-provisioned"
            self.set_env(engine_sidecar._GOVERNANCE_STATE_DIR_ENV, str(absent))
            reply = self.refusal(drive(read_request()))
            # An invented store reporting itself empty is the exact failure this
            # whole protocol exists to prevent.
            self.assertFalse(absent.exists())
        self.assertIn("absent store is not an empty store", reply["error"])

    def test_a_state_directory_that_is_a_file_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as base:
            impostor = pathlib.Path(base) / "state"
            impostor.write_text("not a runtime", encoding="utf-8")
            self.set_env(engine_sidecar._GOVERNANCE_STATE_DIR_ENV, str(impostor))
            self.refusal(drive(read_request()))

    def test_a_missing_evidence_store_directory_is_refused_not_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as state:
            self.set_env(engine_sidecar._GOVERNANCE_STATE_DIR_ENV, state)
            self.set_env(engine_sidecar._GOVERNANCE_EVIDENCE_STORE_ENV,
                         str(pathlib.Path(state) / "no-such-store"))
            reply = self.refusal(drive(read_request()))
        self.assertIn(engine_sidecar._GOVERNANCE_EVIDENCE_STORE_ENV, reply["error"])

    def test_an_unloadable_key_registry_refuses_instead_of_going_unkeyed(self) -> None:
        # Silently continuing with no keys would still "work" — and the engine would
        # then refuse the signed surfaces with "this runtime holds no trusted keys",
        # blaming the operator for a registry they DID provision and which was
        # rejected. The wrong reason is worse than no answer.
        with tempfile.TemporaryDirectory() as state:
            self.set_env(engine_sidecar._GOVERNANCE_STATE_DIR_ENV, state)
            self.set_env(engine_sidecar._GOVERNANCE_REGISTRY_ROOT_ENV,
                         str(pathlib.Path(state) / "no-registry-here"))
            reply = self.refusal(drive(read_request()))
        self.assertIn(engine_sidecar._GOVERNANCE_REGISTRY_ROOT_ENV, reply["error"])
        self.assertIn("could not be loaded", reply["error"])

    def test_a_provisioned_empty_mirror_answers_empty_rather_than_refusing(self) -> None:
        with tempfile.TemporaryDirectory() as state:
            self.set_env(engine_sidecar._GOVERNANCE_STATE_DIR_ENV, state)
            reply = drive(read_request())
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["records"], [])
        self.assertTrue(reply["empty"])
        self.assertTrue(reply["empty_reason"])

    def test_the_engine_sees_the_request_the_desktop_sent(self) -> None:
        # The engine checks the request's field SET for equality. An extra field must
        # therefore be refused by the engine — which only happens if this sidecar
        # forwarded the document unmodified instead of tidying it up first.
        with tempfile.TemporaryDirectory() as state:
            self.set_env(engine_sidecar._GOVERNANCE_STATE_DIR_ENV, state)
            reply = self.refusal(drive(read_request(limit=10)))
            self.refusal(drive(read_request(read_only="true")))
        self.assertIn("fields do not match", reply["error"])


class RelayHonestyTests(_CleanEnv):
    """What the relay does with an engine that misbehaves."""

    def _fake_engine(self, reply):
        class _API:
            def governance_read(self, _request, **_kwargs):
                return reply

        self.addCleanup(setattr, engine_sidecar, "_governance_runtime",
                        engine_sidecar._governance_runtime)
        self.addCleanup(setattr, engine_sidecar, "_governance_api",
                        engine_sidecar._governance_api)
        engine_sidecar._governance_runtime = lambda: object()
        engine_sidecar._governance_api = lambda _runtime: _API()

    def test_a_refusal_carrying_records_is_re_issued_without_them(self) -> None:
        # The one shape that must never cross this hop: ok:false WITH a records key,
        # which a consumer can read as a satisfied, empty chain.
        self._fake_engine({"ok": False, "records": [], "error": "the store is gone"})
        reply = self.refusal(drive(read_request()))
        self.assertIn("the store is gone", reply["error"])

    def test_a_reply_that_is_not_a_reply_becomes_a_refusal(self) -> None:
        # Checked BEFORE the reply is read, so the operator is told the engine
        # answered with nothing usable — not handed the `TypeError` that indexing it
        # would otherwise produce, which names a Python type instead of a fault.
        for bad in (None, [], "ok", {"records": []}, 7):
            self._fake_engine(bad)
            reply = self.refusal(drive(read_request()))
            self.assertIn("no usable reply document", reply["error"])

    def test_a_successful_reply_is_relayed_verbatim(self) -> None:
        served = {"protocol": engine_sidecar.GOVERNANCE_PROTOCOL, "ok": True,
                  "records": [{"id": "r-1"}], "empty": False, "surface": "decisionLedger"}
        self._fake_engine(dict(served))
        self.assertEqual(drive(read_request()), served)


class ProtocolDriftTests(unittest.TestCase):
    """The sidecar holds the protocol name as a literal, so it can refuse even when
    the engine module will not import. A literal can drift; this is the guard."""

    def test_the_sidecar_and_the_engine_name_the_same_protocol(self) -> None:
        import bro_control_room_api  # engine/runtime is on sys.path via engine_sidecar

        self.assertEqual(engine_sidecar.GOVERNANCE_PROTOCOL,
                         bro_control_room_api.GOVERNANCE_PROTOCOL)
        self.assertEqual(engine_sidecar.GOVERNANCE_READ_OP,
                         bro_control_room_api.GOVERNANCE_OP)

    def test_the_sidecars_refusal_has_the_engines_refusal_shape(self) -> None:
        # One refusal shape on the wire, whichever hop produced it — so a consumer
        # cannot tell "the engine refused" from "the sidecar refused" by field set
        # and start treating one of them as softer than the other.
        import bro_control_room_api

        engine = bro_control_room_api._governance_refusal("decisionLedger", None, 1, "no")
        mine = engine_sidecar._governance_refusal(
            {"surface": "decisionLedger", "task_id": None}, "no")
        self.assertEqual(set(mine), set(engine))
        self.assertNotIn("records", mine)

    def test_a_refusal_echoes_no_caller_shaped_values(self) -> None:
        hostile = {"surface": {"$ref": "boom"}, "task_id": ["../escape"]}
        reply = engine_sidecar._governance_refusal(hostile, "refused")
        self.assertIsNone(reply["surface"])
        self.assertIsNone(reply["task_id"])


def approval_request(**overrides) -> dict:
    body = {
        "schema": 1,
        "protocol": engine_sidecar.APPROVAL_REQUEST_PROTOCOL,
        "op": engine_sidecar.APPROVAL_REQUEST_OP,
        "request_id": "req-7f2a91c4",
        "task_id": "task-0001",
        "requested_command": "approve",
        "expected_task_state": "awaiting-owner-approval",
        "reason": "the cockpit operator asks the owner to approve this task",
        "requested_by_type": "desktop-operator",
        "requested_by": "gev@cockpit",
        "requested_at_epoch": 1758240000,
    }
    body.update(overrides)
    return body


class ApprovalRequestOpTests(_CleanEnv):
    """`approval.request` -- the only WRITE in the table, and it is provisioned on its own.

    The read mirror's three variables grant it nothing and it grants them nothing. That is not a
    preference: a half-provisioned operator must not be able to turn a read into a write by accident,
    and the only way to say so mechanically is to make each door need its own key.
    """

    def refusal(self, reply: dict) -> dict:
        self.assertFalse(reply["ok"], reply)
        self.assertEqual(reply["protocol"], engine_sidecar.APPROVAL_REPLY_PROTOCOL)
        self.assertIsInstance(reply["reason"], str)
        self.assertTrue(reply["reason"])
        # The same load-bearing rule as the read's, in this protocol's vocabulary: a refusal may not
        # carry a field a consumer could read as "recorded".
        for absent in ("recorded", "sequence", "entry_sha256", "chain_head_sha256"):
            self.assertNotIn(absent, reply)
        return reply

    def test_the_op_is_served_rather_than_refused_by_name(self):
        """Before anything else: an op absent from the table is refused as unknown, and that refusal
        would satisfy every other test in this class for the wrong reason."""
        reply = drive(approval_request())
        self.assertNotIn("does not serve", str(reply))
        self.assertEqual(reply["op"], engine_sidecar.APPROVAL_REQUEST_OP)

    def test_an_unprovisioned_write_is_refused_and_names_its_own_variable(self):
        reply = self.refusal(drive(approval_request()))
        self.assertIn("BROPS_APPROVAL_REQUEST_LOG_DIR", reply["reason"])

    def test_the_read_mirrors_provisioning_does_not_provision_the_write(self):
        """Measured, not assumed: with the READ fully provisioned the write still refuses."""
        state = pathlib.Path(tempfile.mkdtemp(prefix="gov-state-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(state, ignore_errors=True))
        os.environ["BROPS_GOVERNANCE_STATE_DIR"] = str(state)
        reply = self.refusal(drive(approval_request()))
        self.assertIn("BROPS_APPROVAL_REQUEST_LOG_DIR", reply["reason"])

    def test_a_log_directory_that_does_not_exist_is_refused_rather_than_created(self):
        missing = pathlib.Path(tempfile.mkdtemp(prefix="approval-log-")) / "not-there"
        self.addCleanup(lambda: __import__("shutil").rmtree(missing.parent, ignore_errors=True))
        os.environ["BROPS_APPROVAL_REQUEST_LOG_DIR"] = str(missing)
        reply = self.refusal(drive(approval_request()))
        self.assertIn("not an existing directory", reply["reason"])
        self.assertFalse(missing.exists(), "the sidecar created the store it was refusing to trust")

    def test_the_request_id_is_echoed_on_a_refusal(self):
        """So a caller can correlate a refusal with the ask that caused it. `None` when the document
        was not even an object, which is honest rather than a made-up id."""
        self.assertEqual(self.refusal(drive(approval_request()))["request_id"], "req-7f2a91c4")
        self.assertIsNone(engine_sidecar._approval_refusal("not a dict", "why")["request_id"])


class ApprovalProtocolDriftTests(unittest.TestCase):
    """Three literals in the sidecar, three constants in the engine module, one wire contract."""

    def test_the_sidecar_and_the_engine_name_the_same_protocols(self):
        import bro_approval_requests

        self.assertEqual(engine_sidecar.APPROVAL_REQUEST_PROTOCOL,
                         bro_approval_requests.APPROVAL_REQUEST_PROTOCOL)
        self.assertEqual(engine_sidecar.APPROVAL_REQUEST_OP,
                         bro_approval_requests.APPROVAL_REQUEST_OP)
        self.assertEqual(engine_sidecar.APPROVAL_REPLY_PROTOCOL,
                         bro_approval_requests.APPROVAL_REPLY_PROTOCOL)

    def test_the_request_and_reply_protocols_are_different_names(self):
        """A reply that reused the request's protocol could be replayed back in as a request."""
        self.assertNotEqual(engine_sidecar.APPROVAL_REPLY_PROTOCOL,
                            engine_sidecar.APPROVAL_REQUEST_PROTOCOL)

    def test_the_sidecars_refusal_has_the_engine_modules_refusal_shape(self):
        import bro_approval_requests

        engine = bro_approval_requests._refusal({"request_id": "req-1"}, "no")
        mine = engine_sidecar._approval_refusal({"request_id": "req-1"}, "no")
        self.assertEqual(set(engine), set(mine))
        self.assertEqual(engine, mine)

    def test_the_schema_pins_what_both_sides_call_the_protocol(self):
        schema = json.loads(
            (pathlib.Path(engine_sidecar._ENGINE) / "schemas" / "approval-request.schema.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["protocol"]["const"],
                         engine_sidecar.APPROVAL_REQUEST_PROTOCOL)
        self.assertEqual(schema["properties"]["op"]["const"],
                         engine_sidecar.APPROVAL_REQUEST_OP)


class ApprovalRequestRecordedTests(_CleanEnv):
    """The write, provisioned, with the engine's two published facts faked at their public surfaces.

    `queue_state` and `governance_read` are what the real hop calls, and nothing private is reached
    around them -- so a change that made the hop read the runtime directly would fail here rather than
    quietly bypass the surfaces the cockpit is held to.
    """

    HELD = "awaiting-owner-approval"

    def setUp(self):
        super().setUp()
        import shutil

        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="approval-e2e-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        os.environ["BROPS_APPROVAL_REQUEST_LOG_DIR"] = str(self.dir)
        self.records = []
        held = self.HELD
        records = self.records

        class _API:
            def queue_state(self, *, now_epoch):
                return {"tasks": [{"task_id": "task-0001", "state": held},
                                  {"task_id": "task-0002", "state": "running"}]}

            def governance_read(self, _request, **_kwargs):
                return {"ok": True, "records": list(records)}

        self.addCleanup(setattr, engine_sidecar, "_governance_runtime",
                        engine_sidecar._governance_runtime)
        self.addCleanup(setattr, engine_sidecar, "_governance_api",
                        engine_sidecar._governance_api)
        engine_sidecar._governance_runtime = lambda: object()
        engine_sidecar._governance_api = lambda _runtime: _API()

    def lines(self):
        path = self.dir / "approval-requests.jsonl"
        if not path.exists():
            return []
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def test_a_provisioned_ask_is_recorded_and_the_reply_is_not_a_decision(self):
        reply = drive(approval_request())
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["protocol"], engine_sidecar.APPROVAL_REPLY_PROTOCOL)
        self.assertTrue(reply["recorded"])
        self.assertIs(reply["adjudicated"], False)
        self.assertIs(reply["requester_authenticated"], False)
        self.assertEqual(reply["sequence"], 1)
        for banned in ("granted", "disposition", "verdict", "decision", "outcome", "approved"):
            self.assertNotIn(banned, reply)
        self.assertEqual(len(self.lines()), 1)

    def test_the_engines_own_clock_is_recorded_beside_the_claim(self):
        drive(approval_request(requested_at_epoch=1))
        entry = self.lines()[0]
        self.assertEqual(entry["claimed_at_epoch"], 1)
        self.assertGreater(entry["received_at_epoch"], 1)

    def test_a_stale_expectation_is_refused_through_the_whole_hop(self):
        reply = drive(approval_request(expected_task_state="running"))
        self.assertFalse(reply["ok"], reply)
        self.assertIn(self.HELD, reply["reason"])
        self.assertEqual(self.lines(), [])

    def test_a_task_the_engine_does_not_publish_is_refused(self):
        reply = drive(approval_request(task_id="task-9999"))
        self.assertFalse(reply["ok"], reply)
        self.assertEqual(self.lines(), [])

    def test_a_ref_the_evidence_chain_does_not_hold_is_refused(self):
        self.records.append({"event_id": "ev-held"})
        reply = drive(approval_request(evidence_refs=["ev-held", "ev-absent"]))
        self.assertFalse(reply["ok"], reply)
        self.assertIn("ev-absent", reply["reason"])
        self.assertEqual(self.lines(), [])

    def test_refs_the_evidence_chain_holds_are_recorded(self):
        self.records.extend([{"event_id": "ev-held"}, {"event_id": "ev-two"}])
        reply = drive(approval_request(evidence_refs=["ev-held", "ev-two"]))
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(self.lines()[0]["request"]["evidence_refs"], ["ev-held", "ev-two"])

    def test_a_second_ask_with_the_same_id_is_recorded_as_a_duplicate(self):
        self.assertFalse(drive(approval_request())["duplicate"])
        second = drive(approval_request())
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["sequence"], 2)
        self.assertEqual(len(self.lines()), 2)

    def test_the_log_is_the_only_file_the_hop_creates(self):
        drive(approval_request())
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["approval-requests.jsonl"])

    def test_a_document_carrying_a_key_is_refused_before_anything_is_written(self):
        reply = drive({**approval_request(), "key_id": "control-room-1"})
        self.assertFalse(reply["ok"], reply)
        self.assertIn("approval-request.schema.json", reply["reason"])
        self.assertEqual(self.lines(), [])


if __name__ == "__main__":
    unittest.main()
