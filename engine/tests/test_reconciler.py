import json
import pathlib
import shutil
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from bro_orchestration_runtime import OrchestrationRuntimeError
from bro_orchestration_runtime_v1 import RECONCILER_ID, DurableOrchestrationRuntimeV1
from bro_signature import load_trusted_keys
from broctl import build_registry, generate_key
from _operator_pin import use_operator_pin
from test_orchestration_runtime import AGENT, build_evidence, task_contract

AUTHORITIES = ["operator-root", "issuer", "evidence-recorder", "builder",
               "verifier", "release"]


class ReconcilerFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-rec-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.store = self.tmp / "evidence"
        self.store.mkdir()
        self.keys = {a: generate_key(a, f"dev-{a}", False) for a in AUTHORITIES}
        use_operator_pin(self, self.keys["operator-root"]["public_key"])  # external pin
        registry_root = self.tmp / "registry"
        (registry_root / "config").mkdir(parents=True)
        now = int(time.time())
        (registry_root / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(self.keys.values()), now - 60, 86400)),
            encoding="utf-8")
        self.runtime = DurableOrchestrationRuntimeV1(
            self.tmp / "state", ROOT, evidence_keys=load_trusted_keys(registry_root),
            evidence_store=self.store)

    def running_task(self, task_id, lease_seconds=300):
        self.runtime.create_task(task_contract(task_id), now_epoch=100)
        return self.runtime.claim_next(AGENT, now_epoch=101,
                                       lease_seconds=lease_seconds)["lease_id"]

    def state(self, task_id):
        return self.runtime._state(task_id)


class LeaseIsAuthorityTests(ReconcilerFixture):
    """The base class asked whether you were ever the right agent for this task,
    which stays true after the lease expires, after it is released, and after a
    recovery that issued none. Every mutating call passed on that alone, so a
    worker whose lease died hours ago still drove the task to completed."""

    def test_checkpoint_requires_a_live_lease(self):
        lease = self.running_task("task-cp", lease_seconds=10)
        with self.assertRaises(OrchestrationRuntimeError) as caught:
            self.runtime.checkpoint(
                "task-cp", actor_id=AGENT, lease_id=lease, now_epoch=200,
                completed_criteria=["done"], open_risks=["none"],
                next_action="next", evidence_refs=["e"])
        self.assertIn("missing, expired, or mismatched", str(caught.exception))

    def test_checkpoint_with_a_live_lease_passes(self):
        lease = self.running_task("task-cp2")
        self.runtime.checkpoint(
            "task-cp2", actor_id=AGENT, lease_id=lease, now_epoch=102,
            completed_criteria=["done"], open_risks=["none"],
            next_action="next", evidence_refs=["e"])

    def test_another_agents_lease_is_refused(self):
        self.running_task("task-cp3")
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.checkpoint(
                "task-cp3", actor_id=AGENT, lease_id="lease-someone-else",
                now_epoch=102, completed_criteria=["d"], open_risks=["n"],
                next_action="x", evidence_refs=["e"])

    def test_usage_requires_a_live_lease(self):
        lease = self.running_task("task-usage", lease_seconds=10)
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.record_usage(
                "task-usage", actor_id=AGENT, lease_id=lease, now_epoch=200,
                delta={"tool_calls": 1}, evidence_refs=["e"])

    def test_completion_requires_a_live_lease(self):
        """The one that mattered most: an expired worker completing its task."""
        lease = self.running_task("task-done", lease_seconds=10)
        refs = build_evidence(self.store, self.keys, "task-done", 2)
        with self.assertRaises(OrchestrationRuntimeError) as caught:
            self.runtime.complete_task("task-done", actor_id=AGENT, lease_id=lease,
                                       now_epoch=200, evidence_refs=refs)
        self.assertIn("missing, expired, or mismatched", str(caught.exception))

    def test_completion_with_a_live_lease_passes(self):
        lease = self.running_task("task-done2")
        refs = build_evidence(self.store, self.keys, "task-done2", 2)
        self.assertEqual(
            self.runtime.complete_task("task-done2", actor_id=AGENT, lease_id=lease,
                                       now_epoch=102, evidence_refs=refs)["state"],
            "completed")


