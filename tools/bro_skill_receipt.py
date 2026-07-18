"""Skill receipt producer (Owner Authorization Phase 1).

The runtime validates a BRO_SKILL_RECEIPT structurally: each entry's sha256 must
equal the on-disk skills/<id>/SKILL.md hash, and the receipt must bind the task's
canonical hash, base commit and tree identity (runtime/bro_contracts.py
validate_skill_receipt). Nothing produced one — this closes that gap.

The skill receipt is not itself signed: the Ed25519 mode grant anchors its hash
(skill_receipt_sha256), so tampering with a produced receipt breaks a signed
binding.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_contracts import canonical_json_sha256, file_sha256


def build_skill_receipt(
    task: dict,
    agent: dict,
    *,
    root: pathlib.Path = ROOT,
    now: int | None = None,
    ttl_seconds: int = 3600,
    receipt_id: str = "skill-receipt-1",
) -> dict:
    instant = int(time.time()) if now is None else now

    def entry(skill_id: str, kind: str) -> dict:
        rel = f"skills/{skill_id}/SKILL.md"
        return {"id": skill_id, "kind": kind, "path": rel, "sha256": file_sha256(root / rel)}

    skills = (
        [entry(s, "core") for s in task["core_skills"]]
        + [entry(s, "additional") for s in task["additional_skills"]]
        + [entry(s, "reference") for s in task["reference_skills"]]
    )
    return {
        "schema": 1,
        "receipt_id": receipt_id,
        "task_id": task["task_id"],
        "agent_id": task["agent_id"],
        "contract_sha256": canonical_json_sha256(task),
        "repository_commit": task["repository"]["base_commit"],
        "tree_identity": task["repository"]["tree_identity"],
        "loaded_at_epoch": instant,
        "expires_at_epoch": instant + ttl_seconds,
        "skills": skills,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a structural skill receipt from a task contract.")
    parser.add_argument("--task", required=True, help="path to the task-contract JSON")
    parser.add_argument("--agent", required=True, help="path to the agent-profile JSON")
    parser.add_argument("--out", required=True, help="output path for the skill receipt")
    parser.add_argument("--ttl-seconds", type=int, default=3600)
    parser.add_argument("--receipt-id", default="skill-receipt-1")
    args = parser.parse_args(argv)
    task = json.loads(pathlib.Path(args.task).read_text(encoding="utf-8"))
    agent = json.loads(pathlib.Path(args.agent).read_text(encoding="utf-8"))
    receipt = build_skill_receipt(
        task, agent, root=ROOT, ttl_seconds=args.ttl_seconds, receipt_id=args.receipt_id
    )
    pathlib.Path(args.out).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"GREEN: wrote skill receipt {args.receipt_id} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
