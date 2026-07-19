from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from bro_authorization import ActionClassification
from bro_contracts import ContractError, load_contract_bundle_from_env, load_mode_grant_from_env
from bro_security import SecurityError, enforce_scope

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / ".bro" / "policy.json"
MANIFEST_PATH = ROOT / "config" / "canonical-read-manifest.json"


@dataclass(frozen=True)
class State:
    mode: str
    role: str
    session_id: str
    agent_id: str = ""


def load_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def tracked_files() -> list[str]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [path.decode() for path in raw.split(b"\0") if path]


def tree_identity() -> str:
    digest = hashlib.sha256()
    for rel in tracked_files():
        digest.update(rel.encode() + b"\0" + hashlib.sha256((ROOT / rel).read_bytes()).digest())
    return digest.hexdigest()


def receipt_dir() -> pathlib.Path:
    path = pathlib.Path(tempfile.gettempdir()) / "bro-runtime" / hashlib.sha256(str(ROOT.resolve()).encode()).hexdigest()[:20] / "receipts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def receipt_path(session_id: str) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown")
    return receipt_dir() / f"{safe}.json"


CONDUCTOR_ROLE = "bro"
CANONICAL_CONDUCTOR_ID = "bro-000"
UNKNOWN_ROLE = "unknown"

# The canonical conductor may bootstrap — read the repository to orchestrate —
# without a bound task contract, but ONLY through direct read-only tools. Shell
# tools are excluded by construction: split_shell does not reject $() command
# substitution, so a "read-only" command such as `cat $(rm -rf x)` classifies as
# READ_LOCAL yet executes an arbitrary mutation. Gating on an explicit tool
# allowlist (never Bash/Shell/PowerShell) closes that vector; the capability set
# is the defence-in-depth second check. READ_EXTERNAL is excluded because a
# network fetch is not workspace-bound.
CONDUCTOR_BOOTSTRAP_TOOLS = frozenset({"Read", "Glob", "Grep"})
CONDUCTOR_BOOTSTRAP_CAPABILITIES = frozenset({"READ_LOCAL"})

# Review mode produces findings only, and a shell tool cannot be trusted as
# read-only: its arguments are not parsed, so `find . -delete` classifies as
# READ_LOCAL and `cat /etc/passwd` reads outside the workspace, both slipping past
# the read-only gate. Review therefore allows ONLY these structured read tools;
# every shell/command tool — and anything unrecognised — is denied. A
# command-specific parser can widen this later; deny-by-default is the safe floor.
REVIEW_READ_TOOLS = frozenset({"Read", "Glob", "Grep"})


def current_state(payload: dict) -> State:
    requested = os.getenv("BRO_MODE", load_json(POLICY_PATH)["default_mode"]).strip().lower()
    return State(
        requested,
        # An unset role must not inherit the conductor's exemptions. Defaulting to
        # a privileged identity means forgetting to configure one grants it.
        os.getenv("BRO_ROLE", UNKNOWN_ROLE).strip().lower() or UNKNOWN_ROLE,
        str(payload.get("session_id") or os.getenv("BRO_SESSION_ID") or "unknown"),
        os.getenv("BRO_AGENT_ID", "").strip().lower(),
    )


def is_conductor(state: State) -> bool:
    """The conductor is one exact identity, not anyone claiming the role name.

    There is exactly one Bro. Treating the role string alone as proof lets any
    session assert it by setting an environment variable, so the canonical agent
    id must agree.
    """
    return state.role == CONDUCTOR_ROLE and state.agent_id == CANONICAL_CONDUCTOR_ID


def read_all(session_id: str) -> dict:
    files = tracked_files()
    hashes = {}
    unreadable = []
    for rel in files:
        try:
            hashes[rel] = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        except OSError:
            # A tracked file deleted from the worktree must produce a receipt
            # failure, not an unhandled traceback: the canonical check below is
            # the intended gate and it cannot run if hashing crashes first.
            unreadable.append(rel)
    canonical = load_json(MANIFEST_PATH)["paths"]
    missing = [path for path in canonical if path not in hashes]
    if missing:
        raise RuntimeError(f"canonical files are missing or untracked: {missing}")
    if unreadable:
        raise RuntimeError(f"tracked files are unreadable: {unreadable}")
    receipt = {
        "schema": 1,
        "session_id": session_id,
        "commit": git("rev-parse", "HEAD"),
        "tree_identity": tree_identity(),
        "read_at_epoch": int(time.time()),
        "tracked_files": len(files),
        "tracked_bytes": sum((ROOT / rel).stat().st_size for rel in files),
        "canonical_paths": canonical,
        "hashes": hashes,
        "proof_boundary": "read-to-EOF and hashes",
    }
    receipt_path(session_id).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def load_receipt(session_id: str) -> dict | None:
    try:
        return load_json(receipt_path(session_id))
    except Exception:
        return None


def receipt_fresh(session_id: str) -> tuple[bool, str]:
    receipt = load_receipt(session_id)
    if not receipt:
        return False, "missing full-read receipt"
    age = int(time.time()) - int(receipt.get("read_at_epoch", 0))
    if age > int(load_json(POLICY_PATH)["receipt_max_age_seconds"]):
        return False, f"full-read receipt is stale ({age}s)"
    if receipt.get("tree_identity") != tree_identity():
        return False, "repository tree changed after full-read receipt"
    return True, "fresh"


