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


class DurableOrchestrationRuntimeV1(DurableOrchestrationRuntime):
    """Durable runtime with cross-process queue claim serialization and expiring leases."""

    def __init__(self, state_dir: pathlib.Path | str, root: pathlib.Path | None = None):
        if root is None:
            super().__init__(state_dir)
        else:
            super().__init__(state_dir, root)
        self.claim_lock = self.state_dir / ".claim.lock"

    @contextlib.contextmanager
    def _claim_guard(self) -> Iterator[None]:
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        payload = json.dumps({"pid": os.getpid(), "created_at_epoch": int(time.time())}).encode("utf-8")
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
                    try:
                        self.claim_lock.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise OrchestrationRuntimeError("claim lock acquisition timed out")
                time.sleep(0.01)
        try:
            yield
        finally:
            self.claim_lock.unlink(missing_ok=True)

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
