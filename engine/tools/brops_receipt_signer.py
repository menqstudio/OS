"""Wave 3b — the isolated brops.receipt.v1 signer (design §1.1-1.5, §4.1-4.2).

This is the ONLY component that holds the receipt-signing private key. It is designed to
run as a **separate OS process under a dedicated principal** (design §1.1); its private
key lives in its own store, unreachable by the sidecar (§1.2). It is **not** a
`sign(arbitrary_bytes)` oracle: it accepts only a supervisor-attested, structured
`brops.sign-request.v1` (§4.1), independently validates the run, reads every large input
from the content-addressed store **by handle**, recomputes every hash, and **constructs
the 21-field receipt envelope itself** before signing the exact canonical bytes (§1.4).

Authenticity vs correctness (design §1.3): the supervisor is the trusted evidence
producer and the signer's only authenticated caller. The signer verifies the supervisor
attestation FIRST (against a pinned supervisor-attestation public key) — that is
authenticity. It then recomputes hashes from the store bytes — that is correctness. Both
are required; either failing is a fail-closed `refused` (never a partial/unsigned
success).

STOP (Wave 3b-1, design §5): this slice produces real signatures, but the desktop still
resolves `NoTrustedManifest` ⇒ every governed turn Blocks. No "Verified" is exposed until
the whole 3b chain is GREEN.
"""

from __future__ import annotations

import json
import os
import pathlib
import stat
from dataclasses import dataclass
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from bro_signature import canonical_bytes
from brops_canonical import (
    RECEIPT_PROTOCOL,
    b64url,
    receipt_envelope_bytes,
    request_sha256,
)
from brops_evidence_store import EvidenceStore, EvidenceStoreError

ATTESTATION_PROTOCOL = "brops.run-attestation.v1"
SIGN_REQUEST_PROTOCOL = "brops.sign-request.v1"
SIGN_RESULT_PROTOCOL = "brops.sign-result.v1"
DECISION_COMPLETED = "completed"

# The receipt-signing key is its OWN key class, distinct from issuer/evidence/builder.
RECEIPT_SIGNER_KEY_FILENAME = "brops-receipt-signer.json"

# Evidence fields the signer copies verbatim into the receipt (design §4.1 authoritative
# scalars). The five *_handle fields are resolved through the store separately.
_EVIDENCE_SCALARS = (
    "run_id",
    "execution_attempt_id",
    "lease_id",
    "request_nonce",
    "receipt_id",
    "decision",
    "workspace_id",
    "install_id",
    "supervisor_id",
    "executor_id",
    "builder_id",
    "policy_id",
    "policy_version",
    "requested_at",
    "completed_at",
)
_EVIDENCE_HANDLES = (
    "system_handle",
    "history_handle",
    "output_handle",
    "generation_config_handle",
    "containment_evidence_handle",
    "policy_bundle_handle",
)


@dataclass(frozen=True)
class SignerAuthorizationPolicy:
    """Operator-provisioned authorization the signer enforces INDEPENDENTLY of the
    attestation (design §1.5, audit P1-7). Even a validly-attested run is refused unless
    its identities are in the allow-sets, its policy is in force, its policy bundle matches
    the authorized digest, and its timestamps are sane + not in the future beyond skew."""

    allowed_executor_ids: frozenset[str]
    allowed_builder_ids: frozenset[str]
    allowed_supervisor_ids: frozenset[str]
    expected_policy_id: str
    expected_policy_version: str
    expected_policy_bundle_sha256: str
    max_future_skew_ms: int = 300_000  # 5 minutes


