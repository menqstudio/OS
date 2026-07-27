"""isolated receipt-signer service core (Wave 3b-1B, rev-30 §7 / §4.9).

PURE signer logic for the isolated ``brops.receipt.v1`` signer described in the
Isolated-Signer design (§1.1-§1.5, §4.1-§4.2). This module is deliberately
socket-free and key-free so it can be exercised offline and without the OS
trust chain:

  * The content-addressed artifact store is dict-backed and injected
    (``ArtifactStore``); a real deployment owns it behind the signer's dedicated
    UID/SID. A handle is ``sha256(bytes)`` (lowercase hex); the signer reads by
    handle and refuses unless ``sha256(bytes) == handle``.
  * The receipt-signing private key never appears here. Callers inject a
    ``sign_fn(private_key_handle, message_bytes) -> b64`` and the signer hands it
    ONLY the canonical bytes it assembled from its OWN recomputed receipt.
  * The supervisor attestation is verified FIRST via an injected
    ``verify_attestation(key_handle, message_bytes, sig_b64) -> bool``; the
    signer acts on nothing until the attestation over ``JCS(evidence)`` verifies
    against its pinned attestation key.

The single trust invariant (§1.3-§1.4, "nothing signs caller bytes") is enforced
structurally:

  * ``validate_sign_request`` accepts ONLY the fixed shape of ids/handles/small
    facts. Any inline artifact bytes field (e.g. a smuggled ``output_bytes``) or
    any inline ``*_sha256`` claim is an UNKNOWN field and is REJECTED. Large
    inputs enter ONLY as content-addressed handles.
  * ``sign_result`` RECOMPUTES the receipt envelope itself: every ``*_sha256``
    is derived from the store bytes named by the corresponding handle, never
    trusted from the caller. It then signs ``JCS(recomputed_payload)`` exactly
    once. It is NOT a ``sign(arbitrary_bytes)`` oracle.

Every malformed / oversize / unauthorized input fails CLOSED as a typed refusal
(``brops.governed-receipt-refusal.v1``) carrying a fixed reason — never a
partial or unsigned success.

Only the Python standard library is used.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple

# ---------------------------------------------------------------------------
# Domain-separated protocol tags (§1.9)
# ---------------------------------------------------------------------------

SIGN_REQUEST_PROTOCOL = "brops.sign-request.v1"
RECEIPT_PROTOCOL = "brops.receipt.v1"
ATTESTATION_PROTOCOL = "brops.run-attestation.v1"
ENVELOPE_ARTIFACT_TYPE = "brops.governed-receipt-envelope.v1"
REFUSAL_ARTIFACT_TYPE = "brops.governed-receipt-refusal.v1"

# One fixed whole-request cap (§1.9). Evidence carries only handles + small
# fields, so a well-formed request is tiny; anything larger is hostile.
MAX_REQUEST_BYTES = 256 * 1024
STRING_CAP = 128

# The fixed, exhaustive evidence shape. Anything outside this set (extra keys,
# missing keys, wrong types) is rejected. In particular there is NO field for
# inline artifact bytes and NO inline ``*_sha256`` claim: turn facts enter as
# authoritative small values or as content-addressed handles ONLY.
EVIDENCE_STRING_FIELDS = (
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
)
EVIDENCE_HANDLE_FIELDS = (
    "policy_bundle_handle",
    "generation_config_handle",
    "system_handle",
    "history_handle",
    "output_handle",
    "containment_evidence_handle",
)
EVIDENCE_TS_FIELDS = ("requested_at", "completed_at")
EVIDENCE_FIELDS = EVIDENCE_STRING_FIELDS + EVIDENCE_HANDLE_FIELDS + EVIDENCE_TS_FIELDS

# handle field -> the receipt hash field the signer DERIVES from the store bytes.
HANDLE_TO_RECEIPT_HASH = {
    "policy_bundle_handle": "policy_bundle_sha256",
    "generation_config_handle": "generation_config_sha256",
    "system_handle": "system_sha256",
    "history_handle": "history_sha256",
    "output_handle": "output_sha256",
    "containment_evidence_handle": "containment_evidence_sha256",
}

ATTESTATION_FIELDS = ("attestation_protocol", "supervisor_key_id", "sig")

# The recomputed receipt envelope fields, in a fixed order (§1.4 "the signer
# constructs the canonical receipt itself"). JCS re-sorts on serialization, so
# order here is documentation, not the signed order.
RECEIPT_FIELDS = (
    "protocol",
    "receipt_id",
    "run_id",
    "execution_attempt_id",
    "lease_id",
    "request_nonce",
    "decision",
    "workspace_id",
    "install_id",
    "supervisor_id",
    "executor_id",
    "builder_id",
    "policy_id",
    "policy_version",
    "policy_bundle_sha256",
    "generation_config_sha256",
    "system_sha256",
    "history_sha256",
    "output_sha256",
    "containment_evidence_sha256",
    "completed_at",
)

# Fixed refusal-reason vocabulary (§4.2 tagged union).
REASON_ATTESTATION_INVALID = "attestation_invalid"
REASON_NOT_COMPLETED = "not_completed"
REASON_RUN_BINDING_INVALID = "run_binding_invalid"
REASON_NONCE_MISMATCH = "nonce_mismatch"
REASON_HANDLE_MISSING = "handle_missing"
REASON_HASH_MISMATCH = "hash_mismatch"
REASON_POLICY_MISMATCH = "policy_mismatch"
REASON_CONTAINMENT_MISSING = "containment_missing"
REASON_IDENTITY_DENIED = "identity_denied"
REASON_TIMESTAMP_INVALID = "timestamp_invalid"
REASON_OVERSIZE = "oversize"
REASON_MALFORMED = "malformed"


class SignerError(Exception):
    """Raised for signer misconfiguration / programming errors only.

    Hostile INPUT never raises this — it becomes a fail-closed typed refusal.
    This is reserved for a broken injected seam (bad config, a ``sign_fn`` that
    returns junk, etc.).
    """


class _Refuse(Exception):
    """Internal control-flow signal: fail closed with a fixed reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    """Deterministic JCS-equivalent encoding: sorted keys, compact separators,
    UTF-8. No NaN/Inf (``allow_nan=False``) so a hostile float can't sneak in."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_sha256_hex(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(c in "0123456789abcdef" for c in value)


def _capped_str(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= STRING_CAP


def _is_u64_ms(value: Any) -> bool:
    # bool is an int subclass — exclude it explicitly.
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 2 ** 64


# ---------------------------------------------------------------------------
# Content-addressed artifact store (dict-backed, injectable)
# ---------------------------------------------------------------------------


class ArtifactStore:
    """Append-only, content-addressed evidence store (§4.0).

    A handle is ``sha256(bytes)`` (lowercase hex); the store maps handle -> the
    EXACT bytes. Backed by an injected mapping so tests use a plain ``dict``
    while a real deployment backs it with the signer/supervisor-only protected
    directory. Integrity is by construction: ``put`` refuses to store bytes
    under a handle that is not their real digest, so a handle can never name
    different bytes.
    """

    def __init__(self, backing: Optional[Mapping[str, bytes]] = None) -> None:
        self._blobs: Dict[str, bytes] = {}
        if backing is not None:
            for handle, data in backing.items():
                self.put(data, handle)

    def put(self, data: bytes, handle: Optional[str] = None) -> str:
        """Store ``data`` under its content address; return the handle.

        If ``handle`` is given it MUST equal ``sha256(data)`` (content-addressed
        integrity), else ``SignerError`` — you cannot seed a lying handle.
        """
        if not isinstance(data, (bytes, bytearray)):
            raise SignerError("artifact bytes must be bytes")
        data = bytes(data)
        digest = _sha256_hex(data)
        if handle is not None and handle != digest:
            raise SignerError("refusing to store bytes under a non-matching handle")
        self._blobs[digest] = data
        return digest

    def read_verified(self, handle: str) -> Optional[bytes]:
        """Return the bytes named by ``handle`` iff ``sha256(bytes) == handle``.

        Returns ``None`` when the handle is absent (fail-closed at the call
        site). Raises ``SignerError`` only if a stored blob's digest drifted
        from its key (store corruption) — never trusts a mismatched read.
        """
        data = self._blobs.get(handle)
        if data is None:
            return None
        if _sha256_hex(data) != handle:  # pragma: no cover - corruption guard
            raise SignerError("store corruption: blob digest != handle")
        return data


# ---------------------------------------------------------------------------
# Signer config (the signer's OWN trusted knobs + key custody)
# ---------------------------------------------------------------------------


class SignerConfig:
    """The signer's own trusted config.

    The private key never appears inline: ``receipt_private_key_handle`` is an
    OPAQUE handle (path / KMS id / HSM slot) that only ``sign_fn`` knows how to
    use. ``supervisor_attestation_key_handle`` is likewise the opaque public-key
    handle the injected ``verify_attestation`` consumes.
    """

    def __init__(
        self,
        receipt_key_id: str,
        receipt_private_key_handle: Any,
        supervisor_attestation_key_id: str,
        supervisor_attestation_key_handle: Any,
        allowed_executor_ids: Iterable[str],
        allowed_builder_ids: Iterable[str],
        allowed_supervisor_ids: Iterable[str],
        max_future_skew_ms: int = 60_000,
    ) -> None:
        if not _capped_str(receipt_key_id):
            raise SignerError("receipt_key_id must be a non-empty capped string")
        if receipt_private_key_handle is None:
            raise SignerError("receipt_private_key_handle must be provided (opaque)")
        if not _capped_str(supervisor_attestation_key_id):
            raise SignerError("supervisor_attestation_key_id must be a capped string")
        if supervisor_attestation_key_handle is None:
            raise SignerError("supervisor_attestation_key_handle must be provided")
        if not isinstance(max_future_skew_ms, int) or isinstance(max_future_skew_ms, bool):
            raise SignerError("max_future_skew_ms must be an int")
        if max_future_skew_ms < 0:
            raise SignerError("max_future_skew_ms must be non-negative")
        self.receipt_key_id = receipt_key_id
        self.receipt_private_key_handle = receipt_private_key_handle
        self.supervisor_attestation_key_id = supervisor_attestation_key_id
        self.supervisor_attestation_key_handle = supervisor_attestation_key_handle
        self.allowed_executor_ids = frozenset(allowed_executor_ids)
        self.allowed_builder_ids = frozenset(allowed_builder_ids)
        self.allowed_supervisor_ids = frozenset(allowed_supervisor_ids)
        self.max_future_skew_ms = max_future_skew_ms


# ---------------------------------------------------------------------------
# Sign-request validation (fixed shape ONLY — no arbitrary bytes)
# ---------------------------------------------------------------------------


def _validate_attestation(attestation: Any) -> Dict[str, Any]:
    if not isinstance(attestation, Mapping):
        raise _Refuse(REASON_MALFORMED)
    extra = set(attestation.keys()) - set(ATTESTATION_FIELDS)
    missing = set(ATTESTATION_FIELDS) - set(attestation.keys())
    if extra or missing:
        raise _Refuse(REASON_MALFORMED)
    if attestation["attestation_protocol"] != ATTESTATION_PROTOCOL:
        raise _Refuse(REASON_MALFORMED)
    if not _capped_str(attestation["supervisor_key_id"]):
        raise _Refuse(REASON_MALFORMED)
    if not _capped_str(attestation["sig"]):
        raise _Refuse(REASON_MALFORMED)
    return {
        "attestation_protocol": ATTESTATION_PROTOCOL,
        "supervisor_key_id": attestation["supervisor_key_id"],
        "sig": attestation["sig"],
    }


def _validate_evidence(evidence: Any) -> Dict[str, Any]:
    """Validate the evidence body against the fixed shape; raise ``_Refuse`` on
    ANY violation. This is the ONLY door through which turn facts enter, and it
    admits NO inline artifact bytes and NO caller-supplied ``*_sha256`` claim."""
    if not isinstance(evidence, Mapping):
        raise _Refuse(REASON_MALFORMED)

    keys = set(evidence.keys())
    allowed = set(EVIDENCE_FIELDS)
    # An extra/arbitrary field (e.g. a smuggled ``output_bytes`` or an inline
    # ``output_sha256``) is REJECTED, never silently dropped.
    if keys - allowed or allowed - keys:
        raise _Refuse(REASON_MALFORMED)

    for field in EVIDENCE_STRING_FIELDS:
        if not _capped_str(evidence[field]):
            raise _Refuse(REASON_MALFORMED)
    for field in EVIDENCE_HANDLE_FIELDS:
        if not _is_sha256_hex(evidence[field]):
            raise _Refuse(REASON_MALFORMED)
    for field in EVIDENCE_TS_FIELDS:
        if not _is_u64_ms(evidence[field]):
            raise _Refuse(REASON_MALFORMED)

    return {field: evidence[field] for field in EVIDENCE_FIELDS}


def validate_sign_request(request: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Strict-parse a ``brops.sign-request.v1`` into ``(attestation, evidence)``.

    Fixed top-level shape ``{protocol, attestation, evidence}`` — nothing else.
    Raises ``_Refuse(malformed)`` on any structural violation. Turn facts are
    validated here and NOWHERE else.
    """
    if not isinstance(request, Mapping):
        raise _Refuse(REASON_MALFORMED)
    allowed = {"protocol", "attestation", "evidence"}
    if set(request.keys()) - allowed or allowed - set(request.keys()):
        raise _Refuse(REASON_MALFORMED)
    if request["protocol"] != SIGN_REQUEST_PROTOCOL:
        raise _Refuse(REASON_MALFORMED)
    attestation = _validate_attestation(request["attestation"])
    evidence = _validate_evidence(request["evidence"])
    return attestation, evidence


