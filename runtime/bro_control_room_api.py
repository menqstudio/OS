from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any

from bro_identity import IdentityError, all_agent_identities
from bro_orchestration import OrchestrationError, validate_control_room_command
from bro_orchestration_runtime import DurableOrchestrationRuntime, OrchestrationRuntimeError

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")
FORBIDDEN_SCOPE = {"credential", "deploy", "git", "production", "release", "repository", "brops"}


class ControlRoomAPIError(ValueError):
    pass


def _sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _strings(value: Any, field: str, required: bool = False) -> list[str]:
    if not isinstance(value, list) or (required and not value):
        raise ControlRoomAPIError(f"{field} must be a list")
    if not all(isinstance(x, str) and x.strip() for x in value):
        raise ControlRoomAPIError(f"{field} must contain non-empty strings")
    out = [x.strip() for x in value]
    if len(out) != len(set(out)):
        raise ControlRoomAPIError(f"{field} contains duplicates")
    return out


class ControlRoomAPIV1:
    """Read-only, integrity-bound views over Orchestration Runtime V1."""

    def __init__(self, runtime: DurableOrchestrationRuntime):
        if not isinstance(runtime, DurableOrchestrationRuntime):
            raise ControlRoomAPIError("runtime must be DurableOrchestrationRuntime")
        self.runtime = runtime
        self.root = runtime.root
        self.registry = runtime.registry

    @staticmethod
    def _now(value: int) -> int:
        if not isinstance(value, int) or value < 0:
            raise ControlRoomAPIError("time must be a non-negative integer")
        return value

    def _ids(self) -> list[str]:
        try:
            return sorted(p.name for p in self.runtime.tasks_dir.iterdir() if p.is_dir())
        except OSError as exc:
            raise ControlRoomAPIError(f"runtime task directory unreadable: {exc}") from exc

    def _call(self, function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (OrchestrationRuntimeError, OrchestrationError, OSError) as exc:
            raise ControlRoomAPIError(str(exc)) from exc

    def _contract(self, task_id: str) -> dict[str, Any]:
        return self._call(self.runtime._contract, task_id)

    def _records(self, task_id: str) -> list[dict[str, Any]]:
        records = self._call(self.runtime._records, task_id)
        if not records:
            raise ControlRoomAPIError("task has no runtime records")
        return records

    def _snapshot(self, task_id: str, now: int) -> dict[str, Any]:
        return self._call(self.runtime.task_snapshot, task_id, now)

    def _integrity(self) -> dict[str, Any]:
        report = self._call(self.runtime.integrity_report)
        if not re.fullmatch(r"[0-9a-f]{64}", str(report.get("root_sha256", ""))):
            raise ControlRoomAPIError("runtime integrity root invalid")
        return report

    def _snapshots(self, now: int) -> dict[str, dict[str, Any]]:
        return {task_id: self._snapshot(task_id, now) for task_id in self._ids()}

    def _meta(self, view: str, now: int, integrity: dict, tasks: list[str], stale: list[str]) -> dict:
        return {
            "schema": 1,
            "view": view,
            "generated_at_epoch": now,
            "source": {
                "runtime_state_dir": str(self.runtime.state_dir),
                "orchestration_sst": "orchestration/registry.json",
            },
            "freshness": {
                "max_age_seconds": self.registry["checkpoint_policy"]["max_age_seconds"],
                "stale": bool(stale),
                "stale_task_ids": sorted(stale),
            },
            "integrity": integrity,
            "source_integrity_sha256": integrity["root_sha256"],
            "drill_down": {"available": bool(tasks), "task_ids": sorted(tasks)},
        }

    @staticmethod
    def _evidence(records: list[dict]) -> list[str]:
        refs: set[str] = set()
        for record in records:
            value = record.get("payload", {}).get("evidence_refs")
            if isinstance(value, list):
                refs.update(x for x in value if isinstance(x, str) and x)
        return sorted(refs)

    def mission_overview(self, *, now_epoch: int) -> dict[str, Any]:
        now = self._now(now_epoch)
        integrity = self._integrity()
        projection = self._call(self.runtime.control_room_snapshot, now_epoch=now)
        snapshots = self._snapshots(now)
        ids = sorted(snapshots)
        stale = [x for x, s in snapshots.items() if s["stale"]]
        queues = Counter(s["queue_class"] for s in snapshots.values())
        agents = Counter(self._contract(x)["agent_id"] for x in ids)
        out = self._meta("mission-overview", now, integrity, ids, stale)
        out.update({
            "health": projection["health"],
            "task_count": len(ids),
            "state_counts": projection["state_counts"],
            "queue_counts": {x: queues.get(x, 0) for x in self.runtime.queue},
            "agent_workload_counts": dict(sorted(agents.items())),
            "approval_count": sum(s["state"] in {"awaiting-approval", "waiting-approval"} for s in snapshots.values()),
            "recovery_count": sum(s["state"] in {"recovery-required", "quarantined"} for s in snapshots.values()),
            "tasks": projection["tasks"],
        })
        return out

    def queue_state(self, *, now_epoch: int) -> dict[str, Any]:
        now = self._now(now_epoch)
        integrity = self._integrity()
        tasks = []
        for task_id, snap in self._snapshots(now).items():
            queue = snap["queue_class"]
            policy = next(x for x in self.registry["queue_classes"] if x["id"] == queue)
            tasks.append({
                "task_id": task_id,
                "state": snap["state"],
                "queue_class": queue,
                "priority": policy["priority"],
                "preemptible": policy["preemptible"],
                "agent_id": self._contract(task_id)["agent_id"],
                "stale": snap["stale"],
            })
        tasks.sort(key=lambda x: (-x["priority"], x["task_id"]))
        out = self._meta("queue-state", now, integrity, [x["task_id"] for x in tasks], [x["task_id"] for x in tasks if x["stale"]])
        out.update({"queue_classes": list(self.registry["queue_classes"]), "tasks": tasks})
        return out

    def agent_workload(self, *, now_epoch: int, agent_id: str | None = None) -> dict[str, Any]:
        now = self._now(now_epoch)
        integrity = self._integrity()
        try:
            identities = all_agent_identities(self.root)
        except IdentityError as exc:
            raise ControlRoomAPIError(str(exc)) from exc
        if agent_id is not None and agent_id not in identities:
            raise ControlRoomAPIError("agent identity is not canonical")
        snapshots = self._snapshots(now)
        selected = [agent_id] if agent_id else sorted({self._contract(x)["agent_id"] for x in snapshots})
        agents, tasks, stale = [], [], []
        for identity in selected:
            pack, role = identities[identity]
            assigned = []
            for task_id, snap in snapshots.items():
                if self._contract(task_id)["agent_id"] == identity:
                    item = {"task_id": task_id, "state": snap["state"], "queue_class": snap["queue_class"], "stale": snap["stale"]}
                    assigned.append(item)
                    tasks.append(task_id)
                    if snap["stale"]:
                        stale.append(task_id)
            assigned.sort(key=lambda x: x["task_id"])
            agents.append({
                "agent_id": identity,
                "pack_id": pack,
                "role": role,
                "task_count": len(assigned),
                "state_counts": dict(sorted(Counter(x["state"] for x in assigned).items())),
                "tasks": assigned,
            })
        out = self._meta("agent-workload", now, integrity, tasks, stale)
        out["agents"] = agents
        return out

    def checkpoint_status(self, task_id: str, *, now_epoch: int) -> dict[str, Any]:
        now = self._now(now_epoch)
        integrity = self._integrity()
        snap = self._snapshot(task_id, now)
        checkpoints = [
            {"record_id": r["record_id"], "observed_at_epoch": r["observed_at_epoch"], **r["payload"]}
            for r in self._records(task_id) if r["kind"] == "checkpoint"
        ]
        out = self._meta("checkpoint-status", now, integrity, [task_id], [task_id] if snap["stale"] else [])
        out.update({"task_id": task_id, "state": snap["state"], "last_checkpoint": checkpoints[-1] if checkpoints else None, "checkpoints": checkpoints})
        return out

    def budget_status(self, task_id: str, *, now_epoch: int) -> dict[str, Any]:
        now = self._now(now_epoch)
        integrity = self._integrity()
        snap = self._snapshot(task_id, now)
        limits = self._call(self.runtime._config, task_id)["budget_limits"]
        dimensions = []
        for name in self.registry["budget_policy"]["supported_dimensions"]:
            used = snap["usage"].get(name, 0)
            limit = limits.get(name, {"soft": None, "hard": None})
            if limit["hard"] is not None and used > limit["hard"]:
                status = "hard-exceeded"
            elif limit["soft"] is not None and used > limit["soft"]:
                status = "soft-exceeded"
            elif limit["soft"] is None and limit["hard"] is None:
                status = "unbounded"
            else:
                status = "within-limit"
            dimensions.append({"dimension": name, "used": used, "soft": limit["soft"], "hard": limit["hard"], "status": status})
        out = self._meta("budget-status", now, integrity, [task_id], [task_id] if snap["stale"] else [])
        out.update({"task_id": task_id, "state": snap["state"], "dimensions": dimensions})
        return out

    def approval_inbox(self, *, now_epoch: int) -> dict[str, Any]:
        now = self._now(now_epoch)
        integrity = self._integrity()
        approvals, stale = [], []
        for task_id, snap in self._snapshots(now).items():
            if snap["state"] not in {"awaiting-approval", "waiting-approval"}:
                continue
            latest = [r for r in self._records(task_id) if r["kind"] == "transition"][-1]
            approvals.append({
                "task_id": task_id,
                "state": snap["state"],
                "risk": self._contract(task_id)["risk"],
                "requested_at_epoch": latest["observed_at_epoch"],
                "expires_at_epoch": None,
                "expiry_status": "not-modeled-by-runtime-v1",
                "evidence_refs": list(latest["payload"].get("evidence_refs", [])),
                "allowed_commands": [x["id"] for x in self.registry["commands"] if snap["state"] in x["allowed_states"] and "owner" in x["actors"]],
            })
            if snap["stale"]:
                stale.append(task_id)
        approvals.sort(key=lambda x: (x["requested_at_epoch"], x["task_id"]))
        out = self._meta("approval-inbox", now, integrity, [x["task_id"] for x in approvals], stale)
        out["approvals"] = approvals
        return out

    def recovery_quarantine(self, *, now_epoch: int) -> dict[str, Any]:
        now = self._now(now_epoch)
        integrity = self._integrity()
        items, stale = [], []
        for task_id, snap in self._snapshots(now).items():
            if snap["state"] not in {"recovery-required", "quarantined"}:
                continue
            latest = [r for r in self._records(task_id) if r["kind"] == "transition"][-1]
            items.append({
                "task_id": task_id,
                "state": snap["state"],
                "original_state": latest["payload"].get("previous_state"),
                "observed_effect": None,
                "observed_effect_status": "not-modeled-by-runtime-v1",
                "proof_refs": list(latest["payload"].get("evidence_refs", [])),
                "ambiguity": snap["state"] == "quarantined",
                "allowed_actions": [x["id"] for x in self.registry["commands"] if snap["state"] in x["allowed_states"]],
            })
            if snap["stale"]:
                stale.append(task_id)
        items.sort(key=lambda x: x["task_id"])
        out = self._meta("recovery-quarantine", now, integrity, [x["task_id"] for x in items], stale)
        out["items"] = items
        return out

    def audit_timeline(self, task_id: str, *, now_epoch: int) -> dict[str, Any]:
        now = self._now(now_epoch)
        integrity = self._integrity()
        snap = self._snapshot(task_id, now)
        records = self._records(task_id)
        out = self._meta("audit-timeline", now, integrity, [task_id], [task_id] if snap["stale"] else [])
        out.update({"task_id": task_id, "record_count": len(records), "timeline_sha256": _sha({"task_id": task_id, "records": records}), "records": records})
        return out

    def task_detail(self, task_id: str, *, now_epoch: int) -> dict[str, Any]:
        now = self._now(now_epoch)
        integrity = self._integrity()
        snap = self._snapshot(task_id, now)
        contract = self._contract(task_id)
        records = self._records(task_id)
        config = self._call(self.runtime._config, task_id)
        transitions = [r for r in records if r["kind"] == "transition"]
        routing = [r for r in records if r["kind"] in {"claim-lease", "claim-released", "claim-expired"} or (r["kind"] == "transition" and r["payload"].get("next_state") in {"routing", "running"})]
        timeline = _sha({"task_id": task_id, "records": records})
        out = self._meta("task-detail", now, integrity, [task_id], [task_id] if snap["stale"] else [])
        out.update({
            "task_id": task_id,
            "contract": contract,
            "snapshot": snap,
            "queue": {"class": config["queue_class"], "policy": next(x for x in self.registry["queue_classes"] if x["id"] == config["queue_class"])},
            "routing": routing,
            "checkpoints": [r for r in records if r["kind"] == "checkpoint"],
            "budget": {"limits": config["budget_limits"], "usage": snap["usage"]},
            "approvals": [r for r in transitions if r["payload"].get("next_state") in {"awaiting-approval", "waiting-approval"}],
            "recovery": [r for r in transitions if r["payload"].get("next_state") in {"recovery-required", "quarantined"}],
            "evidence_refs": self._evidence(records),
            "audit": {"record_count": len(records), "timeline_sha256": timeline, "record_head_sha256": snap["record_head_sha256"]},
        })
        return out

    def validate_command_intent(self, command: dict[str, Any], *, now_epoch: int) -> dict[str, Any]:
        now = self._now(now_epoch)
        required = {"schema", "command_id", "task_id", "command", "requested_by_type", "requested_by", "requested_at_epoch", "expires_at_epoch", "expected_task_state", "scope", "reason", "evidence_refs"}
        if not isinstance(command, dict) or set(command) != required:
            raise ControlRoomAPIError("command fields do not match canonical schema")
        if command["schema"] != 1:
            raise ControlRoomAPIError("command schema must be 1")
        for field in ("command_id", "task_id"):
            if not isinstance(command[field], str) or not ID_RE.fullmatch(command[field]):
                raise ControlRoomAPIError(f"{field} format invalid")
        for field in ("command", "requested_by_type", "requested_by", "expected_task_state", "reason"):
            if not isinstance(command[field], str) or not command[field].strip():
                raise ControlRoomAPIError(f"{field} must be a non-empty string")
        scope = _strings(command["scope"], "scope", True)
        evidence = _strings(command["evidence_refs"], "evidence_refs")
        if any({x for x in re.split(r"[^a-z0-9]+", item.lower()) if x} & FORBIDDEN_SCOPE for item in scope):
            raise ControlRoomAPIError("command scope crosses a forbidden mutation boundary")
        actor = (command["requested_by_type"], command["requested_by"])
        if actor not in {("owner", "owner-gev"), ("bro", "bro-000")}:
            raise ControlRoomAPIError("command actor identity is not canonical")
        if command["scope"] != scope or command["evidence_refs"] != evidence:
            raise ControlRoomAPIError("command list values must already be normalized")
        snap = self._snapshot(command["task_id"], now)
        before = self._integrity()
        try:
            validate_control_room_command(command, snap["state"], now, self.root)
        except OrchestrationError as exc:
            raise ControlRoomAPIError(str(exc)) from exc
        if before != self._integrity():
            raise ControlRoomAPIError("command validation mutated runtime state")
        return {
            "schema": 1,
            "command_id": command["command_id"],
            "task_id": command["task_id"],
            "command": command["command"],
            "requested_by_type": actor[0],
            "requested_by": actor[1],
            "current_state": snap["state"],
            "validated_at_epoch": now,
            "valid": True,
            "executed": False,
            "mutation_authorized": False,
            "source_integrity_sha256": before["root_sha256"],
        }
