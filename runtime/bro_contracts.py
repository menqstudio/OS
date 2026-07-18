from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Iterable

ROOT = pathlib.Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_RISKS = {"low", "medium", "high", "critical"}
ALLOWED_MODES = {"review", "work", "release"}
SKILL_KINDS = {"core", "additional", "reference"}


class ContractError(ValueError):
    pass


@dataclass(frozen=True)
class ContractBundle:
    task: dict[str, Any]
    task_sha256: str
    agent: dict[str, Any]
    skill_receipt: dict[str, Any]


def load_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError(f"missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"malformed JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object in {path}")
    return value


def canonical_json_sha256(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git(root: pathlib.Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=root, text=True, encoding="utf-8").strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ContractError(f"git command failed: git {' '.join(args)}") from exc


def current_commit(root: pathlib.Path = ROOT) -> str:
    return git(root, "rev-parse", "HEAD")


def current_tree_identity(root: pathlib.Path = ROOT) -> str:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    h = hashlib.sha256()
    for item in raw.split(b"\0"):
        if not item:
            continue
        rel = item.decode("utf-8")
        path = root / rel
        h.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()


def _require_exact_keys(value: dict[str, Any], required: set[str], optional: set[str] = set()) -> None:
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing:
        raise ContractError(f"missing keys: {sorted(missing)}")
    if extra:
        raise ContractError(f"unexpected keys: {sorted(extra)}")


def _require_string(value: Any, field: str, *, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    result = value.strip()
    if pattern and not pattern.fullmatch(result):
        raise ContractError(f"{field} has invalid format")
    return result


def _require_string_list(value: Any, field: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ContractError(f"{field} must be a {'non-empty ' if not allow_empty else ''}list")
    output: list[str] = []
    for index, item in enumerate(value):
        output.append(_require_string(item, f"{field}[{index}]"))
    if len(output) != len(set(output)):
        raise ContractError(f"{field} contains duplicates")
    return output


def safe_repo_path(value: str) -> str:
    raw = _require_string(value, "repository path").replace("\\", "/")
    path = pathlib.PurePosixPath(raw)
    if path.is_absolute() or raw.startswith("~") or any(part in {"", ".", ".."} for part in path.parts):
        raise ContractError(f"unsafe repository-relative path: {value!r}")
    if ":" in path.parts[0]:
        raise ContractError(f"unsafe drive-qualified path: {value!r}")
    return path.as_posix()


def _registered_skills(root: pathlib.Path) -> set[str]:
    index = load_json(root / "skills" / "index.json")
    skills = index.get("skills")
    if not isinstance(skills, list) or not all(isinstance(item, str) for item in skills):
        raise ContractError("skills/index.json has invalid skills list")
    return set(skills)


def _registered_pack_roles(root: pathlib.Path) -> dict[str, set[str]]:
    registry = load_json(root / "packs" / "registry.json")
    packs = registry.get("packs")
    if not isinstance(packs, list):
        raise ContractError("packs/registry.json has invalid packs list")
    output: dict[str, set[str]] = {}
    for pack in packs:
        if not isinstance(pack, dict):
            raise ContractError("pack registry entry must be an object")
        pack_id = _require_string(pack.get("id"), "pack.id", pattern=ID_RE)
        roles = pack.get("roles")
        if not isinstance(roles, list) or not all(isinstance(role, str) and role.strip() for role in roles):
            raise ContractError(f"pack {pack_id} has invalid roles")
        output[pack_id] = {role.strip() for role in roles}
    return output


def validate_task_contract(value: dict[str, Any], root: pathlib.Path = ROOT) -> dict[str, Any]:
    required = {
        "schema", "task_id", "title", "objective", "mode", "risk", "pack_id", "agent_id",
        "assignee_role", "scope", "prohibited_scope", "inputs", "core_skills", "additional_skills",
        "reference_skills", "done_criteria", "verification", "rollback", "repository"
    }
    _require_exact_keys(value, required)
    if value["schema"] != 1:
        raise ContractError("task contract schema must be 1")
    _require_string(value["task_id"], "task_id", pattern=ID_RE)
    _require_string(value["title"], "title")
    _require_string(value["objective"], "objective")
    mode = _require_string(value["mode"], "mode")
    if mode not in ALLOWED_MODES:
        raise ContractError(f"unsupported mode: {mode}")
    risk = _require_string(value["risk"], "risk")
    if risk not in ALLOWED_RISKS:
        raise ContractError(f"unsupported risk: {risk}")
    pack_id = _require_string(value["pack_id"], "pack_id", pattern=ID_RE)
    agent_id = _require_string(value["agent_id"], "agent_id", pattern=ID_RE)
    role = _require_string(value["assignee_role"], "assignee_role")

    pack_roles = _registered_pack_roles(root)
    if pack_id not in pack_roles:
        raise ContractError(f"unregistered pack_id: {pack_id}")
    if role not in pack_roles[pack_id]:
        raise ContractError(f"role {role!r} is not registered in pack {pack_id!r}")

    scope = [safe_repo_path(item) for item in _require_string_list(value["scope"], "scope", allow_empty=False)]
    prohibited = [safe_repo_path(item) for item in _require_string_list(value["prohibited_scope"], "prohibited_scope")]
    if set(scope) & set(prohibited):
        raise ContractError("scope and prohibited_scope overlap")
    [safe_repo_path(item) for item in _require_string_list(value["inputs"], "inputs")]

    skills = _registered_skills(root)
    core = _require_string_list(value["core_skills"], "core_skills", allow_empty=False)
    additional = _require_string_list(value["additional_skills"], "additional_skills")
    reference = _require_string_list(value["reference_skills"], "reference_skills")
    combined = core + additional + reference
    unknown = sorted(set(combined) - skills)
    if unknown:
        raise ContractError(f"unregistered skills: {unknown}")
    if len(combined) != len(set(combined)):
        raise ContractError("a skill may appear in only one skill class")

    _require_string_list(value["done_criteria"], "done_criteria", allow_empty=False)
    verification = value["verification"]
    if not isinstance(verification, dict):
        raise ContractError("verification must be an object")
    _require_exact_keys(verification, {"required", "verifier_agent_id", "verifier_role", "commands"})
    if not isinstance(verification["required"], bool):
        raise ContractError("verification.required must be boolean")
    verifier_id = verification["verifier_agent_id"]
    verifier_role = verification["verifier_role"]
    if risk in {"medium", "high", "critical"}:
        if verification["required"] is not True:
            raise ContractError(f"{risk} work requires independent verification")
        _require_string(verifier_id, "verification.verifier_agent_id", pattern=ID_RE)
        _require_string(verifier_role, "verification.verifier_role")
        if verifier_id == agent_id:
            raise ContractError("builder and verifier identities must differ")
    elif verifier_id is not None:
        _require_string(verifier_id, "verification.verifier_agent_id", pattern=ID_RE)
    if verifier_role is not None:
        _require_string(verifier_role, "verification.verifier_role")
    _require_string_list(verification["commands"], "verification.commands")

    rollback = value["rollback"]
    if not isinstance(rollback, dict):
        raise ContractError("rollback must be an object")
    _require_exact_keys(rollback, {"strategy", "commands"})
    _require_string(rollback["strategy"], "rollback.strategy")
    _require_string_list(rollback["commands"], "rollback.commands")

    repository = value["repository"]
    if not isinstance(repository, dict):
        raise ContractError("repository must be an object")
    _require_exact_keys(repository, {"full_name", "branch", "worktree", "base_commit", "tree_identity"})
    _require_string(repository["full_name"], "repository.full_name")
    _require_string(repository["branch"], "repository.branch")
    _require_string(repository["worktree"], "repository.worktree")
    _require_string(repository["base_commit"], "repository.base_commit", pattern=GIT_SHA_RE)
    _require_string(repository["tree_identity"], "repository.tree_identity", pattern=SHA256_RE)
    return value


def validate_agent_profile(value: dict[str, Any], root: pathlib.Path = ROOT) -> dict[str, Any]:
    required = {"schema", "agent_id", "pack_id", "role", "core_skills", "allowed_modes", "can_verify", "can_push"}
    _require_exact_keys(value, required)
    if value["schema"] != 1:
        raise ContractError("agent profile schema must be 1")
    _require_string(value["agent_id"], "agent_id", pattern=ID_RE)
    pack_id = _require_string(value["pack_id"], "pack_id", pattern=ID_RE)
    role = _require_string(value["role"], "role")
    pack_roles = _registered_pack_roles(root)
    if pack_id not in pack_roles or role not in pack_roles[pack_id]:
        raise ContractError("agent profile references an unregistered pack/role")
    skills = _require_string_list(value["core_skills"], "core_skills", allow_empty=False)
    unknown = sorted(set(skills) - _registered_skills(root))
    if unknown:
        raise ContractError(f"agent profile has unregistered skills: {unknown}")
    modes = _require_string_list(value["allowed_modes"], "allowed_modes", allow_empty=False)
    if set(modes) - ALLOWED_MODES:
        raise ContractError("agent profile has unsupported mode")
    if not isinstance(value["can_verify"], bool) or not isinstance(value["can_push"], bool):
        raise ContractError("can_verify and can_push must be boolean")
    if value["can_push"] and not (pack_id == "git-release-control" and role == "Push Executor"):
        raise ContractError("only git-release-control / Push Executor may have can_push=true")
    return value


def validate_skill_receipt(
    value: dict[str, Any],
    task: dict[str, Any],
    task_sha256: str,
    agent: dict[str, Any],
    root: pathlib.Path = ROOT,
    now: int | None = None,
) -> dict[str, Any]:
    required = {
        "schema", "receipt_id", "task_id", "agent_id", "contract_sha256", "repository_commit",
        "tree_identity", "loaded_at_epoch", "expires_at_epoch", "skills"
    }
    _require_exact_keys(value, required)
    if value["schema"] != 1:
        raise ContractError("skill receipt schema must be 1")
    _require_string(value["receipt_id"], "receipt_id", pattern=ID_RE)
    if value["task_id"] != task["task_id"]:
        raise ContractError("skill receipt task_id does not match task contract")
    if value["agent_id"] != task["agent_id"] or value["agent_id"] != agent["agent_id"]:
        raise ContractError("skill receipt agent_id binding mismatch")
    if value["contract_sha256"] != task_sha256:
        raise ContractError("skill receipt contract hash mismatch")
    if value["repository_commit"] != task["repository"]["base_commit"]:
        raise ContractError("skill receipt commit binding mismatch")
    if value["tree_identity"] != task["repository"]["tree_identity"]:
        raise ContractError("skill receipt tree binding mismatch")
    if not isinstance(value["loaded_at_epoch"], int) or not isinstance(value["expires_at_epoch"], int):
        raise ContractError("skill receipt timestamps must be integers")
    instant = int(time.time()) if now is None else now
    if value["loaded_at_epoch"] > instant + 60:
        raise ContractError("skill receipt load time is in the future")
    if value["expires_at_epoch"] <= instant:
        raise ContractError("skill receipt is expired")
    if value["expires_at_epoch"] <= value["loaded_at_epoch"]:
        raise ContractError("skill receipt expiry must follow load time")

    entries = value["skills"]
    if not isinstance(entries, list) or not entries:
        raise ContractError("skill receipt skills must be a non-empty list")
    seen: dict[str, str] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ContractError(f"skills[{index}] must be an object")
        _require_exact_keys(entry, {"id", "kind", "path", "sha256"})
        skill_id = _require_string(entry["id"], f"skills[{index}].id", pattern=ID_RE)
        kind = _require_string(entry["kind"], f"skills[{index}].kind")
        if kind not in SKILL_KINDS:
            raise ContractError(f"skills[{index}].kind is invalid")
        expected_path = f"skills/{skill_id}/SKILL.md"
        if safe_repo_path(entry["path"]) != expected_path:
            raise ContractError(f"skills[{index}].path must be {expected_path}")
        digest = _require_string(entry["sha256"], f"skills[{index}].sha256", pattern=SHA256_RE)
        path = root / expected_path
        if not path.is_file():
            raise ContractError(f"required skill body is missing: {expected_path}")
        if file_sha256(path) != digest:
            raise ContractError(f"skill hash mismatch: {skill_id}")
        if skill_id in seen:
            raise ContractError(f"duplicate skill receipt entry: {skill_id}")
        seen[skill_id] = kind

    required = {skill: "core" for skill in task["core_skills"]}
    required.update({skill: "additional" for skill in task["additional_skills"]})
    for skill_id, kind in required.items():
        if seen.get(skill_id) != kind:
            raise ContractError(f"missing or misclassified required skill: {skill_id} ({kind})")
    for skill_id in task["reference_skills"]:
        if skill_id in seen and seen[skill_id] != "reference":
            raise ContractError(f"reference skill is misclassified: {skill_id}")
    return value


def validate_release_grant(value: dict[str, Any], root: pathlib.Path = ROOT, now: int | None = None) -> dict[str, Any]:
    required = {
        "schema", "grant_id", "approved_by", "repository", "remote", "branch", "expected_head_sha",
        "expected_tree_identity", "allowed_action", "issued_at_epoch", "expires_at_epoch", "one_time", "consumed"
    }
    _require_exact_keys(value, required)
    if value["schema"] != 1:
        raise ContractError("release grant schema must be 1")
    _require_string(value["grant_id"], "grant_id", pattern=ID_RE)
    if value["approved_by"] != "Gev":
        raise ContractError("release grant must be approved by Gev")
    _require_string(value["repository"], "repository")
    _require_string(value["remote"], "remote")
    _require_string(value["branch"], "branch")
    _require_string(value["expected_head_sha"], "expected_head_sha", pattern=GIT_SHA_RE)
    _require_string(value["expected_tree_identity"], "expected_tree_identity", pattern=SHA256_RE)
    if value["allowed_action"] != "git-push":
        raise ContractError("release grant may authorize only git-push")
    if value["one_time"] is not True or value["consumed"] is not False:
        raise ContractError("release grant must be unused and one-time")
    if not isinstance(value["issued_at_epoch"], int) or not isinstance(value["expires_at_epoch"], int):
        raise ContractError("release grant timestamps must be integers")
    instant = int(time.time()) if now is None else now
    if value["issued_at_epoch"] > instant + 60 or value["expires_at_epoch"] <= instant:
        raise ContractError("release grant is not currently valid")
    if value["expected_head_sha"] != current_commit(root):
        raise ContractError("release grant is not bound to the current HEAD")
    if value["expected_tree_identity"] != current_tree_identity(root):
        raise ContractError("release grant is not bound to the current repository tree")
    return value


def load_contract_bundle_from_env(root: pathlib.Path = ROOT, now: int | None = None) -> ContractBundle:
    task_path = os.getenv("BRO_TASK_CONTRACT")
    agent_path = os.getenv("BRO_AGENT_PROFILE")
    receipt_path = os.getenv("BRO_SKILL_RECEIPT")
    missing = [name for name, value in {
        "BRO_TASK_CONTRACT": task_path,
        "BRO_AGENT_PROFILE": agent_path,
        "BRO_SKILL_RECEIPT": receipt_path,
    }.items() if not value]
    if missing:
        raise ContractError(f"missing environment bindings: {', '.join(missing)}")
    task = validate_task_contract(load_json(pathlib.Path(task_path)), root)
    agent = validate_agent_profile(load_json(pathlib.Path(agent_path)), root)
    if agent["agent_id"] != task["agent_id"] or agent["pack_id"] != task["pack_id"] or agent["role"] != task["assignee_role"]:
        raise ContractError("agent profile does not match task assignment")
    task_sha = canonical_json_sha256(task)
    receipt = validate_skill_receipt(load_json(pathlib.Path(receipt_path)), task, task_sha, agent, root, now)
    return ContractBundle(task=task, task_sha256=task_sha, agent=agent, skill_receipt=receipt)


def load_release_grant_from_env(root: pathlib.Path = ROOT, now: int | None = None) -> dict[str, Any]:
    path = os.getenv("BRO_RELEASE_GRANT")
    if not path:
        raise ContractError("missing BRO_RELEASE_GRANT")
    return validate_release_grant(load_json(pathlib.Path(path)), root, now)

# Security-v2 signed grants and schema execution.
def _signed_payload_from_env(env_name: str, key_env: str) -> dict[str, Any]:
    from bro_security import verify_signed_document, SecurityError
    path = os.getenv(env_name)
    if not path: raise ContractError(f"missing {env_name}")
    try: return verify_signed_document(load_json(pathlib.Path(path)), key_env)
    except SecurityError as exc: raise ContractError(str(exc)) from exc


def validate_mode_grant(payload: dict[str, Any], *, session_id: str, agent_id: str, role: str, task_sha256: str, root: pathlib.Path = ROOT, now: int | None = None) -> dict[str, Any]:
    required={"schema","grant_id","nonce","session_id","agent_id","role","mode","task_contract_sha256","repository","branch","head_sha","tree_identity","issued_at_epoch","expires_at_epoch"}
    # artifact_type/key_id are injected by the Ed25519 signer (broctl) and echoed
    # back by verify_artifact; accept them without weakening the required set.
    _require_exact_keys(payload, required, optional={"artifact_type", "key_id"})
    if payload["schema"] != 1 or payload["mode"] not in {"work","release"}: raise ContractError("invalid mode grant")
    instant=int(time.time()) if now is None else now
    if payload["issued_at_epoch"] > instant+60 or payload["expires_at_epoch"] <= instant: raise ContractError("mode grant expired or not yet valid")
    expected={"session_id":session_id,"agent_id":agent_id,"role":role,"task_contract_sha256":task_sha256,"head_sha":current_commit(root),"tree_identity":current_tree_identity(root)}
    for key,value in expected.items():
        if payload.get(key) != value: raise ContractError(f"mode grant binding mismatch: {key}")
    return payload


def load_mode_grant_from_env(bundle: ContractBundle, session_id: str, role: str, root: pathlib.Path = ROOT, now: int | None = None) -> dict[str, Any]:
    # Ed25519, not HMAC: the enforcement hook runs in the builder's process, so a
    # symmetric key would let the builder mint its own grant. verify_artifact
    # checks the signature against the operator-signed trusted-key registry, so
    # only the offline issuer key can authorize a mode.
    from bro_signature import SignatureError, load_trusted_keys, verify_artifact
    path = os.getenv("BRO_MODE_GRANT")
    if not path:
        raise ContractError("missing BRO_MODE_GRANT")
    try:
        payload = verify_artifact(load_json(pathlib.Path(path)), "mode-grant", load_trusted_keys(root), now=now)
    except SignatureError as exc:
        raise ContractError(str(exc)) from exc
    return validate_mode_grant(payload, session_id=session_id, agent_id=bundle.agent["agent_id"], role=role, task_sha256=bundle.task_sha256, root=root, now=now)


def validate_release_grant_v2(payload: dict[str, Any], root: pathlib.Path = ROOT, now: int | None = None) -> dict[str, Any]:
    required={"schema","grant_id","nonce","approved_by","repository","remote","branch","expected_head_sha","expected_tree_identity","allowed_action","issued_at_epoch","expires_at_epoch"}
    _require_exact_keys(payload, required)
    if payload["schema"] != 2 or payload["approved_by"] != "Gev" or payload["allowed_action"] != "git-push": raise ContractError("invalid release grant payload")
    instant=int(time.time()) if now is None else now
    if payload["issued_at_epoch"] > instant+60 or payload["expires_at_epoch"] <= instant: raise ContractError("release grant expired or not yet valid")
    if payload["expected_head_sha"] != current_commit(root): raise ContractError("release grant HEAD mismatch")
    if payload["expected_tree_identity"] != current_tree_identity(root): raise ContractError("release grant tree mismatch")
    return payload


def load_release_grant_v2_from_env(root: pathlib.Path = ROOT, now: int | None = None) -> dict[str, Any]:
    from bro_security import consume_nonce, SecurityError
    payload=_signed_payload_from_env("BRO_RELEASE_GRANT","BRO_RELEASE_GRANT_KEY")
    payload=validate_release_grant_v2(payload,root,now)
    ledger=os.getenv("BRO_RELEASE_LEDGER")
    if not ledger: raise ContractError("missing external BRO_RELEASE_LEDGER")
    try: consume_nonce(payload,pathlib.Path(ledger))
    except SecurityError as exc: raise ContractError(str(exc)) from exc
    return payload


def validate_registered_schemas(root: pathlib.Path = ROOT) -> int:
    try:
        import jsonschema
    except ImportError as exc:
        raise ContractError("jsonschema dependency is required") from exc
    registry=load_json(root/"schemas"/"registry.json")
    count=0
    for item in registry.get("schemas",[]):
        path=root/safe_repo_path(item["path"])
        schema=load_json(path)
        try:
            cls=jsonschema.validators.validator_for(schema)
            cls.check_schema(schema)
            cls(schema)
        except Exception as exc: raise ContractError(f"invalid registered schema {item.get('id')}: {exc}") from exc
        count+=1
    if count != len(registry.get("schemas",[])): raise ContractError("schema registry drift")
    return count
