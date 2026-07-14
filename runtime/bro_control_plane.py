from __future__ import annotations

import json
import os
import pathlib

from bro_authority import AuthorityError, resolve_agent_authority, validate_verifier_assignment
from bro_authorization import ActionClassification, classify_tool_action
from bro_contracts import ContractError, validate_agent_profile, validate_task_contract
from bro_execution_lease import (
    LeaseError,
    finalize_execution_lease,
    load_execution_lease_from_env,
    quarantine_execution_lease,
    reserve_execution_lease,
)
from bro_policy import State, authorize_tool as authorize_legacy_tool
from bro_repository_state import RepositoryStateError, verify_repository_binding
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


def _enforce_identity_authority(state: State) -> dict:
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
    return task


def _required_lease_capabilities(classification: ActionClassification) -> tuple[str, ...]:
    return tuple(
        capability
        for capability in classification.capabilities
        if capability not in {"READ_LOCAL", "READ_EXTERNAL", "UNKNOWN"}
    )


def _load_lease_for_request(
    state: State,
    task: dict,
    classification: ActionClassification,
):
    return load_execution_lease_from_env(
        task=task,
        agent_id=state.agent_id,
        session_id=state.session_id,
        required_capabilities=_required_lease_capabilities(classification),
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

    task = None
    if classification.mutating and state.role != "bro":
        try:
            task = _enforce_identity_authority(state)
            verify_repository_binding(task, root=ROOT)
        except (AuthorityError, ContractError) as exc:
            return False, f"canonical identity/authority gate RED: {exc}"
        except RepositoryStateError as exc:
            return False, f"repository binding gate RED: {exc}"

    allowed, reason = authorize_legacy_tool(
        state,
        tool_name,
        tool_input,
        tool_use_id=tool_use_id,
    )
    if not allowed:
        return False, reason

    if classification.mutating and state.role != "bro":
        try:
            lease = _load_lease_for_request(state, task, classification)
            reserve_execution_lease(lease, tool_use_id)
        except LeaseError as exc:
            return False, f"execution lease gate RED: {exc}"

    capabilities = ",".join(classification.capabilities)
    return True, f"allowed by capability kernel ({capabilities}); {reason}"


def settle_execution_tool(
    state: State,
    tool_name: str,
    tool_input: dict,
    tool_use_id: str,
    *,
    success: bool,
    error: str = "",
) -> tuple[bool, bool, str]:
    """Settle a mutation lease after tool completion.

    Returns (handled, green, message). Failures are quarantined because their
    external or filesystem effect may be ambiguous until recovery proves state.
    """
    try:
        classification = classify_request(tool_name, tool_input)
    except SecurityError as exc:
        return True, False, f"execution lease settlement RED: {exc}"
    if not classification.mutating or state.role == "bro":
        return False, True, "not a leased mutation"

    try:
        task = _enforce_identity_authority(state)
        lease = _load_lease_for_request(state, task, classification)
        if success:
            finalize_execution_lease(lease, tool_use_id)
            return True, True, "execution lease consumed"
        quarantine_execution_lease(
            lease,
            tool_use_id,
            error or "mutation tool failed with potentially ambiguous effect",
        )
        return True, False, "execution lease quarantined pending recovery"
    except (AuthorityError, ContractError, LeaseError) as exc:
        return True, False, f"execution lease settlement RED: {exc}"
