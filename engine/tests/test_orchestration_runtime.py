import json
import os
import pathlib
import shlex
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
from bro_evidence import event_hash
from bro_orchestration_runtime import (ACTOR_ASSIGNEE_LEASE, ACTOR_PROVEN_BY_SESSION,
                                       ACTOR_RUNTIME_ORIGINATED,
                                       ACTOR_UNPROVEN, DurableOrchestrationRuntime,
                                       OrchestrationRuntimeError)
from bro_policy import (CANONICAL_CONDUCTOR_ID, CONDUCTOR_ROLE,
                        CONDUCTOR_SESSION_ARTIFACT)
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
    # (audit R-06) The L-4 anti-rollback floor must be PROVISIONED: an absent one refuses rather
    # than reading as "no floor required", because deleting it used to turn the check off
    # silently. Bootstrapping is a deliberate act, and a fixture that builds an evidence store is
    # exactly where a deployment would perform it.
    floor_dir = store / "head-floor"
    floor_dir.mkdir(parents=True, exist_ok=True)
    index = floor_dir / "_index.json"
    if not index.exists():
        index.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    # This process owns the floor it is about to be policed by, which R-06 refuses — a mark the
    # policed account can rewind is not a mark. A test process IS a deployment with no principal
    # separation, so the honest thing is to say so rather than to weaken the rule. `setdefault`
    # so a suite that wants to exercise the refusal can still unset it.
    #
    # (The refusal is POSIX-only, so it fired on Linux CI while every local Windows run passed —
    # the same "the test is skipped on the platform you develop on" blind spot the remediation
    # audit found 22 instances of. Recorded here so the next reader knows why it is set.)
    os.environ.setdefault("BRO_OPERATOR_ROOT_PIN_SELF_OWNED", "acknowledged")

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
        "event_count": count, "last_sequence": count, "head_sequence": 1,
        "issued_at_epoch": 1,
    }
    (store / f"{task_id}.head.json").write_text(
        json.dumps(sign_payload(keys["evidence-recorder"]["private_key"], head)),
        encoding="utf-8")
    return ids


