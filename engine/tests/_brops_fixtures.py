"""Test helper: the `brops_receipt_signer` fixtures three suites each carried a copy of.

`test_brops_isolation`, `test_brops_services` and `test_brops_receipt_signer` all need the same
three things: a raw Ed25519 keypair as hex, a terminal `RunState`, and the environment a signer
process reads its authorization policy from. The first two suites had the run state and the
environment field-for-field identical and all three had the keypair; `_chain_docs.py` says what
that costs — a per-suite copy of a shape is how the shape drifts, and a drifted fixture tests the
drift instead of the protocol.

The values are bound to each other, which is the reason to keep them in one place: the policy
`signer_env` states (`exec-1` / `builder-1` / `sup-1` / `policy-1` / `1` / the digest of
`POLICY_BUNDLE`) is the policy `run_state()` satisfies. Change one side alone and the signer
refuses for a reason no test is asking about.

Not a test module (no ``test_`` prefix), so unittest discovery ignores it.
"""
from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import brops_canonical as bc
from brops_supervisor_attest import RunState

#: The policy bundle `run_state()` carries and `signer_env()` pins the digest of.
POLICY_BUNDLE = b"pb"
#: The key id the supervisor attests under in these fixtures.
ATTESTATION_KEY_ID = "sup-att-1"


def keypair() -> tuple[str, str]:
    """A fresh Ed25519 keypair as (raw private hex, raw public hex)."""
    private = Ed25519PrivateKey.generate()
    raw_private = private.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    ).hex()
    raw_public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()
    return raw_private, raw_public


def run_state(**overrides) -> RunState:
    """A COMPLETED run that the policy in :func:`signer_env` authorizes."""
    base = dict(
        run_id="run-1", execution_attempt_id="attempt-1", lease_id="lease-1",
        request_nonce="00000000-0000-4000-8000-000000000000",
        receipt_id="11111111-1111-4111-8111-111111111111", decision="completed",
        workspace_id="ws-1", install_id="install-1", supervisor_id="sup-1",
        executor_id="exec-1", builder_id="builder-1", policy_id="policy-1", policy_version="1",
        requested_at="1000", completed_at="2000",
        system="s", history=[{"role": "user", "content": "hi"}], output="out",
        generation_config="{}", containment_evidence={"contained": True},
        policy_bundle=POLICY_BUNDLE,
    )
    base.update(overrides)
    return RunState(**base)


def signer_env(*, store_dir, keydir, attestation_pubkey: str) -> dict[str, str]:
    """The variables a signer process reads: where its store and key are, whose attestation it
    accepts, and its own authorization policy (P1-7) — the one :func:`run_state` satisfies."""
    return {
        "BROPS_EVIDENCE_STORE_DIR": str(store_dir),
        "BROPS_RECEIPT_SIGNER_KEYDIR": str(keydir),
        "BROPS_SUPERVISOR_ATTESTATION_PUBKEY": attestation_pubkey,
        "BROPS_SUPERVISOR_ATTESTATION_KEY_ID": ATTESTATION_KEY_ID,
        "BROPS_ALLOWED_EXECUTOR_IDS": "exec-1",
        "BROPS_ALLOWED_BUILDER_IDS": "builder-1",
        "BROPS_ALLOWED_SUPERVISOR_IDS": "sup-1",
        "BROPS_EXPECTED_POLICY_ID": "policy-1",
        "BROPS_EXPECTED_POLICY_VERSION": "1",
        "BROPS_EXPECTED_POLICY_BUNDLE_SHA256": bc.policy_bundle_sha256(POLICY_BUNDLE),
    }
