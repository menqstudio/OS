from __future__ import annotations

import contextlib
import hashlib
import json
import os
import pathlib
import tempfile
import time
import uuid
from typing import Any, Iterator

from bro_contracts import ContractError, validate_task_contract
from bro_evidence import EvidenceError, validate_chain
from bro_identity import IdentityError, all_agent_identities
from bro_orchestration import OrchestrationError, build_control_room_projection, validate_transition

ROOT = pathlib.Path(__file__).resolve().parents[1]
ZERO_HASH = "0" * 64
TERMINAL = {"completed", "failed", "cancelled"}
DEFAULT_LEASE_SECONDS = 300
MAX_LEASE_SECONDS = 86400
LOCK_TIMEOUT_SECONDS = 10
STALE_LOCK_SECONDS = 30


class OrchestrationRuntimeError(ValueError):
    pass


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash_record(record: dict[str, Any]) -> str:
    unsigned = dict(record)
    unsigned.pop("record_sha256", None)
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def _atomic_json(path: pathlib.Path, value: dict[str, Any]) -> None:
    """Atomic replace, for state that is meant to be overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        temporary = pathlib.Path(handle.name)
        handle.write(_canonical(value))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _exclusive_json(path: pathlib.Path, value: dict[str, Any]) -> None:
    """Create a record, or refuse. Never overwrite one.

    The append path computed the next sequence from the current record count,
    checked that the file was absent, and then wrote with os.replace. Two
    processes could read the same count, both find the path absent, and both
    write: os.replace is atomic but it overwrites, so one record vanished and
    the hash chain forked with nobody the wiser. The check and the write have to
    be the same operation, which is what O_EXCL gives.

    The directory is fsynced too: on a crash the file's contents can otherwise
    survive while the name that makes it findable does not.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as exc:
        raise OrchestrationRuntimeError(
            f"record sequence already exists: {path.name}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical(value))
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    if hasattr(os, "O_DIRECTORY"):
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def _load(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise OrchestrationRuntimeError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OrchestrationRuntimeError(f"{path} must contain an object")
    return value


def _strings(value: Any, field: str, *, required: bool = False) -> list[str]:
    if not isinstance(value, list) or (required and not value):
        raise OrchestrationRuntimeError(f"{field} must be a list")
    if not all(isinstance(item, str) and item for item in value) or len(value) != len(set(value)):
        raise OrchestrationRuntimeError(f"{field} must contain unique non-empty strings")
    return list(value)


class DurableOrchestrationRuntime:
    """Filesystem-backed, append-only orchestration runtime.

    Policy remains in the repository SST. Runtime state lives outside Git and is
    reconstructed from immutable task contracts plus hash-chained records.
    """

    def __init__(self, state_dir: pathlib.Path | str, root: pathlib.Path = ROOT,
                 *, evidence_keys: dict | None = None,
                 evidence_store: pathlib.Path | None = None):
        # Without a verifier the runtime can still read, queue, claim and
        # checkpoint; it just cannot declare anything finished. Completion is the
        # one transition that asserts work happened, so it is the one that needs
        # to be able to check.
        self.evidence_keys = evidence_keys
        self.evidence_store = pathlib.Path(evidence_store) if evidence_store else None
        self.root = pathlib.Path(root).resolve()
        self.state_dir = pathlib.Path(state_dir).resolve()
        self.tasks_dir = self.state_dir / "tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.claim_lock = self.state_dir / ".claim.lock"
        self.registry = _load(self.root / "orchestration" / "registry.json")
        self.queue = {
            item["id"]: item["priority"]
            for item in self.registry.get("queue_classes", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("priority"), int)
        }
        if not self.queue:
            raise OrchestrationRuntimeError("queue policy missing")

    def _task_dir(self, task_id: str) -> pathlib.Path:
        if not isinstance(task_id, str) or not task_id or "/" in task_id or "\\" in task_id:
            raise OrchestrationRuntimeError("invalid task_id")
        return self.tasks_dir / task_id

    def _contract(self, task_id: str) -> dict[str, Any]:
        contract = _load(self._task_dir(task_id) / "contract.json")
        try:
            validate_task_contract(contract, self.root)
        except ContractError as exc:
            raise OrchestrationRuntimeError(f"stored task contract invalid: {exc}") from exc
        return contract

    def _records(self, task_id: str) -> list[dict[str, Any]]:
        directory = self._task_dir(task_id) / "records"
        if not directory.exists():
            return []
        output: list[dict[str, Any]] = []
        previous = ZERO_HASH
        for sequence, path in enumerate(sorted(directory.glob("*.json")), start=1):
            record = _load(path)
            if record.get("task_id") != task_id or record.get("sequence") != sequence:
                raise OrchestrationRuntimeError("runtime record identity or sequence invalid")
            if record.get("previous_record_sha256") != previous:
                raise OrchestrationRuntimeError("runtime record hash chain broken")
            if record.get("record_sha256") != _hash_record(record):
                raise OrchestrationRuntimeError("runtime record hash invalid")
            previous = record["record_sha256"]
            output.append(record)
        return output

    def _append(self, task_id: str, kind: str, now_epoch: int, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(now_epoch, int) or now_epoch < 0:
            raise OrchestrationRuntimeError("time must be a non-negative integer")
        records = self._records(task_id)
        sequence = len(records) + 1
        record = {
            "schema": 1,
            "record_id": f"{task_id}.{sequence:08d}",
            "task_id": task_id,
            "sequence": sequence,
            "kind": kind,
            "observed_at_epoch": now_epoch,
            "previous_record_sha256": records[-1]["record_sha256"] if records else ZERO_HASH,
            "payload": payload,
        }
        record["record_sha256"] = _hash_record(record)
        path = self._task_dir(task_id) / "records" / f"{sequence:08d}.json"
        # Exclusive creation, not exists-then-write: the gap between the two is
        # exactly where a concurrent appender computed the same sequence and
        # overwrote this record.
        _exclusive_json(path, record)
        return record

    def _state(self, task_id: str) -> str:
        records = self._records(task_id)
        transitions = [item for item in records if item.get("kind") == "transition"]
        if not transitions:
            raise OrchestrationRuntimeError("task has no lifecycle state")
        return transitions[-1]["payload"]["next_state"]

    def _transition(
        self,
        task_id: str,
        next_state: str,
        actor_type: str,
        actor_id: str,
        now_epoch: int,
        reason_code: str,
        evidence_refs: list[str],
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        previous = None
        records = self._records(task_id)
        transitions = [item for item in records if item.get("kind") == "transition"]
        if transitions:
            previous = transitions[-1]["payload"]["next_state"]
        try:
            validate_transition(previous, next_state, self.root)
        except OrchestrationError as exc:
            raise OrchestrationRuntimeError(str(exc)) from exc
        self._validate_actor(actor_type, actor_id)
        payload = {
            "previous_state": previous,
            "next_state": next_state,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "reason_code": reason_code,
            "evidence_refs": _strings(evidence_refs, "evidence_refs"),
        }
        if extra:
            # Persisted inside the same hash-chained record, so a completion's
            # authorization proof is durable and tamper-evident.
            payload.update(extra)
        self._append(task_id, "transition", now_epoch, payload)
        return self.task_snapshot(task_id, now_epoch)

    def _validate_actor(self, actor_type: str, actor_id: str) -> None:
        if actor_type == "owner" and actor_id == "owner-gev":
            return
        if actor_type == "bro" and actor_id == "bro-000":
            return
        if actor_type == "system" and isinstance(actor_id, str) and actor_id.startswith("system-"):
            return
        if actor_type == "agent":
            try:
                if actor_id in all_agent_identities(self.root):
                    return
            except IdentityError as exc:
                raise OrchestrationRuntimeError(str(exc)) from exc
        raise OrchestrationRuntimeError("actor identity is not canonical")

    def create_task(
        self,
        contract: dict[str, Any],
        *,
        queue_class: str = "standard",
        now_epoch: int,
        budget_limits: dict[str, dict[str, int | None]] | None = None,
    ) -> dict[str, Any]:
        try:
            validate_task_contract(contract, self.root)
        except ContractError as exc:
            raise OrchestrationRuntimeError(str(exc)) from exc
        task_id = contract.get("task_id")
        directory = self._task_dir(task_id)
        if directory.exists():
            raise OrchestrationRuntimeError("task already exists")
        if queue_class not in self.queue:
            raise OrchestrationRuntimeError("unknown queue class")
        limits = self._validate_budget_limits(budget_limits or {})
        _atomic_json(directory / "contract.json", contract)
        self._append(task_id, "runtime-config", now_epoch, {"queue_class": queue_class, "budget_limits": limits})
        self._transition(task_id, "draft", "bro", "bro-000", now_epoch, "task-created", [])
        return self._transition(task_id, "queued", "bro", "bro-000", now_epoch, "queued-for-routing", [])

    def _validate_budget_limits(self, limits: dict[str, dict[str, int | None]]) -> dict[str, dict[str, int | None]]:
        supported = set(self.registry["budget_policy"]["supported_dimensions"])
        output: dict[str, dict[str, int | None]] = {}
        for dimension, value in limits.items():
            if dimension not in supported or not isinstance(value, dict) or set(value) != {"soft", "hard"}:
                raise OrchestrationRuntimeError("invalid budget limits")
            soft, hard = value["soft"], value["hard"]
            if any(item is not None and (not isinstance(item, int) or item <= 0) for item in (soft, hard)):
                raise OrchestrationRuntimeError("invalid budget value")
            if soft is not None and hard is not None and soft > hard:
                raise OrchestrationRuntimeError("soft budget exceeds hard budget")
            output[dimension] = {"soft": soft, "hard": hard}
        return output

    def _config(self, task_id: str) -> dict[str, Any]:
        records = self._records(task_id)
        configs = [item for item in records if item.get("kind") == "runtime-config"]
        if len(configs) != 1:
            raise OrchestrationRuntimeError("runtime config missing or duplicated")
        return configs[0]["payload"]

    # --- Claim serialization and execution leases -------------------------------
    #
    # These used to live only in DurableOrchestrationRuntimeV1, which made safety
    # opt-in via subclass choice: the base class — public, importable — granted
    # authority to an expired or released lease and let two processes double-claim.
    # The guard and the lease are the base contract now; the V1 subclass keeps its
    # richer API (renew/release/recover/reconcile) on top of the same machinery.

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

    def _guard_held_by_this_process(self) -> bool:
        """True when the claim lock is currently held by THIS process.

        The lock payload records its holder's pid, so a wrapper that already
        acquired the guard (the V1 runtime's lease-checked entry points) can be
        told apart from an unrelated holder in another process. The check is
        process-granular, matching the file lock itself.
        """
        try:
            payload = json.loads(self.claim_lock.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, AttributeError):
            return False
        return isinstance(payload, dict) and payload.get("pid") == os.getpid()

    @contextlib.contextmanager
    def _mutation_guard(self) -> Iterator[None]:
        """The claim guard, reentrant per process.

        The base mutation methods must hold the guard themselves so a direct
        base-class caller is serialized, but a V1 wrapper already holds it when
        it delegates here — the file lock is not reentrant and re-acquiring
        would deadlock the wrapped call until timeout.
        """
        if self._guard_held_by_this_process():
            yield
            return
        with self._claim_guard():
            yield

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

        The assignee check asks whether you were ever the right agent for this
        task. That stays true after the lease expires, after it is released, and
        after a recovery that issued none, so it answers a question nobody was
        asking. Only the lease says whether you are authorised right now.
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

    def _enforce_execution_authority(self, task_id: str, actor_id: str,
                                     lease_id: str | None, now_epoch: int) -> None:
        """Deny any assignee mutation that does not ride an active claim lease.

        Every path — base class or subclass — now requires the task to hold an
        active, unexpired, unreleased lease for the acting agent; an expired or
        released claim is denied everywhere, not only in the V1 wrapper. When
        the caller offers a lease_id it must additionally be THE active lease
        (the V1 entry points always do); a wrapper that already validated its
        lease may delegate here without repeating the id.
        """
        if lease_id is not None:
            self._require_lease(task_id, actor_id, lease_id, now_epoch)
            return
        active = self._active_lease(task_id, now_epoch)
        if active is None or active.get("agent_id") != actor_id:
            raise OrchestrationRuntimeError("claim lease is missing, expired, or mismatched")

    def claim_next(self, agent_id: str, *, now_epoch: int,
                   lease_seconds: int = DEFAULT_LEASE_SECONDS) -> dict[str, Any] | None:
        self._validate_actor("agent", agent_id)
        if not isinstance(now_epoch, int) or now_epoch < 0:
            raise OrchestrationRuntimeError("time must be a non-negative integer")
        if not isinstance(lease_seconds, int) or not 1 <= lease_seconds <= MAX_LEASE_SECONDS:
            raise OrchestrationRuntimeError("lease duration invalid")
        with self._mutation_guard():
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
            lease_id = self._mint_lease(task_id, agent_id, now_epoch, lease_seconds)
            self._transition(task_id, "routing", "bro", "bro-000", now_epoch, "routing-started", [])
            snapshot = self._transition(task_id, "running", "agent", agent_id, now_epoch, "execution-started", [])
            snapshot["lease_id"] = lease_id
            snapshot["lease_expires_at_epoch"] = now_epoch + lease_seconds
            return snapshot

    def checkpoint(
        self,
        task_id: str,
        *,
        actor_id: str,
        now_epoch: int,
        completed_criteria: list[str],
        open_risks: list[str],
        next_action: str,
        evidence_refs: list[str],
        lease_id: str | None = None,
    ) -> dict[str, Any]:
        with self._mutation_guard():
            self._enforce_execution_authority(task_id, actor_id, lease_id, now_epoch)
            if self._state(task_id) != "running":
                raise OrchestrationRuntimeError("checkpoint requires running task")
            self._validate_actor("agent", actor_id)
            contract = self._contract(task_id)
            if contract.get("agent_id") != actor_id:
                raise OrchestrationRuntimeError("checkpoint actor is not task assignee")
            if not isinstance(next_action, str) or not next_action:
                raise OrchestrationRuntimeError("next_action required")
            evidence = _strings(evidence_refs, "evidence_refs", required=True)
            payload = {
                "actor_id": actor_id,
                "completed_criteria": _strings(completed_criteria, "completed_criteria", required=True),
                "open_risks": _strings(open_risks, "open_risks", required=True),
                "next_action": next_action,
                "evidence_refs": evidence,
            }
            self._append(task_id, "checkpoint", now_epoch, payload)
            return self.task_snapshot(task_id, now_epoch)

    def record_usage(
        self,
        task_id: str,
        *,
        actor_id: str,
        now_epoch: int,
        delta: dict[str, int],
        evidence_refs: list[str],
        lease_id: str | None = None,
    ) -> dict[str, Any]:
        with self._mutation_guard():
            self._enforce_execution_authority(task_id, actor_id, lease_id, now_epoch)
            if self._state(task_id) != "running":
                raise OrchestrationRuntimeError("usage requires running task")
            self._validate_actor("agent", actor_id)
            supported = set(self.registry["budget_policy"]["supported_dimensions"])
            if not isinstance(delta, dict) or not delta:
                raise OrchestrationRuntimeError("usage delta required")
            if any(key not in supported or not isinstance(value, int) or value <= 0 for key, value in delta.items()):
                raise OrchestrationRuntimeError("usage delta invalid")
            evidence = _strings(evidence_refs, "evidence_refs", required=True)
            self._append(task_id, "usage", now_epoch, {"actor_id": actor_id, "delta": delta, "evidence_refs": evidence})
            totals = self._usage_totals(task_id)
            limits = self._config(task_id)["budget_limits"]
            hard = any(limits.get(key, {}).get("hard") is not None and totals[key] > limits[key]["hard"] for key in totals)
            soft = any(limits.get(key, {}).get("soft") is not None and totals[key] > limits[key]["soft"] for key in totals)
            if hard or soft:
                # The budget gate is taking the task out of running, so it takes
                # the execution authority with it: a lease left active here would
                # block the re-claim after an owner-approved retry until it
                # happened to expire, and would keep asserting an authority the
                # lifecycle just withdrew.
                active = self._active_lease(task_id, now_epoch)
                if active is not None:
                    self._append(task_id, "claim-released", now_epoch,
                                 {"lease_id": active["lease_id"], "reason": "budget-exceeded"})
            if hard:
                return self._transition(task_id, "blocked", "system", "system-budget", now_epoch, "budget-exceeded", evidence)
            if soft:
                return self._transition(task_id, "waiting-approval", "system", "system-budget", now_epoch, "budget-exceeded", evidence)
            return self.task_snapshot(task_id, now_epoch)

    def _usage_totals(self, task_id: str) -> dict[str, int]:
        totals: dict[str, int] = {}
        for record in self._records(task_id):
            if record.get("kind") != "usage":
                continue
            for key, value in record["payload"]["delta"].items():
                totals[key] = totals.get(key, 0) + value
        return totals

    def retry_blocked(self, task_id: str, *, owner_id: str, now_epoch: int, evidence_refs: list[str]) -> dict[str, Any]:
        if self._state(task_id) not in {"blocked", "waiting-approval"}:
            raise OrchestrationRuntimeError("retry requires blocked or waiting-approval state")
        self._validate_actor("owner", owner_id)
        return self._transition(task_id, "queued", "owner", owner_id, now_epoch, "retry-approved", _strings(evidence_refs, "evidence_refs", required=True))

    def cancel_task(
        self,
        task_id: str,
        *,
        actor_type: str,
        actor_id: str,
        now_epoch: int,
        effect_in_flight: bool,
        evidence_refs: list[str],
    ) -> dict[str, Any]:
        state = self._state(task_id)
        if state in TERMINAL:
            raise OrchestrationRuntimeError("terminal task is immutable")
        self._validate_actor(actor_type, actor_id)
        evidence = _strings(evidence_refs, "evidence_refs")
        if effect_in_flight:
            if not evidence:
                raise OrchestrationRuntimeError("in-flight cancellation requires evidence")
            return self._transition(task_id, "recovery-required", actor_type, actor_id, now_epoch, "recovery-required", evidence)
        return self._transition(task_id, "cancelled", actor_type, actor_id, now_epoch, "task-cancelled", evidence)

    def recover_task(self, task_id: str, *, owner_id: str, now_epoch: int, evidence_refs: list[str],
                     lease_seconds: int = DEFAULT_LEASE_SECONDS) -> dict[str, Any]:
        """Recovery hands back authority, not just state: with mutations now
        lease-gated in the base class, a recovery that issued no lease would land
        the task in running with nobody authorised to touch it. A wrapper that
        already holds the guard (the V1 runtime) mints its own lease after this
        returns, so the base mints only for direct callers."""
        delegated = self._guard_held_by_this_process()
        if not isinstance(lease_seconds, int) or not 1 <= lease_seconds <= MAX_LEASE_SECONDS:
            raise OrchestrationRuntimeError("lease duration invalid")
        with self._mutation_guard():
            if self._state(task_id) != "recovery-required":
                raise OrchestrationRuntimeError("recovery proof requires recovery-required state")
            self._validate_actor("owner", owner_id)
            snapshot = self._transition(task_id, "running", "owner", owner_id, now_epoch, "recovery-proved", _strings(evidence_refs, "evidence_refs", required=True))
            if not delegated:
                lease_id = self._mint_lease(
                    task_id, self._contract(task_id)["agent_id"], now_epoch, lease_seconds)
                snapshot["lease_id"] = lease_id
                snapshot["lease_expires_at_epoch"] = now_epoch + lease_seconds
            return snapshot

    def _resolve_evidence(self, task_id: str, evidence_refs: list[str]) -> None:
        """Make the assignee's evidence references mean something.

        `_strings` only proved they were non-empty and unique. Nothing opened
        them, so `evidence_refs=["nope"]` completed a task. Resolving them
        against the signed chain is what turns a claim into evidence, and the
        chain must be whole: a prefix that omits the failure is not a shorter
        proof, it is a different story.
        """
        if self.evidence_keys is None or self.evidence_store is None:
            raise OrchestrationRuntimeError(
                "completion requires an evidence verifier; this runtime was "
                "constructed without one and cannot check what it is asserting")
        try:
            validate_chain(task_id, evidence_refs, self.evidence_keys,
                           store=self.evidence_store)
        except EvidenceError as exc:
            raise OrchestrationRuntimeError(f"completion evidence RED: {exc}") from exc

    def submit_for_verification(self, task_id: str, *, actor_id: str, now_epoch: int,
                                evidence_refs: list[str],
                                lease_id: str | None = None) -> dict[str, Any]:
        """running -> verification.

        The state machine has always allowed this edge and nothing ever took it,
        so `verification` was a state the registry declared and the runtime never
        entered. A task needing an independent verdict went straight from the
        builder's hands to completed.
        """
        with self._mutation_guard():
            self._enforce_execution_authority(task_id, actor_id, lease_id, now_epoch)
            if self._state(task_id) != "running":
                raise OrchestrationRuntimeError("verification requires running task")
            contract = self._contract(task_id)
            if contract.get("agent_id") != actor_id:
                raise OrchestrationRuntimeError("submitting actor is not task assignee")
            refs = _strings(evidence_refs, "evidence_refs", required=True)
            self._resolve_evidence(task_id, refs)
            return self._transition(task_id, "verification", "agent", actor_id, now_epoch,
                                    "verification-requested", refs)

    def complete_task(self, task_id: str, *, actor_id: str, now_epoch: int, evidence_refs: list[str],
                      completion_manifest: dict[str, Any] | None = None,
                      verifier_receipt: dict[str, Any] | None = None,
                      lease_id: str | None = None) -> dict[str, Any]:
        with self._mutation_guard():
            self._enforce_execution_authority(task_id, actor_id, lease_id, now_epoch)
            return self._complete_task_locked(
                task_id, actor_id=actor_id, now_epoch=now_epoch,
                evidence_refs=evidence_refs, completion_manifest=completion_manifest,
                verifier_receipt=verifier_receipt)

    def _complete_task_locked(self, task_id: str, *, actor_id: str, now_epoch: int,
                              evidence_refs: list[str],
                              completion_manifest: dict[str, Any] | None,
                              verifier_receipt: dict[str, Any] | None) -> dict[str, Any]:
        state = self._state(task_id)
        contract = self._contract(task_id)
        verification = contract.get("verification") or {}
        extra: dict[str, Any] | None = None
        if verification.get("required") is True:
            # The contract said an independent verdict was required and the
            # runtime never asked for one: it read that field at write time and
            # ignored it at the only moment it mattered. Reaching the verification
            # state is not the verdict; an independent verifier receipt is.
            if state != "verification":
                raise OrchestrationRuntimeError(
                    "this task requires independent verification; it must pass "
                    "through the verification state, not go straight to completed")
            proof = self._authorize_independent_completion(
                contract, actor_id, completion_manifest, verifier_receipt)
            # The refs recorded are the verified manifest's evidence, not whatever
            # the caller passed, and the authorization proof is persisted in the
            # same hash-chained transition so a later audit can re-verify it even if
            # the evidence store is gone.
            refs = list(proof["evidence_event_ids"])
            extra = {"completion_proof": proof}
        else:
            if state != "running":
                raise OrchestrationRuntimeError("completion requires running task")
            refs = _strings(evidence_refs, "evidence_refs", required=True)
            self._resolve_evidence(task_id, refs)
        if contract.get("agent_id") != actor_id:
            raise OrchestrationRuntimeError("completion actor is not task assignee")
        return self._transition(task_id, "completed", "agent", actor_id, now_epoch,
                                "task-completed", refs, extra=extra)

    def _authorize_independent_completion(self, contract: dict[str, Any], actor_id: str,
                                          completion_manifest: dict[str, Any] | None,
                                          verifier_receipt: dict[str, Any] | None) -> dict[str, Any]:
        """A verification-required task may complete only on an independent
        verifier-signed GREEN receipt (builder != verifier), matching the Stop gate.
        The runtime checks it in-process with its own trusted keys and evidence store
        and its OWN clock (now=None) — the caller cannot rewind time to revive an
        expired or future-issued receipt. Returns the authorization proof to persist."""
        if self.evidence_keys is None or self.evidence_store is None:
            raise OrchestrationRuntimeError(
                "completion verification requires evidence keys and an evidence store")
        from bro_completion import CompletionError, authorize_completion_docs
        try:
            _manifest, _task_hash, proof = authorize_completion_docs(
                contract, actor_id, manifest_doc=completion_manifest,
                receipt_doc=verifier_receipt, keys=self.evidence_keys,
                evidence_store=self.evidence_store, root=self.root, now=None)
        except CompletionError as exc:
            raise OrchestrationRuntimeError(f"completion verification RED: {exc}") from exc
        return proof

    def task_snapshot(self, task_id: str, now_epoch: int) -> dict[str, Any]:
        records = self._records(task_id)
        state = self._state(task_id)
        checkpoints = [item for item in records if item.get("kind") == "checkpoint"]
        last = checkpoints[-1] if checkpoints else None
        observed = last["observed_at_epoch"] if last else records[-1]["observed_at_epoch"]
        max_age = self.registry["checkpoint_policy"]["max_age_seconds"]
        return {
            "task_id": task_id,
            "state": state,
            "queue_class": self._config(task_id)["queue_class"],
            "usage": self._usage_totals(task_id),
            "last_checkpoint": last["payload"] if last else None,
            "stale": now_epoch - observed > max_age,
            "record_count": len(records),
            "record_head_sha256": records[-1]["record_sha256"],
        }

    def control_room_snapshot(self, *, now_epoch: int) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        for directory in sorted(self.tasks_dir.iterdir()):
            if not directory.is_dir():
                continue
            for record in self._records(directory.name):
                if record.get("kind") != "transition":
                    continue
                payload = record["payload"]
                events.append({
                    "schema": 1,
                    "event_id": record["record_id"],
                    "task_id": directory.name,
                    "sequence": len([item for item in events if item["task_id"] == directory.name]) + 1,
                    "previous_state": payload["previous_state"],
                    "next_state": payload["next_state"],
                    "actor_type": payload["actor_type"],
                    "actor_id": payload["actor_id"],
                    "observed_at_epoch": record["observed_at_epoch"],
                    "reason_code": payload["reason_code"],
                    "evidence_refs": payload["evidence_refs"],
                    "repository_binding": None,
                    "correlation_id": directory.name,
                })
        projection = build_control_room_projection(events, now_epoch, self.root)
        projection["source"] = str(self.state_dir)
        projection["source_sha256"] = hashlib.sha256(_canonical({"events": events})).hexdigest()
        return projection

    def integrity_report(self) -> dict[str, Any]:
        heads: dict[str, str] = {}
        for directory in sorted(self.tasks_dir.iterdir()):
            if not directory.is_dir():
                continue
            records = self._records(directory.name)
            heads[directory.name] = records[-1]["record_sha256"]
        return {
            "schema": 1,
            "tasks": len(heads),
            "heads": heads,
            "root_sha256": hashlib.sha256(_canonical(heads)).hexdigest(),
        }