# ---------------------------------------------------------------------------
# The isolated signer
# ---------------------------------------------------------------------------


class IsolatedSigner:
    """Recompute-and-sign core: turns an attested sign-request into a signed
    ``brops.governed-receipt-envelope.v1`` or a typed refusal.

    Injected seams (no real socket, no real key needed):
      * ``store``            — ``ArtifactStore`` read by handle.
      * ``sign_fn``          — ``(private_key_handle, message_bytes) -> b64``.
      * ``verify_attestation`` — ``(key_handle, message_bytes, sig_b64) -> bool``.
      * ``clock_ms``         — ``() -> int`` epoch ms for timestamp sanity.
    """

    def __init__(
        self,
        config: SignerConfig,
        store: ArtifactStore,
        sign_fn: Callable[[Any, bytes], str],
        verify_attestation: Callable[[Any, bytes, str], bool],
        clock_ms: Callable[[], int],
    ) -> None:
        if not isinstance(config, SignerConfig):
            raise SignerError("config must be a SignerConfig")
        if not isinstance(store, ArtifactStore):
            raise SignerError("store must be an ArtifactStore")
        for name, fn in (
            ("sign_fn", sign_fn),
            ("verify_attestation", verify_attestation),
            ("clock_ms", clock_ms),
        ):
            if not callable(fn):
                raise SignerError("%s must be callable" % name)
        self._config = config
        self._store = store
        self._sign_fn = sign_fn
        self._verify_attestation = verify_attestation
        self._clock_ms = clock_ms

    # -- public entrypoint --------------------------------------------------

    def sign_result(self, sign_request: Any) -> Dict[str, Any]:
        """Validate, attest, recompute, and sign — or return a typed refusal.

        Never raises on hostile input: every authorization/validation failure
        becomes ``{"artifact_type": "brops.governed-receipt-refusal.v1",
        "status": "refused", "reason": <fixed reason>}``. Never a partial or
        unsigned success.
        """
        try:
            # (0) whole-request bound (§1.9) BEFORE anything else.
            self._check_request_size(sign_request)
            # (1) strict shape.
            attestation, evidence = validate_sign_request(sign_request)
            # (2) attestation FIRST — the signer acts on nothing unattested.
            evidence_jcs = self._verify_supervisor_attestation(attestation, evidence)
            # (3) independent authorization gate (§1.5).
            self._check_run_binding(evidence)
            self._check_identity(evidence)
            self._check_timestamps(evidence)
            # (4) recompute every hash from the STORE bytes named by the handle.
            derived = self._derive_hashes(evidence)
            # (5) construct the canonical receipt payload from trusted inputs.
            payload = self._recompute_receipt(evidence, derived)
            # (6) sign the EXACT canonical bytes of our OWN payload — never the
            #     caller's bytes.
            message = _canonical_bytes(payload)
            signature_b64 = self._sign_fn(
                self._config.receipt_private_key_handle, message
            )
            if not isinstance(signature_b64, str) or not signature_b64:
                raise SignerError("sign_fn must return a non-empty base64 string")
        except _Refuse as refusal:
            return {
                "artifact_type": REFUSAL_ARTIFACT_TYPE,
                "status": "refused",
                "reason": refusal.reason,
            }

        return {
            "artifact_type": ENVELOPE_ARTIFACT_TYPE,
            "status": "signed",
            "key_id": self._config.receipt_key_id,
            "payload": payload,
            "signature_b64": signature_b64,
            "supervisor_attestation_key_id": self._config.supervisor_attestation_key_id,
            "attestation_evidence_sha256": _sha256_hex(evidence_jcs),
        }

    # -- gate steps ---------------------------------------------------------

    def _check_request_size(self, sign_request: Any) -> None:
        try:
            raw = _canonical_bytes(sign_request) if isinstance(sign_request, Mapping) else b""
        except (TypeError, ValueError):
            raise _Refuse(REASON_MALFORMED)
        if len(raw) > MAX_REQUEST_BYTES:
            raise _Refuse(REASON_OVERSIZE)

    def _verify_supervisor_attestation(
        self, attestation: Mapping[str, Any], evidence: Mapping[str, Any]
    ) -> bytes:
        # The attesting key MUST be the signer's pinned supervisor key.
        if attestation["supervisor_key_id"] != self._config.supervisor_attestation_key_id:
            raise _Refuse(REASON_ATTESTATION_INVALID)
        evidence_jcs = _canonical_bytes(evidence)
        try:
            ok = self._verify_attestation(
                self._config.supervisor_attestation_key_handle,
                evidence_jcs,
                attestation["sig"],
            )
        except Exception:  # a broken verifier must never leak a signature
            raise _Refuse(REASON_ATTESTATION_INVALID)
        if ok is not True:
            raise _Refuse(REASON_ATTESTATION_INVALID)
        return evidence_jcs

    def _check_run_binding(self, evidence: Mapping[str, Any]) -> None:
        # run/attempt/lease already shape-validated as capped non-empty strings.
        if evidence["decision"] != "completed":
            raise _Refuse(REASON_NOT_COMPLETED)
        # request_nonce must be present (already validated) — bind it.
        if not evidence["request_nonce"]:
            raise _Refuse(REASON_NONCE_MISMATCH)

    def _check_identity(self, evidence: Mapping[str, Any]) -> None:
        cfg = self._config
        if evidence["executor_id"] not in cfg.allowed_executor_ids:
            raise _Refuse(REASON_IDENTITY_DENIED)
        if evidence["builder_id"] not in cfg.allowed_builder_ids:
            raise _Refuse(REASON_IDENTITY_DENIED)
        if evidence["supervisor_id"] not in cfg.allowed_supervisor_ids:
            raise _Refuse(REASON_IDENTITY_DENIED)

    def _check_timestamps(self, evidence: Mapping[str, Any]) -> None:
        requested_at = evidence["requested_at"]
        completed_at = evidence["completed_at"]
        if requested_at > completed_at:
            raise _Refuse(REASON_TIMESTAMP_INVALID)
        now = self._clock_ms()
        if not isinstance(now, int) or isinstance(now, bool):
            raise SignerError("clock_ms must return an int (epoch ms)")
        if completed_at > now + self._config.max_future_skew_ms:
            raise _Refuse(REASON_TIMESTAMP_INVALID)

    def _derive_hashes(self, evidence: Mapping[str, Any]) -> Dict[str, str]:
        """Read each artifact from the store BY HANDLE, confirm
        ``sha256(bytes) == handle``, and DERIVE the receipt ``*_sha256`` from the
        exact bytes. No caller-supplied hash is ever trusted."""
        derived: Dict[str, str] = {}
        for handle_field, hash_field in HANDLE_TO_RECEIPT_HASH.items():
            handle = evidence[handle_field]
            data = self._store.read_verified(handle)
            if data is None:
                if handle_field == "containment_evidence_handle":
                    raise _Refuse(REASON_CONTAINMENT_MISSING)
                raise _Refuse(REASON_HANDLE_MISSING)
            digest = _sha256_hex(data)
            if digest != handle:  # pragma: no cover - read_verified already guards
                raise _Refuse(REASON_HASH_MISMATCH)
            derived[hash_field] = digest
        return derived

    def _recompute_receipt(
        self, evidence: Mapping[str, Any], derived: Mapping[str, str]
    ) -> Dict[str, Any]:
        """Assemble the canonical ``brops.receipt.v1`` payload from the signer's
        OWN trusted inputs: authoritative small facts + the freshly derived
        hashes. The caller supplies no receipt bytes."""
        payload = {
            "protocol": RECEIPT_PROTOCOL,
            "receipt_id": evidence["receipt_id"],
            "run_id": evidence["run_id"],
            "execution_attempt_id": evidence["execution_attempt_id"],
            "lease_id": evidence["lease_id"],
            "request_nonce": evidence["request_nonce"],
            "decision": evidence["decision"],
            "workspace_id": evidence["workspace_id"],
            "install_id": evidence["install_id"],
            "supervisor_id": evidence["supervisor_id"],
            "executor_id": evidence["executor_id"],
            "builder_id": evidence["builder_id"],
            "policy_id": evidence["policy_id"],
            "policy_version": evidence["policy_version"],
            "policy_bundle_sha256": derived["policy_bundle_sha256"],
            "generation_config_sha256": derived["generation_config_sha256"],
            "system_sha256": derived["system_sha256"],
            "history_sha256": derived["history_sha256"],
            "output_sha256": derived["output_sha256"],
            "containment_evidence_sha256": derived["containment_evidence_sha256"],
            "completed_at": evidence["completed_at"],
        }
        # Structural self-check: the recomputed payload is EXACTLY RECEIPT_FIELDS.
        if set(payload.keys()) != set(RECEIPT_FIELDS):  # pragma: no cover
            raise SignerError("recomputed receipt field-set drift")
        return payload
