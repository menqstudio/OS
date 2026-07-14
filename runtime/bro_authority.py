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


def _load_policy(root: pathlib.Path = ROOT) -> dict[str, Any]:
    path = root / "agents" / "authority-policy.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AuthorityError("missing agents/authority-policy.json") from exc
    except json.JSONDecodeError as exc:
        raise AuthorityError(f"invalid authority policy JSON: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise AuthorityError("unsupported authority policy schema")
    return value


def _matches_verifier_rule(role: str, policy: dict[str, Any]) -> bool:
    rules = policy.get("verifier_role_rules")
    if not isinstance(rules, dict):
        raise AuthorityError("authority policy verifier_role_rules missing")
    needles = rules.get("role_name_contains_any")
    if not isinstance(needles, list) or not all(isinstance(item, str) and item for item in needles):
        raise AuthorityError("authority policy verifier role matchers invalid")
    return any(needle.casefold() in role.casefold() for needle in needles)


def resolve_agent_authority(
    agent_id: str,
    pack_id: str,
    role: str,
    root: pathlib.Path = ROOT,
) -> AgentAuthority:
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

    if _matches_verifier_rule(role, policy):
        selected = policy["verifier_role_rules"]

    overrides = policy.get("exact_overrides")
    if not isinstance(overrides, list):
        raise AuthorityError("authority policy exact_overrides invalid")
    for item in overrides:
        if not isinstance(item, dict):
            raise AuthorityError("authority override must be an object")
        if item.get("pack_id") == pack_id and item.get("role") == role:
            selected = item
            break

    modes = selected.get("allowed_modes")
    if not isinstance(modes, list) or not modes or not all(isinstance(item, str) for item in modes):
        raise AuthorityError("resolved authority allowed_modes invalid")
    for field in ("can_build", "can_verify", "can_release"):
        if not isinstance(selected.get(field), bool):
            raise AuthorityError(f"resolved authority {field} invalid")
    risk = selected.get("risk_ceiling")
    if risk not in {"low", "medium", "high", "critical"}:
        raise AuthorityError("resolved authority risk_ceiling invalid")

    return AgentAuthority(
        agent_id=agent_id,
        pack_id=pack_id,
        role=role,
        can_build=selected["can_build"],
        can_verify=selected["can_verify"],
        can_release=selected["can_release"],
        allowed_modes=tuple(modes),
        risk_ceiling=risk,
    )


def validate_verifier_assignment(
    *,
    builder_agent_id: str,
    verifier_agent_id: str,
    verifier_role: str,
    risk: str,
    root: pathlib.Path = ROOT,
) -> AgentAuthority:
    identities = all_agent_identities(root)
    pair = identities.get(verifier_agent_id)
    if pair is None:
        raise AuthorityError("verifier_agent_id is not a canonical registered identity")
    verifier_pack, canonical_role = pair
    if verifier_role != canonical_role:
        raise AuthorityError("verifier role does not match canonical identity")
    if verifier_agent_id == builder_agent_id:
        raise AuthorityError("builder and verifier identities must differ")

    authority = resolve_agent_authority(
        verifier_agent_id,
        verifier_pack,
        verifier_role,
        root,
    )
    if not authority.can_verify:
        raise AuthorityError("assigned verifier lacks can_verify authority")

    policy = _load_policy(root)
    order = policy.get("risk_order")
    if not isinstance(order, list) or risk not in order or authority.risk_ceiling not in order:
        raise AuthorityError("risk policy invalid")
    if order.index(authority.risk_ceiling) < order.index(risk):
        raise AuthorityError("assigned verifier risk ceiling is insufficient")
    return authority


def validate_authority_policy(root: pathlib.Path = ROOT) -> int:
    identities = all_agent_identities(root)
    for agent_id, (pack_id, role) in identities.items():
        resolve_agent_authority(agent_id, pack_id, role, root)
    return len(identities)
