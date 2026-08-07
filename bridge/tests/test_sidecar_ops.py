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


if __name__ == "__main__":
    unittest.main()
