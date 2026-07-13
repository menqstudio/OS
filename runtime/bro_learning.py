from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


class LearningError(ValueError):
    pass


def validate_learning_registry(root: pathlib.Path = ROOT) -> dict:
    path = root / "learning" / "registry.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise LearningError(f"cannot load Learning SST: {exc}") from exc

    required_pipeline = [
        "observe", "record-evidence", "extract-lesson", "create-proposal",
        "sandbox-simulation", "benchmark", "independent-review",
        "owner-approval", "versioned-promotion", "monitor", "rollback",
    ]
    if value.get("pipeline") != required_pipeline:
        raise LearningError("learning pipeline changed or is incomplete")

    rules = value.get("promotion_rules") or {}
    required_true = {
        "sandbox_required",
        "benchmark_required",
        "independent_verifier_required",
        "owner_approval_required_for_high_impact",
        "rollback_required",
        "self_verification_forbidden",
        "secret_pii_ingestion_forbidden",
    }
    missing = sorted(key for key in required_true if rules.get(key) is not True)
    if missing:
        raise LearningError(f"learning safety rules missing: {missing}")

    policy = root / value.get("skill_evolution_policy", "")
    if not policy.is_file():
        raise LearningError("skill evolution policy is missing")
    return value
