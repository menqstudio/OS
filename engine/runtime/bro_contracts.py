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
    """The one canonical workspace tree identity, shared with the repository state,
    the mode grant and the completion manifest so a single tree hash flows end to
    end. Delegated to bro_repository_state's implementation (tracked plus untracked
    non-ignored, symlink-aware) rather than a second, tracked-only hash."""
    from bro_repository_state import current_tree_identity as _canonical_tree_identity
    return _canonical_tree_identity(root)


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


# --- the contract path language ----------------------------------------------
# This language is stated twice on purpose: procedurally below, and as a regex in
# schemas/task-contract.schema.json. Either one alone would be decorative — the
# schema was never what actually validated, and it had already drifted into
# accepting strings this module rejects. ContractSchemaAgreementTests in
# tests/test_bro_contracts.py runs one corpus through BOTH and fails when they
# disagree, so a change here that is not mirrored there goes red.
_GLOB_METACHARACTERS = "*?["
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:[\\/]")


def _require_path_string(value: Any, label: str) -> str:
    """Like _require_string, but the value is NOT stripped.

    A path is compared and stored as literal text, so silently trimming it would
    make this validator accept an input the schema rejects — the exact class of
    drift being reconciled. Surrounding whitespace is refused instead.
    """
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    if value != value.strip():
        raise ContractError(f"{label} has leading or trailing whitespace: {value!r}")
    return value


