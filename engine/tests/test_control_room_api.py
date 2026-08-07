from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from bro_control_room_api import (ACTOR_ATTESTATION_MISSING, ACTOR_PROVEN_BY_SESSION,
                                  ACTOR_PROVEN_PER_COMMAND, CONTROL_ROOM_ACTOR_ARTIFACT,
                                  CONTROL_ROOM_COMMAND_ARTIFACT,
                                  ControlRoomAPIError, ControlRoomAPIV1)
from bro_orchestration_runtime_v1 import DurableOrchestrationRuntimeV1
from bro_policy import CANONICAL_CONDUCTOR_ID, CONDUCTOR_ROLE
from bro_signature import load_trusted_keys
from broctl import build_registry, generate_key, sign_payload
from _operator_pin import use_operator_pin

AGENT = "agt-p01-r01"
BASE = "6bb29bd61b171757a6aaef016fbd46e8b970ada9"


def task_contract(task_id: str) -> dict:
    return {
        "schema": 1,
        "task_id": task_id,
        "title": f"Task {task_id}",
        "objective": "Exercise governed Control Room read models",
        "mode": "work",
        "risk": "low",
        "pack_id": "ai-agent-builders",
        "agent_id": AGENT,
        "assignee_role": "Agent Architect",
        "scope": ["runtime"],
        "prohibited_scope": ["release"],
        "inputs": ["orchestration/registry.json"],
        "core_skills": ["ai-agent-engineering"],
        "additional_skills": [],
        "reference_skills": [],
        "done_criteria": ["Read models are integrity-bound"],
        "verification": {"required": False, "verifier_agent_id": None, "verifier_role": None, "commands": []},
        "rollback": {"strategy": "Discard isolated runtime state", "commands": []},
        "repository": {
            "full_name": "menqstudio/Bro",
            "branch": "control-room-api-v1",
            "worktree": "C:/Bro/control-room-api-v1",
            "base_commit": BASE,
            "tree_identity": "1" * 64,
        },
    }


def cancel_command(task_id: str = "task-api-1") -> dict:
    return {
        "schema": 1,
        "command_id": "cmd-1",
        "command": "cancel",
        "task_id": task_id,
        "requested_by_type": "owner",
        "requested_by": "owner-gev",
        "requested_at_epoch": 101,
        "expires_at_epoch": 200,
        "expected_task_state": "queued",
        "scope": [f"task:{task_id}"],
        "reason": "Owner requested cancellation review",
        "evidence_refs": [],
    }


class ControlRoomAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = DurableOrchestrationRuntimeV1(self.temp.name, ROOT)
        self.runtime.create_task(task_contract("task-api-1"), now_epoch=100)
        self.api = ControlRoomAPIV1(self.runtime)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_mission_and_task_views_are_integrity_bound(self) -> None:
        mission = self.api.mission_overview(now_epoch=101)
        detail = self.api.task_detail("task-api-1", now_epoch=101)
        self.assertEqual(mission["task_count"], 1)
        self.assertEqual(detail["snapshot"]["state"], "queued")
        self.assertEqual(mission["source_integrity_sha256"], detail["source_integrity_sha256"])
        self.assertTrue(detail["drill_down"]["available"])
        self.assertEqual(detail["contract"]["repository"]["base_commit"], BASE)

    def test_empty_runtime_is_unknown_not_green(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            api = ControlRoomAPIV1(DurableOrchestrationRuntimeV1(directory, ROOT))
            mission = api.mission_overview(now_epoch=1)
        self.assertEqual(mission["health"], "unknown")
        self.assertEqual(mission["task_count"], 0)
        self.assertFalse(mission["drill_down"]["available"])

    def test_queue_and_agent_views_are_canonical(self) -> None:
        queue = self.api.queue_state(now_epoch=101)
        agent = self.api.agent_workload(now_epoch=101, agent_id=AGENT)
        self.assertEqual(queue["tasks"][0]["queue_class"], "standard")
        self.assertEqual(agent["agents"][0]["pack_id"], "ai-agent-builders")
        self.assertEqual(agent["agents"][0]["role"], "Agent Architect")
        self.assertEqual(agent["agents"][0]["task_count"], 1)

    def test_checkpoint_view_exposes_evidence_and_freshness(self) -> None:
        lease = self.runtime.claim_next(AGENT, now_epoch=101)["lease_id"]
        self.runtime.checkpoint("task-api-1", actor_id=AGENT, lease_id=lease, now_epoch=102, completed_criteria=["Read model built"], open_risks=["None"], next_action="Verify API", evidence_refs=["evidence/checkpoint.json"])
        view = self.api.checkpoint_status("task-api-1", now_epoch=103)
        self.assertEqual(view["last_checkpoint"]["evidence_refs"], ["evidence/checkpoint.json"])
        self.assertFalse(view["freshness"]["stale"])
        self.assertTrue(self.api.checkpoint_status("task-api-1", now_epoch=1003)["freshness"]["stale"])

    def test_budget_and_approval_views_fail_closed_without_inventing_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = DurableOrchestrationRuntimeV1(directory, ROOT)
            runtime.create_task(task_contract("task-budget"), now_epoch=100, budget_limits={"tool_calls": {"soft": 1, "hard": 3}})
            lease = runtime.claim_next(AGENT, now_epoch=101)["lease_id"]
            runtime.record_usage("task-budget", actor_id=AGENT, lease_id=lease, now_epoch=102, delta={"tool_calls": 2}, evidence_refs=["evidence/usage.json"])
            api = ControlRoomAPIV1(runtime)
            budget = api.budget_status("task-budget", now_epoch=103)
            approval = api.approval_inbox(now_epoch=103)
        tool_calls = next(item for item in budget["dimensions"] if item["dimension"] == "tool_calls")
        self.assertEqual(tool_calls["status"], "soft-exceeded")
        self.assertEqual(approval["approvals"][0]["state"], "waiting-approval")
        self.assertIsNone(approval["approvals"][0]["expires_at_epoch"])
        self.assertEqual(approval["approvals"][0]["expiry_status"], "not-modeled-by-runtime-v1")

    def test_recovery_view_exposes_proof_without_inventing_effect(self) -> None:
        # An in-flight cancellation is a privileged lifecycle decision, so the runtime
        # now requires the actor to be PROVEN (O-4): this fixture drives it with a real
        # operator-root-signed conductor-session rather than the owner string it used
        # to type. The owner cannot be proven at all yet — see
        # bro_orchestration_runtime.OWNER_ACTOR_UNPROVABLE.
        now = int(time.time())
        keys = {authority: generate_key(authority, f"dev-rec-{authority}", False)
                for authority in ("operator-root", "builder")}
        use_operator_pin(self, keys["operator-root"]["public_key"])
        base = pathlib.Path(self.temp.name) / "recovery"
        (base / "registry" / "config").mkdir(parents=True)
        (base / "registry" / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(keys.values()), now - 3600, 86400)),
            encoding="utf-8")
        self.runtime = DurableOrchestrationRuntimeV1(
            base / "state", ROOT, evidence_keys=load_trusted_keys(base / "registry"))
        self.runtime.create_task(task_contract("task-api-1"), now_epoch=100)
        self.api = ControlRoomAPIV1(self.runtime)
        attestation = sign_payload(keys["operator-root"]["private_key"], {
            "schema": 1, "artifact_type": CONTROL_ROOM_ACTOR_ARTIFACT,
            "key_id": keys["operator-root"]["key_id"], "session_id": "s-recovery-view",
            "agent_id": CANONICAL_CONDUCTOR_ID, "role": CONDUCTOR_ROLE,
            "issued_at_epoch": now - 10, "expires_at_epoch": now + 3600,
        })
        self.runtime.claim_next(AGENT, now_epoch=101)
        self.runtime.cancel_task("task-api-1", actor_type=CONDUCTOR_ROLE, actor_id=CANONICAL_CONDUCTOR_ID, now_epoch=102, effect_in_flight=True, evidence_refs=["evidence/ambiguous-effect.json"], actor_attestation=attestation)
        view = self.api.recovery_quarantine(now_epoch=103)
        self.assertEqual(view["items"][0]["state"], "recovery-required")
        self.assertEqual(view["items"][0]["proof_refs"], ["evidence/ambiguous-effect.json"])
        self.assertIsNone(view["items"][0]["observed_effect"])

    def test_audit_timeline_is_deterministic(self) -> None:
        first = self.api.audit_timeline("task-api-1", now_epoch=101)
        second = self.api.audit_timeline("task-api-1", now_epoch=101)
        self.assertEqual(first["timeline_sha256"], second["timeline_sha256"])
        self.assertEqual(first["record_count"], len(first["records"]))

    def test_command_intent_refuses_a_self_asserted_actor(self) -> None:
        """O-4: `requested_by` is two strings out of the caller's own JSON.

        The API used to compare them against the literals and then echo the
        claimed identity back inside `"valid": true`, laundering a self-assertion
        into something downstream reads as verified. An unproven actor is now a
        refusal, and the refusal says what proof it wanted.
        """
        before = self.runtime.task_snapshot("task-api-1", 101)
        with self.assertRaises(ControlRoomAPIError) as caught:
            self.api.validate_command_intent(cancel_command(), now_epoch=101)
        self.assertIn("self-asserted", str(caught.exception))
        self.assertIn("actor_attestation", str(caught.exception))
        self.assertEqual(before, self.runtime.task_snapshot("task-api-1", 101))

    def test_wrong_actor_and_forbidden_scope_fail_closed(self) -> None:
        wrong_actor = cancel_command(); wrong_actor["requested_by"] = "not-owner"
        with self.assertRaises(ControlRoomAPIError) as caught:
            self.api.validate_command_intent(wrong_actor, now_epoch=101)
        self.assertIn("not canonical", str(caught.exception))
        forbidden = cancel_command(); forbidden["scope"] = ["repository:menqstudio/Bro"]
        with self.assertRaises(ControlRoomAPIError) as caught:
            self.api.validate_command_intent(forbidden, now_epoch=101)
        self.assertIn("forbidden mutation boundary", str(caught.exception))

    def test_noncanonical_command_shape_fails_closed(self) -> None:
        command = cancel_command(); command["requested_by_id"] = command.pop("requested_by")
        with self.assertRaises(ControlRoomAPIError): self.api.validate_command_intent(command, now_epoch=101)

    def test_unknown_task_and_agent_fail_closed(self) -> None:
        with self.assertRaises(ControlRoomAPIError): self.api.task_detail("task-missing", now_epoch=101)
        with self.assertRaises(ControlRoomAPIError): self.api.agent_workload(now_epoch=101, agent_id="agt-p99-r99")

    def test_tampered_runtime_is_denied_by_all_reads(self) -> None:
        record = pathlib.Path(self.temp.name) / "tasks" / "task-api-1" / "records" / "00000002.json"
        value = json.loads(record.read_text(encoding="utf-8")); value["payload"]["next_state"] = "completed"
        record.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(ControlRoomAPIError): self.api.mission_overview(now_epoch=101)
        with self.assertRaises(ControlRoomAPIError): self.api.task_detail("task-api-1", now_epoch=101)


