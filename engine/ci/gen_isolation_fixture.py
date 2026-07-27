"""Wave 3b-1A — generate the fixture the Linux isolation-proof job provisions (audit P0-1).

Writes, under the base dir passed as argv[1]:
  signerkeys/brops-receipt-signer.json      — the receipt-signing private key (owner-only)
  attkeys/brops-supervisor-attestation.json — the supervisor-attestation private key
  att-pub                                   — the attestation PUBLIC key (hex)
  registry/config/trusted-keys.json         — a signed trusted-key registry
  operator-pin                              — the operator-root public key (hex) for the pin
  policy-bundle-sha                         — sha256 of the run's policy bundle (for the
                                              signer's expected-bundle env)
  state/ci-run-1__ci-attempt-1.json         — a VALID signed run record (lease + passing
                                              receipt + evidence chain) so the isolation
                                              job can run a real supervisor->signer signed
                                              round-trip (positive control) before the
                                              four denial proofs.

Run as the CI (login) user BEFORE ownership is tightened; the shell script then chowns the
private-key/state dirs to the service principals so the login user can no longer read them.
"""

import base64
import hashlib
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "runtime"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bro_evidence import event_hash
from bro_receipt import catalog_sha256
from broctl import build_registry, generate_key, sign_payload

RUN_ID = "ci-run-1"
ATTEMPT_ID = "ci-attempt-1"
TASK_ID = "ci-task-1"
AGENT = "agt-p01-r01"
CAND_HEAD = "a" * 40
CAND_TREE = "b" * 64
POLICY_BUNDLE = b"ci-policy-bundle"


def _raw():
    p = Ed25519PrivateKey.generate()
    priv = p.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    ).hex()
    pub = p.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()
    return priv, pub


def _evidence_chain(store: pathlib.Path, ev_key: dict, task_id: str, count: int = 2) -> list[str]:
    previous, ids, digest = None, [], ""
    for sequence in range(1, count + 1):
        event_id = f"{task_id}-e{sequence}"
        payload = {
            "artifact_type": "evidence-event", "key_id": ev_key["key_id"],
            "event_id": event_id, "sequence": sequence, "previous_event_hash": previous,
            "task_id": task_id, "event_type": "work-recorded", "agent_id": AGENT,
            "payload_hash": "a" * 64, "issued_at_epoch": 1,
        }
        (store / f"{event_id}.json").write_text(json.dumps(sign_payload(ev_key["private_key"], payload)))
        digest = event_hash(payload)
        previous = digest
        ids.append(event_id)
    head = {
        "artifact_type": "evidence-head", "key_id": ev_key["key_id"], "task_id": task_id,
        "final_event_hash": digest, "event_count": count, "last_sequence": count,
        "head_sequence": 1, "issued_at_epoch": 1,
    }
    (store / f"{task_id}.head.json").write_text(json.dumps(sign_payload(ev_key["private_key"], head)))
    return ids


def main(base: str) -> int:
    root = pathlib.Path(base)
    now = int(time.time())

    sig_priv, _ = _raw()
    att_priv, att_pub = _raw()
    (root / "signerkeys" / "brops-receipt-signer.json").write_text(
        json.dumps({"key_id": "rk", "private_key": sig_priv})
    )
    (root / "attkeys" / "brops-supervisor-attestation.json").write_text(
        json.dumps({"key_id": "sup-att-1", "private_key": att_priv})
    )
    (root / "att-pub").write_text(att_pub)

    keys = {a: generate_key(a, f"dev-{a}", False) for a in ("operator-root", "issuer", "evidence-recorder")}
    (root / "registry" / "config" / "trusted-keys.json").write_text(
        json.dumps(build_registry(list(keys.values()), now - 60, 86_400))
    )
    (root / "operator-pin").write_text(keys["operator-root"]["public_key"])
    (root / "policy-bundle-sha").write_text(hashlib.sha256(POLICY_BUNDLE).hexdigest())

    # A VALID signed run record (lease + passing receipt + evidence chain) for the
    # positive supervisor->signer round-trip. Identities match the signer's allow-sets.
    store = root / "store"
    event_ids = _evidence_chain(store, keys["evidence-recorder"], TASK_ID, 2)
    lease_payload = {
        "artifact_type": "execution-lease", "key_id": keys["issuer"]["key_id"], "schema": 1,
        "lease_id": "ci-lease-1", "nonce": "nonce-000000000001", "task_id": TASK_ID,
        "agent_id": AGENT, "session_id": "ci-session-1", "repository": "menqstudio/Bro",
        "branch": TASK_ID, "worktree": str(root / "wt"), "head_sha": CAND_HEAD,
        "tree_identity": CAND_TREE, "allowed_capabilities": ["EXECUTE_CODE", "WRITE_REPOSITORY"],
        "issued_at_epoch": now - 10, "expires_at_epoch": now + 3600, "max_tool_calls": 1,
        "task_class": "standard-builder", "protected_scope": [],
        "control_plane_digest": "e" * 64, "workspace_id": "ws-1",
    }
    receipt_payload = {
        "artifact_type": "evidence-event", "key_id": keys["evidence-recorder"]["key_id"],
        "receipt_id": "ci-receipt-1", "task_id": TASK_ID, "command": ["pytest", "-q"],
        "working_directory": str(root / "wt"), "candidate_head": CAND_HEAD,
        "candidate_tree": CAND_TREE, "exit_code": 0, "stdout_sha256": "c" * 64,
        "stderr_sha256": "d" * 64, "runner_id": "runner-1", "runner_platform": "linux",
        "started_at_epoch": now - 5, "finished_at_epoch": now - 1,
        "test_catalog_sha256": catalog_sha256(pathlib.Path(__file__).resolve().parents[1]),
        "issued_at_epoch": now - 1,
    }
    record = {
        "run_id": RUN_ID, "execution_attempt_id": ATTEMPT_ID, "decision": "completed",
        "contained": True,
        "task": {"task_id": TASK_ID, "repository": {
            "full_name": "menqstudio/Bro", "branch": TASK_ID, "worktree": str(root / "wt"),
            "base_commit": CAND_HEAD, "tree_identity": CAND_TREE}},
        "agent_id": AGENT, "session_id": "ci-session-1", "control_plane_digest": "e" * 64,
        "lease_document": sign_payload(keys["issuer"]["private_key"], lease_payload),
        "receipt_document": sign_payload(keys["evidence-recorder"]["private_key"], receipt_payload),
        "candidate_head": CAND_HEAD, "candidate_tree": CAND_TREE, "evidence_event_ids": event_ids,
        "lease_id": "ci-lease-1", "request_nonce": "nonce-ci-1", "receipt_id": "ci-receipt-1",
        "workspace_id": "ws-1", "install_id": "install-1", "supervisor_id": "sup-1",
        "executor_id": "exec-1", "builder_id": "builder-1", "policy_id": "policy-1",
        "policy_version": "1", "requested_at": str((now - 5) * 1000),
        "completed_at": str((now - 1) * 1000), "system": "sys", "output": "the reply",
        "history": [{"role": "user", "content": "hi"}], "generation_config": "{}",
        "containment_evidence": {"contained": True},
        "policy_bundle_b64": base64.urlsafe_b64encode(POLICY_BUNDLE).rstrip(b"=").decode(),
    }
    (root / "state" / f"{RUN_ID}__{ATTEMPT_ID}.json").write_text(json.dumps(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
