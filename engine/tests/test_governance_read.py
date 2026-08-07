"""The governance mirror (`brops.governance-read.v1`) actually serves records.

The cockpit's four governance surfaces had a client and no server: the desktop sent a
well-formed read request and the engine had nothing listening, so every page rendered
its honest blocked state forever. These tests hold the server to the two properties
that make such a mirror worth trusting.

**Empty is not blocked.** The interesting assertions here are mostly about the shape of
*nothing*. A read that found no records answers `ok:true, empty:true` with a reason; a
read that could not look answers `ok:false` and carries no `records` key at all. A
surface that blurs those two eventually paints a calm, empty page over a blind engine,
which is worse than an error.

**A short answer is refused, not returned.** Deleting an evidence anchor, or one event
out of a chain, must make the read FAIL. Returning the events that survived would be a
truncated history presented as a complete one — exactly the attack `bro_evidence`'s
signed head exists to stop, re-opened at the read side.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from bro_contracts import canonical_json_sha256
from bro_control_room_api import GOVERNANCE_OP, GOVERNANCE_PROTOCOL, ControlRoomAPIV1
from bro_evidence import EvidenceError, list_chain_task_ids, read_chain, read_chains
from bro_orchestration_runtime import DurableOrchestrationRuntime
from bro_orchestration_runtime_v1 import DurableOrchestrationRuntimeV1
from bro_run_receipt import candidate_state, run_and_sign
from bro_signature import load_trusted_keys
from broctl import build_registry, generate_key, sign_payload
from _operator_pin import use_operator_pin
# Helper functions and constants only — importing a TestCase from another module would
# re-run that module's whole suite under this one's name.
from test_orchestration_runtime import (AGENT, AUTHORITIES, RUN_CMD, VERIFIER_AGENT,
                                        VERIFIER_ROLE, build_evidence, task_contract,
                                        verification_contract)

EVENT_SCHEMA = json.loads((ROOT / "schemas" / "evidence-event.schema.json").read_text(encoding="utf-8"))
RECEIPT_SCHEMA = json.loads((ROOT / "schemas" / "verifier-receipt.schema.json").read_text(encoding="utf-8"))


def read_request(surface: str, task_id: str | None = None, **overrides) -> dict:
    body = {
        "protocol": GOVERNANCE_PROTOCOL,
        "op": GOVERNANCE_OP,
        "surface": surface,
        "task_id": task_id,
        "read_only": True,
    }
    body.update(overrides)
    return body


class GovernanceRequestTests(unittest.TestCase):
    """The request half: what the engine agrees to answer at all."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.runtime = DurableOrchestrationRuntimeV1(self.temporary.name, ROOT)
        self.api = ControlRoomAPIV1(self.runtime)

    def refuse(self, request) -> dict:
        reply = self.api.governance_read(request, now_epoch=100)
        self.assertFalse(reply["ok"], reply)
        self.assertTrue(reply["error"])
        # The load-bearing one: a refusal has no `records` key, so no consumer can
        # read it as a successful read that happened to find nothing.
        self.assertNotIn("records", reply)
        return reply

    def test_a_foreign_protocol_or_op_is_refused(self) -> None:
        self.refuse(read_request("decisionLedger", protocol="brops.governance-read.v2"))
        self.refuse(read_request("decisionLedger", op="governance.write"))

    def test_only_an_explicit_read_only_true_is_served(self) -> None:
        # `1` and `"true"` are truthy but are not an assertion of read-only intent.
        for value in (False, 1, "true", None, [], {}):
            self.refuse(read_request("decisionLedger", read_only=value))

    def test_an_unknown_surface_is_refused(self) -> None:
        for surface in ("mystery", "", None, "decisionledger"):
            self.refuse(read_request(surface))

    def test_an_unknown_or_missing_field_is_refused(self) -> None:
        extra = read_request("decisionLedger")
        extra["limit"] = 10
        self.refuse(extra)
        missing = read_request("decisionLedger")
        del missing["task_id"]
        self.refuse(missing)

    def test_a_non_canonical_task_id_is_refused(self) -> None:
        for value in ("../escape", "a/b", "", 7, "a" * 200, True):
            self.refuse(read_request("decisionLedger", task_id=value))

    def test_a_non_object_request_is_refused(self) -> None:
        for value in ("{}", [], None, 7):
            self.refuse(value)

    def test_an_empty_runtime_reports_empty_rather_than_failing(self) -> None:
        for surface in ("decisionLedger", "verdicts", "approvalQueue"):
            reply = self.api.governance_read(read_request(surface), now_epoch=100)
            self.assertTrue(reply["ok"], reply)
            self.assertEqual(reply["records"], [])
            self.assertEqual(reply["record_count"], 0)
            self.assertTrue(reply["empty"])
            self.assertIn("no tasks", reply["empty_reason"])

    def test_an_evidence_read_with_no_store_refuses_rather_than_reporting_empty(self) -> None:
        # This runtime was built without an evidence store, so it is blind. Blind is
        # not the same fact as "the chain is empty", and must not read as it.
        reply = self.refuse(read_request("evidenceChain"))
        self.assertIn("not bound to an evidence store", reply["error"])
        self.assertIn("not an empty chain", reply["error"])

    def test_the_reply_never_writes_to_the_runtime(self) -> None:
        self.runtime.create_task(task_contract("task-ro"), now_epoch=100)
        before = self.api._integrity()
        for surface in ("decisionLedger", "verdicts", "approvalQueue", "evidenceChain"):
            self.api.governance_read(read_request(surface), now_epoch=101)
        self.assertEqual(before, self.api._integrity())