def _require_path_list(value: Any, field: str, *, allow_empty: bool = True) -> list[str]:
    """Like _require_string_list, but entries reach the path gate unstripped.

    _require_string_list trims each entry, which would let a contract carry
    " docs" and be validated as "docs" — accepted here, rejected by the schema,
    and stored as the padded original. Paths are the one list where trimming is a
    correctness bug rather than a convenience.
    """
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ContractError(f"{field} must be a {'non-empty ' if not allow_empty else ''}list")
    output = [_require_path_string(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if len(output) != len(set(output)):
        raise ContractError(f"{field} contains duplicates")
    return output


def _path_segments(body: str, value: str, label: str) -> list[str]:
    """Split a '/'-separated path body, refusing every form that makes an entry
    mean something other than what it reads as."""
    if "\x00" in body:
        raise ContractError(f"{label} contains a NUL byte: {value!r}")
    if "\\" in body:
        # Refused outright rather than folded to '/'. Folding is why this
        # validator used to accept strings the schema rejects, and a backslash is
        # the classic way to smuggle a separator past a '..' rule on a platform
        # that treats it as one.
        raise ContractError(f"backslashes are not allowed in {label}: {value!r}")
    if any(ch in body for ch in _GLOB_METACHARACTERS):
        # Scopes must be provably literal (M-6): the enforcement layers historically
        # disagreed on glob semantics (prefix matching vs fnmatch), and a bare "*"
        # scope silently disabled confinement entirely. Rejecting glob
        # metacharacters here means a contract scope always names a real path or
        # directory prefix, and both enforcement layers agree on what it covers.
        raise ContractError(f"glob metacharacters are not allowed in {label}: {value!r}")
    segments = body.split("/")
    for segment in segments:
        if not segment:
            raise ContractError(f"{label} has an empty path segment: {value!r}")
        if segment != segment.strip():
            raise ContractError(f"{label} segment has leading or trailing whitespace: {value!r}")
        if segment in {".", ".."}:
            raise ContractError(f"{label} has a '.' or '..' segment: {value!r}")
        if ":" in segment:
            # A drive letter, a drive-relative "C:x", or a Windows alternate data
            # stream — none of which mean what the text appears to say.
            raise ContractError(f"{label} carries a drive or stream marker: {value!r}")
    return segments


def safe_repo_path(value: str) -> str:
    raw = _require_path_string(value, "repository path")
    if raw == ".":
        # The repository root itself. path_allowed matches "." literally and
        # nothing beneath it, so this names the root entry and grants no more.
        return "."
    if raw.startswith("/") or raw.startswith("~") or _DRIVE_PREFIX.match(raw):
        raise ContractError(f"unsafe repository-relative path: {value!r}")
    return "/".join(_path_segments(raw, value, "repository path"))


def is_absolute_scope(value: str) -> bool:
    """True when a scope entry names a location by absolute path rather than
    relative to this checkout. Shared with the enforcement layer so that "what
    counts as absolute" is decided in exactly one place."""
    if not isinstance(value, str):
        return False
    return value.startswith("/") or bool(_DRIVE_PREFIX.match(value))


def safe_work_path(value: str) -> str:
    """A task-scope entry: repo-relative, or an ABSOLUTE location.

    Bro must be able to hand a specialist a folder that is not part of this
    checkout (a UI specialist writing into a Desktop project), so a scope entry is
    allowed to be absolute. POSIX "/x" and Windows "C:/x" share one rule set:
    forward slashes only, no glob metacharacters, no "." or ".." segment, no empty
    segment, no drive or stream marker inside a segment. A bare filesystem root
    ("/" or "C:/") is refused — that is not a scope, it is the absence of one.
    UNC and device namespaces ("//host/share", "\\\\?\\C:\\x") are refused because
    they bypass normal path resolution.

    LIMITATION, stated rather than implied away: this is a syntactic gate. It
    cannot prove the named directory is not itself a symlink into somewhere else,
    because a scope may name a path that does not exist yet. Real containment is
    decided at use time against the real filesystem — bro_security.enforce_scope
    resolves both the target and the scope entry before comparing them, and
    bro_workspace.authorize_path re-checks every target against the
    operator-signed workspace root.
    """
    raw = _require_path_string(value, "task scope path")
    if not is_absolute_scope(raw):
        return safe_repo_path(raw)
    if raw.startswith("/"):
        prefix, body = "/", raw[1:]
    elif raw[2] != "/":
        raise ContractError(f"backslashes are not allowed in task scope path: {value!r}")
    else:
        prefix, body = raw[:3], raw[3:]
    if not body:
        raise ContractError(f"a filesystem root is not a scope: {value!r}")
    return prefix + "/".join(_path_segments(body, value, "absolute scope path"))


def _registered_skills(root: pathlib.Path) -> set[str]:
    index = load_json(root / "skills" / "index.json")
    skills = index.get("skills")
    if not isinstance(skills, list) or not all(isinstance(item, str) for item in skills):
        raise ContractError("skills/index.json has invalid skills list")
    return set(skills)


def _registered_pack_roles(root: pathlib.Path) -> dict[str, set[str]]:
    """Pack -> roles, derived exactly as the identity ordinals are derived.

    This used to read packs/registry.json["packs"][*]["roles"] directly, which
    omits the mandatory "Automation & Flow Engineer" role that bro_identity
    appends to every pack before assigning ordinals. The result was that all 52
    of those canonical, addressable identities failed contract validation as "not
    registered in pack" and could never be handed a task at all. Asking
    bro_identity for the map keeps one derivation instead of two that disagree.
    """
    # Deferred import: bro_identity is stdlib-only and imports nothing from this
    # module, so there is no cycle; deferring keeps this module's import surface flat.
    from bro_identity import IdentityError, pack_roles
    try:
        return {pack_id: set(roles) for pack_id, roles in pack_roles(root).items()}
    except IdentityError as exc:
        raise ContractError(f"pack/role registry is invalid: {exc}") from exc


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

    # The assignee's risk ceiling is policy, and policy that is never compared
    # against anything is decoration. This is the point where a task and a role
    # are bound together, so it is the point where the ceiling has to hold.
    # Deferred import: bro_authority imports bro_identity and nothing from this
    # module, so there is no cycle; deferring keeps the import surface flat.
    from bro_authority import AuthorityError, enforce_risk_ceiling
    try:
        enforce_risk_ceiling(pack_id, role, risk, root)
    except AuthorityError as exc:
        raise ContractError(str(exc)) from exc

    scope = [safe_work_path(item) for item in _require_path_list(value["scope"], "scope", allow_empty=False)]
    prohibited = [safe_work_path(item) for item in _require_path_list(value["prohibited_scope"], "prohibited_scope")]
    if set(scope) & set(prohibited):
        raise ContractError("scope and prohibited_scope overlap")
    # inputs are files read from THIS checkout, so they stay repo-relative — the
    # schema types them as repoPath and the validator must not quietly widen them.
    [safe_repo_path(item) for item in _require_path_list(value["inputs"], "inputs")]

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


MODE_GRANT_NONCE_RE = re.compile(r"^[A-Za-z0-9._-]{16,128}$")


def validate_mode_grant(payload: dict[str, Any], *, session_id: str, agent_id: str, role: str, task_sha256: str, agent_sha256: str, skill_sha256: str, root: pathlib.Path = ROOT, now: int | None = None) -> dict[str, Any]:
    required={"schema","grant_id","nonce","session_id","agent_id","role","mode","task_contract_sha256","agent_profile_sha256","skill_receipt_sha256","repository","branch","head_sha","tree_identity","issued_at_epoch","expires_at_epoch"}
    # artifact_type/key_id are injected by the Ed25519 signer (broctl) and echoed
    # back by verify_artifact; accept them without weakening the required set.
    _require_exact_keys(payload, required, optional={"artifact_type", "key_id"})
    if payload["schema"] != 1 or payload["mode"] not in {"work","release"}: raise ContractError("invalid mode grant")
    if not isinstance(payload["nonce"], str) or not MODE_GRANT_NONCE_RE.fullmatch(payload["nonce"]):
        raise ContractError("mode grant nonce is malformed")
    instant=int(time.time()) if now is None else now
    if payload["issued_at_epoch"] > instant+60 or payload["expires_at_epoch"] <= instant: raise ContractError("mode grant expired or not yet valid")
    # The mode grant is the only Ed25519-signed artifact in the bundle; anchoring
    # the agent-profile and skill-receipt hashes here makes the signed grant the
    # integrity root for those otherwise-unsigned structural artifacts — tampering
    # with either breaks a signed binding.
    expected={"session_id":session_id,"agent_id":agent_id,"role":role,"task_contract_sha256":task_sha256,"agent_profile_sha256":agent_sha256,"skill_receipt_sha256":skill_sha256,"head_sha":current_commit(root),"tree_identity":current_tree_identity(root)}
    for key,value in expected.items():
        if payload.get(key) != value: raise ContractError(f"mode grant binding mismatch: {key}")
    return payload


def _mode_grant_nonce_ledger(root: pathlib.Path = ROOT) -> pathlib.Path | None:
    """Resolve the mode-grant nonce ledger directory (L-1).

    The ledger is a deployment knob (BRO_MODE_GRANT_NONCE_LEDGER); when it is
    configured it MUST be an absolute path outside the repository — a ledger the
    builder can commit over is no ledger — and configuration errors fail closed."""
    raw = os.getenv("BRO_MODE_GRANT_NONCE_LEDGER")
    if not raw:
        return None
    path = pathlib.Path(raw).expanduser()
    if not path.is_absolute():
        raise ContractError("BRO_MODE_GRANT_NONCE_LEDGER must be an absolute path")
    try:
        path.resolve(strict=False).relative_to(root.resolve())
    except ValueError:
        return path
    raise ContractError("BRO_MODE_GRANT_NONCE_LEDGER must be outside the repository")


def bind_mode_grant_nonce(payload: dict[str, Any], ledger_dir: pathlib.Path) -> None:
    """Consume the mode-grant nonce against the ledger (L-1).

    A mode grant authorizes a whole session and is re-validated on every tool
    call, so the nonce is not strictly single-presentation like a release nonce.
    Instead the FIRST presentation atomically binds the nonce to the grant's full
    signed fingerprint; later presentations of the SAME grant re-validate
    idempotently, while any other grant reusing the nonce — a replay under a new
    session, head, tree or validity window — is rejected. O_EXCL makes the first
    write the only write, mirroring the release-grant nonce ledger."""
    nonce = str(payload.get("nonce", ""))
    if not MODE_GRANT_NONCE_RE.fullmatch(nonce):
        raise ContractError("mode grant nonce is malformed")
    binding = canonical_json_sha256({key: payload.get(key) for key in (
        "grant_id", "session_id", "agent_id", "role", "mode", "task_contract_sha256",
        "agent_profile_sha256", "skill_receipt_sha256", "repository", "branch",
        "head_sha", "tree_identity", "issued_at_epoch", "expires_at_epoch")})
    ledger_dir.mkdir(parents=True, exist_ok=True)
    record_path = ledger_dir / (hashlib.sha256(nonce.encode()).hexdigest() + ".bound")
    record = {
        "schema": 1,
        "nonce_sha256": record_path.stem,
        "binding_sha256": binding,
        "bound_at_epoch": int(time.time()),
    }
    try:
        fd = os.open(record_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            existing = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError("mode grant nonce ledger record is unreadable") from exc
        if existing.get("binding_sha256") != binding:
            raise ContractError("mode grant nonce was already consumed by a different grant")
        return
    except OSError as exc:
        raise ContractError(f"mode grant nonce ledger is unwritable: {exc}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, sort_keys=True)
    except Exception:
        try:
            record_path.unlink()
        except OSError:
            pass
        raise


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
    grant = validate_mode_grant(payload, session_id=session_id, agent_id=bundle.agent["agent_id"], role=role, task_sha256=bundle.task_sha256, agent_sha256=canonical_json_sha256(bundle.agent), skill_sha256=canonical_json_sha256(bundle.skill_receipt), root=root, now=now)
    ledger = _mode_grant_nonce_ledger(root)
    if ledger is not None:
        bind_mode_grant_nonce(grant, ledger)
    return grant


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
