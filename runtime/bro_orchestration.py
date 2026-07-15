from __future__ import annotations

import json
import pathlib
from collections import Counter
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]


class OrchestrationError(ValueError):
    pass


def _load(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise OrchestrationError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OrchestrationError(f"{path} must contain an object")
    return value


def _unique_strings(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise OrchestrationError(f"{label} must be a list")
    if not all(isinstance(item, str) and item for item in value):
        raise OrchestrationError(f"{label} must contain strings")
    if len(value) != len(set(value)):
        raise OrchestrationError(f"{label} contains duplicates")
    return list(value)


def validate_orchestration_registry(root: pathlib.Path = ROOT) -> dict[str, int]:
    registry = _load(root / "orchestration" / "registry.json")
    if registry.get("schema") != 1:
        raise OrchestrationError("orchestration schema must be 1")

    states = _unique_strings(registry.get("states"), "states", nonempty=True)
    state_set = set(states)
    initial = registry.get("initial_state")
    terminals = set(_unique_strings(registry.get("terminal_states"), "terminal_states", nonempty=True))
    if initial not in state_set or not terminals <= state_set or initial in terminals:
        raise OrchestrationError("invalid initial or terminal states")

    transitions = registry.get("transitions")
    if not isinstance(transitions, dict) or set(transitions) != state_set:
        raise OrchestrationError("transitions must define every state")
    for source, targets in transitions.items():
        target_list = _unique_strings(targets, f"transitions.{source}")
        if not set(target_list) <= state_set:
            raise OrchestrationError(f"unknown transition target from {source}")
        if source in terminals and target_list:
            raise OrchestrationError(f"terminal state is mutable: {source}")
        if source in target_list:
            raise OrchestrationError(f"self transition forbidden: {source}")

    schema_registry = _load(root / "schemas" / "registry.json")
    registered = {
        item.get("path") for item in schema_registry.get("schemas", []) if isinstance(item, dict)
    }
    for key in ("event_schema", "command_schema"):
        path = registry.get(key)
        if path not in registered or not isinstance(path, str) or not (root / path).is_file():
            raise OrchestrationError(f"missing registered {key}")

    queue_classes = registry.get("queue_classes")
    if not isinstance(queue_classes, list) or not queue_classes:
        raise OrchestrationError("queue_classes required")
    queue_ids: set[str] = set()
    priorities: set[int] = set()
    for item in queue_classes:
        if not isinstance(item, dict):
            raise OrchestrationError("invalid queue class")
        queue_id, priority = item.get("id"), item.get("priority")
        if not isinstance(queue_id, str) or not queue_id or queue_id in queue_ids:
            raise OrchestrationError("invalid queue id")
        if not isinstance(priority, int) or priority <= 0 or priority in priorities:
            raise OrchestrationError("invalid queue priority")
        if not isinstance(item.get("preemptible"), bool):
            raise OrchestrationError("queue preemptible must be boolean")
        queue_ids.add(queue_id)
        priorities.add(priority)

    commands = registry.get("commands")
    if not isinstance(commands, list) or not commands:
        raise OrchestrationError("commands required")
    command_ids: set[str] = set()
    for item in commands:
        if not isinstance(item, dict):
            raise OrchestrationError("invalid command")
        command_id = item.get("id")
        actors = set(_unique_strings(item.get("actors"), f"{command_id}.actors", nonempty=True))
        allowed = set(_unique_strings(item.get("allowed_states"), f"{command_id}.states", nonempty=True))
        if not isinstance(command_id, str) or command_id in command_ids:
            raise OrchestrationError("duplicate command")
        if not actors <= {"owner", "bro"} or not allowed <= state_set:
            raise OrchestrationError(f"invalid command policy: {command_id}")
        if not isinstance(item.get("evidence_required"), bool):
            raise OrchestrationError("command evidence flag must be boolean")
        command_ids.add(command_id)

    surfaces = registry.get("control_room_surfaces")
    if not isinstance(surfaces, list) or not surfaces:
        raise OrchestrationError("Control Room surfaces required")
    surface_ids: set[str] = set()
    for surface in surfaces:
        if not isinstance(surface, dict):
            raise OrchestrationError("invalid Control Room surface")
        surface_id = surface.get("id")
        if not isinstance(surface_id, str) or surface_id in surface_ids:
            raise OrchestrationError("duplicate Control Room surface")
        _unique_strings(surface.get("read_models"), f"{surface_id}.read_models", nonempty=True)
        exposed = set(_unique_strings(surface.get("commands"), f"{surface_id}.commands"))
        if not exposed <= command_ids:
            raise OrchestrationError(f"surface exposes unknown command: {surface_id}")
        for flag in ("source_required", "freshness_required", "drilldown_required", "evidence_required"):
            if surface.get(flag) is not True:
                raise OrchestrationError(f"surface contract missing {flag}: {surface_id}")
        surface_ids.add(surface_id)

    rules = registry.get("rules")
    required_rules = {
        "unknown_state_is_not_green",
        "impossible_transition_is_denied",
        "terminal_states_are_immutable",
        "events_are_append_only",
        "ui_direct_repository_mutation_forbidden",
        "ui_direct_credential_access_forbidden",
        "ui_direct_release_mutation_forbidden",
    }
    if not isinstance(rules, dict) or not all(rules.get(key) is True for key in required_rules):
        raise OrchestrationError("orchestration safety rules changed")

    return {
        "states": len(states),
        "commands": len(command_ids),
        "surfaces": len(surface_ids),
        "queues": len(queue_ids),
    }


def validate_transition(previous_state: str | None, next_state: str, root: pathlib.Path = ROOT) -> None:
    registry = _load(root / "orchestration" / "registry.json")
    states = set(registry["states"])
    if next_state not in states:
        raise OrchestrationError(f"unknown state: {next_state}")
    if previous_state is None:
        if next_state != registry["initial_state"]:
            raise OrchestrationError("first state must be initial_state")
        return
    if previous_state not in states or next_state not in registry["transitions"][previous_state]:
        raise OrchestrationError(f"impossible transition denied: {previous_state} -> {next_state}")


def build_control_room_projection(events: list[dict[str, Any]], now_epoch: int, root: pathlib.Path = ROOT) -> dict[str, Any]:
    if not isinstance(events, list) or not isinstance(now_epoch, int) or now_epoch < 0:
        raise OrchestrationError("invalid projection input")
    registry = _load(root / "orchestration" / "registry.json")
    latest: dict[str, dict[str, Any]] = {}
    seen_events: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            raise OrchestrationError("event must be an object")
        event_id, task_id = event.get("event_id"), event.get("task_id")
        if not isinstance(event_id, str) or event_id in seen_events or not isinstance(task_id, str):
            raise OrchestrationError("invalid or duplicate event identity")
        validate_transition(event.get("previous_state"), event.get("next_state"), root)
        current = latest.get(task_id)
        if current is not None:
            if event.get("sequence") != current.get("sequence", 0) + 1:
                raise OrchestrationError("event sequence must be contiguous")
            if event.get("previous_state") != current.get("next_state"):
                raise OrchestrationError("event chain state mismatch")
        latest[task_id] = event
        seen_events.add(event_id)

    counts = Counter({state: 0 for state in registry["states"]})
    tasks = []
    max_age = registry["checkpoint_policy"]["max_age_seconds"]
    for task_id in sorted(latest):
        event = latest[task_id]
        state = event["next_state"]
        observed = event.get("observed_at_epoch")
        if not isinstance(observed, int):
            raise OrchestrationError("event time must be integer")
        stale = now_epoch - observed > max_age
        counts[state] += 1
        tasks.append({
            "task_id": task_id,
            "state": state,
            "sequence": event.get("sequence"),
            "stale": stale,
            "waiting_approval": state in {"awaiting-approval", "waiting-approval"},
            "recovery_open": state in {"recovery-required", "quarantined"},
            "evidence_refs": list(event.get("evidence_refs", [])),
        })

    if not tasks:
        health = "unknown"
    elif any(task["state"] == "quarantined" for task in tasks):
        health = "critical"
    elif any(task["stale"] or task["state"] in {"blocked", "failed", "recovery-required"} for task in tasks):
        health = "degraded"
    else:
        health = "healthy"
    return {
        "schema": 1,
        "source": "orchestration/registry.json",
        "generated_at_epoch": now_epoch,
        "health": health,
        "state_counts": {state: counts[state] for state in registry["states"]},
        "tasks": tasks,
    }


def validate_control_room_command(command: dict[str, Any], current_state: str, now_epoch: int, root: pathlib.Path = ROOT) -> None:
    if not isinstance(command, dict):
        raise OrchestrationError("command must be an object")
    registry = _load(root / "orchestration" / "registry.json")
    policy = next((item for item in registry["commands"] if item["id"] == command.get("command")), None)
    if policy is None:
        raise OrchestrationError("unknown command")
    if command.get("requested_by_type") not in policy["actors"]:
        raise OrchestrationError("actor may not issue command")
    if command.get("expected_task_state") != current_state or current_state not in policy["allowed_states"]:
        raise OrchestrationError("stale or forbidden command state")
    requested, expires = command.get("requested_at_epoch"), command.get("expires_at_epoch")
    if not isinstance(requested, int) or not isinstance(expires, int) or expires <= requested or expires <= now_epoch:
        raise OrchestrationError("expired command")
    evidence = command.get("evidence_refs")
    if not isinstance(evidence, list) or (policy["evidence_required"] and not evidence):
        raise OrchestrationError("command evidence missing")


if __name__ == "__main__":
    print(validate_orchestration_registry())
