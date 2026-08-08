"""The governance mirror's last hop: engine -> sidecar -> the desktop's stdout.

`engine/tests/test_governance_read.py` proves the engine answers honestly.
`bridge/tests/test_sidecar_ops.py` proves the sidecar dispatches honestly. Neither
proves the join, and the join is where this feature was actually broken: the engine
had a real three-valued reply and the desktop had a real reader for it, with nothing
in between. A test that stops at either side would have stayed green through the
entire outage.

So these tests drive the SIDECAR ENTRY POINT over a real orchestration runtime and
assert against what comes out of the pipe. What they are watching for is the middle
value surviving the crossing: `ok:true` + records, `ok:true` + `empty:true`, and
`ok:false` with no `records` key at all. A transport that turns "I looked and there
is nothing" into "I could not look" — or, far worse, the other way round — is a
transport that eventually shows a calm, empty governance page over a blind engine.
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = ROOT.parent / "bridge"
for _path in (ROOT / "runtime", ROOT / "tools", pathlib.Path(__file__).resolve().parent,
              BRIDGE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from _prerequisites import BRIDGE_SIDECAR, require  # noqa: E402

# Stated before the import it would otherwise break on, and stated for the whole module:
# every test here drives the real sidecar entry point, which lives in bridge/. The JOIN
# between the two trees is the thing under test, so no fixture inside engine/ could
# stand in for it -- this is an assertion about the source repository. Deployment Step 6
# copies engine/ alone, where the missing tree used to surface as a bare
# "ModuleNotFoundError: No module named 'engine_sidecar'" from the loader. Under CI,
# where bridge/ is always checked out, `require` FAILS rather than skipping.
require(BRIDGE_SIDECAR)

import engine_sidecar  # noqa: E402  (bridge/ placed on the path above)
from bro_control_room_api import GOVERNANCE_OP, GOVERNANCE_PROTOCOL, ControlRoomAPIV1  # noqa: E402
from bro_orchestration_runtime_v1 import DurableOrchestrationRuntimeV1  # noqa: E402
# Helper functions only — importing a TestCase from another module would re-run that
# module's whole suite under this one's name.
from test_orchestration_runtime import AGENT, task_contract  # noqa: E402

SIDECAR = BRIDGE / "engine_sidecar.py"


def read_request(surface: str = "decisionLedger", task_id=None, **overrides) -> dict:
    body = {
        "protocol": GOVERNANCE_PROTOCOL,
        "op": GOVERNANCE_OP,
        "surface": surface,
        "task_id": task_id,
        "read_only": True,
    }
    body.update(overrides)
    return body


class GovernanceSidecarRouteTests(unittest.TestCase):
    """A real runtime on one side, the sidecar's stdout on the other."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state_dir = pathlib.Path(self.temporary.name) / "state"
        self.state_dir.mkdir()
        self.runtime = DurableOrchestrationRuntimeV1(self.state_dir, ROOT)
        self.api = ControlRoomAPIV1(self.runtime)
        for key in (engine_sidecar._GOVERNANCE_EVIDENCE_STORE_ENV,
                    engine_sidecar._GOVERNANCE_REGISTRY_ROOT_ENV):
            self._set_env(key, None)
        self._set_env(engine_sidecar._GOVERNANCE_STATE_DIR_ENV, str(self.state_dir))

    def _set_env(self, key: str, value: str | None) -> None:
        saved = os.environ.get(key)

        def restore() -> None:
            if saved is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = saved

        self.addCleanup(restore)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    def drive(self, request, argv=()) -> dict:
        stdin = io.StringIO(json.dumps(request))
        stdout = io.StringIO()
        code = engine_sidecar.run(list(argv), stdin, stdout)
        self.assertEqual(code, 0, "the sidecar must always exit 0")
        return json.loads(stdout.getvalue())

    # --- the three values, one by one ------------------------------------------------

    def test_an_empty_runtime_crosses_the_bridge_as_empty_not_as_blocked(self) -> None:
        # The value that is easy to lose. Before the dispatch existed this arrived as
        # a fail-closed execution error and the cockpit showed a blocked mirror, which
        # is the same picture a real outage draws.
        for surface in ("decisionLedger", "verdicts", "approvalQueue"):
            reply = self.drive(read_request(surface))
            self.assertTrue(reply["ok"], reply)
            self.assertEqual(reply["records"], [])
            self.assertTrue(reply["empty"])
            self.assertTrue(reply["empty_reason"], "an empty mirror must say why")

    def test_real_records_arrive_exactly_as_the_engine_produced_them(self) -> None:
        self.runtime.create_task(task_contract("task-route"), now_epoch=100)
        self.runtime.claim_next(AGENT, now_epoch=101)
        reply = self.drive(read_request())
        self.assertTrue(reply["ok"], reply)
        self.assertFalse(reply["empty"])
        self.assertEqual([record["next_state"] for record in reply["records"]],
                         ["draft", "queued", "routing", "running"])
        # Verbatim: the same document the engine hands its in-process callers, minus
        # only the clock. Anything the transport added or dropped shows up here.
        direct = self.api.governance_read(read_request(), now_epoch=reply["read_at_epoch"])
        self.assertEqual(reply, direct)

    def test_an_engine_refusal_crosses_the_bridge_still_carrying_no_records(self) -> None:
        # This runtime has no evidence store, so the engine is blind to the chain and
        # says so in its own words. The transport must not soften that into an empty
        # chain — and must not append a `records` key on the way past.
        reply = self.drive(read_request("evidenceChain"))
        self.assertFalse(reply["ok"], reply)
        self.assertNotIn("records", reply)
        self.assertIn("not an empty chain", reply["error"])

    def test_a_task_filter_survives_the_crossing(self) -> None:
        self.runtime.create_task(task_contract("task-one"), now_epoch=100)
        self.runtime.create_task(task_contract("task-two"), now_epoch=100)
        reply = self.drive(read_request(task_id="task-two"))
        self.assertTrue(reply["ok"], reply)
        self.assertTrue(reply["known_task"])
        self.assertEqual({record["task_id"] for record in reply["records"]}, {"task-two"})
        # And an id the engine never heard of is a known-absence, not a refusal.
        unknown = self.drive(read_request(task_id="task-nowhere"))
        self.assertTrue(unknown["ok"], unknown)
        self.assertTrue(unknown["empty"])
        self.assertFalse(unknown["known_task"])

    # --- what the crossing must not do -----------------------------------------------

    def test_the_read_writes_nothing_to_the_runtime(self) -> None:
        self.runtime.create_task(task_contract("task-ro"), now_epoch=100)
        before = self.api._integrity()
        for surface in ("decisionLedger", "verdicts", "approvalQueue", "evidenceChain"):
            self.drive(read_request(surface))
        self.assertEqual(before, self.api._integrity())

    def test_a_read_never_reaches_the_execution_path(self) -> None:
        # `_real_callables` raises unconditionally pending Wave 3b-1B and must stay
        # that way. A read has no business anywhere near it — not even to be refused
        # by it, which is how the mirror broke in the first place.
        calls: list[str] = []
        for name in ("_real_callables", "run_governed_turn"):
            original = getattr(engine_sidecar, name)
            self.addCleanup(setattr, engine_sidecar, name, original)
            setattr(engine_sidecar, name,
                    lambda *a, _n=name, **k: calls.append(_n) or (_ for _ in ()).throw(
                        AssertionError(f"a governance read reached {_n}")))
        self.assertTrue(self.drive(read_request())["ok"])
        self.assertEqual(calls, [])

    def test_the_governed_turn_path_is_untouched_by_the_dispatch(self) -> None:
        # No `op` key -> the original contract, still fail-closed and still shaped as
        # a bridge-result. The mirror must not have cost the chat path anything.
        request = {
            "task_id": "t-route", "task_class": "standard-builder", "rationale": "hi",
            "system": "s", "history": [{"role": "user", "content": "hello"}],
            "request": {
                "protocol": "brops.request.v1", "workspace_id": "ws", "install_id": "in",
                "request_nonce": "n", "system_sha256": "aa" * 32,
                "history_sha256": "bb" * 32, "generation_config_sha256": "cc" * 32,
                "requested_at": "1000",
            },
        }
        reply = self.drive(request)
        self.assertEqual(set(reply), {"ok", "result", "receipt", "error"})
        self.assertFalse(reply["ok"])
        self.assertIsNone(reply["result"])

    # --- the real pipe ----------------------------------------------------------------

    def test_the_same_answer_comes_back_over_a_real_subprocess_pipe(self) -> None:
        # The desktop spawns this file and reads its stdout. In-memory StringIO proves
        # the routing; only a real process proves nothing else is written to the pipe.
        self.runtime.create_task(task_contract("task-pipe"), now_epoch=100)
        completed = subprocess.run(
            [sys.executable, str(SIDECAR)],
            input=json.dumps(read_request()), capture_output=True, text=True,
            env={**os.environ, engine_sidecar._GOVERNANCE_STATE_DIR_ENV: str(self.state_dir)},
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        reply = json.loads(completed.stdout)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual({record["task_id"] for record in reply["records"]}, {"task-pipe"})

    def test_an_unknown_op_over_the_real_pipe_is_a_named_refusal(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SIDECAR)],
            input=json.dumps({"op": "probe.integration"}), capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        reply = json.loads(completed.stdout)
        self.assertFalse(reply["ok"])
        self.assertNotIn("records", reply)
        self.assertIn("probe.integration", reply["error"])


if __name__ == "__main__":
    unittest.main()