class ReconcileTests(ReconcilerFixture):
    def test_stranded_task_moves_to_recovery_required(self):
        """No lease means nobody may advance it; not queued means nobody may
        claim it. Nothing reaped it, so it sat in running forever."""
        self.running_task("task-stranded", lease_seconds=10)
        self.assertEqual(self.state("task-stranded"), "running")
        result = self.runtime.reconcile(now_epoch=200)
        self.assertEqual([x["task_id"] for x in result["stranded"]], ["task-stranded"])
        self.assertEqual(result["failed"], [])
        self.assertEqual(self.state("task-stranded"), "recovery-required")

    def test_task_with_a_live_lease_is_left_alone(self):
        self.running_task("task-alive", lease_seconds=3600)
        result = self.runtime.reconcile(now_epoch=200)
        self.assertEqual(result["stranded"], [])
        self.assertEqual(self.state("task-alive"), "running")

    def test_queued_task_is_not_stranded(self):
        self.runtime.create_task(task_contract("task-queued"), now_epoch=100)
        self.assertEqual(self.runtime.reconcile(now_epoch=200)["stranded"], [])
        self.assertEqual(self.state("task-queued"), "queued")

    def test_completed_task_is_not_touched(self):
        lease = self.running_task("task-fin")
        refs = build_evidence(self.store, self.keys, "task-fin", 2)
        self.runtime.complete_task("task-fin", actor_id=AGENT, lease_id=lease,
                                   now_epoch=102, evidence_refs=refs)
        self.assertEqual(self.runtime.reconcile(now_epoch=9999)["stranded"], [])
        self.assertEqual(self.state("task-fin"), "completed")

    def test_reconcile_is_idempotent(self):
        self.running_task("task-twice", lease_seconds=10)
        self.assertEqual(len(self.runtime.reconcile(now_epoch=200)["stranded"]), 1)
        self.assertEqual(self.runtime.reconcile(now_epoch=201)["stranded"], [])

    def test_reconciler_acts_as_itself(self):
        self.running_task("task-actor", lease_seconds=10)
        self.runtime.reconcile(now_epoch=200)
        transitions = [r for r in self.runtime._records("task-actor")
                       if r.get("kind") == "transition"]
        self.assertEqual(transitions[-1]["payload"]["actor_id"], RECONCILER_ID)

    def test_unreadable_task_is_reported_not_swallowed(self):
        """A sweep that hides the task it could not reconcile reports success
        while the task stays stranded."""
        self.running_task("task-broken", lease_seconds=10)
        self.running_task("task-ok", lease_seconds=10)
        for record in (self.runtime.state_dir / "tasks" / "task-broken" / "records").iterdir():
            record.write_text("{ not json", encoding="utf-8")
        result = self.runtime.reconcile(now_epoch=200)
        self.assertEqual([x["task_id"] for x in result["failed"]], ["task-broken"])
        self.assertEqual([x["task_id"] for x in result["stranded"]], ["task-ok"])


class RecoveryHandsBackAuthorityTests(ReconcilerFixture):
    """recovery-required leads only to running, quarantined, failed or cancelled.
    There is no edge back to a claimable state, so a recovery that issues no
    lease lands the task in exactly the condition the reconciler exists to clear
    and would strand it again on the next sweep, forever.

    That lease hand-back is now UNREACHABLE, and deliberately so: clearing a recovery
    quarantine is an owner authorisation, `owner-gev` was a string any caller could
    type, and no owner-bound artifact type exists for this engine to verify one with
    (`bro_orchestration_runtime.OWNER_ACTOR_UNPROVABLE`). A recovery anybody can sign
    off is not a recovery. So the tests below assert the refusal and the stranding it
    leaves behind; the hand-back behaviour returns — with its own tests — when the
    owner mints the artifact that message names.
    """

    def test_recovery_is_refused_until_the_owner_actor_can_be_proven(self):
        self.running_task("task-rec", lease_seconds=10)
        self.runtime.reconcile(now_epoch=200)
        with self.assertRaises(OrchestrationRuntimeError) as caught:
            self.runtime.recover_task(
                "task-rec", owner_id="owner-gev", now_epoch=201, evidence_refs=["proof"])
        message = str(caught.exception)
        self.assertIn("cannot be validated", message)
        for named in ("ARTIFACT_AUTHORITY", "config/trusted-keys.json", "actor_attestation"):
            self.assertIn(named, message)
        self.assertEqual(self.state("task-rec"), "recovery-required")

    def test_a_refused_recovery_leaves_the_task_quarantined_not_running(self):
        """The refusal must not half-apply: no lease, no state change, and the
        reconciler does not report the task as stranded (it is quarantined, which is
        where a recovery it cannot authorise belongs)."""
        self.running_task("task-rec2", lease_seconds=10)
        self.runtime.reconcile(now_epoch=200)
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.recover_task("task-rec2", owner_id="owner-gev", now_epoch=201,
                                      evidence_refs=["proof"])
        self.assertIsNone(self.runtime._active_lease("task-rec2", 202))
        self.assertEqual(self.runtime.reconcile(now_epoch=202)["stranded"], [])
        self.assertEqual(self.state("task-rec2"), "recovery-required")

    def test_the_assignee_cannot_work_a_task_whose_recovery_was_refused(self):
        self.running_task("task-rec3", lease_seconds=10)
        self.runtime.reconcile(now_epoch=200)
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.recover_task("task-rec3", owner_id="owner-gev", now_epoch=201,
                                      evidence_refs=["proof"])
        refs = build_evidence(self.store, self.keys, "task-rec3", 2)
        with self.assertRaises(OrchestrationRuntimeError) as caught:
            self.runtime.complete_task("task-rec3", actor_id=AGENT, lease_id="lease-invented",
                                       now_epoch=202, evidence_refs=refs)
        self.assertIn("lease", str(caught.exception))

    def test_recovery_rejects_an_invalid_lease_duration(self):
        self.running_task("task-rec4", lease_seconds=10)
        self.runtime.reconcile(now_epoch=200)
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.recover_task("task-rec4", owner_id="owner-gev", now_epoch=201,
                                      evidence_refs=["proof"], lease_seconds=0)


if __name__ == "__main__":
    unittest.main()
