from __future__ import annotations

import json
import os
import pathlib
import sys

from bro_audit_log import append as audit_append
from bro_completion import authorize_conductor_stop, authorize_stop
from bro_contracts import ContractError, validate_task_contract
from bro_control_plane import authorize_tool, classify_request, settle_execution_tool
from bro_policy import canonical_context, current_state, read_all, receipt_fresh
from bro_release_v3 import ReleaseV3Error, settle_release_push

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


# --- Shadow (observe-only) enforcement ---------------------------------------
# BRO_ENFORCEMENT=shadow makes the wall observe rather than block: every decision
# it *would* have blocked is recorded to the append-only BRO_SHADOW_LEDGER instead
# of being enforced, so an operator can measure a rollout against real traffic
# before flipping to enforce. Both env vars share the trust basis of BRO_MODE/
# BRO_ROLE: the hook reads the harness process environment, which the agent's own
# tool subprocesses cannot mutate.
#
# It is deliberately fail-safe. Shadow softens a block ONLY when the decision was
# durably recorded: a bypass we cannot record is a bypass we do not grant, so a
# missing/unwritable/in-repo ledger falls back to enforce. Shadow covers policy
# decisions only; an unexpected hook fault still denies via fail_closed, because a
# malfunctioning gate is not a policy verdict.
def _shadow_enabled() -> bool:
    return os.getenv("BRO_ENFORCEMENT", "enforce").strip().lower() == "shadow"


def _observe(kind: str, reason: str, data: dict, state) -> bool:
    """Record a would-block decision to the shadow ledger. Return True only when
    shadow is enabled AND the record was durably written; otherwise False, so the
    caller enforces the block."""
    if not _shadow_enabled():
        return False
    raw = os.getenv("BRO_SHADOW_LEDGER")
    if not raw:
        return False
    entry = {
        "kind": kind,
        "reason": reason,
        "session_id": state.session_id,
        "mode": state.mode,
        "role": state.role,
        "agent_id": state.agent_id,
        "tool": str(data.get("tool_name") or ""),
        "tool_use_id": str(data.get("tool_use_id") or ""),
    }
    try:
        audit_append(pathlib.Path(raw), "shadow-would-block", entry, repo_root=ROOT)
    except Exception:
        return False
    return True


def _observe_or_block(*, event: str, kind: str, reason: str, hook_name: str, data: dict, state) -> None:
    """Enforce a block, or in shadow mode record it and emit a benign observation."""
    if _observe(kind, reason, data, state):
        emit({"hookSpecificOutput": {"hookEventName": hook_name, "additionalContext": f"[SHADOW] would block ({kind}): {reason}"}})
        return
    if event == "pre-tool":
        deny(reason)
    else:
        emit({"decision": "block", "reason": reason})


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
        hook = "SessionStart" if event == "session-start" else "SubagentStart"
        emit({"hookSpecificOutput": {"hookEventName": hook, "additionalContext": canonical_context() + f"\nFULL_READ_RECEIPT GREEN files={receipt['tracked_files']} bytes={receipt['tracked_bytes']} tree={receipt['tree_identity']} mode={state.mode} role={state.role}"}})
        return 0
    if event == "prompt":
        fresh, reason = receipt_fresh(state.session_id)
        if not fresh:
            receipt = read_all(state.session_id)
            reason = f"refreshed tree={receipt['tree_identity']}"
        emit({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": f"BRO_MODE={state.mode}; BRO_ROLE={state.role}; literacy={reason}. Bro must remain responsive and delegate execution."}})
        return 0
    if event == "pre-tool":
        fresh, _ = receipt_fresh(state.session_id)
        note = ""
        if not fresh:
            receipt = read_all(state.session_id)
            note = f"Automatic mandatory reread completed before this tool call: tree={receipt['tree_identity']}. "
        tool = str(data.get("tool_name") or "")
        tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
        allowed, why = authorize_tool(state, tool, tool_input, tool_use_id=str(data.get("tool_use_id") or ""))
        if not allowed:
            _observe_or_block(event="pre-tool", kind="pre-tool-deny", reason=note + why, hook_name="PreToolUse", data=data, state=state)
        elif note:
            emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": note}})
        return 0
    if event in {"post-tool", "post-tool-failure"}:
        tool = str(data.get("tool_name") or "")
        tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
        tool_use_id = str(data.get("tool_use_id") or "")
        success = event == "post-tool"
        error = str(data.get("error") or "")
        hook = "PostToolUse" if success else "PostToolUseFailure"
        try:
            classification = classify_request(tool, tool_input)
        except Exception:
            classification = None
        if classification is not None and classification.push:
            command = str(tool_input.get("command") or tool_input.get("script") or "")
            try:
                green, message = settle_release_push(state_agent_id=state.agent_id, state_mode=state.mode, state_role=state.role, command=command, tool_use_id=tool_use_id, success=success, error=error)
            except ReleaseV3Error as exc:
                green, message = False, f"Release Grant V3 settlement RED: {exc}"
            if not green and success:
                _observe_or_block(event="post-tool", kind="release-settlement-block", reason=message, hook_name=hook, data=data, state=state)
            else:
                emit({"hookSpecificOutput": {"hookEventName": hook, "additionalContext": message}})
            return 0
        handled, green, message = settle_execution_tool(state, tool, tool_input, tool_use_id, success=success, error=error)
        if not handled:
            return 0
        if not green and success:
            _observe_or_block(event="post-tool", kind="execution-settlement-block", reason=message, hook_name=hook, data=data, state=state)
        else:
            emit({"hookSpecificOutput": {"hookEventName": hook, "additionalContext": message}})
        return 0
    if event == "stop":
        fresh, reason = receipt_fresh(state.session_id)
        if not fresh:
            emit({"decision": "block", "reason": f"Cannot finish: {reason}"})
            return 0
        try:
            task = _task_from_env()
        except ContractError as exc:
            # No contract bound: either the conductor, which owes no builder
            # evidence because it never builds, or an executor missing its
            # contract, which owes everything.
            allowed, why = authorize_conductor_stop(state, ROOT)
            emit({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": why}}
                 if allowed else
                 {"decision": "block", "reason": f"completion gate RED: {exc}; {why}"})
            return 0
        allowed, why = authorize_stop(task, state.agent_id, ROOT)
        emit({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": why}} if allowed else {"decision": "block", "reason": why})
        return 0
    return 0


def fail_closed(event: str, exc: BaseException) -> int:
    """An unexpected exception must still produce a decision.

    A traceback exits non-zero and emits nothing, so the enforcement point simply
    disappears and the caller is left with no verdict. Any failure the gates did
    not anticipate is therefore converted into the same answer they would have
    given: deny. Exit code stays 0 because the decision travels in the payload,
    not the status.
    """
    reason = f"hook failed closed: {type(exc).__name__}: {exc}"
    if event == "pre-tool":
        deny(reason)
    elif event in {"stop", "subagent-stop", "post-tool", "post-tool-failure"}:
        emit({"decision": "block", "reason": reason})
    else:
        emit({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                     "additionalContext": reason}})
    return 0


if __name__ == "__main__":
    event_name = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        code = main()
    except Exception as exc:  # noqa: BLE001 - a hook may never crash open
        code = fail_closed(event_name, exc)
    raise SystemExit(code)