class SignRefused(Exception):
    """A fail-closed refusal carrying an enum reason (design §4.2). Never a signature."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def _refuse(reason: str, detail: str = "") -> "SignRefused":
    return SignRefused(reason, detail)


def load_receipt_signing_key(keydir: os.PathLike[str] | str) -> dict[str, str]:
    """Load `{key_id, private_key(hex)}` from the signer's own key dir. On POSIX the dir
    must be owner-only (mirrors `broctl._require_private_key_dir`)."""
    directory = pathlib.Path(keydir).expanduser().resolve()
    if os.name == "posix" and directory.exists():
        mode = directory.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise ValueError(f"receipt-signer key dir {directory} is group/other-accessible")
    path = directory / RECEIPT_SIGNER_KEY_FILENAME
    key = json.loads(path.read_text(encoding="utf-8"))
    if not key.get("key_id") or not key.get("private_key"):
        raise ValueError("receipt-signer key file missing key_id/private_key")
    return {"key_id": str(key["key_id"]), "private_key": str(key["private_key"])}


def _verify_attestation(
    sign_request: Mapping[str, Any], attestation_pubkey_hex: str, supervisor_key_id: str
) -> Mapping[str, Any]:
    """Verify the supervisor attestation over `JCS(evidence)` (design §1.3, §1.5 item 0)
    against the pinned supervisor-attestation public key. Returns the trusted evidence."""
    if not isinstance(sign_request, Mapping):
        raise _refuse("malformed", "sign-request is not an object")
    if sign_request.get("protocol") != SIGN_REQUEST_PROTOCOL:
        raise _refuse("malformed", "wrong sign-request protocol")
    attestation = sign_request.get("attestation")
    evidence = sign_request.get("evidence")
    if not isinstance(attestation, Mapping) or not isinstance(evidence, Mapping):
        raise _refuse("malformed", "missing attestation/evidence")
    if attestation.get("attestation_protocol") != ATTESTATION_PROTOCOL:
        raise _refuse("attestation_invalid", "wrong attestation protocol")
    if attestation.get("supervisor_key_id") != supervisor_key_id:
        raise _refuse("attestation_invalid", "attestation key id is not the pinned key")
    sig_b64 = attestation.get("sig")
    if not isinstance(sig_b64, str) or not sig_b64:
        raise _refuse("attestation_invalid", "missing attestation signature")
    # base64url (no pad) → raw 64-byte Ed25519 signature.
    try:
        padding = "=" * (-len(sig_b64) % 4)
        import base64

        signature = base64.urlsafe_b64decode(sig_b64 + padding)
    except Exception as exc:  # noqa: BLE001 — any decode failure is fail-closed
        raise _refuse("attestation_invalid", f"attestation signature not base64url: {exc}")
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(attestation_pubkey_hex))
        pub.verify(signature, canonical_bytes(dict(evidence)))
    except (InvalidSignature, ValueError) as exc:
        raise _refuse("attestation_invalid", f"attestation does not verify: {exc}")
    return evidence


def _authorize(evidence: Mapping[str, Any], policy: SignerAuthorizationPolicy, now_ms: int) -> None:
    """The signer's independent authorization gate (design §1.5; audit P1-7). Handle
    checks (item 3, 5) and the request binding (item 2) happen where the store is read."""
    for field in _EVIDENCE_SCALARS:
        value = evidence.get(field)
        if not isinstance(value, str) or value == "":
            raise _refuse("malformed", f"evidence.{field} must be a non-empty string")
    for field in _EVIDENCE_HANDLES:
        value = evidence.get(field)
        if not isinstance(value, str) or len(value) != 64 or any(
            c not in "0123456789abcdef" for c in value
        ):
            raise _refuse("malformed", f"evidence.{field} must be a 64-hex handle")
    if evidence["decision"] != DECISION_COMPLETED:
        raise _refuse("not_completed", evidence["decision"])

    # Identity (item 6): each principal must be in its operator-provisioned allow-set —
    # non-empty is NOT enough (audit P1-7).
    if evidence["executor_id"] not in policy.allowed_executor_ids:
        raise _refuse("identity_denied", f"executor {evidence['executor_id']} not allowed")
    if evidence["builder_id"] not in policy.allowed_builder_ids:
        raise _refuse("identity_denied", f"builder {evidence['builder_id']} not allowed")
    if evidence["supervisor_id"] not in policy.allowed_supervisor_ids:
        raise _refuse("identity_denied", f"supervisor {evidence['supervisor_id']} not allowed")

    # Policy in force (item 4): the run's policy id + version must be the authorized ones.
    if (
        evidence["policy_id"] != policy.expected_policy_id
        or evidence["policy_version"] != policy.expected_policy_version
    ):
        raise _refuse("policy_mismatch", "policy id/version is not in force")

    # Timestamps (item 7): integer ms, requested <= completed, and neither in the future
    # beyond the allowed skew (defends a rolled-forward clock / replayed future receipt).
    try:
        requested = int(evidence["requested_at"])
        completed = int(evidence["completed_at"])
    except ValueError:
        raise _refuse("timestamp_invalid", "requested_at/completed_at are not ms integers")
    if requested < 0 or completed < 0 or requested > completed:
        raise _refuse("timestamp_invalid", f"{requested} > {completed}")
    horizon = now_ms + policy.max_future_skew_ms
    if requested > horizon or completed > horizon:
        raise _refuse("timestamp_invalid", "timestamp is in the future beyond the allowed skew")


def _resolve_handles(evidence: Mapping[str, Any], store: EvidenceStore) -> dict[str, str]:
    """Read each artifact by handle, confirming `sha256(bytes) == handle` (design §1.5
    item 3/5). The verified handle IS the receipt's `*_sha256` (content-addressed)."""
    resolved: dict[str, str] = {}
    for field in _EVIDENCE_HANDLES:
        handle = evidence[field]
        try:
            store.read(handle)  # reads + verifies sha256(bytes) == handle, else raises
        except EvidenceStoreError as exc:
            # A missing artifact is handle_missing; a corrupted one is hash_mismatch.
            if store.has(handle):
                raise _refuse("hash_mismatch", str(exc))
            reason = "containment_missing" if field == "containment_evidence_handle" else "handle_missing"
            raise _refuse(reason, str(exc))
        resolved[field] = handle
    return resolved


