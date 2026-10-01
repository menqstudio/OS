import json
import os
import pathlib
import sys
import tempfile
import threading
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import bro_orchestration_runtime as runtime_base
import bro_orchestration_runtime_v1 as runtime_v1
from bro_orchestration_runtime import OrchestrationRuntimeError
from bro_orchestration_runtime_v1 import DurableOrchestrationRuntimeV1

AGENT = "agt-p01-r01"


def task_contract(task_id: str) -> dict:
    return {
        "schema": 1,
        "task_id": task_id,
        "title": f"Task {task_id}",
        "objective": "Exercise atomic orchestration claim leases",
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
        "done_criteria": ["Claim is serialized and evidence-backed"],
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


class ClaimLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.state_dir = pathlib.Path(self.temporary.name)
        self.runtime = DurableOrchestrationRuntimeV1(self.state_dir, ROOT)

    def tearDown(self):
        self.temporary.cleanup()

    def test_parallel_claim_returns_task_once(self):
        self.runtime.create_task(task_contract("task-parallel"), now_epoch=100)
        results = []
        errors = []

        def claim():
            try:
                results.append(DurableOrchestrationRuntimeV1(self.state_dir, ROOT).claim_next(AGENT, now_epoch=101))
            except Exception as exc:
                errors.append(exc)

        workers = [threading.Thread(target=claim) for _ in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        self.assertFalse(errors)
        claimed = [item for item in results if item is not None]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["task_id"], "task-parallel")
        self.assertRegex(claimed[0]["lease_id"], r"^lease-[0-9a-f]{32}$")

    def test_active_lease_blocks_second_claim(self):
        self.runtime.create_task(task_contract("task-one"), now_epoch=100)
        first = self.runtime.claim_next(AGENT, now_epoch=101, lease_seconds=10)
        self.assertIsNotNone(first)
        self.runtime.create_task(task_contract("task-two"), now_epoch=102)
        second = self.runtime.claim_next(AGENT, now_epoch=103)
        self.assertEqual(second["task_id"], "task-two")

    def test_renew_requires_exact_lease_and_agent(self):
        self.runtime.create_task(task_contract("task-renew"), now_epoch=100)
        claimed = self.runtime.claim_next(AGENT, now_epoch=101, lease_seconds=10)
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.renew_claim(
                "task-renew", agent_id=AGENT, lease_id="lease-wrong",
                now_epoch=102, lease_seconds=10,
            )
        renewed = self.runtime.renew_claim(
            "task-renew", agent_id=AGENT, lease_id=claimed["lease_id"],
            now_epoch=102, lease_seconds=20,
        )
        self.assertNotEqual(renewed["lease_id"], claimed["lease_id"])
        self.assertEqual(renewed["expires_at_epoch"], 122)

    def test_release_requires_evidence(self):
        self.runtime.create_task(task_contract("task-release"), now_epoch=100)
        claimed = self.runtime.claim_next(AGENT, now_epoch=101)
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.release_claim(
                "task-release", agent_id=AGENT, lease_id=claimed["lease_id"],
                now_epoch=102, evidence_refs=[],
            )
        snapshot = self.runtime.release_claim(
            "task-release", agent_id=AGENT, lease_id=claimed["lease_id"],
            now_epoch=102, evidence_refs=["evidence/release.json"],
        )
        self.assertEqual(snapshot["state"], "running")

    def test_expired_queued_lease_is_recovered(self):
        self.runtime.create_task(task_contract("task-expired"), now_epoch=100)
        self.runtime._append(
            "task-expired", "claim-lease", 101,
            {
                "lease_id": "lease-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "agent_id": AGENT,
                "issued_at_epoch": 101,
                "expires_at_epoch": 102,
            },
        )
        claimed = self.runtime.claim_next(AGENT, now_epoch=103)
        self.assertEqual(claimed["task_id"], "task-expired")
        kinds = [item["kind"] for item in self.runtime._records("task-expired")]
        self.assertIn("claim-expired", kinds)

    def test_invalid_lease_duration_fails_closed(self):
        self.runtime.create_task(task_contract("task-duration"), now_epoch=100)
        with self.assertRaises(OrchestrationRuntimeError):
            self.runtime.claim_next(AGENT, now_epoch=101, lease_seconds=0)

    def test_v1_inherits_the_lease_machinery_and_records_what_the_base_records(self):
        # V1 carried byte-for-byte copies of three lease methods and a drifted copy of
        # claim_next, which recorded the runtime's own routing transition with no
        # identity basis. The runtime the bridge sidecar ships must write the same
        # ledger as the class it extends.
        for name in ("_mint_lease", "_require_lease", "_active_lease"):
            self.assertNotIn(name, vars(DurableOrchestrationRuntimeV1), name)
        self.assertIs(runtime_v1.DEFAULT_LEASE_SECONDS, runtime_base.DEFAULT_LEASE_SECONDS)
        self.assertIs(runtime_v1.MAX_LEASE_SECONDS, runtime_base.MAX_LEASE_SECONDS)
        self.runtime.create_task(task_contract("task-basis"), now_epoch=100)
        self.runtime.claim_next(AGENT, now_epoch=101, lease_seconds=5)
        basis = {record["payload"]["next_state"]: record["payload"]["actor_identity_basis"]
                 for record in self.runtime._records("task-basis") if record["kind"] == "transition"}
        self.assertEqual(basis["routing"], runtime_base.ACTOR_RUNTIME_ORIGINATED)
        self.assertEqual(basis["running"], runtime_base.ACTOR_UNPROVEN)
        # The reconciler is the runtime's own decision too.
        self.assertEqual(self.runtime.reconcile(now_epoch=200)["stranded"],
                         [{"task_id": "task-basis", "reason": "lease-lost-while-running"}])
        last = self.runtime._records("task-basis")[-1]["payload"]
        self.assertEqual(last["next_state"], "recovery-required")
        self.assertEqual(last["actor_identity_basis"], runtime_base.ACTOR_RUNTIME_ORIGINATED)

    def test_the_base_class_guard_serializes_threads_of_one_process(self):
        # The reentrancy registry was keyed by lock file alone, so a second THREAD of
        # the holding process was told it already held the guard and walked in beside
        # the holder. V1's own claim_next hid that by always taking the real lock; the
        # base class every other caller instantiates collided on every run.
        self.runtime.create_task(task_contract("task-threads"), now_epoch=100)
        # Deterministically: while this thread holds the guard, another thread of the
        # same process does not.
        seen = []
        with self.runtime._claim_guard():
            self.assertTrue(self.runtime._guard_held_by_this_process())
            other = threading.Thread(
                target=lambda: seen.append(self.runtime._guard_held_by_this_process()))
            other.start()
            other.join()
        self.assertEqual(seen, [False])
        # And as the race it is.
        results = []
        errors = []

        def claim():
            try:
                results.append(runtime_base.DurableOrchestrationRuntime(
                    self.state_dir, ROOT).claim_next(AGENT, now_epoch=101))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=claim) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertFalse(errors)
        self.assertEqual(len([item for item in results if item is not None]), 1)

    def test_a_backdated_clock_is_refused(self):
        # Lease expiry is judged against the caller's now_epoch. A time earlier than
        # the ledger has already observed must not be accepted as "now".
        self.runtime.create_task(task_contract("task-clock"), now_epoch=100)
        claimed = self.runtime.claim_next(AGENT, now_epoch=200, lease_seconds=10)
        before = len(self.runtime._records("task-clock"))
        with self.assertRaisesRegex(OrchestrationRuntimeError, "time moved backwards"):
            self.runtime.checkpoint(
                "task-clock", actor_id=AGENT, lease_id=claimed["lease_id"], now_epoch=150,
                completed_criteria=["x"], open_risks=["none"], next_action="continue",
                evidence_refs=["evidence/x"])
        self.assertEqual(len(self.runtime._records("task-clock")), before)
        # The same instant, and any later one, is still accepted.
        self.runtime.checkpoint(
            "task-clock", actor_id=AGENT, lease_id=claimed["lease_id"], now_epoch=200,
            completed_criteria=["x"], open_risks=["none"], next_action="continue",
            evidence_refs=["evidence/x"])


