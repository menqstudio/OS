from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from typing import Any

from bro_identity import IdentityError, all_agent_identities, expected_agent_id

ROOT = pathlib.Path(__file__).resolve().parents[1]


class AuthorityError(ValueError):
    pass


@dataclass(frozen=True)
class AgentAuthority:
    agent_id: str
    pack_id: str
    role: str
    can_build: bool
    can_verify: bool
    can_release: bool
    allowed_modes: tuple[str, ...]
    risk_ceiling: str


def _json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AuthorityError(f"missing {path.relative_to(ROOT)}") from exc
    except json.JSONDecodeError as exc:
        raise AuthorityError(f"invalid JSON in {path.relative_to(ROOT)}: {exc}") from exc
    if not isinstance(value, dict):
        raise AuthorityError(f"{path.relative_to(ROOT)} must contain an object")
    return value


def _load_policy(root: pathlib.Path = ROOT) -> dict[str, Any]:
    value = _json(root / "agents" / "authority-policy.json")
    if value.get("schema") != 2:
        raise AuthorityError("unsupported authority policy schema")
    return value


def _designated_verifier_roles(root: pathlib.Path, policy: dict[str, Any]) -> set[tuple[str, str]]:
    rule = policy.get("designated_verifier")
    if not isinstance(rule, dict) or rule.get("strategy") != "final-declared-role-for-independent-verifier-pack":
        raise AuthorityError("designated verifier strategy invalid")
    packs = _json(root / "packs" / "registry.json").get("packs")
    if not isinstance(packs, list):
        raise AuthorityError("pack registry has no packs")
    designated: set[tuple[str, str]] = set()
    for pack in packs:
        if not isinstance(pack, dict):
            raise AuthorityError("pack registry entry must be an object")
        if pack.get("independent_verifier_required") is True:
            roles = pack.get("roles")
            if not isinstance(roles, list) or not roles or not all(isinstance(x, str) and x for x in roles):
                raise AuthorityError(f"pack {pack.get('id')} has invalid roles")
            designated.add((str(pack.get("id")), roles[-1]))
    for override in policy.get("exact_overrides", []):
        if isinstance(override, dict) and override.get("can_verify") is True:
            designated.add((str(override.get("pack_id")), str(override.get("role"))))
    return designated


def _authority_from(selected: dict[str, Any], *, agent_id: str, pack_id: str, role: str) -> AgentAuthority:
    modes = selected.get("allowed_modes")
    if not isinstance(modes, list) or not modes or not all(isinstance(item, str) for item in modes):
        raise AuthorityError("resolved authority allowed_modes invalid")
    for field in ("can_build", "can_verify", "can_release"):
        if not isinstance(selected.get(field), bool):
            raise AuthorityError(f"resolved authority {field} invalid")
    risk = selected.get("risk_ceiling")
    if risk not in {"low", "medium", "high", "critical"}:
        raise AuthorityError("resolved authority risk_ceiling invalid")
    return AgentAuthority(agent_id, pack_id, role, selected["can_build"], selected["can_verify"], selected["can_release"], tuple(modes), risk)


def resolve_agent_authority(agent_id: str, pack_id: str, role: str, root: pathlib.Path = ROOT) -> AgentAuthority:
    try:
        expected = expected_agent_id(pack_id, role, root)
    except IdentityError as exc:
        raise AuthorityError(str(exc)) from exc
    if agent_id != expected:
        raise AuthorityError(f"non-canonical agent_id: expected {expected} for {pack_id} / {role}")
    policy = _load_policy(root)
    selected = policy.get("default")
    if not isinstance(selected, dict):
        raise AuthorityError("authority policy default missing")
    if (pack_id, role) in _designated_verifier_roles(root, policy):
        selected = policy["designated_verifier"]
    overrides = policy.get("exact_overrides")
    if not isinstance(overrides, list):
        raise AuthorityError("authority policy exact_overrides invalid")
    for item in overrides:
        if not isinstance(item, dict):
            raise AuthorityError("authority override must be an object")
        if item.get("pack_id") == pack_id and item.get("role") == role:
            selected = item
            break
    return _authority_from(selected, agent_id=agent_id, pack_id=pack_id, role=role)


def validate_verifier_assignment(*, builder_agent_id: str, verifier_agent_id: str, verifier_role: str, risk: str, root: pathlib.Path = ROOT) -> AgentAuthority:
    identities = all_agent_identities(root)
    pair = identities.get(verifier_agent_id)
    if pair is None:
        raise AuthorityError("verifier_agent_id is not a canonical registered identity")
    verifier_pack, canonical_role = pair
    if verifier_role != canonical_role:
        raise AuthorityError("verifier role does not match canonical identity")
    if verifier_agent_id == builder_agent_id:
        raise AuthorityError("builder and verifier identities must differ")
    authority = resolve_agent_authority(verifier_agent_id, verifier_pack, verifier_role, root)
    if not authority.can_verify:
        raise AuthorityError("assigned verifier lacks designated can_verify authority")
    policy = _load_policy(root)
    order = policy.get("risk_order")
    if not isinstance(order, list) or risk not in order or authority.risk_ceiling not in order:
        raise AuthorityError("risk policy invalid")
    if order.index(authority.risk_ceiling) < order.index(risk):
        raise AuthorityError("assigned verifier risk ceiling is insufficient")
    return authority


def validate_authority_policy(root: pathlib.Path = ROOT) -> int:
    policy = _load_policy(root)
    designated = _designated_verifier_roles(root, policy)
    identities = all_agent_identities(root)
    resolved_designated: set[tuple[str, str]] = set()
    for agent_id, (pack_id, role) in identities.items():
        authority = resolve_agent_authority(agent_id, pack_id, role, root)
        if authority.can_verify:
            resolved_designated.add((pack_id, role))
    if resolved_designated != designated:
        raise AuthorityError("resolved verifier authority differs from designated verifier set")
    return len(identities)
