import json
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

from bro_contracts import canonical_json_sha256
from bro_evidence import event_hash
from bro_orchestration_runtime import DurableOrchestrationRuntime, OrchestrationRuntimeError
from bro_run_receipt import candidate_state, run_and_sign
from bro_signature import load_trusted_keys, verify_artifact
from broctl import build_registry, generate_key, sign_payload
from _operator_pin import use_operator_pin

AUTHORITIES = ["operator-root", "issuer", "evidence-recorder", "builder",
               "verifier", "release"]


def build_evidence(store: pathlib.Path, keys: dict, task_id: str, count: int) -> list[str]:
    """A real signed chain with a signed head.

    complete_task used to accept any non-empty strings, so the tests handed it
    "evidence/completed.json" and it believed them. Evidence has to resolve now,
    which means the tests have to produce some.
    """
    previous, ids, digest = None, [], ""
    for sequence in range(1, count + 1):
        event_id = f"{task_id}-e{sequence}"
        payload = {
            "artifact_type": "evidence-event",
            "key_id": keys["evidence-recorder"]["key_id"],
            "event_id": event_id, "sequence": sequence,
            "previous_event_hash": previous, "task_id": task_id,
            "event_type": "work-recorded", "agent_id": AGENT,
            "payload_hash": "a" * 64, "issued_at_epoch": 1,
        }
        (store / f"{event_id}.json").write_text(
            json.dumps(sign_payload(keys["evidence-recorder"]["private_key"], payload)),
            encoding="utf-8")
        digest = event_hash(payload)
        previous = digest
        ids.append(event_id)
    head = {
        "artifact_type": "evidence-head",
        "key_id": keys["evidence-recorder"]["key_id"],
        "task_id": task_id, "final_event_hash": digest,
        "event_count": count, "last_sequence": count, "issued_at_epoch": 1,
    }
    (store / f"{task_id}.head.json").write_text(
        json.dumps(sign_payload(keys["evidence-recorder"]["private_key"], head)),
        encoding="utf-8")
    return ids

AGENT = "agt-p01-r01"
OTHER_AGENT = "agt-p01-r02"


def task_contract(task_id: str, agent_id: str = AGENT) -> dict:
    role = "Agent Architect" if agent_id == AGENT else "Agent Builder"
    return {
        "schema": 1,
        "task_id": task_id,
        "title": f"Task {task_id}",
        "objective": "Exercise durable orchestration runtime",
        "mode": "work",
        "risk": "low",
        "pack_id": "ai-agent-builders",
        "agent_id": agent_id,
        "assignee_role": role,
        "scope": ["runtime"],
        "prohibited_scope": ["release"],
        "inputs": ["orchestration/registry.json"],
        "core_skills": ["ai-agent-engineering"],
        "additional_skills": [],
        "reference_skills": [],
        "done_criteria": ["Runtime behavior is evidence-backed"],
        "verification": {
            "required": False,
            "verifier_agent_id": None,
            "verifier_role": None,
            "commands": [],
        },
        "rollback": {"strategy": "Discard isolated runtime state", "commands": []},
        "repository": {
            "full_name": "menqstudio/Bro",
            "branch": "orchestration-runtime-v1",
            "worktree": "C:/Bro/runtime-v1",
            "base_commit": "b5d1a343a8777738d4113e3e28cf27527f04020a",
            "tree_identity": "1" * 64,
        },
    }


class DurableRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.temporary.name)
        self.store = base / "evidence"
        self.store.mkdir()
        self.keys = {a: generate_key(a, f"dev-{a}", False) for a in AUTHORITIES}
        # the builder and verifier keys are bound to the agent identities the
        # verification-required completion tests present (blocker 6b: identity is
        # cryptographic, not a string the signer writes)
        self.keys["builder"]["subject_agent_id"] = AGENT
        self.keys["verifier"]["subject_agent_id"] = "agt-p01-r05"
        # a second, correctly-typed verifier-authority key bound to a DIFFERENT agent
        # — it must not be able to sign as the designated verifier (blocker 6b)
        self.keys["verifier_other"] = generate_key(
            "verifier", "dev-verifier-other", False, subject_agent_id="agt-p01-r99")
        self.keys["builder_other"] = generate_key(
            "builder", "dev-builder-other", False, subject_agent_id="agt-p01-r99")
        use_operator_pin(self, self.keys["operator-root"]["public_key"])  # external pin
        registry_root = base / "registry"
        (registry_root / "config").mkdir(parents=True)
        now = int(time.time())
        (registry_root / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(self.keys.values()), now - 60, 86400)),
            encoding="utf-8")
        self.trusted = load_trusted_keys(registry_root)
        self.runtime = DurableOrchestrationRuntime(
            base / "state", ROOT, evidence_keys=self.trusted, evidence_store=self.store)

    def tearDown(self):
        self.temporary.cleanup()

    def test_priority_queue_and_exact_agent_claim(self):
        self.runtime.create_task(task_contract("task-background"), queue_class="background", now_epoch=100)
        self.runtime.create_task(task_contract("task-recovery"), queue_class="recovery", now_epoch=101)
        self.assertIsNone(self.runtime.claim_next(OTHER_AGENT, now_epoch=102))
        self.assertEqual(self.runtime.claim_next(AGENT, now_epoch=102)["task_id"], "task-recovery")
        self.assertEqual(self.runtime.claim_next(AGENT, now_epoch=103)["task_id"], "task-background")

    def test_duplicate_task_and_unknown_queue_fail_closed(self):
        self.runtime.create_task(task_contract("task-duplicate"), now_epoch=100)
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.create_task(task_contract("task-duplicate"), now_epoch=101)
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.create_task(task_contract("task-invalid"), queue_class="magic", now_epoch=100)

    def test_checkpoint_requires_evidence_and_becomes_stale(self):
        self.runtime.create_task(task_contract("task-checkpoint"), now_epoch=100)
        self.runtime.claim_next(AGENT, now_epoch=101)
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.checkpoint(
                "task-checkpoint", actor_id=AGENT, now_epoch=110,
                completed_criteria=["claimed"], open_risks=["none"],
                next_action="Continue", evidence_refs=[]
            )
        snapshot = self.runtime.checkpoint(
            "task-checkpoint", actor_id=AGENT, now_epoch=110,
            completed_criteria=["claimed"], open_risks=["none"],
            next_action="Continue", evidence_refs=["evidence/checkpoint.json"]
        )
        self.assertFalse(snapshot["stale"])
        self.assertTrue(self.runtime.task_snapshot("task-checkpoint", 1011)["stale"])

    def test_soft_and_hard_budget_gates(self):
        limits = {"tool_calls": {"soft": 2, "hard": 4}}
        self.runtime.create_task(task_contract("task-soft"), now_epoch=100, budget_limits=limits)
        self.runtime.claim_next(AGENT, now_epoch=101)
        soft = self.runtime.record_usage(
            "task-soft", actor_id=AGENT, now_epoch=102,
            delta={"tool_calls": 3}, evidence_refs=["evidence/soft.json"]
        )
        self.assertEqual(soft["state"], "waiting-approval")

        self.runtime.create_task(task_contract("task-hard"), now_epoch=103, budget_limits=limits)
        self.runtime.claim_next(AGENT, now_epoch=104)
        hard = self.runtime.record_usage(
            "task-hard", actor_id=AGENT, now_epoch=105,
            delta={"tool_calls": 5}, evidence_refs=["evidence/hard.json"]
        )
        self.assertEqual(hard["state"], "blocked")

    def test_owner_retry_and_terminal_immutability(self):
        limits = {"tool_calls": {"soft": None, "hard": 1}}
        self.runtime.create_task(task_contract("task-retry"), now_epoch=100, budget_limits=limits)
        self.runtime.claim_next(AGENT, now_epoch=101)
        self.runtime.record_usage(
            "task-retry", actor_id=AGENT, now_epoch=102,
            delta={"tool_calls": 2}, evidence_refs=["evidence/hard.json"]
        )
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.retry_blocked(
                "task-retry", owner_id="owner-fake", now_epoch=103,
                evidence_refs=["evidence/retry.json"]
            )
        self.assertEqual(self.runtime.retry_blocked(
            "task-retry", owner_id="owner-gev", now_epoch=103,
            evidence_refs=["evidence/retry.json"]
        )["state"], "queued")
        self.runtime.claim_next(AGENT, now_epoch=104)
        refs = build_evidence(self.store, self.keys, "task-retry", 2)
        self.assertEqual(self.runtime.complete_task(
            "task-retry", actor_id=AGENT, now_epoch=105, evidence_refs=refs
        )["state"], "completed")
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.cancel_task(
                "task-retry", actor_type="owner", actor_id="owner-gev",
                now_epoch=106, effect_in_flight=False, evidence_refs=[]
            )

    def test_inflight_cancel_requires_recovery_proof(self):
        self.runtime.create_task(task_contract("task-recovery"), now_epoch=100)
        self.runtime.claim_next(AGENT, now_epoch=101)
        state = self.runtime.cancel_task(
            "task-recovery", actor_type="owner", actor_id="owner-gev",
            now_epoch=102, effect_in_flight=True,
            evidence_refs=["evidence/ambiguous.json"]
        )
        self.assertEqual(state["state"], "recovery-required")
        recovered = self.runtime.recover_task(
            "task-recovery", owner_id="owner-gev", now_epoch=103,
            evidence_refs=["evidence/recovery.json"]
        )
        self.assertEqual(recovered["state"], "running")
        cancelled = self.runtime.cancel_task(
            "task-recovery", actor_type="bro", actor_id="bro-000",
            now_epoch=104, effect_in_flight=False, evidence_refs=[]
        )
        self.assertEqual(cancelled["state"], "cancelled")

    def test_hash_chain_tamper_is_denied(self):
        self.runtime.create_task(task_contract("task-tamper"), now_epoch=100)
        record = self.runtime.state_dir / "tasks" / "task-tamper" / "records" / "00000002.json"
        value = json.loads(record.read_text())
        value["payload"]["next_state"] = "completed"
        record.write_text(json.dumps(value))
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.integrity_report()

    def test_control_room_projection_is_derived_from_records(self):
        self.runtime.create_task(task_contract("task-projection"), now_epoch=100)
        self.runtime.claim_next(AGENT, now_epoch=101)
        projection = self.runtime.control_room_snapshot(now_epoch=102)
        self.assertEqual(projection["health"], "healthy")
        self.assertEqual(projection["state_counts"]["running"], 1)
        self.assertRegex(projection["source_sha256"], r"^[0-9a-f]{64}$")


