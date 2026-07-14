from __future__ import annotations

from bro_authorization import ActionClassification, classify_tool_action
from bro_policy import State, authorize_tool as authorize_legacy_tool
from bro_security import SecurityError


def classify_request(tool_name: str, tool_input: dict) -> ActionClassification:
    return classify_tool_action(tool_name, tool_input)


def authorize_tool(
    state: State,
    tool_name: str,
    tool_input: dict,
    tool_use_id: str = "",
) -> tuple[bool, str]:
    """Canonical PreToolUse ingress for Phase 1.

    The capability kernel is authoritative for tool/action registration and
    UNKNOWN denial. Existing V1 task, grant, scope, and release gates remain
    downstream until their dedicated migration phases.
    """
    try:
        classification = classify_request(tool_name, tool_input)
    except SecurityError as exc:
        return False, f"tool capability gate RED: {exc}"

    if classification.unknown:
        return (
            False,
            f"tool capability gate RED: unknown tool/action "
            f"{classification.tool}:{classification.action}",
        )

    allowed, reason = authorize_legacy_tool(
        state,
        tool_name,
        tool_input,
        tool_use_id=tool_use_id,
    )
    if not allowed:
        return False, reason

    capabilities = ",".join(classification.capabilities)
    return True, f"allowed by capability kernel ({capabilities}); {reason}"