def head_binding(store: pathlib.Path, task_id: str) -> dict:
    """The O-5 evidence-head binding a completion manifest must now carry.

    The manifest names exactly one signed head — its monotonic `head_sequence` and the
    digest of the signed document itself — so the anti-rollback high-water mark lives in
    something the builder signed rather than only in a directory anyone can delete.
    """
    document = json.loads((store / f"{task_id}.head.json").read_text(encoding="utf-8"))
    return {
        "evidence_head_sha256": canonical_json_sha256(document),
        "head_sequence": document["payload"]["head_sequence"],
    }


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

    def conductor_attestation(self, **overrides) -> dict:
        """An operator-root-signed `conductor-session` — the one actor credential
        this runtime can actually verify."""
        now = int(time.time())
        payload = {
            "schema": 1,
            "artifact_type": CONDUCTOR_SESSION_ARTIFACT,
            "key_id": self.keys["operator-root"]["key_id"],
            "session_id": "s-conductor-runtime",
            "agent_id": CANONICAL_CONDUCTOR_ID,
            "role": CONDUCTOR_ROLE,
            "issued_at_epoch": now - 10,
            "expires_at_epoch": now + 3600,
        }
        payload.update(overrides)
        return sign_payload(self.keys["operator-root"]["private_key"], payload)

    def blocked_task(self, task_id: str = "task-retry") -> None:
        limits = {"tool_calls": {"soft": None, "hard": 1}}
        self.runtime.create_task(task_contract(task_id), now_epoch=100, budget_limits=limits)
        self.runtime.claim_next(AGENT, now_epoch=101)
        self.runtime.record_usage(
            task_id, actor_id=AGENT, now_epoch=102,
            delta={"tool_calls": 2}, evidence_refs=["evidence/hard.json"]
        )

    def test_owner_retry_is_refused_and_names_the_missing_owner_artifact(self):
        """O-4 in the runtime: `owner-gev` was a string the caller typed.

        Approving a retry is the OWNER's decision and nothing in this engine can
        verify that a caller is the owner, so the call refuses and says exactly what
        the owner must mint. It must not re-queue on a self-assertion, and the task
        must stay where the budget gate left it.
        """
        self.blocked_task()
        with self.assertRaises(OrchestrationRuntimeError) as caught:
            self.runtime.retry_blocked(
                "task-retry", owner_id="owner-gev", now_epoch=103,
                evidence_refs=["evidence/retry.json"]
            )
        message = str(caught.exception)
        self.assertIn("cannot be validated", message)
        for named in ("ARTIFACT_AUTHORITY", "config/trusted-keys.json", "actor_attestation"):
            self.assertIn(named, message)
        self.assertEqual(self.runtime._state("task-retry"), "blocked")

    def test_a_non_canonical_owner_is_still_refused_for_being_non_canonical(self):
        self.blocked_task("task-retry-2")
        with self.assertRaises(OrchestrationRuntimeError) as caught:
            self.runtime.retry_blocked(
                "task-retry-2", owner_id="owner-fake", now_epoch=103,
                evidence_refs=["evidence/retry.json"]
            )
        self.assertIn("not canonical", str(caught.exception))

    def test_an_owner_claim_is_not_rescued_by_another_signed_artifact(self):
        """The owner path does not become passable by presenting SOMETHING signed.

        A real operator-root-signed conductor-session is the strongest credential
        this runtime holds, and it still does not make its bearer the owner.
        """
        self.blocked_task("task-retry-3")
        with self.assertRaises(OrchestrationRuntimeError) as caught:
            self.runtime.retry_blocked(
                "task-retry-3", owner_id="owner-gev", now_epoch=103,
                evidence_refs=["evidence/retry.json"],
                actor_attestation=self.conductor_attestation(role="owner",
                                                             agent_id="owner-gev"),
            )
        self.assertIn("cannot be validated", str(caught.exception))
        self.assertEqual(self.runtime._state("task-retry-3"), "blocked")

    def test_terminal_task_is_immutable(self):
        self.runtime.create_task(task_contract("task-terminal"), now_epoch=100)
        self.runtime.claim_next(AGENT, now_epoch=101)
        refs = build_evidence(self.store, self.keys, "task-terminal", 2)
        self.assertEqual(self.runtime.complete_task(
            "task-terminal", actor_id=AGENT, now_epoch=105, evidence_refs=refs
        )["state"], "completed")
        with self.assertRaises(OrchestrationRuntimeError) as caught:
            self.runtime.cancel_task(
                "task-terminal", actor_type=CONDUCTOR_ROLE, actor_id=CANONICAL_CONDUCTOR_ID,
                now_epoch=106, effect_in_flight=False, evidence_refs=[],
                actor_attestation=self.conductor_attestation(),
            )
        self.assertIn("terminal task is immutable", str(caught.exception))

    def test_inflight_cancel_requires_recovery_proof(self):
        """A proven conductor may cancel; recovery still needs the owner, who cannot
        yet be proven, so the quarantine holds rather than being cleared on a claim."""
        self.runtime.create_task(task_contract("task-recovery"), now_epoch=100)
        self.runtime.claim_next(AGENT, now_epoch=101)
        state = self.runtime.cancel_task(
            "task-recovery", actor_type=CONDUCTOR_ROLE, actor_id=CANONICAL_CONDUCTOR_ID,
            now_epoch=102, effect_in_flight=True,
            evidence_refs=["evidence/ambiguous.json"],
            actor_attestation=self.conductor_attestation(),
        )
        self.assertEqual(state["state"], "recovery-required")
        with self.assertRaises(OrchestrationRuntimeError) as caught:
            self.runtime.recover_task(
                "task-recovery", owner_id="owner-gev", now_epoch=103,
                evidence_refs=["evidence/recovery.json"]
            )
        self.assertIn("cannot be validated", str(caught.exception))
        self.assertEqual(self.runtime._state("task-recovery"), "recovery-required")

    def test_a_cancelling_conductor_is_proven_and_the_proof_is_persisted(self):
        self.runtime.create_task(task_contract("task-cancel"), now_epoch=100)
        self.runtime.claim_next(AGENT, now_epoch=101)
        cancelled = self.runtime.cancel_task(
            "task-cancel", actor_type=CONDUCTOR_ROLE, actor_id=CANONICAL_CONDUCTOR_ID,
            now_epoch=104, effect_in_flight=False, evidence_refs=[],
            actor_attestation=self.conductor_attestation(),
        )
        self.assertEqual(cancelled["state"], "cancelled")
        payload = self.runtime._records("task-cancel")[-1]["payload"]
        # The record says what discharged the identity, not merely what was claimed.
        self.assertEqual(payload["actor_identity_basis"], ACTOR_PROVEN_BY_SESSION)
        self.assertEqual(payload["actor_proof"]["key_id"], self.keys["operator-root"]["key_id"])
        self.assertEqual(payload["actor_proof"]["session_id"], "s-conductor-runtime")
        self.assertRegex(payload["actor_proof"]["attestation_sha256"], r"^[0-9a-f]{64}$")

    def test_the_runtimes_own_decisions_are_recorded_as_runtime_originated(self):
        """The bookkeeping transitions this runtime attributes to itself are not
        caller claims, and the ones that ARE caller claims must not borrow that word."""
        self.runtime.create_task(task_contract("task-basis"), now_epoch=100)
        bases = [record["payload"]["actor_identity_basis"]
                 for record in self.runtime._records("task-basis")
                 if record["kind"] == "transition"]
        self.assertEqual(bases, [ACTOR_RUNTIME_ORIGINATED, ACTOR_RUNTIME_ORIGINATED])
        self.runtime.claim_next(AGENT, now_epoch=101)
        running = self.runtime._records("task-basis")[-1]["payload"]
        self.assertEqual(running["actor_type"], "agent")
        self.assertEqual(running["actor_identity_basis"], ACTOR_UNPROVEN)

    def test_an_agent_transition_records_the_credential_it_actually_had(self):
        """The assignee paths are not literal comparisons and are not refused — but
        they are not signatures either, so they must not be written down as proven.
        Presenting the runtime-minted lease is worth recording; delegating without it
        proves nothing about the caller and is recorded as the claim it is."""
        self.runtime.create_task(task_contract("task-basis-lease"), now_epoch=100)
        lease = self.runtime.claim_next(AGENT, now_epoch=101)["lease_id"]
        refs = build_evidence(self.store, self.keys, "task-basis-lease", 2)
        self.runtime.complete_task("task-basis-lease", actor_id=AGENT, lease_id=lease,
                                   now_epoch=102, evidence_refs=refs)
        self.assertEqual(
            self.runtime._records("task-basis-lease")[-1]["payload"]["actor_identity_basis"],
            ACTOR_ASSIGNEE_LEASE)

        self.runtime.create_task(task_contract("task-basis-nolease"), now_epoch=100)
        self.runtime.claim_next(AGENT, now_epoch=101)
        refs = build_evidence(self.store, self.keys, "task-basis-nolease", 2)
        self.runtime.complete_task("task-basis-nolease", actor_id=AGENT,
                                   now_epoch=102, evidence_refs=refs)
        self.assertEqual(
            self.runtime._records("task-basis-nolease")[-1]["payload"]["actor_identity_basis"],
            ACTOR_UNPROVEN)

    def test_an_unproven_conductor_cancel_is_refused_every_way_it_can_be_faked(self):
        """Every failure mode of the attestation, against a live task."""
        self.runtime.create_task(task_contract("task-fake"), now_epoch=100)

        def refuse(contains, **kwargs):
            with self.assertRaises(OrchestrationRuntimeError) as caught:
                self.runtime.cancel_task(
                    "task-fake", actor_type=CONDUCTOR_ROLE, actor_id=CANONICAL_CONDUCTOR_ID,
                    now_epoch=104, effect_in_flight=False, evidence_refs=[], **kwargs)
            self.assertIn(contains, str(caught.exception))
            self.assertEqual(self.runtime._state("task-fake"), "queued")

        refuse("self-asserted")                                        # no attestation
        forged = self.conductor_attestation()
        forged["payload"]["session_id"] = "s-somebody-else"            # tampered
        refuse("RED", actor_attestation=forged)
        wrong_authority = dict(self.conductor_attestation()["payload"])
        wrong_authority["key_id"] = self.keys["builder"]["key_id"]
        refuse("RED", actor_attestation=sign_payload(
            self.keys["builder"]["private_key"], wrong_authority))
        refuse("RED", actor_attestation=self.conductor_attestation(    # wrong artifact type
            artifact_type="workspace-binding"))
        refuse("does not speak for this actor",                        # another identity
               actor_attestation=self.conductor_attestation(agent_id="agt-p01-r01"))
        refuse("expired", actor_attestation=self.conductor_attestation(
            expires_at_epoch=int(time.time()) - 1))
        refuse("expired", actor_attestation=self.conductor_attestation(
            expires_at_epoch="9999999999"))
        refuse("session_id", actor_attestation=self.conductor_attestation(session_id=""))
        for value in ({}, [], 7, {"payload": {}}, "not-a-document"):
            refuse("RED", actor_attestation=value)

    def test_a_backdated_caller_clock_cannot_revive_an_expired_attestation(self):
        """The credential is judged on the WALL clock, not the caller's now_epoch."""
        self.runtime.create_task(task_contract("task-clock"), now_epoch=100)
        stale = self.conductor_attestation(expires_at_epoch=int(time.time()) - 1)
        with self.assertRaises(OrchestrationRuntimeError) as caught:
            self.runtime.cancel_task(
                "task-clock", actor_type=CONDUCTOR_ROLE, actor_id=CANONICAL_CONDUCTOR_ID,
                now_epoch=104, effect_in_flight=False, evidence_refs=[],
                actor_attestation=stale)
        self.assertIn("expired", str(caught.exception))

    def test_a_runtime_without_trusted_keys_refuses_rather_than_trusting_the_claim(self):
        blind = DurableOrchestrationRuntime(
            pathlib.Path(self.temporary.name) / "blind-state", ROOT)
        blind.create_task(task_contract("task-blind"), now_epoch=100)
        with self.assertRaises(OrchestrationRuntimeError) as caught:
            blind.cancel_task(
                "task-blind", actor_type=CONDUCTOR_ROLE, actor_id=CANONICAL_CONDUCTOR_ID,
                now_epoch=104, effect_in_flight=False, evidence_refs=[],
                actor_attestation=self.conductor_attestation())
        self.assertIn("no trusted keys", str(caught.exception))

    def test_a_caller_may_not_borrow_the_runtime_or_agent_identities(self):
        self.runtime.create_task(task_contract("task-borrow"), now_epoch=100)
        for actor_type, actor_id, expected in (
                ("system", "system-budget", "may not act as the runtime"),
                ("agent", AGENT, "bare identity claim")):
            with self.subTest(actor_type=actor_type):
                with self.assertRaises(OrchestrationRuntimeError) as caught:
                    self.runtime.cancel_task(
                        "task-borrow", actor_type=actor_type, actor_id=actor_id,
                        now_epoch=104, effect_in_flight=False, evidence_refs=[],
                        actor_attestation=self.conductor_attestation())
                self.assertIn(expected, str(caught.exception))
                self.assertEqual(self.runtime._state("task-borrow"), "queued")

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
        issued_at = now if issued is None else issued
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
            **head_binding(self.store, contract["task_id"]),
            "nonce": uuid.uuid4().hex,
            "issued_at_epoch": issued_at,
            "expires_at_epoch": issued_at + 3600,
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

        # O-5: the evidence high-water mark travels into this record, which lives in a
        # different store from the evidence it polices. Wiping the evidence store's
        # anti-rollback floor — just done above — does not erase it, so a later completion
        # naming a LOWER head_sequence than one already recorded here is a rollback an
        # auditor can see from signed bytes rather than from custodial filesystem state.
        self.assertEqual(record["evidence_head_sequence"], mpayload["head_sequence"])
        self.assertEqual(record["evidence_head_sha256"], mpayload["evidence_head_sha256"])
        self.assertGreaterEqual(record["evidence_head_sequence"], 1)

    def test_a_non_required_task_still_completes_without_a_receipt(self):
        now = int(time.time())
        self.runtime.create_task(task_contract("task-noverif"), now_epoch=now)
        self.runtime.claim_next(AGENT, now_epoch=now + 1)
        refs = build_evidence(self.store, self.keys, "task-noverif", 2)
        result = self.runtime.complete_task("task-noverif", actor_id=AGENT, now_epoch=now + 2, evidence_refs=refs)
        self.assertEqual(result["state"], "completed")


if __name__ == "__main__":
    unittest.main()
