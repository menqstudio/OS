from __future__ import annotations

import hashlib
import json
import pathlib
import re
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENT_ID_RE = re.compile(r"^agt-p[0-9]{2}-r[0-9]{2}$")


class IdentityError(ValueError):
    pass


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise IdentityError(f"missing identity file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise IdentityError(f"malformed identity JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise IdentityError(f"identity file must contain an object: {path}")
    return value


def _identity_source(root: pathlib.Path = ROOT) -> list[dict[str, Any]]:
    registry = _load_json(root / "packs" / "registry.json")
    packs = registry.get("packs")
    if not isinstance(packs, list) or not packs:
        raise IdentityError("packs/registry.json has no packs")
    source: list[dict[str, Any]] = []
    seen_packs: set[str] = set()
    for pack in packs:
        if not isinstance(pack, dict):
            raise IdentityError("pack registry entry must be an object")
        pack_id = pack.get("id")
        roles = pack.get("roles")
        if not isinstance(pack_id, str) or not pack_id:
            raise IdentityError("pack id must be a non-empty string")
        if pack_id in seen_packs:
            raise IdentityError(f"duplicate pack id: {pack_id}")
        seen_packs.add(pack_id)
        if not isinstance(roles, list) or not roles or not all(isinstance(role, str) and role for role in roles):
            raise IdentityError(f"pack {pack_id} has invalid roles")
        if len(roles) != len(set(roles)):
            raise IdentityError(f"pack {pack_id} has duplicate roles")
        source.append({"pack_id": pack_id, "roles": roles})
    return source


def identity_fingerprint(root: pathlib.Path = ROOT) -> str:
    payload = json.dumps(_identity_source(root), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def expected_agent_id(pack_id: str, role: str, root: pathlib.Path = ROOT) -> str:
    for pack_ordinal, pack in enumerate(_identity_source(root), 1):
        if pack["pack_id"] != pack_id:
            continue
        for role_ordinal, registered_role in enumerate(pack["roles"], 1):
            if registered_role == role:
                return f"agt-p{pack_ordinal:02d}-r{role_ordinal:02d}"
        raise IdentityError(f"unregistered role {role!r} in pack {pack_id!r}")
    raise IdentityError(f"unregistered pack: {pack_id}")


def all_agent_identities(root: pathlib.Path = ROOT) -> dict[str, tuple[str, str]]:
    identities: dict[str, tuple[str, str]] = {}
    for pack_ordinal, pack in enumerate(_identity_source(root), 1):
        for role_ordinal, role in enumerate(pack["roles"], 1):
            agent_id = f"agt-p{pack_ordinal:02d}-r{role_ordinal:02d}"
            if agent_id in identities:
                raise IdentityError(f"duplicate derived agent id: {agent_id}")
            identities[agent_id] = (pack["pack_id"], role)
    return identities


def validate_identity_registry(root: pathlib.Path = ROOT) -> dict[str, Any]:
    registry = _load_json(root / "agents" / "registry.json")
    required = {
        "schema", "bro_id", "specialist_id_pattern", "derivation", "identity_source",
        "pack_count", "agent_count", "identity_fingerprint_sha256", "ordinals_are_one_based",
        "ordinals_are_immutable", "ids_are_never_reused"
    }
    if set(registry) != required:
        raise IdentityError("agents/registry.json has unexpected or missing keys")
    if registry["schema"] != 1 or registry["bro_id"] != "bro-000":
        raise IdentityError("invalid Bro identity registry header")
    if registry["specialist_id_pattern"] != r"^agt-p[0-9]{2}-r[0-9]{2}$":
        raise IdentityError("specialist ID pattern changed")
    if registry["identity_source"] != "packs/registry.json":
        raise IdentityError("identity source must be packs/registry.json")
    if registry["ordinals_are_one_based"] is not True or registry["ordinals_are_immutable"] is not True:
        raise IdentityError("agent ordinals must be one-based and immutable")
    if registry["ids_are_never_reused"] is not True:
        raise IdentityError("agent IDs must never be reused")
    source = _identity_source(root)
    identities = all_agent_identities(root)
    if registry["pack_count"] != len(source):
        raise IdentityError("pack count does not match identity source")
    if registry["agent_count"] != len(identities):
        raise IdentityError("agent count does not match identity source")
    if registry["identity_fingerprint_sha256"] != identity_fingerprint(root):
        raise IdentityError("pack/role identity fingerprint changed; reordering is forbidden")
    if not all(AGENT_ID_RE.fullmatch(agent_id) for agent_id in identities):
        raise IdentityError("derived agent ID violates the canonical pattern")
    return registry


def validate_agent_profile_identity(profile: dict[str, Any], root: pathlib.Path = ROOT) -> str:
    validate_identity_registry(root)
    agent_id = profile.get("agent_id")
    pack_id = profile.get("pack_id")
    role = profile.get("role")
    if not isinstance(agent_id, str) or not AGENT_ID_RE.fullmatch(agent_id):
        raise IdentityError("agent_id must use the canonical agt-pNN-rNN format")
    if not isinstance(pack_id, str) or not isinstance(role, str):
        raise IdentityError("agent profile must include pack_id and role")
    expected = expected_agent_id(pack_id, role, root)
    if agent_id != expected:
        raise IdentityError(f"agent_id mismatch: expected {expected} for {pack_id} / {role}")
    return expected
