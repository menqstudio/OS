"""Wave 3b — supervisor evidence-production + run attestation (design §1.3, §4.1, §4.4).

The supervisor is the trusted evidence producer (design §1.3, P0-2). This module is the
**only** path that builds the evidence the receipt signer consumes, and it is
deliberately **not an oracle**: its public entry point accepts only a
`{run_id, execution_attempt_id}` handle (design §4.4) and builds the evidence from the
supervisor's own terminal run state — it never signs or attests caller-supplied evidence
(P0-1). It then publishes every large artifact to the content-addressed store and signs a
detached attestation over `JCS(evidence)` with the supervisor-attestation key (its own
key class, unreachable by the sidecar).

The `RunStateProvider` protocol abstracts "the supervisor's own terminal run state for an
attempt" so the live supervisor and the tests plug the same contract. A real provider
reads validated lease + terminal status + policy + containment + the run's exact
system/history/output from the supervisor's internal state; it must refuse to return
state for an attempt that is not terminally `completed` and contained.
"""

from __future__ import annotations

import json
import os
import pathlib
import stat
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bro_signature import canonical_bytes
from brops_canonical import b64url
from brops_evidence_store import EvidenceStore
from brops_receipt_signer import ATTESTATION_PROTOCOL, SIGN_REQUEST_PROTOCOL
from brops_canonical import (
    containment_evidence_bytes,
    generation_config_bytes,
    history_bytes,
    output_bytes,
    system_bytes,
)

SUPERVISOR_ATTESTATION_KEY_FILENAME = "brops-supervisor-attestation.json"
DECISION_COMPLETED = "completed"


class AttestationError(Exception):
    """Fail-closed: the supervisor refuses to attest a run it cannot fully vouch for."""


@dataclass(frozen=True)
class RunState:
    """The authoritative facts the supervisor holds for one terminal, contained attempt.
    Every field is the supervisor's own — none comes from a caller (design §1.3)."""

    run_id: str
    execution_attempt_id: str
    lease_id: str
    request_nonce: str
    receipt_id: str
    decision: str
    workspace_id: str
    install_id: str
    supervisor_id: str
    executor_id: str
    builder_id: str
    policy_id: str
    policy_version: str
    requested_at: str
    completed_at: str
    # Large artifacts (published to the store, carried to the signer as handles):
    system: str
    history: Sequence[Mapping[str, str]]
    output: str
    generation_config: str
    containment_evidence: Mapping[str, Any]
    policy_bundle: bytes


class RunStateProvider(Protocol):
    """Supplies the supervisor's own terminal run state for an attempt. MUST refuse
    (return None / raise) for any attempt that is not terminally completed + contained."""

    def terminal_run_state(self, run_id: str, execution_attempt_id: str) -> RunState | None:
        ...


def load_attestation_key(keydir: os.PathLike[str] | str) -> dict[str, str]:
    """Load `{key_id, private_key(hex)}` for the supervisor-attestation key from its own
    dir (owner-only on POSIX). This key is distinct from the receipt-signing key."""
    directory = pathlib.Path(keydir).expanduser().resolve()
    if os.name == "posix" and directory.exists():
        mode = directory.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise ValueError(f"attestation key dir {directory} is group/other-accessible")
    path = directory / SUPERVISOR_ATTESTATION_KEY_FILENAME
    key = json.loads(path.read_text(encoding="utf-8"))
    if not key.get("key_id") or not key.get("private_key"):
        raise ValueError("attestation key file missing key_id/private_key")
    return {"key_id": str(key["key_id"]), "private_key": str(key["private_key"])}


def build_evidence(run_state: RunState, store: EvidenceStore) -> dict[str, Any]:
    """Publish each large artifact to the store and build the evidence object with
    handles + authoritative scalars (design §4.1). The handle IS the artifact's sha256."""
    if run_state.decision != DECISION_COMPLETED:
        raise AttestationError(f"refusing to attest a non-completed run: {run_state.decision}")
    system_handle = store.publish(system_bytes(run_state.system))
    history_handle = store.publish(history_bytes(run_state.history))
    output_handle = store.publish(output_bytes(run_state.output))
    generation_config_handle = store.publish(generation_config_bytes(run_state.generation_config))
    containment_handle = store.publish(containment_evidence_bytes(run_state.containment_evidence))
    policy_bundle_handle = store.publish(run_state.policy_bundle)
    return {
        "run_id": run_state.run_id,
        "execution_attempt_id": run_state.execution_attempt_id,
        "lease_id": run_state.lease_id,
        "request_nonce": run_state.request_nonce,
        "receipt_id": run_state.receipt_id,
        "decision": run_state.decision,
        "workspace_id": run_state.workspace_id,
        "install_id": run_state.install_id,
        "supervisor_id": run_state.supervisor_id,
        "executor_id": run_state.executor_id,
        "builder_id": run_state.builder_id,
        "policy_id": run_state.policy_id,
        "policy_version": run_state.policy_version,
        "requested_at": run_state.requested_at,
        "completed_at": run_state.completed_at,
        "system_handle": system_handle,
        "history_handle": history_handle,
        "output_handle": output_handle,
        "generation_config_handle": generation_config_handle,
        "containment_evidence_handle": containment_handle,
        "policy_bundle_handle": policy_bundle_handle,
    }


def attest(evidence: Mapping[str, Any], attestation_key: Mapping[str, str]) -> dict[str, Any]:
    """Sign a detached attestation over `JCS(evidence)` and wrap it in a
    `brops.sign-request.v1` (design §1.3, §4.1)."""
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(attestation_key["private_key"]))
    signature = private.sign(canonical_bytes(dict(evidence)))
    return {
        "protocol": SIGN_REQUEST_PROTOCOL,
        "attestation": {
            "attestation_protocol": ATTESTATION_PROTOCOL,
            "supervisor_key_id": attestation_key["key_id"],
            "sig": b64url(signature),
        },
        "evidence": dict(evidence),
    }


def produce_sign_request(
    run_id: str,
    execution_attempt_id: str,
    *,
    run_state_provider: RunStateProvider,
    store: EvidenceStore,
    attestation_key: Mapping[str, str],
) -> dict[str, Any]:
    """The supervisor's ONLY receipt-evidence entry (design §4.4): accepts a run handle,
    NEVER an evidence object. Builds evidence from the supervisor's own terminal state,
    publishes artifacts, and returns the attested `brops.sign-request.v1`."""
    if not run_id or not execution_attempt_id:
        raise AttestationError("run_id and execution_attempt_id are required")
    run_state = run_state_provider.terminal_run_state(run_id, execution_attempt_id)
    if run_state is None:
        raise AttestationError(
            f"no terminal completed run state for {run_id}/{execution_attempt_id}"
        )
    if run_state.run_id != run_id or run_state.execution_attempt_id != execution_attempt_id:
        raise AttestationError("run state identity does not match the requested handle")
    evidence = build_evidence(run_state, store)
    return attest(evidence, attestation_key)
