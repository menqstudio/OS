from __future__ import annotations

import json
import pathlib
import re

from bro_identity import all_agent_identities

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SkillEvolutionError(ValueError):
    pass


def validate_skill_evolution(value: dict, root: pathlib.Path = ROOT) -> dict:
    skills = set(json.loads((root / "skills" / "index.json").read_text(encoding="utf-8"))["skills"])
    agents = set(all_agent_identities(root))

    if value.get("skill_id") not in skills:
        raise SkillEvolutionError("unknown skill_id")
    if value.get("proposed_by_agent_id") not in agents:
        raise SkillEvolutionError("unknown proposer agent")

    review = value.get("independent_review") or {}
    owner = value.get("owner_approval") or {}
    candidate = value.get("candidate") or {}
    rollback = value.get("rollback") or {}

    if review.get("verifier_agent_id") == value.get("proposed_by_agent_id"):
        raise SkillEvolutionError("proposer cannot self-verify")
    if review.get("verifier_agent_id") not in agents:
        raise SkillEvolutionError("unknown verifier agent")

    for digest in (
        candidate.get("sha256"),
        candidate.get("baseline_sha256"),
        rollback.get("previous_sha256"),
    ):
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise SkillEvolutionError("invalid SHA-256 binding")

    status = value.get("promotion_status")
    if status in {"approved", "promoted"}:
        if review.get("verdict") != "green":
            raise SkillEvolutionError("promotion requires GREEN independent review")
        if owner.get("approved") is not True or owner.get("approved_by") != "Gev":
            raise SkillEvolutionError("promotion requires Gev approval")

    if status == "promoted" and candidate.get("sha256") == candidate.get("baseline_sha256"):
        raise SkillEvolutionError("promoted candidate must differ from baseline")

    return value
