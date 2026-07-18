from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time
from typing import Any

from bro_authority import AuthorityError, validate_verifier_assignment
from bro_contracts import canonical_json_sha256
from bro_evidence import EvidenceError, validate_chain, validate_criterion_evidence
from bro_recovery import RecoveryError, _load_state
from bro_repository_state import resolve_state
from bro_security import SecurityError, verify_signed_document
from bro_signature import SignatureError, load_trusted_keys

ROOT = pathlib.Path(__file__).resolve().parents[1]
LEVELS = ["L1", "L2", "L3", "L4", "L5"]


class CompletionError(ValueError):
    pass


def _json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompletionError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CompletionError(f"{path} must contain an object")
    return value


def _signed_env(path_env: str, key_env: str) -> dict[str, Any]:
    raw = os.getenv(path_env)
    if not raw:
        raise CompletionError(f"missing {path_env}")
    try:
        return verify_signed_document(_json(pathlib.Path(raw)), key_env)
    except SecurityError as exc:
        raise CompletionError(str(exc)) from exc


def _external_dir(env_name: str) -> pathlib.Path:
    raw = os.getenv(env_name)
    if not raw:
        raise CompletionError(f"missing external {env_name}")
    path = pathlib.Path(raw).expanduser()
    if not path.is_absolute():
        raise CompletionError(f"{env_name} must be absolute")
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return resolved
    raise CompletionError(f"{env_name} must be outside the repository")


def validate_evidence_chain(task_id: str, event_ids: list[str],
                            root: pathlib.Path = ROOT) -> str:
    """Prove the submitted events are the whole chain, not a flattering prefix.

    The previous implementation checked backward linkage over a caller-supplied
    list. That catches dropping events from the front, because the first must
    have no predecessor, and says nothing about the back. A builder holding
    genuine signed events for work-started, tests-passed, tests-failed and
    rolled-back submitted the first two, and every check passed: the failure and
    the rollback that hid it were simply never mentioned. No forgery, just
    selective disclosure.

    It also verified with HMAC, which made the flaw unfixable in place. The
    verifying key is the signing key and the hook runs in the builder's own
    process, so any anchor the builder had to present it could also mint.
    Delegating to the Ed25519 path is what makes the head an authority.
    """
    try:
        return validate_chain(task_id, event_ids, load_trusted_keys(root),
                              store=_external_dir("BRO_EVIDENCE_STORE"))
    except (EvidenceError, SignatureError) as exc:
        raise CompletionError(str(exc)) from exc


def _no_pending_execution() -> None:
    ledger = _external_dir("BRO_EXECUTION_LEASE_LEDGER")
    if any(ledger.glob("*.active")) or any(ledger.glob("*.ambiguous")):
        raise CompletionError("pending or ambiguous execution lease exists")


def _no_pending_recovery(task_id: str) -> None:
    try:
        state = _load_state(task_id)
    except RecoveryError as exc:
        raise CompletionError(str(exc)) from exc
    if state and state.get("phase") != "MUTATION_RECORDED":
        raise CompletionError(f"unresolved recovery state blocks completion: {state.get('phase')}")


def _clean_repository(root: pathlib.Path) -> None:
    try:
        dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True, encoding="utf-8").strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CompletionError("cannot inspect repository cleanliness") from exc
    if dirty:
        raise CompletionError("repository is dirty")


def validate_completion(task: dict[str, Any], agent_id: str, root: pathlib.Path = ROOT) -> tuple[dict[str, Any], str]:
    manifest = _signed_env("BRO_COMPLETION_MANIFEST", "BRO_COMPLETION_KEY")
    required = {"schema", "task_id", "agent_id", "task_contract_sha256", "candidate_head", "candidate_tree", "done_criteria", "tests", "evidence_event_ids", "open_risks", "rollback_ready", "issued_at_epoch"}
    if set(manifest) != required or manifest.get("schema") != 1:
        raise CompletionError("invalid completion manifest shape")
    task_hash = canonical_json_sha256(task)
    for key, value in {"task_id": task["task_id"], "agent_id": agent_id, "task_contract_sha256": task_hash}.items():
        if manifest.get(key) != value:
            raise CompletionError(f"completion manifest binding mismatch: {key}")
    state = resolve_state(root)
    if manifest["candidate_head"] != state.head_sha or manifest["candidate_tree"] != state.tree_identity:
        raise CompletionError("completion candidate does not match current repository state")
    criteria = manifest.get("done_criteria")
    if not isinstance(criteria, list) or [x.get("criterion") for x in criteria if isinstance(x, dict)] != task["done_criteria"]:
        raise CompletionError("completion done criteria do not exactly match task")
    if any(not isinstance(x, dict) or x.get("status") != "satisfied" or not x.get("evidence_event_ids") for x in criteria):
        raise CompletionError("completion criterion lacks satisfied evidence")
    tests = manifest.get("tests")
    if not isinstance(tests, list) or not tests or any(not isinstance(x, dict) or x.get("status") != "passed" for x in tests):
        raise CompletionError("completion tests are not all passed")
    if manifest.get("open_risks") or manifest.get("rollback_ready") is not True:
        raise CompletionError("completion has open risks or rollback is not ready")
    chain_ids = manifest["evidence_event_ids"]
    validate_evidence_chain(task["task_id"], chain_ids, root)
    # The criteria above only had to cite *some* evidence id. Nothing tied those
    # ids to the chain that was just proven, so a criterion could rest on a real,
    # signed event belonging to a different chain entirely.
    try:
        for criterion in criteria:
            validate_criterion_evidence(task["task_id"], criterion["evidence_event_ids"], chain_ids)
        for test in tests:
            validate_criterion_evidence(task["task_id"], [test["evidence_event_id"]], chain_ids)
    except EvidenceError as exc:
        raise CompletionError(str(exc)) from exc
    _clean_repository(root)
    _no_pending_execution()
    _no_pending_recovery(task["task_id"])
    return manifest, task_hash


