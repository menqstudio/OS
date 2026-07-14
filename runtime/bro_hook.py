from __future__ import annotations

import json
import os
import pathlib
import sys

from bro_completion import authorize_stop
from bro_contracts import ContractError, validate_task_contract
from bro_control_plane import authorize_tool, settle_execution_tool
from bro_policy import (
    canonical_context,
    current_state,
    read_all,
    receipt_fresh,
    settle_release_tool,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


def payload() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def deny(reason: str) -> None:
    emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}})


def _task_from_env() -> dict:
    raw = os.getenv("BRO_TASK_CONTRACT")
    if not raw:
        raise ContractError("missing BRO_TASK_CONTRACT")
    try:
        value = json.loads(pathlib.Path(raw).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read BRO_TASK_CONTRACT: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError("BRO_TASK_CONTRACT must contain an object")
    return validate_task_contract(value, ROOT)


def main() -> int:
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    data = payload()
    state = current_state(data)

    if event in {"session-start", "subagent-start"}:
        receipt = read_all(state.session_id)
        context = canonical_context()
        hook_name = "SessionStart" if event == "session-start" else "SubagentStart"
        emit({"hookSpecificOutput": {"hookEventName": hook_name, "additionalContext": context + "\nFULL_READ_RECEIPT GREEN " + f"files={receipt['tracked_files']} bytes={receipt['tracked_bytes']} tree={receipt['tree_identity']} mode={state.mode} role={state.role}"}})
        return 0

    if event == "prompt":
        fresh, reason = receipt_fresh(state.session_id)
        if not fresh:
            receipt = read_all(state.session_id)
            reason = f"refreshed tree={receipt['tree_identity']}"
        emit({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": f"BRO_MODE={state.mode}; BRO_ROLE={state.role}; literacy={reason}. Bro must remain responsive and delegate execution."}})
        return 0

    if event == "pre-tool":
        fresh, _reason = receipt_fresh(state.session_id)
        reread_note = ""
        if not fresh:
            receipt = read_all(state.session_id)
            reread_note = f"Automatic mandatory reread completed before this tool call: tree={receipt['tree_identity']}. "
        tool_name = str(data.get("tool_name") or "")
        tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
        tool_use_id = str(data.get("tool_use_id") or "")
        allowed, why = authorize_tool(state, tool_name, tool_input, tool_use_id=tool_use_id)
        if not allowed:
            deny(reread_note + why)
            return 0
        if reread_note:
            emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": reread_note}})
        return 0

    if event in {"post-tool", "post-tool-failure"}:
        tool_name = str(data.get("tool_name") or "")
        tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
        tool_use_id = str(data.get("tool_use_id") or "")
        success = event == "post-tool"
        error = str(data.get("error") or "")
        hook_name = "PostToolUse" if success else "PostToolUseFailure"
        lease_handled, lease_green, lease_message = settle_execution_tool(state, tool_name, tool_input, tool_use_id, success=success, error=error)
        if lease_handled and not lease_green:
            if success:
                emit({"decision": "block", "reason": lease_message})
            else:
                emit({"hookSpecificOutput": {"hookEventName": hook_name, "additionalContext": lease_message}})
            return 0
        release_handled, release_green, release_message = settle_release_tool(state, tool_name, tool_input, tool_use_id, success=success, error=error)
        messages = []
        if lease_handled:
            messages.append(lease_message)
        if release_handled:
            messages.append(release_message)
        if not release_handled and not lease_handled:
            return 0
        if release_handled and not release_green:
            if success:
                emit({"decision": "block", "reason": release_message})
            else:
                emit({"hookSpecificOutput": {"hookEventName": hook_name, "additionalContext": release_message}})
            return 0
        emit({"hookSpecificOutput": {"hookEventName": hook_name, "additionalContext": "; ".join(messages)}})
        return 0

    if event == "stop":
        fresh, reason = receipt_fresh(state.session_id)
        if not fresh:
            emit({"decision": "block", "reason": f"Cannot finish: {reason}"})
            return 0
        try:
            task = _task_from_env()
        except ContractError as exc:
            emit({"decision": "block", "reason": f"completion gate RED: {exc}"})
            return 0
        allowed, why = authorize_stop(task, state.agent_id, ROOT)
        if not allowed:
            emit({"decision": "block", "reason": why})
        else:
            emit({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": why}})
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
