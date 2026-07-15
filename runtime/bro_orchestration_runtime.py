from __future__ import annotations

import hashlib
import json
import os
import pathlib
import tempfile
from typing import Any

from bro_contracts import ContractError, validate_task_contract
from bro_identity import IdentityError, all_agent_identities
from bro_orchestration import OrchestrationError, build_control_room_projection, validate_transition

ROOT = pathlib.Path(__file__).resolve().parents[1]
ZERO_HASH = "0" * 64
TERMINAL = {"completed", "failed", "cancelled"}


class OrchestrationRuntimeError(ValueError):
    pass


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash_record(record: dict[str, Any]) -> str:
    unsigned = dict(record)
    unsigned.pop("record_sha256", None)
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def _atomic_json(path: pathlib.Path, value: dict[str, Any]) -> None:
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

    def __init__(self, state_dir: pathlib.Path | str, root: pathlib.Path = ROOT):
        self.root = pathlib.Path(root).resolve()
        self.state_dir = pathlib.Path(state_dir).resolve()
        self.tasks_dir = self.state_dir / "tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
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
        if path.exists():
            raise OrchestrationRuntimeError("record sequence already exists")
        _atomic_json(path, record)
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

    def claim_next(self, agent_id: str, *, now_epoch: int) -> dict[str, Any] | None:
        self._validate_actor("agent", agent_id)
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
            config = self._config(task_id)
            first = self._records(task_id)[0]["observed_at_epoch"]
            candidates.append((-self.queue[config["queue_class"]], first, task_id))
        if not candidates:
            return None
        _, _, task_id = sorted(candidates)[0]
        self._transition(task_id, "routing", "bro", "bro-000", now_epoch, "routing-started", [])
        return self._transition(task_id, "running", "agent", agent_id, now_epoch, "execution-started", [])

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
    ) -> dict[str, Any]:
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
    ) -> dict[str, Any]:
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

    def recover_task(self, task_id: str, *, owner_id: str, now_epoch: int, evidence_refs: list[str]) -> dict[str, Any]:
        if self._state(task_id) != "recovery-required":
            raise OrchestrationRuntimeError("recovery proof requires recovery-required state")
        self._validate_actor("owner", owner_id)
        return self._transition(task_id, "running", "owner", owner_id, now_epoch, "recovery-proved", _strings(evidence_refs, "evidence_refs", required=True))

    def complete_task(self, task_id: str, *, actor_id: str, now_epoch: int, evidence_refs: list[str]) -> dict[str, Any]:
        if self._state(task_id) != "running":
            raise OrchestrationRuntimeError("completion requires running task")
        contract = self._contract(task_id)
        if contract.get("agent_id") != actor_id:
            raise OrchestrationRuntimeError("completion actor is not task assignee")
        return self._transition(task_id, "completed", "agent", actor_id, now_epoch, "task-completed", _strings(evidence_refs, "evidence_refs", required=True))

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