VERIFIER_AGENT = "agt-p01-r05"
VERIFIER_ROLE = "Independent Verifier"
RUN_CMD = [sys.executable, "-c", "print('ok')"]


def verification_contract(task_id):
    c = task_contract(task_id)
    c["risk"] = "low"
    c["verification"] = {"required": True, "verifier_agent_id": VERIFIER_AGENT,
                         "verifier_role": VERIFIER_ROLE, "commands": [shlex.join(RUN_CMD)]}
    return c


class DurableVerificationCompletionTests(DurableRuntimeTests):
    """Blocker 6b: a verification-required task completes only on an independent
    verifier-signed GREEN receipt (builder != verifier), matching the Stop gate.
    complete_task authorizes the manifest + verifier receipt in-process
    (self.evidence_keys / self.store), execution receipts from the same store."""

    def setUp(self):
        super().setUp()
        self.clean = pathlib.Path(self.temporary.name) / "clean-repo"
        (self.clean / "tests").mkdir(parents=True)
        shutil.copy(ROOT / "tests" / "catalog.json", self.clean / "tests" / "catalog.json")
        for args in (["init", "-q"], ["config", "user.email", "t@e.com"], ["config", "user.name", "t"]):
            subprocess.run(["git", "-C", str(self.clean), *args], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.clean), "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.clean), "commit", "-qm", "init"], check=True, capture_output=True)

    def _to_verification(self, task_id, now):
        self.runtime.create_task(verification_contract(task_id), now_epoch=now)
        self.runtime.claim_next(AGENT, now_epoch=now + 1)
        refs = build_evidence(self.store, self.keys, task_id, 2)
        self.runtime.submit_for_verification(task_id, actor_id=AGENT, now_epoch=now + 2, evidence_refs=refs)
        return self.runtime._contract(task_id), refs

    def _execution_receipt(self, task_id, now):
        doc, _ = run_and_sign(RUN_CMD, key=self.keys["evidence-recorder"], task_id=task_id,
                              root=self.clean, runner_id="runner", now=now)
        rid = doc["payload"]["receipt_id"]
        (self.store / f"{rid}.json").write_text(json.dumps(doc), encoding="utf-8")
        return list(doc["payload"]["command"]), rid

    def _manifest(self, contract, refs, command, rid, now, *, issued=None, signing_key="builder"):
        key = self.keys[signing_key]
        payload = {
            "artifact_type": "completion-manifest", "key_id": key["key_id"],
            "schema": 1, "task_id": contract["task_id"], "agent_id": AGENT,
            "task_contract_sha256": canonical_json_sha256(contract),
            "candidate_head": candidate_state(self.clean)[0], "candidate_tree": candidate_state(self.clean)[1],
            "done_criteria": [{"criterion": contract["done_criteria"][0], "status": "satisfied",
                               "evidence_event_ids": [refs[0]]}],
            "tests": [{"command": command, "status": "passed", "evidence_event_id": refs[1],
                       "execution_receipt_id": rid}],
            "evidence_event_ids": refs, "open_risks": [], "rollback_ready": True,
            "issued_at_epoch": now if issued is None else issued,
        }
        return payload, sign_payload(key["private_key"], payload)

    def _receipt(self, contract, mpayload, refs, now, *, verifier=VERIFIER_AGENT, verdict="GREEN",
                 manifest_sha=None, signing_key="verifier", issued=None, expires=None):
        head, tree = candidate_state(self.clean)
        key = self.keys[signing_key]
        payload = {
            "artifact_type": "verifier-receipt", "key_id": key["key_id"],
            "schema": 1, "receipt_id": "vr-1", "task_id": contract["task_id"],
            "builder_agent_id": AGENT, "verifier_agent_id": verifier, "verifier_role": VERIFIER_ROLE,
            "independence_level": "L1", "task_contract_sha256": canonical_json_sha256(contract),
            "completion_manifest_sha256": manifest_sha or canonical_json_sha256(mpayload),
            "candidate_head": head, "candidate_tree": tree, "evidence_event_ids": refs,
            "verdict": verdict, "issued_at_epoch": now if issued is None else issued,
            "expires_at_epoch": (now + 3600) if expires is None else expires,
        }
        return sign_payload(key["private_key"], payload)

    def _artifacts(self, task_id, now, **rk):
        contract, refs = self._to_verification(task_id, now)
        command, rid = self._execution_receipt(task_id, now)
        mpayload, manifest = self._manifest(contract, refs, command, rid, now)
        return contract, refs, manifest, self._receipt(contract, mpayload, refs, now, **rk)

    def test_independent_verifier_receipt_completes(self):
        now = int(time.time())
        _c, refs, manifest, receipt = self._artifacts("task-verif-ok", now)
        result = self.runtime.complete_task("task-verif-ok", actor_id=AGENT, now_epoch=now + 3,
                                            evidence_refs=refs, completion_manifest=manifest, verifier_receipt=receipt)
        self.assertEqual(result["state"], "completed")

    def test_completion_without_verifier_receipt_is_denied(self):
        now = int(time.time())
        _c, refs = self._to_verification("task-verif-noreceipt", now)
        with self.assertRaises(OrchestrationRuntimeError) as c:
            self.runtime.complete_task("task-verif-noreceipt", actor_id=AGENT, now_epoch=now + 3, evidence_refs=refs)
        self.assertIn("verification RED", str(c.exception))
        self.assertEqual(self.runtime.task_snapshot("task-verif-noreceipt", now + 4)["state"], "verification")

    def test_red_verdict_is_denied(self):
        now = int(time.time())
        _c, refs, manifest, receipt = self._artifacts("task-verif-red", now, verdict="RED")
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.complete_task("task-verif-red", actor_id=AGENT, now_epoch=now + 3,
                                       evidence_refs=refs, completion_manifest=manifest, verifier_receipt=receipt)

    def test_receipt_bound_to_the_wrong_manifest_is_denied(self):
        now = int(time.time())
        _c, refs, manifest, receipt = self._artifacts("task-verif-wm", now, manifest_sha="d" * 64)
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.complete_task("task-verif-wm", actor_id=AGENT, now_epoch=now + 3,
                                       evidence_refs=refs, completion_manifest=manifest, verifier_receipt=receipt)

    def test_receipt_naming_a_different_verifier_is_denied(self):
        now = int(time.time())
        _c, refs, manifest, receipt = self._artifacts("task-verif-ov", now, verifier=OTHER_AGENT)
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.complete_task("task-verif-ov", actor_id=AGENT, now_epoch=now + 3,
                                       evidence_refs=refs, completion_manifest=manifest, verifier_receipt=receipt)

    def test_expired_receipt_cannot_be_revived_by_a_rewound_clock(self):
        # blocker A: the security clock is the runtime's, not the caller's now_epoch.
        # A receipt that expired in real time stays expired even if the caller passes
        # an older now_epoch that falls inside the receipt's window.
        now = int(time.time())
        contract, refs = self._to_verification("task-verif-exp", now)
        command, rid = self._execution_receipt("task-verif-exp", now)
        mpayload, manifest = self._manifest(contract, refs, command, rid, now, issued=now - 200)
        receipt = self._receipt(contract, mpayload, refs, now, issued=now - 200, expires=now - 100)
        with self.assertRaises(OrchestrationRuntimeError) as c:
            self.runtime.complete_task("task-verif-exp", actor_id=AGENT, now_epoch=now - 150,
                                       evidence_refs=refs, completion_manifest=manifest, verifier_receipt=receipt)
        self.assertIn("expired", str(c.exception))

    def test_verifier_key_not_bound_to_the_designated_verifier_is_denied(self):
        # blocker C: a correctly-typed verifier-authority key bound to another agent
        # cannot sign as the designated verifier — identity is cryptographic.
        now = int(time.time())
        contract, refs = self._to_verification("task-verif-id", now)
        command, rid = self._execution_receipt("task-verif-id", now)
        mpayload, manifest = self._manifest(contract, refs, command, rid, now)
        receipt = self._receipt(contract, mpayload, refs, now, signing_key="verifier_other")
        with self.assertRaises(OrchestrationRuntimeError) as c:
            self.runtime.complete_task("task-verif-id", actor_id=AGENT, now_epoch=now + 3,
                                       evidence_refs=refs, completion_manifest=manifest, verifier_receipt=receipt)
        self.assertIn("bound to", str(c.exception))

    def test_manifest_signed_by_a_builder_key_not_bound_to_the_assignee_is_denied(self):
        # blocker C (builder side): a builder-authority key bound to another agent
        # cannot sign the completion manifest for this assignee.
        now = int(time.time())
        contract, refs = self._to_verification("task-verif-bid", now)
        command, rid = self._execution_receipt("task-verif-bid", now)
        mpayload, manifest = self._manifest(contract, refs, command, rid, now, signing_key="builder_other")
        receipt = self._receipt(contract, mpayload, refs, now)
        with self.assertRaises(OrchestrationRuntimeError) as c:
            self.runtime.complete_task("task-verif-bid", actor_id=AGENT, now_epoch=now + 3,
                                       evidence_refs=refs, completion_manifest=manifest, verifier_receipt=receipt)
        self.assertIn("bound to", str(c.exception))

    def test_completion_proof_is_re_verifiable_after_the_evidence_store_is_gone(self):
        # blocker B: the WHOLE verified signed documents are persisted in the same
        # hash-chained record, so an audit can re-verify the signatures, key ids,
        # verdict, identity and timestamps from the record alone — even after the
        # evidence store is deleted.
        now = int(time.time())
        _c, refs, manifest, receipt = self._artifacts("task-verif-proof", now)
        self.runtime.complete_task("task-verif-proof", actor_id=AGENT, now_epoch=now + 3,
                                   evidence_refs=refs, completion_manifest=manifest, verifier_receipt=receipt)
        completed = [r for r in self.runtime._records("task-verif-proof")
                     if r.get("kind") == "transition" and r["payload"]["next_state"] == "completed"][-1]
        proof = completed["payload"]["completion_proof"]
        self.assertEqual(completed["payload"]["evidence_refs"], refs)  # refs from verified manifest

        # the deletable evidence store is gone; the persisted record still stands
        shutil.rmtree(self.store, ignore_errors=True)
        record = self.runtime._records("task-verif-proof")[-1]["payload"]["completion_proof"]

        # RE-VERIFY the signatures and payloads from the persisted documents alone
        mpayload = verify_artifact(record["completion_manifest_document"], "completion-manifest", self.trusted)
        self.assertEqual(mpayload["agent_id"], AGENT)
        self.assertEqual(canonical_json_sha256(mpayload), record["completion_manifest_sha256"])
        rpayload = verify_artifact(record["verifier_receipt_document"], "verifier-receipt", self.trusted)
        self.assertEqual(rpayload["verdict"], "GREEN")
        self.assertEqual(rpayload["verifier_agent_id"], VERIFIER_AGENT)
        self.assertEqual(rpayload["receipt_id"], "vr-1")
        self.assertEqual(canonical_json_sha256(rpayload), record["verifier_receipt_sha256"])
        # and the signing key's bound identity still holds
        self.assertEqual(self.trusted[rpayload["key_id"]].subject_agent_id, VERIFIER_AGENT)
        self.assertEqual(self.trusted[mpayload["key_id"]].subject_agent_id, AGENT)

    def test_a_non_required_task_still_completes_without_a_receipt(self):
        now = int(time.time())
        self.runtime.create_task(task_contract("task-noverif"), now_epoch=now)
        self.runtime.claim_next(AGENT, now_epoch=now + 1)
        refs = build_evidence(self.store, self.keys, "task-noverif", 2)
        result = self.runtime.complete_task("task-noverif", actor_id=AGENT, now_epoch=now + 2, evidence_refs=refs)
        self.assertEqual(result["state"], "completed")


if __name__ == "__main__":
    unittest.main()