def sign(
    sign_request: Mapping[str, Any],
    *,
    store: EvidenceStore,
    signing_key: Mapping[str, str],
    supervisor_attestation_pubkey_hex: str,
    supervisor_key_id: str,
    policy: SignerAuthorizationPolicy,
    now_ms: int,
) -> dict[str, Any]:
    """Verify → authorize → validate → construct → sign. Returns a `brops.sign-result.v1`
    union (design §4.2): `{status:"signed", ...}` or `{status:"refused", reason, ...}`.
    Never raises for a refusal — the caller always gets a structured result to relay."""
    receipt_id = None
    try:
        if isinstance(sign_request, Mapping) and isinstance(sign_request.get("evidence"), Mapping):
            rid = sign_request["evidence"].get("receipt_id")
            receipt_id = rid if isinstance(rid, str) else None

        evidence = _verify_attestation(
            sign_request, supervisor_attestation_pubkey_hex, supervisor_key_id
        )
        receipt_id = evidence.get("receipt_id") if isinstance(evidence.get("receipt_id"), str) else receipt_id
        _authorize(evidence, policy, now_ms)
        handles = _resolve_handles(evidence, store)
        # Policy-bundle authority (audit P1-7): the run's policy bundle must be the exact
        # operator-authorized digest, not merely a well-formed handle.
        if handles["policy_bundle_handle"] != policy.expected_policy_bundle_sha256:
            raise _refuse("policy_mismatch", "policy bundle digest is not the authorized one")

        # Recompute request_sha256 independently from the derived hashes (design §1.5
        # item 2) — never trust an incoming request_sha256.
        req_sha = request_sha256(
            workspace_id=evidence["workspace_id"],
            install_id=evidence["install_id"],
            request_nonce=evidence["request_nonce"],
            system_sha256=handles["system_handle"],
            history_sha256=handles["history_handle"],
            generation_config_sha256=handles["generation_config_handle"],
            requested_at=evidence["requested_at"],
        )

        # Construct the 21-field envelope ourselves (design §1.4). The verified handles
        # ARE the content-addressed `*_sha256` values.
        fields = {
            "protocol": RECEIPT_PROTOCOL,
            "key_id": signing_key["key_id"],
            "receipt_id": evidence["receipt_id"],
            "decision": DECISION_COMPLETED,
            "request_nonce": evidence["request_nonce"],
            "request_sha256": req_sha,
            "requested_at": evidence["requested_at"],
            "completed_at": evidence["completed_at"],
            "workspace_id": evidence["workspace_id"],
            "install_id": evidence["install_id"],
            "supervisor_id": evidence["supervisor_id"],
            "executor_id": evidence["executor_id"],
            "builder_id": evidence["builder_id"],
            "policy_id": evidence["policy_id"],
            "policy_version": evidence["policy_version"],
            "system_sha256": handles["system_handle"],
            "history_sha256": handles["history_handle"],
            "output_sha256": handles["output_handle"],
            "generation_config_sha256": handles["generation_config_handle"],
            "containment_evidence_sha256": handles["containment_evidence_handle"],
            "policy_bundle_sha256": handles["policy_bundle_handle"],
        }
        try:
            envelope_bytes = receipt_envelope_bytes(fields)
        except ValueError as exc:
            raise _refuse("malformed", f"constructed envelope invalid: {exc}")

        private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(signing_key["private_key"]))
        signature = private.sign(envelope_bytes)

        return {
            "protocol": SIGN_RESULT_PROTOCOL,
            "status": "signed",
            "receipt_id": evidence["receipt_id"],
            "envelope_jcs_b64": b64url(envelope_bytes),
            "signature_b64": b64url(signature),
            "key_id": signing_key["key_id"],
            # Durable forensic-attestation record (design §4.2, P1-3): echo what we verified.
            "attestation_evidence_jcs_b64": b64url(canonical_bytes(dict(evidence))),
            "attestation_signature_b64": sign_request["attestation"]["sig"],
            "supervisor_attestation_key_id": supervisor_key_id,
            "run_id": evidence["run_id"],
            "execution_attempt_id": evidence["execution_attempt_id"],
            "lease_id": evidence["lease_id"],
        }
    except SignRefused as refused:
        return {
            "protocol": SIGN_RESULT_PROTOCOL,
            "status": "refused",
            "receipt_id": receipt_id,
            "reason": refused.reason,
        }


