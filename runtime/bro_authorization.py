from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from typing import Any

from bro_security import (
    READ_ONLY_SHELL,
    SHELL_MUTATORS,
    SHELL_WRAPPERS,
    CommandInfo,
    SecurityError,
    analyze_command,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "tools" / "registry.json"

MUTATING_CAPABILITIES = {
    "WRITE_REPOSITORY",
    "WRITE_FILESYSTEM",
    "WRITE_EXTERNAL",
    "SEND_COMMUNICATION",
    "PUBLISH",
    "SPEND",
    "CHANGE_ACCESS",
    "DELETE",
    "DESTRUCTIVE",
}

DIRECT_ACTIONS = {
    "Read": "read",
    "Glob": "search",
    "Grep": "search",
    "WebSearch": "search",
    "WebFetch": "fetch",
    "Write": "write",
    "Edit": "edit",
    "MultiEdit": "edit",
    "NotebookEdit": "edit",
}


@dataclass(frozen=True)
class ActionClassification:
    tool: str
    action: str
    capabilities: tuple[str, ...]
    targets: tuple[str, ...]
    mutating: bool
    push: bool
    requires_task: bool
    requires_scope: bool
    requires_work_grant: bool
    command_infos: tuple[CommandInfo, ...] = ()

    @property
    def unknown(self) -> bool:
        return "UNKNOWN" in self.capabilities


def load_tool_registry(root: pathlib.Path = ROOT) -> dict[str, Any]:
    path = root / "tools" / "registry.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SecurityError("missing canonical tool capability registry") from exc
    except json.JSONDecodeError as exc:
        raise SecurityError(f"invalid tool capability registry: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise SecurityError("unsupported tool capability registry schema")
    classes = value.get("capability_classes")
    tools = value.get("tools")
    if not isinstance(classes, list) or "UNKNOWN" not in classes:
        raise SecurityError("tool registry must define UNKNOWN capability")
    if not isinstance(tools, list) or not tools:
        raise SecurityError("tool registry has no tools")
    known_classes = set(classes)
    names: set[str] = set()
    for item in tools:
        if not isinstance(item, dict):
            raise SecurityError("tool registry entry must be an object")
        name = item.get("name")
        resolver = item.get("resolver")
        actions = item.get("actions")
        if not isinstance(name, str) or not name or name in names:
            raise SecurityError("tool registry contains missing or duplicate name")
        if resolver not in {"direct", "shell"} or not isinstance(actions, dict):
            raise SecurityError(f"invalid resolver/actions for tool {name}")
        names.add(name)
        for action_name, action in actions.items():
            if not isinstance(action_name, str) or not isinstance(action, dict):
                raise SecurityError(f"invalid action entry for tool {name}")
            capabilities = action.get("capabilities")
            if not isinstance(capabilities, list) or not capabilities:
                raise SecurityError(f"action {name}:{action_name} has no capabilities")
            unknown = set(capabilities) - known_classes
            if unknown:
                raise SecurityError(
                    f"action {name}:{action_name} uses unknown capabilities: {sorted(unknown)}"
                )
    return value


def _tool_entry(registry: dict[str, Any], tool_name: str) -> dict[str, Any] | None:
    for item in registry["tools"]:
        if item["name"] == tool_name:
            return item
    return None


def _direct_targets(tool_input: dict[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for key in ("file_path", "path", "notebook_path", "destination", "source"):
        value = tool_input.get(key)
        if isinstance(value, str):
            values.append(value)
    for key in ("files", "paths", "edits"):
        value = tool_input.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    values.append(item)
                elif isinstance(item, dict):
                    for nested_key in ("file_path", "path"):
                        nested = item.get(nested_key)
                        if isinstance(nested, str):
                            values.append(nested)
    return tuple(values)


def _shell_capabilities(info: CommandInfo) -> tuple[str, ...]:
    if info.executable == "git":
        if info.push:
            return ("WRITE_EXTERNAL", "PUBLISH", "USE_NETWORK", "USE_CREDENTIAL")
        if info.recognized_read_only:
            return ("READ_LOCAL",)
        return ("WRITE_REPOSITORY", "EXECUTE_CODE")
    if info.recognized_read_only and info.executable in READ_ONLY_SHELL:
        return ("READ_LOCAL",)
    if info.executable == "gh":
        return ("WRITE_EXTERNAL", "USE_NETWORK", "USE_CREDENTIAL")
    if info.executable in SHELL_MUTATORS:
        capabilities = ["WRITE_REPOSITORY", "EXECUTE_CODE"]
        if info.executable in {"rm", "del", "erase", "rmdir", "remove-item"}:
            capabilities.append("DELETE")
        return tuple(capabilities)
    if info.executable in SHELL_WRAPPERS:
        return ("EXECUTE_CODE",)
    return ("UNKNOWN",)


def _classify_shell(tool_name: str, tool_input: dict[str, Any]) -> ActionClassification:
    command = str(tool_input.get("command") or tool_input.get("script") or "")
    if not command.strip():
        raise SecurityError("shell tool has no command")
    infos = tuple(analyze_command(command))
    if not infos:
        raise SecurityError("shell command produced no classified action")
    capabilities: set[str] = set()
    targets: list[str] = []
    actions: list[str] = []
    push = False
    for info in infos:
        capabilities.update(_shell_capabilities(info))
        targets.extend(info.targets)
        push = push or info.push
        actions.append(f"{info.executable}:{info.subcommand or 'invoke'}")
    mutating = any(cap in MUTATING_CAPABILITIES for cap in capabilities) or any(
        info.mutating for info in infos
    )
    return ActionClassification(
        tool=tool_name,
        action=" + ".join(actions),
        capabilities=tuple(sorted(capabilities)),
        targets=tuple(targets),
        mutating=mutating,
        push=push,
        requires_task=mutating,
        requires_scope=mutating and not push,
        requires_work_grant=mutating,
        command_infos=infos,
    )


def classify_tool_action(
    tool_name: str,
    tool_input: dict[str, Any],
    root: pathlib.Path = ROOT,
) -> ActionClassification:
    registry = load_tool_registry(root)
    entry = _tool_entry(registry, tool_name)
    if entry is None:
        return ActionClassification(
            tool=tool_name,
            action="unknown",
            capabilities=("UNKNOWN",),
            targets=(),
            mutating=True,
            push=False,
            requires_task=True,
            requires_scope=False,
            requires_work_grant=True,
        )
    if entry["resolver"] == "shell":
        return _classify_shell(tool_name, tool_input)
    action_name = DIRECT_ACTIONS.get(tool_name)
    action = entry["actions"].get(action_name or "")
    if action is None:
        return ActionClassification(
            tool=tool_name,
            action=action_name or "unknown",
            capabilities=("UNKNOWN",),
            targets=(),
            mutating=True,
            push=False,
            requires_task=True,
            requires_scope=False,
            requires_work_grant=True,
        )
    capabilities = tuple(sorted(action["capabilities"]))
    mutating = any(cap in MUTATING_CAPABILITIES for cap in capabilities)
    return ActionClassification(
        tool=tool_name,
        action=action_name or "unknown",
        capabilities=capabilities,
        targets=_direct_targets(tool_input),
        mutating=mutating,
        push=False,
        requires_task=bool(action.get("requires_task")),
        requires_scope=bool(action.get("requires_scope")),
        requires_work_grant=bool(action.get("requires_work_grant")),
    )
