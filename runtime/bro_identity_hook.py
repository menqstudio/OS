from __future__ import annotations

import json
import os
import pathlib
import re
import sys

from bro_identity import IdentityError, validate_agent_profile_identity

MUTATING_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}
MUTATING_SHELL = re.compile(
    r"(?ix)(^|[;&|]\s*)(rm|del|erase|rmdir|remove-item|set-content|add-content|out-file|new-item|move-item|copy-item|"
    r"git\s+(add|commit|push|merge|rebase|reset|checkout|switch|branch|tag|clean)|"
    r"gh\s+(pr|issue|release|workflow|repo)\b|npm\s+install|pnpm\s+add|yarn\s+add|pip\s+install)\b"
)


def _payload() -> dict:
    try:
        value = json.load(sys.stdin)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}))


def _is_mutation(tool_name: str, tool_input: dict) -> bool:
    if tool_name in MUTATING_TOOLS:
        return True
    if tool_name in {"Bash", "PowerShell", "Shell"}:
        command = str(tool_input.get("command") or tool_input.get("script") or "")
        return bool(MUTATING_SHELL.search(command))
    return False


def main() -> int:
    data = _payload()
    mode = os.getenv("BRO_MODE", "review").strip().lower()
    tool_name = str(data.get("tool_name") or "")
    tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    if mode not in {"work", "release"} or not _is_mutation(tool_name, tool_input):
        return 0
    profile_path = os.getenv("BRO_AGENT_PROFILE")
    if not profile_path:
        _deny("agent identity gate RED: missing BRO_AGENT_PROFILE")
        return 0
    try:
        profile = json.loads(pathlib.Path(profile_path).read_text(encoding="utf-8"))
        canonical_id = validate_agent_profile_identity(profile)
    except (OSError, json.JSONDecodeError, IdentityError) as exc:
        _deny(f"agent identity gate RED: {exc}")
        return 0
    env_id = os.getenv("BRO_AGENT_ID", "").strip().lower()
    if not env_id:
        _deny("agent identity gate RED: missing BRO_AGENT_ID")
        return 0
    if env_id != canonical_id:
        _deny(f"agent identity gate RED: BRO_AGENT_ID must be {canonical_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
