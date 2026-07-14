from __future__ import annotations

import json
import os
import pathlib

from bro_authority import AuthorityError, resolve_agent_authority, validate_verifier_assignment
from bro_authorization import ActionClassification, classify_tool_action
from bro_contracts import ContractError, validate_agent_profile, validate_task_contract
from bro_execution_lease import LeaseError, finalize_execution_lease, load_execution_lease_from_env, quarantine_execution_lease, reserve_execution_lease
from bro_policy import State, authorize_tool as authorize_legacy_tool
from bro_release_v3 import ReleaseV3Error, authorize_release_push
from bro_repository_state import RepositoryStateError, verify_repository_binding
from bro_security import SecurityError

ROOT = pathlib.Path(__file__).resolve().parents[1]


def classify_request(tool_name: str, tool_input: dict) -> ActionClassification:
    return classify_tool_action(tool_name, tool_input)


def _load_bound_json(env_name: str) -> dict:
    raw = os.getenv(env_name)
    if not raw:
        raise ContractError(f"missing {env_name}")
    try:
        value = json.loads(pathlib.Path(raw).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load {env_name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{env_name} must contain a JSON object")
    return value


def _enforce_identity_authority(state: State) -> dict:
    task = validate_task_contract(_load_bound_json("BRO_TASK_CONTRACT"), ROOT)
    profile = validate_agent_profile(_load_bound_json("BRO_AGENT_PROFILE"), ROOT)
    if (task["agent_id"], task["pack_id"], task["assignee_role"]) != (profile["agent_id"], profile["pack_id"], profile["role"]):
        raise AuthorityError("task assignment and agent profile do not match")
    authority = resolve_agent_authority(profile["agent_id"], profile["pack_id"], profile["role"], ROOT)
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
        validate_verifier_assignment(builder_agent_id=profile["agent_id"], verifier_agent_id=verification["verifier_agent_id"], verifier_role=verification["verifier_role"], risk=task["risk"], root=ROOT)
    return task


def _lease(state: State, task: dict, classification: ActionClassification):
    capabilities = tuple(x for x in classification.capabilities if x not in {"READ_LOCAL", "READ_EXTERNAL", "UNKNOWN"})
    return load_execution_lease_from_env(task=task, agent_id=state.agent_id, session_id=state.session_id, required_capabilities=capabilities)


def authorize_tool(state: State, tool_name: str, tool_input: dict, tool_use_id: str = "") -> tuple[bool, str]:
    try:
        classification = classify_request(tool_name, tool_input)
    except SecurityError as exc:
        return False, f"tool capability gate RED: {exc}"
    if classification.unknown:
        return False, f"tool capability gate RED: unknown tool/action {classification.tool}:{classification.action}"
    if classification.push:
        command = str(tool_input.get("command") or tool_input.get("script") or "")
        try:
            authorize_release_push(state_agent_id=state.agent_id, state_mode=state.mode, state_role=state.role, command=command, tool_use_id=tool_use_id)
            return True, "Release Grant V3 authorized; nonce reserved pending settlement"
        except (ReleaseV3Error, SecurityError) as exc:
            return False, f"Release Grant V3 RED: {exc}"
    task = None
    if classification.mutating and state.role != "bro":
        try:
            task = _enforce_identity_authority(state)
            verify_repository_binding(task, root=ROOT)
        except (AuthorityError, ContractError) as exc:
            return False, f"canonical identity/authority gate RED: {exc}"
        except RepositoryStateError as exc:
            return False, f"repository binding gate RED: {exc}"
    allowed, reason = authorize_legacy_tool(state, tool_name, tool_input, tool_use_id=tool_use_id)
    if not allowed:
        return False, reason
    if classification.mutating and state.role != "bro":
        try:
            reserve_execution_lease(_lease(state, task, classification), tool_use_id)
        except LeaseError as exc:
            return False, f"execution lease gate RED: {exc}"
    return True, f"allowed by capability kernel ({','.join(classification.capabilities)}); {reason}"


def settle_execution_tool(state: State, tool_name: str, tool_input: dict, tool_use_id: str, *, success: bool, error: str = "") -> tuple[bool, bool, str]:
    try:
        classification = classify_request(tool_name, tool_input)
    except SecurityError as exc:
        return True, False, f"execution lease settlement RED: {exc}"
    if classification.push or not classification.mutating or state.role == "bro":
        return False, True, "not an execution-lease settlement"
    try:
        task = _enforce_identity_authority(state)
        lease = _lease(state, task, classification)
        if success:
            finalize_execution_lease(lease, tool_use_id)
            return True, True, "execution lease consumed"
        quarantine_execution_lease(lease, tool_use_id, error or "mutation outcome ambiguous")
        return True, False, "execution lease quarantined pending recovery"
    except (AuthorityError, ContractError, LeaseError) as exc:
        return True, False, f"execution lease settlement RED: {exc}"
