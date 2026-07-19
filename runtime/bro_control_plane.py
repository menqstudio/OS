from __future__ import annotations

import json
import os
import pathlib

from bro_authority import AuthorityError, resolve_agent_authority, validate_verifier_assignment
from bro_authorization import ActionClassification, classify_tool_action
from bro_contracts import ContractError, validate_agent_profile, validate_task_contract
from bro_execution_lease import LeaseError, finalize_execution_lease, load_execution_lease_from_env, quarantine_execution_lease, reserve_execution_lease
from bro_freeze import FreezeError, authorize_under_freeze, freeze_authority, load_freeze
from bro_policy import State, authorize_classified_action
from bro_protected import ProtectedScopeError, authorize_protected_scope, load_protected_manifest, verify_control_plane_digest
from bro_recovery import RecoveryError, cancel_prepared, prepare_mutation, settle_mutation
from bro_release_v3 import ReleaseV3Error, authorize_release_push
from bro_repository_state import RepositoryStateError, verify_repository_binding
from bro_security import SecurityError
from bro_workspace import Workspace, WorkspaceError, authorize_targets, load_workspace
from bro_workspace import verify_repository_binding as verify_workspace_remote

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


def _shell_cwd(classification: ActionClassification, workspace: Workspace) -> pathlib.Path:
    return workspace.root


def _bind_workspace(classification: ActionClassification) -> Workspace:
    """Every local action requires an active binding, a matching repository and an
    unchanged control plane. A missing, malformed, inactive or stale binding
    denies: scope that cannot be proven is not scope."""
    workspace = load_workspace(ROOT)
    verify_workspace_remote(workspace)
    manifest = load_protected_manifest(ROOT)
    verify_control_plane_digest(ROOT, manifest, workspace.control_plane_digest)
    targets = classification.targets or (".",)
    authorize_targets(workspace, targets, _shell_cwd(classification, workspace))
    return workspace


def _relative_targets(workspace: Workspace, classification: ActionClassification) -> list[str]:
    resolved = authorize_targets(workspace, classification.targets or (),
                                 _shell_cwd(classification, workspace))
    return [path.relative_to(workspace.root).as_posix() for path in resolved]


def _lease(state: State, task: dict, classification: ActionClassification,
           workspace: Workspace | None = None):
    caps = tuple(x for x in classification.capabilities if x not in {"READ_LOCAL", "READ_EXTERNAL", "UNKNOWN"})
    # The reserve/authorize gate passes the live workspace so the lease is bound to
    # this exact control plane and workspace at consumption time. Settlement re-loads
    # the lease with no workspace (a protected mutation may already have changed the
    # digest); it is reachable only after a reserve that enforced both, so omitting
    # them there is not a bypass.
    return load_execution_lease_from_env(
        task=task, agent_id=state.agent_id, session_id=state.session_id,
        required_capabilities=caps,
        control_plane_digest=workspace.control_plane_digest if workspace else None,
        workspace_id=workspace.workspace_id if workspace else None)


def authorize_tool(state: State, tool_name: str, tool_input: dict, tool_use_id: str = "") -> tuple[bool, str]:
    try:
        classification = classify_request(tool_name, tool_input)
    except SecurityError as exc:
        return False, f"tool capability gate RED: {exc}"
    if classification.unknown:
        return False, f"tool capability gate RED: unknown tool/action {classification.tool}:{classification.action}"
    try:
        freeze = load_freeze(state.session_id)
    except FreezeError as exc:
        return False, f"freeze state gate RED: {exc}"
    if freeze is not None:
        # Checked before the digest: the protected mutation this session just made
        # is exactly what invalidates its own binding, and settlement must survive it.
        return authorize_under_freeze(freeze, classification)
    try:
        workspace = _bind_workspace(classification)
    except (WorkspaceError, ProtectedScopeError) as exc:
        return False, f"workspace scope gate RED: {exc}"
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
            verify_repository_binding(task, agent_id=state.agent_id, session_id=state.session_id, root=ROOT)
        except (AuthorityError, ContractError) as exc:
            return False, f"canonical identity/authority gate RED: {exc}"
        except RepositoryStateError as exc:
            return False, f"repository binding gate RED: {exc}"
        try:
            authority = _load_bound_json("BRO_PROTECTED_AUTHORITY") if os.getenv(
                "BRO_PROTECTED_AUTHORITY") else {"task_class": "standard-builder"}
            authorize_protected_scope(load_protected_manifest(ROOT), authority,
                                      _relative_targets(workspace, classification))
        except (ContractError, ProtectedScopeError, WorkspaceError) as exc:
            return False, f"protected control-plane gate RED: {exc}"
    allowed, reason = authorize_classified_action(state, classification, tool_input)
    if not allowed:
        return False, reason
    if classification.mutating and state.role != "bro":
        prepared = False
        try:
            prepare_mutation(task=task, agent_id=state.agent_id, session_id=state.session_id, tool_use_id=tool_use_id, capabilities=classification.capabilities, targets=classification.targets, tool=classification.tool, action_name=classification.action)
            prepared = True
            reserve_execution_lease(_lease(state, task, classification, workspace), tool_use_id)
        except (RecoveryError, LeaseError) as exc:
            if prepared:
                try:
                    cancel_prepared(task["task_id"], tool_use_id)
                except RecoveryError:
                    return False, f"transaction gate RED: {exc}; prepared recovery journal could not be cancelled"
            return False, f"transaction gate RED: {exc}"
    return True, f"allowed by capability kernel ({','.join(classification.capabilities)}); recovery journal prepared; {reason}"


def settle_execution_tool(state: State, tool_name: str, tool_input: dict, tool_use_id: str, *, success: bool, error: str = "") -> tuple[bool, bool, str]:
    try:
        classification = classify_request(tool_name, tool_input)
    except SecurityError as exc:
        return True, False, f"execution settlement RED: {exc}"
    if classification.push or not classification.mutating or state.role == "bro":
        return False, True, "not a governed mutation settlement"
    try:
        task = _enforce_identity_authority(state)
        recovery_green, recovery_message = settle_mutation(task["task_id"], tool_use_id, success=success, error=error)
        lease = _lease(state, task, classification)
        if success:
            finalize_execution_lease(lease, tool_use_id)
            return True, recovery_green, f"execution lease consumed; {recovery_message}"
        quarantine_execution_lease(lease, tool_use_id, error or "mutation outcome ambiguous")
        return True, False, f"execution lease quarantined; {recovery_message}"
    except (AuthorityError, ContractError, LeaseError, RecoveryError) as exc:
        return True, False, f"execution/recovery settlement RED: {exc}"
