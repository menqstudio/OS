"""Owner-side specialist authorization producer (Owner Authorization Phase 1).

Given an owner-authored task contract and agent profile, this completes the
governed authorization bundle: it produces the structural skill receipt (real
on-disk SKILL.md hashes) and the Ed25519-signed mode grant, which anchors the
task-contract, agent-profile and skill-receipt hashes. The mode grant is the one
signed artifact in the bundle; everything else is anchored by it.

This is the producer half of the flow the runtime already verifies
(load_contract_bundle_from_env + load_mode_grant_from_env). It never holds a
signing key of its own beyond the issuer key the owner passes in; a builder
process cannot run it to widen its own authority because it cannot sign.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

from bro_contracts import canonical_json_sha256
from bro_skill_receipt import build_skill_receipt
from broctl import sign_payload


def build_mode_grant_payload(
    task: dict,
    agent: dict,
    receipt: dict,
    *,
    session_id: str,
    role: str,
    mode: str,
    head_sha: str,
    tree_identity: str,
    now: int,
    ttl_seconds: int = 3600,
    grant_id: str = "mode-grant-1",
    nonce: str = "mode-grant-nonce-000001",
) -> dict:
    return {
        "schema": 1,
        "grant_id": grant_id,
        "nonce": nonce,
        "session_id": session_id,
        "agent_id": task["agent_id"],
        "role": role,
        "mode": mode,
        "task_contract_sha256": canonical_json_sha256(task),
        "agent_profile_sha256": canonical_json_sha256(agent),
        "skill_receipt_sha256": canonical_json_sha256(receipt),
        "repository": task["repository"]["full_name"],
        "branch": task["repository"]["branch"],
        "head_sha": head_sha,
        "tree_identity": tree_identity,
        "issued_at_epoch": now,
        "expires_at_epoch": now + ttl_seconds,
    }


def sign_mode_grant(payload: dict, issuer_key: dict, now: int) -> dict:
    body = {"artifact_type": "mode-grant", "key_id": issuer_key["key_id"],
            "issued_at_epoch": payload.get("issued_at_epoch", now), **payload}
    return sign_payload(issuer_key["private_key"], body)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Complete a specialist authorization bundle from a task contract + agent profile.")
    parser.add_argument("--task", required=True, help="owner-authored task-contract JSON")
    parser.add_argument("--agent", required=True, help="owner-authored agent-profile JSON")
    parser.add_argument("--issuer-key", required=True, help="issuer key file (broctl keygen --authority issuer)")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--role", required=True, help="operational role bound to the grant")
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--tree-identity", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--ttl-seconds", type=int, default=3600)
    args = parser.parse_args(argv)

    now = int(time.time())
    task = json.loads(pathlib.Path(args.task).read_text(encoding="utf-8"))
    agent = json.loads(pathlib.Path(args.agent).read_text(encoding="utf-8"))
    issuer_key = json.loads(pathlib.Path(args.issuer_key).read_text(encoding="utf-8"))
    out = pathlib.Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    receipt = build_skill_receipt(task, agent, root=ROOT, now=now, ttl_seconds=args.ttl_seconds)
    grant_payload = build_mode_grant_payload(
        task, agent, receipt, session_id=args.session_id, role=args.role, mode=task["mode"],
        head_sha=args.head_sha, tree_identity=args.tree_identity, now=now, ttl_seconds=args.ttl_seconds,
    )
    signed_grant = sign_mode_grant(grant_payload, issuer_key, now)

    files = {
        "BRO_TASK_CONTRACT": (out / "task-contract.json", task),
        "BRO_AGENT_PROFILE": (out / "agent-profile.json", agent),
        "BRO_SKILL_RECEIPT": (out / "skill-receipt.json", receipt),
        "BRO_MODE_GRANT": (out / "mode-grant.signed.json", signed_grant),
    }
    for path, obj in files.values():
        path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")

    print("GREEN: specialist authorization bundle produced. Bind these before the specialist session:")
    for env, (path, _obj) in files.items():
        print(f"  export {env}={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