def canonical_context() -> str:
    return "BRO CANONICAL STARTUP CONTEXT\n" + "".join(
        f"\n===== {path} =====\n{(ROOT / path).read_text(encoding='utf-8')} "
        for path in load_json(MANIFEST_PATH)["paths"]
    )


def _normalize_repo(value: object) -> str:
    normalized = str(value or "").strip().replace("\\", "/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    if normalized.startswith("git@") and ":" in normalized:
        normalized = normalized.split("@", 1)[1].replace(":", "/", 1)
    elif "://" in normalized:
        parsed = urlparse(normalized)
        normalized = (parsed.netloc + parsed.path).lstrip("/")
    return normalized.lower()


def enforce_grant_bindings(grant: dict, task: dict, mode: str) -> tuple[bool, str]:
    """Bind the mode grant to the task's repository, branch and mode.

    Shared by the tool path and the Stop gate: validate_mode_grant proves the grant
    is signed and bound to the session, agent, hashes, HEAD and tree, but it does not
    compare the repository, branch or mode against the task. Without this a correctly
    signed grant for another repository, branch or mode could authorize an action —
    or a completion. The grant's mode must equal the task's mode and the current
    runtime mode."""
    if _normalize_repo(grant.get("repository")) != _normalize_repo(task["repository"]["full_name"]):
        return False, "grant repository binding mismatch"
    if str(grant.get("branch")) != str(task["repository"]["branch"]):
        return False, "grant branch binding mismatch"
    if grant.get("mode") != task.get("mode") or grant.get("mode") != mode:
        return False, "grant mode binding mismatch"
    return True, "bound"


def authorize_classified_action(
    state: State,
    classification: ActionClassification,
    tool_input: dict,
) -> tuple[bool, str]:
    """Apply downstream mode, delegation, contract, grant, and scope policy.

    Tool parsing and release authorization are intentionally outside this module.
    """
    if state.mode not in {"review", "work", "release"}:
        return False, f"unknown BRO_MODE={state.mode!r}"
    if state.mode == "review":
        if classification.mutating:
            return False, "review mode is technically read-only"
        if classification.unknown:
            return False, "review mode denies unknown action"
        if classification.orchestration:
            return False, "review mode produces findings only and may not delegate execution"
        if classification.tool not in REVIEW_READ_TOOLS:
            return False, (f"review mode allows only structured read tools "
                           f"{sorted(REVIEW_READ_TOOLS)}; {classification.tool!r} is denied — a "
                           f"shell/command tool's unparsed arguments can smuggle a mutation or an "
                           f"out-of-workspace read past the read-only classification")
        return True, "allowed"
    if classification.orchestration:
        if not is_conductor(state):
            return False, ("only the canonical conductor may delegate; "
                           f"role={state.role!r} agent={state.agent_id!r}")
        return True, "conductor delegation permitted; the supervisor issues the lease"
    if classification.push:
        return False, "release actions must use Release Grant V3 control path"
    if classification.mutating and state.role == CONDUCTOR_ROLE:
        return False, "Bro remains free and may not perform repository mutation; delegate to a governed specialist"
    if classification.mutating and state.role == UNKNOWN_ROLE:
        return False, "unauthenticated role may not mutate; BRO_ROLE is unset"
    # Conductor bootstrap: the one canonical conductor may read the repository to
    # bootstrap and orchestrate without a task-contract bundle, but only through
    # an explicit allowlist of direct read-only tools (Read/Glob/Grep) — never a
    # shell tool, whose command substitution can smuggle a mutation past the
    # read-only classification. Bro never builds and can never mutate (denied
    # above), so an allowlisted read authorizes nothing a specialist would need a
    # contract for. The exemption requires the exact canonical identity
    # (is_conductor, not the role string); the capability check is a second,
    # defence-in-depth gate. Workspace binding and path escape are enforced
    # upstream in _bind_workspace, and the hook refreshes the full-read receipt
    # before this runs, so the path is workspace-bound and receipt-bound. Push,
    # orchestration, unknown and mutating actions were denied above or carry a
    # tool/capability outside these sets, and fall through to the full contract gate.
    if (is_conductor(state)
            and classification.tool in CONDUCTOR_BOOTSTRAP_TOOLS
            and classification.capabilities
            and all(cap in CONDUCTOR_BOOTSTRAP_CAPABILITIES for cap in classification.capabilities)):
        return True, "conductor read-only bootstrap: no task contract required for a machine-local read"
    try:
        bundle = load_contract_bundle_from_env(ROOT)
    except ContractError as exc:
        return False, f"task/agent/skill gate RED: {exc}"
    if state.agent_id and state.agent_id != bundle.agent["agent_id"].lower():
        return False, "BRO_AGENT_ID does not match bound agent profile"
    try:
        mode_grant = load_mode_grant_from_env(bundle, state.session_id, state.role, ROOT)
    except ContractError as exc:
        return False, f"mode grant RED: {exc}"
    bound, reason = enforce_grant_bindings(mode_grant, bundle.task, state.mode)
    if not bound:
        return False, reason
    if classification.mutating:
        try:
            enforce_scope(ROOT, list(classification.targets), bundle.task["scope"], bundle.task["prohibited_scope"])
        except SecurityError as exc:
            return False, f"scope gate RED: {exc}"
    return True, "allowed"