# --------------------------------------------------------------------------- #
# Signer service components + request handling (design §1.1, §4). All config comes ONLY
# from the signer's OWN environment — never from the request — so a caller cannot point
# the signer at a foreign key or a looser policy. `handle_sign_request` is shared by the
# stdin entrypoint here and the socket service in `brops_signer_service`.
# --------------------------------------------------------------------------- #
_CONTRACTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "contracts"


def _sign_request_schema() -> dict:
    return json.loads((_CONTRACTS_DIR / "brops-sign-request.v1.schema.json").read_text("utf-8"))


def load_authorization_policy(env: Mapping[str, str] | None = None) -> SignerAuthorizationPolicy:
    """Build the signer's authorization policy from its own environment (audit P1-7)."""
    e = os.environ if env is None else env

    def _set(name: str) -> "frozenset[str]":
        return frozenset(x.strip() for x in e.get(name, "").split(",") if x.strip())

    return SignerAuthorizationPolicy(
        allowed_executor_ids=_set("BROPS_ALLOWED_EXECUTOR_IDS"),
        allowed_builder_ids=_set("BROPS_ALLOWED_BUILDER_IDS"),
        allowed_supervisor_ids=_set("BROPS_ALLOWED_SUPERVISOR_IDS"),
        expected_policy_id=e["BROPS_EXPECTED_POLICY_ID"].strip(),
        expected_policy_version=e["BROPS_EXPECTED_POLICY_VERSION"].strip(),
        expected_policy_bundle_sha256=e["BROPS_EXPECTED_POLICY_BUNDLE_SHA256"].strip(),
        max_future_skew_ms=int(e.get("BROPS_MAX_FUTURE_SKEW_MS", "300000")),
    )


