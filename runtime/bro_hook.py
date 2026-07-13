from __future__ import annotations

import json
import sys

from bro_policy import authorize_tool, canonical_context, current_state, read_all, receipt_fresh


def payload() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def deny(reason: str) -> None:
    emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}})


def main() -> int:
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    data = payload()
    state = current_state(data)

    if event in {"session-start", "subagent-start"}:
        receipt = read_all(state.session_id)
        context = canonical_context()
        hook_name = "SessionStart" if event == "session-start" else "SubagentStart"
        emit({"hookSpecificOutput": {"hookEventName": hook_name, "additionalContext": context + f"\nFULL_READ_RECEIPT GREEN files={receipt['tracked_files']} bytes={receipt['tracked_bytes']} tree={receipt['tree_identity']} mode={state.mode} role={state.role}"}})
        return 0

    if event == "prompt":
        fresh, reason = receipt_fresh(state.session_id)
        if not fresh:
            receipt = read_all(state.session_id)
            reason = f"refreshed tree={receipt['tree_identity']}"
        emit({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": f"BRO_MODE={state.mode}; BRO_ROLE={state.role}; literacy={reason}. Bro must remain responsive and delegate execution."}})
        return 0

    if event == "pre-tool":
        fresh, reason = receipt_fresh(state.session_id)
        reread_note = ""
        if not fresh:
            receipt = read_all(state.session_id)
            reread_note = f"Automatic mandatory reread completed before this tool call: tree={receipt['tree_identity']}. "
        tool_name = str(data.get("tool_name") or "")
        tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
        allowed, why = authorize_tool(state, tool_name, tool_input)
        if not allowed:
            deny(reread_note + why)
            return 0
        if reread_note:
            emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": reread_note}})
        return 0

    if event == "stop":
        fresh, reason = receipt_fresh(state.session_id)
        if not fresh:
            emit({"decision": "block", "reason": f"Cannot finish: {reason}"})
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