class GovernanceMirrorTests(unittest.TestCase):
    """The store half: real signed records, and honest refusals when they are short."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = pathlib.Path(self.temporary.name)
        self.store = base / "evidence"
        self.store.mkdir()
        self.keys = {a: generate_key(a, f"dev-{a}", False) for a in AUTHORITIES}
        self.keys["builder"]["subject_agent_id"] = AGENT
        self.keys["verifier"]["subject_agent_id"] = VERIFIER_AGENT
        use_operator_pin(self, self.keys["operator-root"]["public_key"])
        registry_root = base / "registry"
        (registry_root / "config").mkdir(parents=True)
        now = int(time.time())
        (registry_root / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(self.keys.values()), now - 60, 86400)),
            encoding="utf-8")
        self.trusted = load_trusted_keys(registry_root)
        self.state_dir = base / "state"
        self.runtime = DurableOrchestrationRuntime(self.state_dir, ROOT,
                                                   evidence_keys=self.trusted,
                                                   evidence_store=self.store)
        self.api = ControlRoomAPIV1(self.runtime)

    def read(self, surface: str, task_id: str | None = None, now: int = 200) -> dict:
        return self.api.governance_read(read_request(surface, task_id), now_epoch=now)

    # --- decision ledger ------------------------------------------------------------

    def test_the_decision_ledger_mirrors_real_hash_chained_transitions(self) -> None:
        self.runtime.create_task(task_contract("task-ledger"), now_epoch=100)
        self.runtime.claim_next(AGENT, now_epoch=101)
        reply = self.read("decisionLedger")
        self.assertTrue(reply["ok"], reply)
        self.assertFalse(reply["empty"])
        self.assertEqual([record["next_state"] for record in reply["records"]],
                         ["draft", "queued", "routing", "running"])
        for record in reply["records"]:
            # The desktop mirror rejects any record without a non-empty string id.
            self.assertIsInstance(record["id"], str)
            self.assertTrue(record["id"])
            self.assertEqual(record["task_id"], "task-ledger")
            self.assertRegex(record["record_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(reply["record_authentication"], "runtime-hash-chain-verified")
        self.assertEqual(reply["source"]["runtime_state_dir"], str(self.state_dir))

    def test_the_decision_ledger_honours_a_task_filter(self) -> None:
        self.runtime.create_task(task_contract("task-one"), now_epoch=100)
        self.runtime.create_task(task_contract("task-two"), now_epoch=100)
        reply = self.read("decisionLedger", "task-two")
        self.assertTrue(reply["ok"], reply)
        self.assertTrue(reply["known_task"])
        self.assertEqual({record["task_id"] for record in reply["records"]}, {"task-two"})

    # --- evidence chain -------------------------------------------------------------

    def test_the_evidence_chain_mirrors_the_signed_chain_in_published_schema_shape(self) -> None:
        self.runtime.create_task(task_contract("task-chain"), now_epoch=100)
        event_ids = build_evidence(self.store, self.keys, "task-chain", 3)
        reply = self.read("evidenceChain", "task-chain")
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertFalse(reply["empty"])
        # Order is the chain's own sequence — the wire shape drops `sequence`, so the
        # list order is the only thing carrying it.
        self.assertEqual([record["event_id"] for record in reply["records"]], event_ids)
        required = set(EVENT_SCHEMA["required"])
        self.assertFalse(EVENT_SCHEMA["additionalProperties"])
        for record in reply["records"]:
            self.assertEqual(set(record), required)
            self.assertEqual(record["schema"], 1)
            self.assertEqual(record["task_id"], "task-chain")
            self.assertRegex(record["payload_hash"], r"^[0-9a-f]{64}$")
        self.assertIsNone(reply["records"][0]["previous_event_hash"])
        self.assertEqual(reply["record_authentication"], "ed25519-signature-verified")

    def test_an_unfiltered_read_spans_every_chain_in_the_store(self) -> None:
        for task_id in ("task-alpha", "task-beta"):
            self.runtime.create_task(task_contract(task_id), now_epoch=100)
            build_evidence(self.store, self.keys, task_id, 2)
        reply = self.read("evidenceChain")
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertEqual(reply["record_count"], 4)
        self.assertEqual({record["task_id"] for record in reply["records"]},
                         {"task-alpha", "task-beta"})

    def test_a_deleted_anchor_refuses_instead_of_mirroring_a_shorter_chain(self) -> None:
        self.runtime.create_task(task_contract("task-trunc"), now_epoch=100)
        build_evidence(self.store, self.keys, "task-trunc", 3)
        (self.store / "task-trunc.head.json").unlink()
        reply = self.read("evidenceChain", "task-trunc")
        self.assertFalse(reply["ok"], reply)
        self.assertNotIn("records", reply)
        self.assertIn("no signed head", reply["error"])

    def test_a_missing_event_refuses_instead_of_mirroring_a_prefix(self) -> None:
        self.runtime.create_task(task_contract("task-gap"), now_epoch=100)
        event_ids = build_evidence(self.store, self.keys, "task-gap", 3)
        (self.store / f"{event_ids[-1]}.json").unlink()
        reply = self.read("evidenceChain", "task-gap")
        self.assertFalse(reply["ok"], reply)
        self.assertNotIn("records", reply)
        self.assertIn("incomplete", reply["error"])

    def test_a_task_with_no_evidence_is_empty_not_blocked(self) -> None:
        self.runtime.create_task(task_contract("task-noev"), now_epoch=100)
        reply = self.read("evidenceChain", "task-noev")
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertEqual(reply["records"], [])
        self.assertTrue(reply["empty"])
        self.assertTrue(reply["known_task"])
        self.assertIn("no evidence event", reply["empty_reason"])

    def test_an_unknown_task_is_reported_as_unknown_not_merely_empty(self) -> None:
        reply = self.read("evidenceChain", "task-nobody-has-heard-of")
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertTrue(reply["empty"])
        self.assertFalse(reply["known_task"])
        self.assertIn("no such task", reply["empty_reason"])

    def test_a_foreign_artifact_in_the_store_is_skipped_not_mistaken_for_an_event(self) -> None:
        # The evidence store is shared with execution receipts and heads, so the read
        # must select on the claimed artifact type rather than on "it parsed".
        self.runtime.create_task(task_contract("task-mixed"), now_epoch=100)
        event_ids = build_evidence(self.store, self.keys, "task-mixed", 2)
        (self.store / "rcpt-deadbeefdeadbeef.json").write_text(
            json.dumps({"payload": {"artifact_type": "execution-receipt",
                                    "task_id": "task-mixed", "receipt_id": "rcpt-1"},
                        "signature": "not-a-real-signature"}),
            encoding="utf-8")
        reply = self.read("evidenceChain", "task-mixed")
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertEqual([record["event_id"] for record in reply["records"]], event_ids)

    def test_an_event_claiming_the_chain_but_failing_verification_is_a_hard_error(self) -> None:
        # The other side of the rule above: a file that says it IS a chain event and
        # then does not verify must fail the read, never be quietly dropped.
        self.runtime.create_task(task_contract("task-forged"), now_epoch=100)
        build_evidence(self.store, self.keys, "task-forged", 2)
        forged = json.loads((self.store / "task-forged-e1.json").read_text(encoding="utf-8"))
        forged["payload"]["event_type"] = "tampered"
        (self.store / "task-forged-e9.json").write_text(json.dumps(forged), encoding="utf-8")
        reply = self.read("evidenceChain", "task-forged")
        self.assertFalse(reply["ok"], reply)
        self.assertNotIn("records", reply)

    # --- approval queue -------------------------------------------------------------

    def test_the_approval_queue_mirrors_a_real_budget_hold(self) -> None:
        self.runtime.create_task(task_contract("task-appr"), now_epoch=100,
                                 budget_limits={"tool_calls": {"soft": 1, "hard": 3}})
        self.runtime.claim_next(AGENT, now_epoch=101)
        self.runtime.record_usage("task-appr", actor_id=AGENT, now_epoch=102,
                                  delta={"tool_calls": 2},
                                  evidence_refs=["evidence/usage.json"])
        reply = self.read("approvalQueue", now=103)
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertFalse(reply["empty"])
        self.assertEqual([record["id"] for record in reply["records"]], ["task-appr"])
        record = reply["records"][0]
        self.assertEqual(record["state"], "waiting-approval")
        self.assertEqual(record["task_id"], "task-appr")
        # The queue is mirrored, never acted on: these are commands an owner *could*
        # issue, not commands anything here has issued.
        self.assertIn("approve", record["allowed_commands"])
        self.assertIn("deny", record["allowed_commands"])

    def test_a_runtime_with_tasks_but_no_hold_reports_an_empty_queue(self) -> None:
        self.runtime.create_task(task_contract("task-calm"), now_epoch=100)
        reply = self.read("approvalQueue")
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertTrue(reply["empty"])
        self.assertIn("waiting on an owner approval", reply["empty_reason"])

    # --- verdicts -------------------------------------------------------------------

    def _clean_repository(self) -> pathlib.Path:
        clean = pathlib.Path(self.temporary.name) / "clean-repo"
        (clean / "tests").mkdir(parents=True)
        shutil.copy(ROOT / "tests" / "catalog.json", clean / "tests" / "catalog.json")
        for args in (["init", "-q"], ["config", "user.email", "t@e.com"],
                     ["config", "user.name", "t"]):
            subprocess.run(["git", "-C", str(clean), *args], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(clean), "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(clean), "commit", "-qm", "init"],
                       check=True, capture_output=True)
        return clean

    def _complete_under_verification(self, task_id: str, now: int) -> None:
        clean = self._clean_repository()
        self.runtime.create_task(verification_contract(task_id), now_epoch=now)
        self.runtime.claim_next(AGENT, now_epoch=now + 1)
        refs = build_evidence(self.store, self.keys, task_id, 2)
        self.runtime.submit_for_verification(task_id, actor_id=AGENT, now_epoch=now + 2,
                                             evidence_refs=refs)
        contract = self.runtime._contract(task_id)
        document, _ = run_and_sign(RUN_CMD, key=self.keys["evidence-recorder"],
                                   task_id=task_id, root=clean, runner_id="runner", now=now)
        receipt_id = document["payload"]["receipt_id"]
        (self.store / f"{receipt_id}.json").write_text(json.dumps(document), encoding="utf-8")
        head, tree = candidate_state(clean)
        manifest_payload = {
            "artifact_type": "completion-manifest",
            "key_id": self.keys["builder"]["key_id"],
            "schema": 1, "task_id": task_id, "agent_id": AGENT,
            "task_contract_sha256": canonical_json_sha256(contract),
            "candidate_head": head, "candidate_tree": tree,
            "done_criteria": [{"criterion": contract["done_criteria"][0],
                               "status": "satisfied", "evidence_event_ids": [refs[0]]}],
            "tests": [{"command": list(document["payload"]["command"]), "status": "passed",
                       "evidence_event_id": refs[1], "execution_receipt_id": receipt_id}],
            "evidence_event_ids": refs, "open_risks": [], "rollback_ready": True,
            "nonce": uuid.uuid4().hex,
            "issued_at_epoch": now, "expires_at_epoch": now + 3600,
        }
        manifest = sign_payload(self.keys["builder"]["private_key"], manifest_payload)
        receipt = sign_payload(self.keys["verifier"]["private_key"], {
            "artifact_type": "verifier-receipt", "key_id": self.keys["verifier"]["key_id"],
            "schema": 1, "receipt_id": "vr-1", "task_id": task_id,
            "builder_agent_id": AGENT, "verifier_agent_id": VERIFIER_AGENT,
            "verifier_role": VERIFIER_ROLE, "independence_level": "L1",
            "task_contract_sha256": canonical_json_sha256(contract),
            "completion_manifest_sha256": canonical_json_sha256(manifest_payload),
            "candidate_head": head, "candidate_tree": tree, "evidence_event_ids": refs,
            "verdict": "GREEN", "issued_at_epoch": now, "expires_at_epoch": now + 3600,
        })
        self.runtime.complete_task(task_id, actor_id=AGENT, now_epoch=now + 3,
                                   evidence_refs=refs, completion_manifest=manifest,
                                   verifier_receipt=receipt)

    def test_verdicts_mirror_a_re_verified_verifier_receipt(self) -> None:
        now = int(time.time())
        self._complete_under_verification("task-verdict", now)
        reply = self.read("verdicts", now=now + 4)
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertFalse(reply["empty"])
        self.assertEqual(len(reply["records"]), 1)
        record = reply["records"][0]
        self.assertEqual(set(record), set(RECEIPT_SCHEMA["required"]))
        self.assertEqual(record["verdict"], "GREEN")
        self.assertEqual(record["receipt_id"], "vr-1")
        self.assertEqual(record["task_id"], "task-verdict")
        self.assertEqual(record["verifier_agent_id"], VERIFIER_AGENT)
        self.assertEqual(reply["record_authentication"], "ed25519-signature-verified")

        # Same records, a reader that cannot check them. The receipt is sitting right
        # there in the hash-chained transition, but without trusted keys its signature
        # cannot be re-verified — so this refuses rather than passing it along.
        blind = DurableOrchestrationRuntime(self.state_dir, ROOT)
        refusal = ControlRoomAPIV1(blind).governance_read(
            read_request("verdicts"), now_epoch=now + 4)
        self.assertFalse(refusal["ok"], refusal)
        self.assertNotIn("records", refusal)
        self.assertIn("without trusted keys", refusal["error"])

    def test_a_runtime_with_no_verified_completion_reports_no_verdict(self) -> None:
        self.runtime.create_task(task_contract("task-plain"), now_epoch=100)
        reply = self.read("verdicts")
        self.assertTrue(reply["ok"], reply.get("error"))
        self.assertTrue(reply["empty"])
        self.assertIn("no verdict", reply["empty_reason"])


class EvidenceEnumerationTests(unittest.TestCase):
    """`bro_evidence`'s new read path, on its own."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = pathlib.Path(self.temporary.name)
        self.store = base / "evidence"
        self.store.mkdir()
        self.keys = {a: generate_key(a, f"dev-{a}", False) for a in AUTHORITIES}
        use_operator_pin(self, self.keys["operator-root"]["public_key"])
        registry_root = base / "registry"
        (registry_root / "config").mkdir(parents=True)
        now = int(time.time())
        (registry_root / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(self.keys.values()), now - 60, 86400)),
            encoding="utf-8")
        self.trusted = load_trusted_keys(registry_root)

    def test_an_empty_store_reads_as_an_empty_chain(self) -> None:
        self.assertEqual(list_chain_task_ids(self.store), [])
        self.assertEqual(read_chain(self.store, "task-none", self.trusted), [])

    def test_heads_are_discoverable_and_chains_read_back_in_order(self) -> None:
        first = build_evidence(self.store, self.keys, "task-x", 3)
        build_evidence(self.store, self.keys, "task-y", 1)
        self.assertEqual(list_chain_task_ids(self.store), ["task-x", "task-y"])
        chain = read_chain(self.store, "task-x", self.trusted)
        self.assertEqual([event["event_id"] for event in chain], first)
        self.assertEqual([event["sequence"] for event in chain], [1, 2, 3])

    def test_events_without_an_anchor_refuse_rather_than_read_short(self) -> None:
        build_evidence(self.store, self.keys, "task-z", 2)
        (self.store / "task-z.head.json").unlink()
        with self.assertRaises(EvidenceError) as caught:
            read_chain(self.store, "task-z", self.trusted)
        self.assertIn("no signed head", str(caught.exception))

    def test_an_unreadable_store_raises_rather_than_reading_empty(self) -> None:
        with self.assertRaises(EvidenceError):
            list_chain_task_ids(self.store / "does-not-exist")

    def test_reading_many_chains_at_once_agrees_with_reading_them_one_by_one(self) -> None:
        # The single-pass read exists for speed; it must not become a second, laxer
        # implementation of the same guarantees.
        build_evidence(self.store, self.keys, "task-p", 3)
        build_evidence(self.store, self.keys, "task-q", 1)
        ids = ["task-p", "task-q", "task-absent"]
        batch = read_chains(self.store, ids, self.trusted)
        self.assertEqual(sorted(batch), sorted(ids))
        for task_id in ids:
            self.assertEqual([event["event_id"] for event in batch[task_id]],
                             [event["event_id"] for event
                              in read_chain(self.store, task_id, self.trusted)])
        self.assertEqual(batch["task-absent"], [])

    def test_one_broken_chain_fails_a_batch_read_rather_than_shortening_it(self) -> None:
        build_evidence(self.store, self.keys, "task-good", 2)
        build_evidence(self.store, self.keys, "task-bad", 2)
        (self.store / "task-bad.head.json").unlink()
        with self.assertRaises(EvidenceError):
            read_chains(self.store, ["task-good", "task-bad"], self.trusted)


if __name__ == "__main__":
    unittest.main()
