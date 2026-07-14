from __future__ import annotations

import json
import os
import pathlib

from bro_authority import AuthorityError, resolve_agent_authority, validate_verifier_assignment
from bro_authorization import ActionClassification, classify_tool_action
from bro_contracts import ContractError, validate_agent_profile, validate_task_contract
from bro_policy import State, authorize_tool as authorize_legacy_tool
from bro_security import SecurityError

ROOT = pathlib.Path(__file__).resolve().parents[1]


def classify_request(tool_name: str, tool_input: dict) -> ActionClassification:
    return classify_tool_action(tool_name, tool_input)


def _load_bound_json(env_name: str) -> dict:
    raw = os.getenv(env_name)
    if not raw:
        raise ContractError(f"missing {env_name}")
    path = pathlib.Path(raw)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError(f"missing bound file for {env_name}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"malformed bound file for {env_name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{env_name} must contain a JSON object")
    return value


def _enforce_identity_authority(state: State) -> None:
    task = validate_task_contract(_load_bound_json("BRO_TASK_CONTRACT"), ROOT)
    profile = validate_agent_profile(_load_bound_json("BRO_AGENT_PROFILE"), ROOT)

    if (
        task["agent_id"] != profile["agent_id"]
        or task["pack_id"] != profile["pack_id"]
        or task["assignee_role"] != profile["role"]
    ):
        raise AuthorityError("task assignment and agent profile do not match")

    authority = resolve_agent_authority(
        profile["agent_id"], profile["pack_id"], profile["role"], ROOT
    )
    if state.agent_id != authority.agent_id:
        raise AuthorityError("BRO_AGENT_ID does not match canonical assigned agent")
    if state.mode not in authority.allowed_modes:
        raise AuthorityError("canonical agent authority does not allow requested mode")
    if state.mode == "release" and not authority.can_release:
        raise AuthorityError("canonical agent lacks release authority")
    if state.mode == "work" and not authority.can_build:
        raise AuthorityError("canonical agent lacks builder authority")

    verification = task["verification"]
    if verification["required"]:
        validate_verifier_assignment(
            builder_agent_id=profile["agent_id"],
            verifier_agent_id=verification["verifier_agent_id"],
            verifier_role=verification["verifier_role"],
            risk=task["risk"],
            root=ROOT,
        )


def authorize_tool(
    state: State,
    tool_name: str,
    tool_input: dict,
    tool_use_id: str = "",
) -> tuple[bool, str]:
    """Canonical PreToolUse ingress for Control Plane migration phases."""
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

    if classification.mutating and state.role != "bro":
        try:
            _enforce_identity_authority(state)
        except (AuthorityError, ContractError) as exc:
            return False, f"canonical identity/authority gate RED: {exc}"

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