class InterruptedCreationTests(unittest.TestCase):
    """One half-created task directory must not wedge the queue, and must be finishable."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.state_dir = pathlib.Path(self.temporary.name)
        self.runtime = DurableOrchestrationRuntimeV1(self.state_dir, ROOT)

    def tearDown(self):
        self.temporary.cleanup()

    def interrupt(self, task_id: str, *, after_writes: int) -> None:
        """Run create_task and kill it after `after_writes` of its record writes."""
        real_append = self.runtime._append
        calls = {"n": 0}

        def dying_append(*args, **kwargs):
            if calls["n"] >= after_writes:
                raise RuntimeError("process died")
            calls["n"] += 1
            return real_append(*args, **kwargs)

        self.runtime._append = dying_append
        try:
            with self.assertRaisesRegex(RuntimeError, "process died"):
                self.runtime.create_task(task_contract(task_id), now_epoch=100)
        finally:
            del self.runtime._append

    def test_a_half_created_task_does_not_fail_the_claim_of_a_healthy_one(self):
        self.runtime.create_task(task_contract("task-healthy"), now_epoch=100)
        self.interrupt("task-half", after_writes=0)
        self.assertTrue((self.state_dir / "tasks" / "task-half" / "contract.json").exists())
        claimed = self.runtime.claim_next(AGENT, now_epoch=101)
        self.assertEqual(claimed["task_id"], "task-healthy")
        # Reported, with the head an empty chain has — not an IndexError.
        report = self.runtime.integrity_report()
        self.assertEqual(report["heads"]["task-half"], "0" * 64)
        # And the reconciler names it instead of hiding it.
        failed = self.runtime.reconcile(now_epoch=102)["failed"]
        self.assertEqual([item["task_id"] for item in failed], ["task-half"])

    def test_an_interrupted_creation_is_resumed_from_every_point(self):
        for after_writes in (0, 1, 2):
            task_id = f"task-resume-{after_writes}"
            self.interrupt(task_id, after_writes=after_writes)
            self.assertEqual(len(self.runtime._records(task_id)), after_writes)
            snapshot = self.runtime.create_task(task_contract(task_id), now_epoch=100)
            self.assertEqual(snapshot["state"], "queued", task_id)
            records = self.runtime._records(task_id)
            self.assertEqual([r["kind"] for r in records],
                             ["runtime-config", "transition", "transition"], task_id)
            self.assertEqual([r["payload"].get("next_state") for r in records[1:]],
                             ["draft", "queued"], task_id)
        self.assertEqual(self.runtime.claim_next(AGENT, now_epoch=101)["state"], "running")

    def test_resuming_requires_exactly_what_the_interrupted_call_wrote(self):
        self.interrupt("task-other", after_writes=1)
        different = task_contract("task-other")
        different["objective"] = "Something else entirely"
        with self.assertRaisesRegex(OrchestrationRuntimeError, "different contract"):
            self.runtime.create_task(different, now_epoch=100)
        with self.assertRaisesRegex(OrchestrationRuntimeError, "different queue class or budget"):
            self.runtime.create_task(task_contract("task-other"), now_epoch=100,
                                     budget_limits={"tokens": {"soft": 1, "hard": 2}})
        self.assertEqual(len(self.runtime._records("task-other")), 1)

    def test_a_created_task_is_still_refused_a_second_creation(self):
        self.runtime.create_task(task_contract("task-once"), now_epoch=100)
        with self.assertRaisesRegex(OrchestrationRuntimeError, "task already exists"):
            self.runtime.create_task(task_contract("task-once"), now_epoch=100)
        self.runtime.claim_next(AGENT, now_epoch=101)
        with self.assertRaisesRegex(OrchestrationRuntimeError, "task already exists"):
            self.runtime.create_task(task_contract("task-once"), now_epoch=102)

    def test_a_record_that_does_not_verify_still_stops_the_claim(self):
        # Only the never-started case is skipped. A broken chain is not a crash
        # artifact, and claim_next must keep refusing to look past it.
        self.runtime.create_task(task_contract("task-healthy"), now_epoch=100)
        self.runtime.create_task(task_contract("task-tampered"), now_epoch=100)
        record = self.state_dir / "tasks" / "task-tampered" / "records" / "00000002.json"
        record.write_text(record.read_text(encoding="utf-8").replace("draft", "queued"),
                          encoding="utf-8")
        with self.assertRaisesRegex(OrchestrationRuntimeError, "hash invalid"):
            self.runtime.claim_next(AGENT, now_epoch=101)


class StaleLockTests(unittest.TestCase):
    """The stale-lock breaker must leave alone a lock re-taken since it was judged stale."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.state_dir = pathlib.Path(self.temporary.name)
        self.runtime = DurableOrchestrationRuntimeV1(self.state_dir, ROOT)
        self.lock = self.runtime.claim_lock

    def tearDown(self):
        self.temporary.cleanup()

    def write_lock(self, token: str, *, age: float) -> None:
        self.lock.write_text(json.dumps({"owner_token": token, "pid": 1}), encoding="utf-8")
        moment = time.time() - age
        os.utime(self.lock, (moment, moment))

    def test_a_fresh_lock_is_not_broken_even_when_the_token_matches(self):
        self.write_lock("holder", age=0)
        self.runtime._break_stale_lock("holder")
        self.assertEqual(self.runtime._lock_owner(), "holder")
        # A genuinely stale one with the observed token is.
        self.write_lock("dead", age=runtime_base.STALE_LOCK_SECONDS + 5)
        self.runtime._break_stale_lock("dead")
        self.assertFalse(self.lock.exists())

    def test_a_lock_retaken_after_the_staleness_check_is_not_stolen(self):
        # The waiter stats a stale lock; before it reads the owner, the lock is
        # released and re-taken. It then reads the NEW token, and the breaker used to
        # compare that against its own immediate re-read — equal, so it stole a live lock.
        self.write_lock("dead", age=runtime_base.STALE_LOCK_SECONDS + 5)
        real_owner = self.runtime._lock_owner
        retaken = {"done": False}

        def owner_after_retake():
            if not retaken["done"]:
                retaken["done"] = True
                self.write_lock("live", age=0)
            return real_owner()

        self.runtime._lock_owner = owner_after_retake
        original_timeout = runtime_base.LOCK_TIMEOUT_SECONDS
        runtime_base.LOCK_TIMEOUT_SECONDS = 0.3
        try:
            with self.assertRaisesRegex(OrchestrationRuntimeError, "timed out"):
                with self.runtime._claim_guard():
                    self.fail("entered the guard by stealing a live lock")
        finally:
            runtime_base.LOCK_TIMEOUT_SECONDS = original_timeout
            del self.runtime._lock_owner
        self.assertEqual(self.runtime._lock_owner(), "live")


if __name__ == "__main__":
    unittest.main()
