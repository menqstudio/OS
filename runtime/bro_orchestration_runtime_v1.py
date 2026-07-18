from __future__ import annotations

import contextlib
import json
import os
import pathlib
import time
import uuid
from typing import Any, Iterator

from bro_orchestration_runtime import DurableOrchestrationRuntime, OrchestrationRuntimeError

DEFAULT_LEASE_SECONDS = 300
MAX_LEASE_SECONDS = 86400
LOCK_TIMEOUT_SECONDS = 10
STALE_LOCK_SECONDS = 30
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
        self.claim_lock = self.state_dir / ".claim.lock"

    def _lock_owner(self) -> str | None:
        try:
            return json.loads(self.claim_lock.read_text(encoding="utf-8")).get("owner_token")
        except (OSError, json.JSONDecodeError, AttributeError):
            return None

    def _break_stale_lock(self, observed_token: str | None) -> None:
        """Steal a stale lock by renaming it, so only one breaker can win.

        Unlinking it directly meant every process that saw the same stale lock
        deleted it, and the second deletion landed on the lock the first breaker
        had already replaced. Rename is exclusive: the loser gets ENOENT because
        the source is already gone.

        The token observed before the staleness check is re-read here, so a lock
        that was released and re-taken in the meantime is left alone.
        """
        if self._lock_owner() != observed_token:
            return
        stolen = self.claim_lock.with_name(f".claim.stale.{uuid.uuid4().hex}")
        try:
            os.replace(self.claim_lock, stolen)
        except (FileNotFoundError, PermissionError):
            return
        stolen.unlink(missing_ok=True)

    @contextlib.contextmanager
    def _claim_guard(self) -> Iterator[None]:
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        token = uuid.uuid4().hex
        payload = json.dumps({"owner_token": token, "pid": os.getpid(),
                              "created_at_epoch": int(time.time())}).encode("utf-8")
        while True:
            try:
                descriptor = os.open(self.claim_lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb", closefd=True) as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                break
            except FileExistsError:
                try:
                    age = time.time() - self.claim_lock.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > STALE_LOCK_SECONDS:
                    # Read the owner only when actually breaking. Reading it on
                    # every spin put every waiter in a read/delete race with the
                    # holder's release, and a lost race there leaks the lock: the
                    # holder cannot confirm the lock is its own, declines to
                    # remove it, and everyone else waits out the timeout.
                    self._break_stale_lock(self._lock_owner())
                    continue
                if time.monotonic() >= deadline:
                    raise OrchestrationRuntimeError("claim lock acquisition timed out")
                time.sleep(0.01)
        try:
            yield
        finally:
            # Release "my lock", not "the lock". An overrunning holder whose lock
            # was already broken and retaken must not delete the new holder's,
            # which would put two processes inside the guard at once.
            if self._lock_owner() == token:
                self.claim_lock.unlink(missing_ok=True)

    def _mint_lease(self, task_id: str, agent_id: str, now_epoch: int,
                    lease_seconds: int) -> str:
        lease_id = f"lease-{uuid.uuid4().hex}"
        self._append(task_id, "claim-lease", now_epoch, {
            "lease_id": lease_id,
            "agent_id": agent_id,
            "issued_at_epoch": now_epoch,
            "expires_at_epoch": now_epoch + lease_seconds,
        })
        return lease_id

    def _require_lease(self, task_id: str, agent_id: str, lease_id: str,
                       now_epoch: int) -> dict[str, Any]:
        """Execution authority is the lease, not the contract.

        The assignee check the base class performs asks whether you were ever the
        right agent for this task. That stays true after the lease expires, after
        it is released, and after a recovery that issued none, so it answered a
        question nobody was asking. Only the lease says whether you are
        authorised right now.
        """
        active = self._active_lease(task_id, now_epoch)
        if active is None or active.get("lease_id") != lease_id or active.get("agent_id") != agent_id:
            raise OrchestrationRuntimeError("claim lease is missing, expired, or mismatched")
        return active

    def _active_lease(self, task_id: str, now_epoch: int) -> dict[str, Any] | None:
        latest: dict[str, Any] | None = None
        for record in self._records(task_id):
            if record.get("kind") == "claim-lease":
                latest = record["payload"]
            elif record.get("kind") in {"claim-released", "claim-expired"}:
                latest = None
        if latest is None:
            return None
        if latest["expires_at_epoch"] <= now_epoch:
            self._append(
                task_id,
                "claim-expired",
                now_epoch,
                {"lease_id": latest["lease_id"], "reason": "lease-expired-before-claim"},
            )
            return None
        return latest

    def claim_next(
        self,
        agent_id: str,
        *,
        now_epoch: int,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> dict[str, Any] | None:
        self._validate_actor("agent", agent_id)
        if not isinstance(now_epoch, int) or now_epoch < 0:
            raise OrchestrationRuntimeError("time must be a non-negative integer")
        if not isinstance(lease_seconds, int) or not 1 <= lease_seconds <= MAX_LEASE_SECONDS:
            raise OrchestrationRuntimeError("lease duration invalid")
        with self._claim_guard():
            candidates: list[tuple[int, int, str]] = []
            for directory in self.tasks_dir.iterdir():
                if not directory.is_dir():
                    continue
                task_id = directory.name
                if self._state(task_id) != "queued":
                    continue
                contract = self._contract(task_id)
                if contract.get("agent_id") != agent_id:
                    continue
                if self._active_lease(task_id, now_epoch) is not None:
                    continue
                config = self._config(task_id)
                first = self._records(task_id)[0]["observed_at_epoch"]
                candidates.append((-self.queue[config["queue_class"]], first, task_id))
            if not candidates:
                return None
            _, _, task_id = sorted(candidates)[0]
            lease_id = f"lease-{uuid.uuid4().hex}"
            self._append(
                task_id,
                "claim-lease",
                now_epoch,
                {
                    "lease_id": lease_id,
                    "agent_id": agent_id,
                    "issued_at_epoch": now_epoch,
                    "expires_at_epoch": now_epoch + lease_seconds,
                },
            )
            self._transition(task_id, "routing", "bro", "bro-000", now_epoch, "routing-started", [])
            snapshot = self._transition(task_id, "running", "agent", agent_id, now_epoch, "execution-started", [])
            snapshot["lease_id"] = lease_id
            snapshot["lease_expires_at_epoch"] = now_epoch + lease_seconds
            return snapshot

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
                      now_epoch: int, evidence_refs: list[str]) -> dict[str, Any]:
        with self._claim_guard():
            self._require_lease(task_id, actor_id, lease_id, now_epoch)
            return super().complete_task(
                task_id, actor_id=actor_id, now_epoch=now_epoch,
                evidence_refs=evidence_refs)

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
                    self._transition(task_id, "recovery-required", "system",
                                     RECONCILER_ID, now_epoch, "recovery-required", [])
                    stranded.append({"task_id": task_id, "reason": "lease-lost-while-running"})
                except OrchestrationRuntimeError as exc:
                    # One unreadable task must not stop the sweep that would have
                    # reconciled the rest, but it must not vanish either.
                    failed.append({"task_id": task_id, "error": str(exc)})
        return {"stranded": stranded, "failed": failed}
