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
