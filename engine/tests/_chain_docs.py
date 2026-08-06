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

import json
from typing import Any, Mapping


def canonical(document: Mapping[str, Any]) -> bytes:
    """The same sorted-keys/compact encoding the supervisor content-addresses with."""
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def terminal_record(evidence_like: Mapping[str, Any], *, request_sha256: str,
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
