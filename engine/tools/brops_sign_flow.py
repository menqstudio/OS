"""Wave 3b-1 — compose supervisor evidence-production + signing into a bridge outcome.

The sidecar's real mode needs a `SupervisorResult`-shaped outcome whose attributes
`bridge/engine_adapter._receipt_of` reads (`receipt_envelope_jcs_b64`,
`receipt_signature_b64`, and the new `receipt_containment_evidence_b64`). This module is
the seam: given a completed run (by `{run_id, execution_attempt_id}`) it runs the
supervisor→store→attest→signer chain (design §1.3-1.5, §4) and returns that outcome, or
**fails closed** (raises) if the signer refuses — a completed run whose receipt is not
signed yields NO result (design §1.8).

STOP (design §5): this produces a real signed receipt, but the desktop still resolves
`NoTrustedManifest` ⇒ Blocks. No "Verified" is exposed in 3b-1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import brops_receipt_signer as signer
from brops_canonical import b64url, containment_evidence_bytes
from brops_evidence_store import EvidenceStore
from brops_supervisor_attest import RunStateProvider, produce_sign_request


class SignFlowError(Exception):
    """A completed run whose receipt could not be signed — fail-closed, no result."""


@dataclass
class SignedOutcome:
    """A `SupervisorResult`-shaped object carrying the SIGNED receipt wire for the bridge
    adapter. `status` is the run's terminal status; the signed material rides the extra
    `receipt_*` attributes `_receipt_of` reads."""

    task_id: str
    status: str
    _text: str
    exit_code: int | None = 0
    evidence: tuple[str, ...] = ()
    receipt_envelope_jcs_b64: str | None = None
    receipt_signature_b64: str | None = None
    receipt_containment_evidence_b64: str | None = None
    # The full sign-result union (incl. the forensic-attestation record, design §4.2),
    # kept for callers that persist it. Not read by `_receipt_of`.
    sign_result: Mapping[str, Any] = field(default_factory=dict)


def sign_completed_run(
    run_id: str,
    execution_attempt_id: str,
    *,
    run_state_provider: RunStateProvider,
    store: EvidenceStore,
    signing_key: Mapping[str, str],
    attestation_key: Mapping[str, str],
    supervisor_attestation_pubkey_hex: str,
) -> SignedOutcome:
    """Run the supervisor→signer chain for a completed attempt and return the signed
    outcome. Raises `SignFlowError` on any refusal (fail-closed)."""
    # The supervisor builds evidence from its own state (never caller-supplied) and
    # publishes artifacts to the store; the result is an attested sign-request.
    request = produce_sign_request(
        run_id,
        execution_attempt_id,
        run_state_provider=run_state_provider,
        store=store,
        attestation_key=attestation_key,
    )
    result = signer.sign(
        request,
        store=store,
        signing_key=signing_key,
        supervisor_attestation_pubkey_hex=supervisor_attestation_pubkey_hex,
        supervisor_key_id=attestation_key["key_id"],
    )
    if result.get("status") != "signed":
        raise SignFlowError(
            f"signer refused the receipt for {run_id}/{execution_attempt_id}: "
            f"{result.get('reason', 'unknown')}"
        )

    # The supervisor's own state supplies the output text + the exact containment bytes
    # the desktop persists (design §4.2). Re-fetch from the same provider.
    run_state = run_state_provider.terminal_run_state(run_id, execution_attempt_id)
    if run_state is None:  # pragma: no cover — produce_sign_request already validated it
        raise SignFlowError("run state vanished after signing")

    return SignedOutcome(
        task_id=run_id,
        status=run_state.decision,  # "completed"
        _text=run_state.output,
        exit_code=0,
        evidence=(f"evidence:receipt:{result['receipt_id']}",),
        receipt_envelope_jcs_b64=result["envelope_jcs_b64"],
        receipt_signature_b64=result["signature_b64"],
        receipt_containment_evidence_b64=b64url(
            containment_evidence_bytes(run_state.containment_evidence)
        ),
        sign_result=result,
    )