class ControlRoomActorProofTests(unittest.TestCase):
    """O-4: the actor claim is discharged by a signature or the command is refused.

    The conductor already has the credential this needs — the operator-root-signed
    `conductor-session` artifact of M-4/O-3 — so a command claiming `bro`/`bro-000`
    must present one, verified against the operator-signed trusted-key registry with
    real Ed25519, bound to that role and agent id, and unexpired.

    The owner has no such credential and this change does not invent one: there is no
    owner-authority artifact type in `bro_signature.ARTIFACT_AUTHORITY`, no signature
    field in `schemas/control-room-command.schema.json`, and no trusted key that could
    sign either. An owner-issued command is therefore refused BY NAME, which is the
    honest state — not validated on its own say-so.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = pathlib.Path(self.temp.name)
        self.now = int(time.time())
        self.keys = {authority: generate_key(authority, f"dev-{authority}", False)
                     for authority in ("operator-root", "builder")}
        use_operator_pin(self, self.keys["operator-root"]["public_key"])
        (base / "registry" / "config").mkdir(parents=True)
        (base / "registry" / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(self.keys.values()), self.now - 3600, 86400)),
            encoding="utf-8")
        self.trusted = load_trusted_keys(base / "registry")
        self.runtime = DurableOrchestrationRuntimeV1(base / "state", ROOT,
                                                     evidence_keys=self.trusted)
        self.runtime.create_task(task_contract("task-actor-1"), now_epoch=self.now)
        self.api = ControlRoomAPIV1(self.runtime)

    def command(self, **overrides) -> dict:
        body = cancel_command("task-actor-1")
        body.update({
            "requested_by_type": CONDUCTOR_ROLE,
            "requested_by": CANONICAL_CONDUCTOR_ID,
            "requested_at_epoch": self.now,
            "expires_at_epoch": self.now + 3600,
            "scope": ["task:task-actor-1"],
        })
        body.update(overrides)
        return body

    def attestation(self, authority: str = "operator-root", **overrides) -> dict:
        payload = {
            "schema": 1,
            "artifact_type": CONTROL_ROOM_ACTOR_ARTIFACT,
            "key_id": self.keys[authority]["key_id"],
            "session_id": "s-conductor-control-room",
            "agent_id": CANONICAL_CONDUCTOR_ID,
            "role": CONDUCTOR_ROLE,
            "issued_at_epoch": self.now - 10,
            "expires_at_epoch": self.now + 3600,
        }
        payload.update(overrides)
        return sign_payload(self.keys[authority]["private_key"], payload)

    def owner_attestation(self, authority: str = "operator-root", command: dict | None = None,
                          **overrides) -> dict:
        """A `control-room-command` artifact bound to one command.

        Deliberately built from the command it authorises rather than from constants: a fixture
        that hard-codes the ids would keep passing if the binding check were deleted, which is the
        one thing this artifact exists to do.
        """
        cmd = command or self.command(requested_by_type="owner", requested_by="owner-gev")
        payload = {
            "schema": 1,
            "artifact_type": CONTROL_ROOM_COMMAND_ARTIFACT,
            "key_id": self.keys[authority]["key_id"],
            "session_id": "s-owner-ceremony",
            "agent_id": "owner-gev",
            "role": "owner",
            "command_id": cmd["command_id"],
            "task_id": cmd["task_id"],
            "command": cmd["command"],
            "issued_at_epoch": self.now - 10,
            "expires_at_epoch": self.now + 3600,
        }
        payload.update(overrides)
        return sign_payload(self.keys[authority]["private_key"], payload)

    def refuse(self, contains: str, **kwargs) -> str:
        with self.assertRaises(ControlRoomAPIError) as caught:
            self.api.validate_command_intent(self.command(), now_epoch=self.now + 1, **kwargs)
        self.assertIn(contains, str(caught.exception))
        return str(caught.exception)

    # --- the proven path ------------------------------------------------------------

    def test_an_operator_signed_session_proves_the_conductor_actor(self) -> None:
        before = self.api._integrity()
        result = self.api.validate_command_intent(
            self.command(), now_epoch=self.now + 1, actor_attestation=self.attestation())
        self.assertTrue(result["valid"])
        self.assertFalse(result["executed"])
        self.assertFalse(result["mutation_authorized"])
        # The reply says what verified the identity, not merely what was claimed.
        self.assertEqual(result["actor_identity"], ACTOR_PROVEN_BY_SESSION)
        self.assertEqual(result["actor_key_id"], self.keys["operator-root"]["key_id"])
        self.assertEqual(result["actor_session_id"], "s-conductor-control-room")
        self.assertRegex(result["actor_attestation_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(before, self.api._integrity())

    # --- everything that must refuse ------------------------------------------------

    def test_a_conductor_command_without_an_attestation_is_refused(self) -> None:
        message = self.refuse("self-asserted")
        self.assertIn("conductor-session", message)

    def test_an_owner_command_with_no_attestation_says_what_to_mint(self) -> None:
        """The refusal must name the missing ARTIFACT, not a missing feature.

        It used to list three code changes that would close O-4. All three landed, so a reader
        following that message would have gone off to build what already existed. What is missing
        now is the Owner's signature, and only one of those two is actionable by whoever hits it.
        """
        owner = self.command(requested_by_type="owner", requested_by="owner-gev")
        with self.assertRaises(ControlRoomAPIError) as caught:
            self.api.validate_command_intent(owner, now_epoch=self.now + 1,
                                             actor_attestation=None)
        message = str(caught.exception)
        self.assertIn(ACTOR_ATTESTATION_MISSING, message)

    def test_an_owner_command_bound_to_this_command_is_proven(self) -> None:
        owner = self.command(requested_by_type="owner", requested_by="owner-gev")
        reply = self.api.validate_command_intent(
            owner, now_epoch=self.now + 1,
            actor_attestation=self.owner_attestation(command=owner))
        self.assertTrue(reply["valid"])
        self.assertEqual(reply["actor_identity"], ACTOR_PROVEN_PER_COMMAND)
        self.assertNotEqual(reply["actor_identity"], ACTOR_PROVEN_BY_SESSION,
                            "a per-command proof must not report itself as a session")

    def test_an_owner_attestation_for_a_different_command_is_refused(self) -> None:
        """The whole point of the artifact: signing one command must not authorise another.

        Each field is varied on its own, so deleting any single comparison leaves a red test.
        """
        owner = self.command(requested_by_type="owner", requested_by="owner-gev")
        for field, other in (("command_id", "cmd-somebody-elses"),
                             ("task_id", "t-999.1"),
                             ("command", "retry")):
            with self.subTest(field=field):
                elsewhere = dict(owner)
                elsewhere[field] = other
                with self.assertRaises(ControlRoomAPIError) as caught:
                    self.api.validate_command_intent(
                        owner, now_epoch=self.now + 1,
                        actor_attestation=self.owner_attestation(command=elsewhere))
                self.assertIn("different command", str(caught.exception))

    def test_proving_an_owner_without_the_command_refuses_rather_than_weakening(self) -> None:
        """Defence in depth, and it needed its own test to be a check at all.

        `validate_command_intent` always passes the command, so every other test exercises the
        bound path and this guard stayed green when deleted — i.e. it was untested. It exists for
        a FUTURE caller that reaches `_prove_command_actor` directly: without it, `command=None`
        would skip the binding loop entirely and an owner artifact would silently become a session
        credential. Reached here by calling the method directly, which is the only way to get the
        argument wrong.
        """
        owner = self.command(requested_by_type="owner", requested_by="owner-gev")
        with self.assertRaises(ControlRoomAPIError) as caught:
            self.api._prove_command_actor(
                ("owner", "owner-gev"), self.owner_attestation(command=owner), None)
        self.assertIn("no command was supplied", str(caught.exception))

    def test_an_owner_cannot_present_a_conductor_session(self) -> None:
        """A session credential authorises a window; the owner's identity is not a window.

        `self.attestation()` is a valid `conductor-session`. Offered for an owner command it must
        fail on the artifact type, not be quietly accepted as good enough.
        """
        owner = self.command(requested_by_type="owner", requested_by="owner-gev")
        with self.assertRaises(ControlRoomAPIError) as caught:
            self.api.validate_command_intent(owner, now_epoch=self.now + 1,
                                             actor_attestation=self.attestation())
        self.assertIn("RED", str(caught.exception))

    def test_an_attestation_signed_by_the_wrong_authority_is_refused(self) -> None:
        self.refuse("RED", actor_attestation=self.attestation("builder"))

    def test_a_tampered_attestation_is_refused(self) -> None:
        forged = self.attestation()
        forged["payload"]["session_id"] = "s-somebody-else"
        self.refuse("RED", actor_attestation=forged)

    def test_an_attestation_that_speaks_for_another_identity_is_refused(self) -> None:
        for field, value in (("agent_id", "agt-p01-r01"), ("role", "specialist")):
            with self.subTest(field=field):
                self.refuse("does not speak for this actor",
                            actor_attestation=self.attestation(**{field: value}))

    def test_an_expired_or_undated_attestation_is_refused(self) -> None:
        for expires in (self.now - 1, "9999999999", None, True):
            with self.subTest(expires=expires):
                self.refuse("expired",
                            actor_attestation=self.attestation(expires_at_epoch=expires))

    def test_an_artifact_of_another_type_may_not_stand_in(self) -> None:
        self.refuse("RED", actor_attestation=self.attestation(artifact_type="workspace-binding"))

    def test_a_backdated_caller_clock_cannot_revive_an_expired_attestation(self) -> None:
        """The credential is judged on the wall clock, not on the caller's `now_epoch`."""
        stale = self.attestation(expires_at_epoch=self.now - 1)
        with self.assertRaises(ControlRoomAPIError) as caught:
            self.api.validate_command_intent(self.command(), now_epoch=self.now - 100,
                                             actor_attestation=stale)
        self.assertIn("expired", str(caught.exception))

    def test_a_non_document_attestation_is_refused(self) -> None:
        for value in ("{}", [], 7, {"payload": {}}, {"payload": {}, "signature": "zz", "x": 1}):
            with self.subTest(value=value):
                self.refuse("RED", actor_attestation=value)

    def test_a_runtime_with_no_trusted_keys_refuses_rather_than_trusting_the_claim(self) -> None:
        blind = DurableOrchestrationRuntimeV1(pathlib.Path(self.temp.name) / "blind", ROOT)
        blind.create_task(task_contract("task-actor-1"), now_epoch=self.now)
        api = ControlRoomAPIV1(blind)
        with self.assertRaises(ControlRoomAPIError) as caught:
            api.validate_command_intent(self.command(), now_epoch=self.now + 1,
                                        actor_attestation=self.attestation())
        self.assertIn("no trusted keys", str(caught.exception))

    def test_a_proven_actor_does_not_soften_the_other_gates(self) -> None:
        """Identity proof is one gate, not a master key."""
        stale = self.command(expected_task_state="running")
        with self.assertRaises(ControlRoomAPIError) as caught:
            self.api.validate_command_intent(stale, now_epoch=self.now + 1,
                                             actor_attestation=self.attestation())
        self.assertIn("stale or forbidden command state", str(caught.exception))
        forbidden = self.command(scope=["repository:menqstudio/Bro"])
        with self.assertRaises(ControlRoomAPIError):
            self.api.validate_command_intent(forbidden, now_epoch=self.now + 1,
                                             actor_attestation=self.attestation())

if __name__ == "__main__":
    unittest.main()