def validate_verifier_receipt(task: dict[str, Any], manifest: dict[str, Any], task_hash: str, root: pathlib.Path = ROOT) -> dict[str, Any]:
    receipt = _signed_env("BRO_VERIFIER_RECEIPT", "BRO_VERIFIER_RECEIPT_KEY")
    required = {"schema", "receipt_id", "task_id", "builder_agent_id", "verifier_agent_id", "verifier_role", "independence_level", "task_contract_sha256", "completion_manifest_sha256", "candidate_head", "candidate_tree", "evidence_event_ids", "verdict", "issued_at_epoch", "expires_at_epoch"}
    if set(receipt) != required or receipt.get("schema") != 1 or receipt.get("verdict") != "GREEN":
        raise CompletionError("invalid verifier receipt shape or verdict")
    verification = task["verification"]
    expected = {"task_id": task["task_id"], "builder_agent_id": task["agent_id"], "verifier_agent_id": verification["verifier_agent_id"], "verifier_role": verification["verifier_role"], "task_contract_sha256": task_hash, "completion_manifest_sha256": canonical_json_sha256(manifest), "candidate_head": manifest["candidate_head"], "candidate_tree": manifest["candidate_tree"]}
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise CompletionError(f"verifier receipt binding mismatch: {key}")
    now = int(time.time())
    if not isinstance(receipt["issued_at_epoch"], int) or not isinstance(receipt["expires_at_epoch"], int) or receipt["expires_at_epoch"] <= now:
        raise CompletionError("verifier receipt expired or invalid")
    try:
        validate_verifier_assignment(builder_agent_id=task["agent_id"], verifier_agent_id=receipt["verifier_agent_id"], verifier_role=receipt["verifier_role"], risk=task["risk"], root=root)
    except AuthorityError as exc:
        raise CompletionError(str(exc)) from exc
    policy = _json(root / "agents" / "authority-policy.json")
    minimum = policy["independence_minimum_by_risk"][task["risk"]]
    level = receipt["independence_level"]
    if level not in LEVELS or LEVELS.index(level) < LEVELS.index(minimum):
        raise CompletionError("verifier independence level is insufficient")
    validate_evidence_chain(task["task_id"], receipt["evidence_event_ids"])
    return receipt


def authorize_stop(task: dict[str, Any], agent_id: str, root: pathlib.Path = ROOT) -> tuple[bool, str]:
    try:
        manifest, task_hash = validate_completion(task, agent_id, root)
        if task["verification"]["required"]:
            validate_verifier_receipt(task, manifest, task_hash, root)
        return True, "completion and verification evidence GREEN"
    except CompletionError as exc:
        return False, f"completion gate RED: {exc}"


def authorize_conductor_stop(state, root: pathlib.Path = ROOT) -> tuple[bool, str]:
    """Let the conductor end a turn it did not execute.

    Demanding a builder's completion manifest from the conductor is a category
    error: Bro delegates and never builds, so the artifact can never exist and
    the turn can never end. The gate was not strict, it was unsatisfiable.

    This exemption is narrow by construction. It covers exactly one identity, it
    only applies when no task contract is bound, and it refuses a frozen session.
    Anything Bro claimed to complete lives under a task contract, and a bound
    contract routes back to the full gate, so the exemption cannot be used to
    escape evidence for work actually performed.

    Deliberately not covered: whether delegations this turn resolved. That needs
    the supervisor, which does not exist yet, so the honest position is that this
    exemption asserts nothing about delegated work.
    """
    from bro_policy import is_conductor

    if not is_conductor(state):
        return False, ("conductor stop exemption requires the canonical conductor; "
                       f"role={state.role!r} agent={state.agent_id!r}")
    if os.getenv("BRO_TASK_CONTRACT"):
        return False, ("conductor holds a task contract and is therefore an "
                       "executor for this turn; the completion gate applies")
    try:
        from bro_freeze import FreezeError, load_freeze

        if load_freeze(state.session_id) is not None:
            return False, ("session authority is frozen after a protected mutation; "
                           "it must terminate rather than finish")
    except FreezeError as exc:
        return False, f"freeze state gate RED: {exc}"
    return True, ("conductor turn: no task contract bound, so no builder evidence "
                  "is owed; startup receipt is current")
