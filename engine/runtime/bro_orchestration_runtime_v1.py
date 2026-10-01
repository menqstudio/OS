from __future__ import annotations

import pathlib
import uuid
from typing import Any

from bro_orchestration_runtime import (ACTOR_RUNTIME_ORIGINATED,
                                       DEFAULT_LEASE_SECONDS,
                                       MAX_LEASE_SECONDS,
                                       DurableOrchestrationRuntime,
                                       OrchestrationRuntimeError)

RECONCILER_ID = "system-reconciler"


class DurableOrchestrationRuntimeV1(DurableOrchestrationRuntime):
    """Durable runtime with cross-process queue claim serialization and expiring leases."""

    def __init__(self, state_dir: pathlib.Path | str, root: pathlib.Path | None = None,
                 *, evidence_keys: dict | None = None,
                 evidence_store: pathlib.Path | None = None):
        kwargs = {"evidence_keys": evidence_keys, "evidence_store": evidence_store}
        if root is None:
            super().__init__(state_dir, **kwargs)
        else:
            super().__init__(state_dir, root, **kwargs)

    # _mint_lease, _require_lease and _active_lease are the base class's, and so is the
    # body of claim_next. This class kept its own copies after they moved there, and
    # the copy of claim_next had drifted: it recorded the runtime's own routing
    # transition with no identity basis, so the ledger of the runtime the bridge
    # sidecar ships said "unproven-caller-claim" where the base class says
    # "runtime-originated".

    def claim_next(self, agent_id: str, *, now_epoch: int,
                   lease_seconds: int = DEFAULT_LEASE_SECONDS) -> dict[str, Any] | None:
        # Like every other entry point here: take the claim guard itself, then
        # delegate. The base method's guard is reentrant, so it rides this one.
        with self._claim_guard():
            return super().claim_next(agent_id, now_epoch=now_epoch, lease_seconds=lease_seconds)

    def renew_claim(
        self,
        task_id: str,
        *,
        agent_id: str,
        lease_id: str,
        now_epoch: int,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> dict[str, Any]:
        self._validate_actor("agent", agent_id)
        if not isinstance(lease_seconds, int) or not 1 <= lease_seconds <= MAX_LEASE_SECONDS:
            raise OrchestrationRuntimeError("lease duration invalid")
        with self._claim_guard():
            active = self._active_lease(task_id, now_epoch)
            if active is None or active.get("lease_id") != lease_id or active.get("agent_id") != agent_id:
                raise OrchestrationRuntimeError("claim lease is missing, expired, or mismatched")
            self._append(task_id, "claim-released", now_epoch, {"lease_id": lease_id, "reason": "renewed"})
            renewed = f"lease-{uuid.uuid4().hex}"
            self._append(
                task_id,
                "claim-lease",
                now_epoch,
                {
                    "lease_id": renewed,
                    "agent_id": agent_id,
                    "issued_at_epoch": now_epoch,
                    "expires_at_epoch": now_epoch + lease_seconds,
                },
            )
            return {"task_id": task_id, "lease_id": renewed, "expires_at_epoch": now_epoch + lease_seconds}

    def release_claim(
        self,
        task_id: str,
        *,
        agent_id: str,
        lease_id: str,
        now_epoch: int,
        evidence_refs: list[str],
    ) -> dict[str, Any]:
        self._validate_actor("agent", agent_id)
        if not isinstance(evidence_refs, list) or not evidence_refs or not all(isinstance(x, str) and x for x in evidence_refs):
            raise OrchestrationRuntimeError("claim release requires evidence")
        with self._claim_guard():
            active = self._active_lease(task_id, now_epoch)
            if active is None or active.get("lease_id") != lease_id or active.get("agent_id") != agent_id:
                raise OrchestrationRuntimeError("claim lease is missing, expired, or mismatched")
            self._append(
                task_id,
                "claim-released",
                now_epoch,
                {"lease_id": lease_id, "agent_id": agent_id, "evidence_refs": list(evidence_refs)},
            )
            return self.task_snapshot(task_id, now_epoch)

    def checkpoint(self, task_id: str, *, actor_id: str, lease_id: str, now_epoch: int,
                   completed_criteria: list[str], open_risks: list[str],
                   next_action: str, evidence_refs: list[str]) -> dict[str, Any]:
        with self._claim_guard():
            self._require_lease(task_id, actor_id, lease_id, now_epoch)
            return super().checkpoint(
                task_id, actor_id=actor_id, now_epoch=now_epoch,
                completed_criteria=completed_criteria, open_risks=open_risks,
                next_action=next_action, evidence_refs=evidence_refs)

    def record_usage(self, task_id: str, *, actor_id: str, lease_id: str,
                     now_epoch: int, delta: dict[str, int],
                     evidence_refs: list[str]) -> dict[str, Any]:
        with self._claim_guard():
            self._require_lease(task_id, actor_id, lease_id, now_epoch)
            return super().record_usage(
                task_id, actor_id=actor_id, now_epoch=now_epoch,
                delta=delta, evidence_refs=evidence_refs)

    def submit_for_verification(self, task_id: str, *, actor_id: str, lease_id: str,
                                now_epoch: int, evidence_refs: list[str]) -> dict[str, Any]:
        with self._claim_guard():
            self._require_lease(task_id, actor_id, lease_id, now_epoch)
            return super().submit_for_verification(
                task_id, actor_id=actor_id, now_epoch=now_epoch,
                evidence_refs=evidence_refs)

    def complete_task(self, task_id: str, *, actor_id: str, lease_id: str,
                      now_epoch: int, evidence_refs: list[str],
                      completion_manifest: dict[str, Any] | None = None,
                      verifier_receipt: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._claim_guard():
            self._require_lease(task_id, actor_id, lease_id, now_epoch)
            return super().complete_task(
                task_id, actor_id=actor_id, now_epoch=now_epoch,
                evidence_refs=evidence_refs, completion_manifest=completion_manifest,
                verifier_receipt=verifier_receipt)

    def recover_task(self, task_id: str, *, owner_id: str, now_epoch: int,
                     evidence_refs: list[str],
                     lease_seconds: int = DEFAULT_LEASE_SECONDS) -> dict[str, Any]:
        """Recovery has to hand back authority, not just state.

        recovery-required leads only to running, quarantined, failed or
        cancelled: there is no edge back to a claimable state. So a recovery that
        issues no lease lands the task in running with nobody authorised to touch
        it, which is the exact condition the reconciler exists to clear — it
        would strand the task again on the next sweep, forever.
        """
        if not isinstance(lease_seconds, int) or not 1 <= lease_seconds <= MAX_LEASE_SECONDS:
            raise OrchestrationRuntimeError("lease duration invalid")
        with self._claim_guard():
            snapshot = super().recover_task(
                task_id, owner_id=owner_id, now_epoch=now_epoch,
                evidence_refs=evidence_refs)
            lease_id = self._mint_lease(
                task_id, self._contract(task_id)["agent_id"], now_epoch, lease_seconds)
            snapshot["lease_id"] = lease_id
            snapshot["lease_expires_at_epoch"] = now_epoch + lease_seconds
            return snapshot

    def reconcile(self, *, now_epoch: int) -> dict[str, list[dict[str, Any]]]:
        """Return lifecycle state and execution authority to agreement.

        Lease expiry was observed only by whoever touched that exact task next,
        and claim_next looks at queued tasks only. A task whose agent died
        mid-execution was therefore reaped by nothing: it holds no lease, so
        nobody may advance it, and it is not queued, so nobody may claim it. It
        sat in running permanently.

        Stranded tasks go to recovery-required, not back to queued. The registry
        has no running->queued edge, and the better reason is that a vanished
        agent leaves effects of unknown extent behind. Requeuing would assert the
        work is safe to redo, which is precisely what the runtime cannot know.
        blocked would be lighter and would claim the same thing.

        Failures are returned rather than swallowed. A sweep that hides the task
        it could not reconcile reports success while the task stays stranded,
        which is the failure mode this whole exercise has been chasing.
        """
        stranded: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        with self._claim_guard():
            for directory in sorted(self.tasks_dir.iterdir()):
                if not directory.is_dir():
                    continue
                task_id = directory.name
                try:
                    if self._state(task_id) != "running":
                        continue
                    if self._active_lease(task_id, now_epoch) is not None:
                        continue
                    # The reconciler is this runtime's own automatic decision, not a
                    # caller's claim, and is recorded as what it is.
                    self._transition(task_id, "recovery-required", "system",
                                     RECONCILER_ID, now_epoch, "recovery-required", [],
                                     identity_basis=ACTOR_RUNTIME_ORIGINATED)
                    stranded.append({"task_id": task_id, "reason": "lease-lost-while-running"})
                except OrchestrationRuntimeError as exc:
                    # One unreadable task must not stop the sweep that would have
                    # reconciled the rest, but it must not vanish either.
                    failed.append({"task_id": task_id, "error": str(exc)})
        return {"stranded": stranded, "failed": failed}
