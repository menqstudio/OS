from __future__ import annotations

import json
import os
import pathlib
import sys

from bro_authorization import classify_tool_action
from bro_identity import IdentityError, validate_agent_profile_identity
from bro_security import SecurityError


def _payload() -> dict:
    try:
        value = json.load(sys.stdin)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _deny(reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


def main() -> int:
    data = _payload()
    mode = os.getenv("BRO_MODE", "review").strip().lower()
    tool_name = str(data.get("tool_name") or "")
    tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}

    try:
        classification = classify_tool_action(tool_name, tool_input)
    except SecurityError as exc:
        _deny(f"agent identity gate RED: classifier failed: {exc}")
        return 0

    if classification.unknown:
        _deny(
            f"agent identity gate RED: unknown tool/action "
            f"{classification.tool}:{classification.action}"
        )
        return 0

    if mode not in {"work", "release"} or not classification.mutating:
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