@dataclass
class SignerComponents:
    store: EvidenceStore
    signing_key: Mapping[str, str]
    supervisor_attestation_pubkey_hex: str
    supervisor_key_id: str
    policy: SignerAuthorizationPolicy


def load_components(env: Mapping[str, str] | None = None) -> SignerComponents:
    """Load the signer's store + keys + policy from its own environment. Raises on any
    missing/invalid provisioning (the caller turns that into a fail-closed refusal)."""
    e = os.environ if env is None else env
    return SignerComponents(
        store=EvidenceStore(e["BROPS_EVIDENCE_STORE_DIR"]),
        signing_key=load_receipt_signing_key(e["BROPS_RECEIPT_SIGNER_KEYDIR"]),
        supervisor_attestation_pubkey_hex=e["BROPS_SUPERVISOR_ATTESTATION_PUBKEY"].strip(),
        supervisor_key_id=e["BROPS_SUPERVISOR_ATTESTATION_KEY_ID"].strip(),
        policy=load_authorization_policy(e),
    )


def _refused_malformed(sign_request: Any) -> dict[str, Any]:
    rid = None
    if isinstance(sign_request, Mapping) and isinstance(sign_request.get("evidence"), Mapping):
        r = sign_request["evidence"].get("receipt_id")
        rid = r if isinstance(r, str) else None
    return {"protocol": SIGN_RESULT_PROTOCOL, "status": "refused", "receipt_id": rid, "reason": "malformed"}


def handle_sign_request(
    sign_request: Mapping[str, Any], components: SignerComponents, now_ms: int
) -> dict[str, Any]:
    """Schema-validate a decoded `brops.sign-request.v1` (unknown-field rejection) then
    sign. A schema failure is a fail-closed `refused{malformed}` (design §4)."""
    import brops_protocol

    try:
        brops_protocol.validate(sign_request, _sign_request_schema())
    except brops_protocol.ProtocolError:
        return _refused_malformed(sign_request)
    return sign(
        sign_request,
        store=components.store,
        signing_key=components.signing_key,
        supervisor_attestation_pubkey_hex=components.supervisor_attestation_pubkey_hex,
        supervisor_key_id=components.supervisor_key_id,
        policy=components.policy,
        now_ms=now_ms,
    )


# --------------------------------------------------------------------------- #
# stdin/stdout entrypoint — a single framed request in, a single framed result out
# (design §1.9 framing, audit P1-4). The socket SERVICE (design §1.1) lives in
# `brops_signer_service`; this entrypoint is used for one-shot invocation and tests.
# --------------------------------------------------------------------------- #
def main(reader, writer) -> int:
    """Read one length-prefixed `brops.sign-request.v1` frame from `reader` (binary),
    write one `brops.sign-result.v1` frame to `writer` (binary). Always exits 0."""
    import time

    import brops_protocol

    now_ms = int(time.time() * 1000)
    try:
        components = load_components()
    except (KeyError, ValueError, EvidenceStoreError):
        brops_protocol.write_frame(writer, _refused_malformed(None))
        return 0
    try:
        sign_request = brops_protocol.read_frame(reader)
    except brops_protocol.ProtocolError:
        brops_protocol.write_frame(writer, _refused_malformed(None))
        return 0
    brops_protocol.write_frame(writer, handle_sign_request(sign_request, components, now_ms))
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.stdin.buffer, sys.stdout.buffer))
