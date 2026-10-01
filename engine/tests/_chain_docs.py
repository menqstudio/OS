"""Real protected-chain documents for the signer's §7 gate (audit round 3, R3-01).

The signer used to check only that `record_handle` / `lease_handle` /
`execution_receipt_handle` RESOLVED, so every suite seeded them with stub bytes like
``{"terminal_record":"COMPLETED"}`` and the gate passed. It now re-reads each document and
requires it to agree with the attested evidence, which is the reason the signer runs as a
separate OS principal at all — so the fixtures have to publish what the supervisor publishes.

Shared here rather than copied into four suites: a per-suite copy of the shape is how the shape
drifts, and a drifted fixture tests the drift instead of the protocol.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def canonical(document: Mapping[str, Any]) -> bytes:
    """The same sorted-keys/compact encoding the supervisor content-addresses with."""
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def terminal_record(evidence_like: Mapping[str, Any], *, request_sha256: str,
                    challenge_handle: str = "c" * 64,
                    challenge_registry_hash: str = "d" * 64,
                    challenge_registry_epoch: int = 7,
                    **overrides: Any) -> dict:
    """`brops.governed-turn-record.v1`, as `governed_supervisor.build_terminal_record` emits it.

    `request_sha256` is passed separately because the signer RECOMPUTES it from store bytes and
    never accepts a transported one — so the record is held against the signer's own arithmetic.
    """
    document = {
        "protocol": "brops.governed-turn-record.v1",
        "run_id": evidence_like["run_id"],
        "task_id": evidence_like["task_id"],
        "execution_attempt_id": evidence_like["execution_attempt_id"],
        "workspace_id": evidence_like["workspace_id"],
        "install_id": evidence_like["install_id"],
        "request_nonce": evidence_like["request_nonce"],
        "receipt_id": evidence_like["receipt_id"],
        "supervisor_id": evidence_like["supervisor_id"],
        "request_sha256": request_sha256,
        "system_handle": evidence_like["system_handle"],
        "history_handle": evidence_like["history_handle"],
        "generation_config_handle": evidence_like["generation_config_handle"],
        "output_handle": evidence_like["output_handle"],
        "containment_evidence_handle": evidence_like["containment_evidence_handle"],
        "decision": "completed",
        # The six the shape carried for the supervisor and not for the fixtures, added 2026-09-20.
        # Three of them are now in `_CHAIN_AGREEMENT["record_handle"]` and are read from the evidence,
        # so a fixture that omitted them would be refused `..._missing` rather than tested:
        "requested_at_ms": evidence_like["requested_at"],
        "challenge_accepted_at_ms": evidence_like["challenge_accepted_at_ms"],
        "completed_at_ms": evidence_like["completed_at"],
        # ...and three the evidence does not carry at all, so the signer cannot compare them. They are
        # here because the supervisor writes them and a fixture missing a field is a fixture testing a
        # document nobody publishes. `NM-XBIND-01` names exactly these three.
        "challenge_handle": challenge_handle,
        "challenge_registry_hash": challenge_registry_hash,
        "challenge_registry_epoch": challenge_registry_epoch,
    }
    document.update(overrides)
    return document


def execution_receipt(evidence_like: Mapping[str, Any], **overrides: Any) -> dict:
    document = {
        "protocol": "brops.execution-receipt.v1",
        "run_id": evidence_like["run_id"],
        "execution_attempt_id": evidence_like["execution_attempt_id"],
        "output_handle": evidence_like["output_handle"],
    }
    document.update(overrides)
    return document


def lease_payload(evidence_like: Mapping[str, Any], **overrides: Any) -> dict:
    document = {"execution_attempt_id": evidence_like["execution_attempt_id"]}
    document.update(overrides)
    return document


def run_evidence_chain(output_bytes: bytes, *, head_sequence: int,
                       output_sha256: str | None = None, cgroup: str = "cg-1") -> bytes:
    """A `brops.run-evidence-chain.v1` document with the three events `governed_recorder` writes.

    The payload KEYS are the recorder's (`proof/src/bin/governed_recorder.rs`, the `evidence_out`
    block): `lease-validated` carries `lease_path`/`lease_sha256`, `execution-launched` carries
    `cgroup` and the path and digest of both the executor and the launcher, `output-captured`
    carries `launcher_exit`/`output_bytes`/`output_sha256`. The VALUES are fixture values. Two
    suites each had a copy of this that claimed the recorder's exact shape, and the two copies
    disagreed with each other and with the recorder; `derive_evidence_from_chain` reads only the
    `output-captured` payload, which is the one part all three agreed on and the reason nothing
    noticed.

    The supervisor derives the evidence head from this and refuses a completion whose
    `output_handle` is not the `output-captured` digest (audit F-01), so a test that wants to
    model a lying broker or executor passes an `output_sha256` that does not match the bytes.
    """
    def sha(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    payloads = [
        ("lease-validated", {"lease_path": "/tcb/executor.lease", "lease_sha256": sha(b"lease")}),
        ("execution-launched", {
            "cgroup": cgroup,
            "executor_path": "/tcb/executor",
            "executor_sha256": sha(b"executor"),
            "launcher_path": "/tcb/launcher",
            "launcher_sha256": sha(b"launcher"),
        }),
        ("output-captured", {
            "launcher_exit": 0,
            "output_bytes": len(output_bytes),
            "output_sha256": output_sha256 or sha(output_bytes),
        }),
    ]
    previous, events = None, []
    for sequence, (event_type, payload) in enumerate(payloads, start=1):
        event = {
            "event_type": event_type,
            "payload": payload,
            "payload_sha256": sha(canonical(payload)),
            "previous_event_hash": previous,
            "sequence": sequence,
        }
        previous = sha(canonical(event))
        events.append(event)
    return canonical({
        "event_count": len(events),
        "events": events,
        "final_event_hash": previous,
        "head_sequence": head_sequence,
        "last_sequence": len(events),
        "protocol": "brops.run-evidence-chain.v1",
    })
