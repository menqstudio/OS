"""`bro_approval_requests` — the five obligations, each held by a test that dies when it is broken.

The obligations were written in `docs/design/T-021_SCHEMA_AUDIT.md` BEFORE this module existed, for the
reason `docs/OWNER_ACTION_REQUIRED.md` gives about the invariants above them: a contract test designed by
whoever is trying to pass it proves nothing. So the names below are the audit's, not the code's.

Every refusal test also asserts that NOTHING WAS APPENDED. A refusal that quietly records is the worst
of the two outcomes: the reader is told no and the log says yes.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_approval_requests import (          # noqa: E402  (path set above, as every test here does)
    APPROVAL_REPLY_PROTOCOL,
    APPROVAL_REQUEST_OP,
    APPROVAL_REQUEST_PROTOCOL,
    ApprovalRequestError,
    ApprovalRequestLog,
)

HELD_STATE = "awaiting-owner-approval"
TASKS = {"task-0001": HELD_STATE, "task-0002": "running"}
ENGINE_NOW = 1_758_300_000
CLAIMED = 1_758_240_000


def ask(**overrides):
    doc = {
        "schema": 1,
        "protocol": APPROVAL_REQUEST_PROTOCOL,
        "op": APPROVAL_REQUEST_OP,
        "request_id": "req-7f2a91c4",
        "task_id": "task-0001",
        "requested_command": "approve",
        "expected_task_state": HELD_STATE,
        "reason": "the cockpit operator asks the owner to approve this task",
        "requested_by_type": "desktop-operator",
        "requested_by": "gev@cockpit",
        "requested_at_epoch": CLAIMED,
    }
    doc.update(overrides)
    return doc


class ApprovalRequestLogTests(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="approval-requests-"))
        self.log = ApprovalRequestLog(self.dir / "state", ROOT)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def record(self, request=None, **kwargs):
        kwargs.setdefault("now_epoch", ENGINE_NOW)
        kwargs.setdefault("task_states", TASKS)
        return self.log.record(ask() if request is None else request, **kwargs)

    def assertNothingAppended(self, reply):
        self.assertFalse(reply["ok"], reply)
        for absent in ("recorded", "sequence", "entry_sha256", "chain_head_sha256"):
            self.assertNotIn(absent, reply, f"a refusal must not carry `{absent}`")
        self.assertEqual(self.log.entries(), [], "a refusal appended to the log")

    # -- the control -----------------------------------------------------------------------
    def test_a_well_formed_ask_is_recorded(self):
        reply = self.record()
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["protocol"], APPROVAL_REPLY_PROTOCOL)
        self.assertTrue(reply["recorded"])
        self.assertEqual(reply["sequence"], 1)
        self.assertEqual(len(self.log.entries()), 1)
        self.log.verify_chain()

    def test_the_reply_cannot_be_read_as_a_decision(self):
        """Invariant 2, on the way back. There is no field to read instead of `adjudicated: false`."""
        reply = self.record()
        self.assertIs(reply["adjudicated"], False)
        self.assertIn("recorded, not adjudicated", reply["note"])
        for banned in ("granted", "disposition", "verdict", "decision", "outcome", "approved",
                       "state", "result"):
            with self.subTest(field=banned):
                self.assertNotIn(banned, reply)

    def test_the_reply_says_the_requester_was_not_authenticated(self):
        """Invariant 4. The engine records what was CLAIMED and says how it was established."""
        reply = self.record()
        self.assertIs(reply["requester_authenticated"], False)
        self.assertIs(self.log.entries()[0]["requester_authenticated"], False)

    # -- O-1 -------------------------------------------------------------------------------
    def test_a_repeated_request_id_is_recorded_as_a_duplicate_and_not_a_second_decision(self):
        first = self.record()
        second = self.record()
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"], "the second ask with one id must say so")
        self.assertEqual(second["sequence"], 2)
        self.assertEqual(len(self.log.entries()), 2, "a duplicate is RECORDED, not dropped")
        self.assertIs(second["adjudicated"], False)

    def test_a_different_request_id_is_not_a_duplicate(self):
        self.record()
        self.assertFalse(self.record(ask(request_id="req-0000ffff"))["duplicate"])

    # -- O-2 -------------------------------------------------------------------------------
    def test_a_stale_expectation_is_refused_and_names_both_states(self):
        reply = self.record(ask(expected_task_state="running"))
        self.assertNothingAppended(reply)
        self.assertIn(HELD_STATE, reply["reason"])
        self.assertIn("running", reply["reason"])

    def test_an_unknown_task_is_refused(self):
        reply = self.record(ask(task_id="task-9999"))
        self.assertNothingAppended(reply)
        self.assertIn("task-9999", reply["reason"])

    def test_the_state_the_engine_held_is_recorded_beside_the_ask(self):
        self.record()
        self.assertEqual(self.log.entries()[0]["task_state_when_received"], HELD_STATE)

    # -- O-3 -------------------------------------------------------------------------------
    def test_the_requesters_clock_is_recorded_as_claimed_beside_the_engines_own(self):
        self.record()
        entry = self.log.entries()[0]
        self.assertEqual(entry["claimed_at_epoch"], CLAIMED)
        self.assertEqual(entry["received_at_epoch"], ENGINE_NOW)
        self.assertNotEqual(entry["claimed_at_epoch"], entry["received_at_epoch"],
                            "the fixture must differ, or this test would pass on either field")

    # -- O-4 -------------------------------------------------------------------------------
    def test_an_evidence_ref_the_engine_does_not_hold_is_refused_by_name(self):
        reply = self.record(ask(evidence_refs=["ev-1", "ev-missing"]),
                            evidence_has=lambda ref: ref == "ev-1")
        self.assertNothingAppended(reply)
        self.assertIn("ev-missing", reply["reason"])
        self.assertNotIn("ev-1'", reply["reason"], "a ref the store HAS must not be named as missing")

    def test_refs_are_refused_when_the_engine_cannot_resolve_any(self):
        reply = self.record(ask(evidence_refs=["ev-1"]))
        self.assertNothingAppended(reply)
        self.assertIn("cannot resolve", reply["reason"])

    def test_refs_the_engine_holds_are_recorded(self):
        reply = self.record(ask(evidence_refs=["ev-1", "ev-2"]), evidence_has=lambda ref: True)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(self.log.entries()[0]["request"]["evidence_refs"], ["ev-1", "ev-2"])

    # -- the schema is the single source ---------------------------------------------------
    def test_a_document_carrying_a_key_is_refused_by_the_schema(self):
        reply = self.record({**ask(), "key_id": "control-room-1"})
        self.assertNothingAppended(reply)
        self.assertIn("approval-request.schema.json", reply["reason"])

    def test_a_document_claiming_to_be_the_owner_is_refused(self):
        self.assertNothingAppended(self.record(ask(requested_by_type="owner")))

    def test_a_command_that_is_not_one_of_the_three_asks_is_refused(self):
        self.assertNothingAppended(self.record(ask(requested_command="cancel")))

    def test_something_that_is_not_an_object_is_refused(self):
        for junk in ("[]", 7, None, ["approve"]):
            with self.subTest(request=junk):
                self.assertNothingAppended(self.log.record(junk, now_epoch=ENGINE_NOW,
                                                           task_states=TASKS))

    def test_the_engine_refuses_rather_than_accepting_what_it_cannot_validate(self):
        """Fail-closed on its own validator. `sys.modules['jsonschema'] = None` makes the import raise,
        which is what a job that installs nothing looks like from inside this function."""
        saved = sys.modules.get("jsonschema", "absent")
        sys.modules["jsonschema"] = None
        try:
            reply = self.record()
        finally:
            if saved == "absent":
                del sys.modules["jsonschema"]
            else:
                sys.modules["jsonschema"] = saved
        self.assertNothingAppended(reply)
        self.assertIn("jsonschema", reply["reason"])
        self.assertIn("refuses", reply["reason"])

    # -- the chain -------------------------------------------------------------------------
    def test_each_line_names_the_digest_of_the_one_before(self):
        self.record()
        self.record(ask(request_id="req-two"))
        self.record(ask(request_id="req-three"))
        entries = self.log.entries()
        self.assertEqual(entries[0]["previous_sha256"], "")
        for before, after in zip(entries, entries[1:]):
            self.assertEqual(after["previous_sha256"], before["entry_sha256"])
        self.log.verify_chain()
        self.assertEqual(self.log.chain_head(), entries[-1]["entry_sha256"])

    def test_a_tampered_line_breaks_the_chain_and_stops_the_next_append(self):
        self.record()
        self.record(ask(request_id="req-two"))
        lines = self.log.path.read_text(encoding="utf-8").splitlines()
        doctored = json.loads(lines[0])
        doctored["request"]["reason"] = "something nobody asked"
        lines[0] = json.dumps(doctored, sort_keys=True, separators=(",", ":"))
        self.log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(ApprovalRequestError):
            self.log.verify_chain()
        with self.assertRaises(ApprovalRequestError):
            self.record(ask(request_id="req-three"))

    def test_a_malformed_line_raises_rather_than_being_skipped(self):
        self.record()
        with self.log.path.open("a", encoding="utf-8") as fh:
            fh.write("{not json\n")
        with self.assertRaises(ApprovalRequestError):
            self.log.entries()

    def test_the_log_is_one_json_object_per_line_and_newline_terminated(self):
        self.record()
        self.record(ask(request_id="req-two"))
        raw = self.log.path.read_bytes().decode("utf-8")
        self.assertTrue(raw.endswith("\n"))
        self.assertEqual(len(raw.strip().split("\n")), 2)
        for line in raw.strip().split("\n"):
            self.assertIsInstance(json.loads(line), dict)

    def test_the_only_thing_this_module_writes_is_that_log(self):
        """Nothing here can move a task, and this is the mechanical half of saying so."""
        self.record()
        self.assertEqual([p.name for p in self.log.state_dir.iterdir()], ["approval-requests.jsonl"])

    def test_the_wire_constants_are_what_the_schema_pins(self):
        schema = json.loads((ROOT / "schemas" / "approval-request.schema.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["protocol"]["const"], APPROVAL_REQUEST_PROTOCOL)
        self.assertEqual(schema["properties"]["op"]["const"], APPROVAL_REQUEST_OP)
        self.assertNotEqual(APPROVAL_REPLY_PROTOCOL, APPROVAL_REQUEST_PROTOCOL,
                            "a reply that reused the request's protocol could be replayed as one")


if __name__ == "__main__":
    unittest.main()
