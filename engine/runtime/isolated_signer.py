"""isolated receipt-signer service core (Wave 3b-1B, rev-30 §7 / §4.9).

PURE signer logic for the isolated ``brops.governed-receipt-envelope.v1`` signer
described in the Isolated-Signer design (§1.1-§1.5, §4.1-§4.2, §4.9). This module
is deliberately socket-free and key-free so it can be exercised offline and
without the OS trust chain:

  * The content-addressed artifact store is dict-backed and injected
    (``ArtifactStore``); a real deployment owns it behind the signer's dedicated
    UID/SID. A handle is ``sha256(bytes)`` (lowercase hex); the signer reads by
    handle and refuses unless ``sha256(bytes) == handle``.
  * The receipt-signing private key never appears here. Callers inject a
    ``sign_fn(private_key_handle, message_bytes) -> b64`` and the signer hands it
    ONLY the canonical bytes it assembled from its OWN recomputed payload.
  * The supervisor attestation is verified FIRST via an injected
    ``verify_attestation(key_handle, message_bytes, sig_b64) -> bool``; the
    signer acts on nothing until the attestation over ``JCS(evidence)`` verifies
    against its pinned attestation key.

The single trust invariant (§1.3-§1.4, "nothing signs caller bytes") is enforced
structurally:

  * ``validate_sign_request`` accepts ONLY the fixed shape of ids/handles/small
    facts. Any inline artifact bytes field (e.g. a smuggled ``output_bytes``) or
    any inline ``*_sha256`` claim for a store-derived digest is an UNKNOWN field
    and is REJECTED. Large inputs enter ONLY as content-addressed handles.
  * ``sign_result`` RECOMPUTES the receipt envelope itself: every store-derived
    ``*_sha256`` (including ``output_sha256``/``output_bytes`` and the
    ``request_sha256`` request-envelope digest) is derived from the store bytes
    named by the corresponding handle, never trusted from the caller. It then
    signs ``JCS(recomputed_payload)`` exactly once. It is NOT a
    ``sign(arbitrary_bytes)`` oracle.

The signed artifact is the FINAL-ACCEPTANCE envelope the desktop/broker verifies
in ``governed_verification.rs`` (§7.1): a FLAT ``brops.governed-receipt-envelope.v1``
payload of EXACTLY 23 keys (17 string, 6 integer) with ``key_id`` and the
attestation binding INSIDE the signature. The broker reconstructs
``JCS(payload)`` from these fields and Ed25519-verifies it under the pinned
isolated-signer key, so this signer and that verifier MUST agree byte-for-byte.

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
# Domain-separated protocol tags (§1.9, §2.2, §4.9)
# ---------------------------------------------------------------------------

SIGN_REQUEST_PROTOCOL = "brops.sign-request.v1"
# The canonical governed-request envelope protocol whose JCS digest is
# ``request_sha256`` (mirrors receipt.rs ``REQUEST_PROTOCOL`` / §2.2). The signer
# RECOMPUTES this digest; it never trusts a transported request_sha256.
REQUEST_PROTOCOL = "brops.request.v1"
ATTESTATION_PROTOCOL = "brops.run-attestation.v1"
# The frozen §4.9 artifact #12 discriminator. MUST equal
# governed_verification.rs::RECEIPT_ENVELOPE_ARTIFACT_TYPE.
ENVELOPE_ARTIFACT_TYPE = "brops.governed-receipt-envelope.v1"
REFUSAL_ARTIFACT_TYPE = "brops.governed-receipt-refusal.v1"

# One fixed whole-request cap (§1.9). Evidence carries only handles + small
# fields, so a well-formed request is tiny; anything larger is hostile.
MAX_REQUEST_BYTES = 256 * 1024
STRING_CAP = 128

# ---------------------------------------------------------------------------
# The fixed, exhaustive evidence shape (§4.9 source inputs). Anything outside
# this set (extra keys, missing keys, wrong types) is rejected. In particular
# there is NO field for inline artifact bytes and NO inline store-derived
# ``*_sha256`` claim: turn facts enter as authoritative small values or as
# content-addressed handles ONLY.
# ---------------------------------------------------------------------------

# Capped non-empty strings — authoritative small facts carried verbatim.
EVIDENCE_STRING_FIELDS = (
    "run_id",
    "execution_attempt_id",
    "task_id",
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

# Store handles the signer READS to DERIVE a ``*_sha256`` from the exact bytes.
# ``system``/``history``/``generation_config`` feed the recomputed request_sha256;
# ``output`` feeds output_sha256/output_bytes; ``policy_bundle``/``containment``
# are authorization evidence (their presence is required, §1.5).
EVIDENCE_DERIVE_HANDLE_FIELDS = (
    "policy_bundle_handle",
    "generation_config_handle",
    "system_handle",
    "history_handle",
    "output_handle",
    "containment_evidence_handle",
)

# Protected-chain store handles carried VERBATIM into the signed envelope. The
# signer deep-verifies that each resolves in its protected store (§7) — it will
# not mint an envelope naming a record/lease/execution-receipt it cannot see —
# but the handle *value* (already the content address) is what the envelope
# carries; the broker never dereferences it (§4.6 authority rule).
EVIDENCE_CHAIN_HANDLE_FIELDS = (
    "record_handle",
    "lease_handle",
    "execution_receipt_handle",
)

# 64-hex evidence-chain digest carried verbatim (attested by the supervisor; not
# a store blob the signer dereferences).
EVIDENCE_DIGEST_FIELDS = ("evidence_final_event_hash",)

# Epoch-ms timestamps (u64).
EVIDENCE_TS_FIELDS = ("requested_at", "completed_at", "challenge_accepted_at_ms")

# Evidence-head counters — bare positive integers (the ``governed_evidence_head_floor``
# CHECK constraints require each >= 1).
EVIDENCE_COUNT_FIELDS = (
    "evidence_event_count",
    "evidence_last_sequence",
    "evidence_head_sequence",
)

EVIDENCE_HANDLE_FIELDS = EVIDENCE_DERIVE_HANDLE_FIELDS + EVIDENCE_CHAIN_HANDLE_FIELDS
EVIDENCE_FIELDS = (
    EVIDENCE_STRING_FIELDS
    + EVIDENCE_HANDLE_FIELDS
    + EVIDENCE_DIGEST_FIELDS
    + EVIDENCE_TS_FIELDS
    + EVIDENCE_COUNT_FIELDS
)

# derive-handle field -> the ``*_sha256`` the signer DERIVES from the store bytes.
HANDLE_TO_DERIVED_HASH = {
    "policy_bundle_handle": "policy_bundle_sha256",
    "generation_config_handle": "generation_config_sha256",
    "system_handle": "system_sha256",
    "history_handle": "history_sha256",
    "output_handle": "output_sha256",
    "containment_evidence_handle": "containment_evidence_sha256",
}

ATTESTATION_FIELDS = ("attestation_protocol", "supervisor_key_id", "sig")

# The §4.9 flat envelope payload — EXACTLY these 23 keys. 17 string-valued, 6
# integer-valued. JCS re-sorts on serialization, so this order is documentation,
# not the signed order. This set MUST equal the field set reconstructed by
# governed_verification.rs::ReceiptEnvelope::payload_jcs.
ENVELOPE_STRING_KEYS = (
    "artifact_type",
    "key_id",
    "receipt_id",
    "run_id",
    "execution_attempt_id",
    "task_id",
    "workspace_id",
    "install_id",
    "request_nonce",
    "request_sha256",
    "record_handle",
    "lease_handle",
    "execution_receipt_handle",
    "output_sha256",
    "evidence_final_event_hash",
    "supervisor_attestation_key_id",
    "attestation_evidence_sha256",
)
ENVELOPE_INTEGER_KEYS = (
    "output_bytes",
    "challenge_accepted_at_ms",
    "completed_at_ms",
    "evidence_event_count",
    "evidence_last_sequence",
    "evidence_head_sequence",
)
ENVELOPE_PAYLOAD_FIELDS = ENVELOPE_STRING_KEYS + ENVELOPE_INTEGER_KEYS

# Fixed refusal-reason vocabulary (§4.2 tagged union).
REASON_ATTESTATION_INVALID = "attestation_invalid"
REASON_NOT_COMPLETED = "not_completed"
REASON_RUN_BINDING_INVALID = "run_binding_invalid"
REASON_NONCE_MISMATCH = "nonce_mismatch"
REASON_HANDLE_MISSING = "handle_missing"
#: A published chain document disagrees with the attested evidence about a field they
#: BOTH carry (audit round 3, R3-01). Typed separately from "absent" because the two mean
#: different things: one is a broken deployment, this one is two accounts of the same run
#: that cannot both be true.
REASON_CHAIN_DISAGREEMENT = "chain_document_disagrees_with_attested_evidence"
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
    UTF-8, no NaN/Inf. Used for the attestation-evidence digest and the
    whole-request size bound (internal consistency only)."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _jcs_bytes(payload: Mapping[str, Any]) -> bytes:
    """RFC-8785-compatible JCS for a flat object over the fixed ASCII key set:
    sorted keys, compact separators, raw UTF-8 (``ensure_ascii=False``), integers
    as bare JSON integers. This is EXACTLY the encoding the Rust broker
    reconstructs (``serde_json::to_vec`` of a sorted ``Map``), so the isolated
    signer's ``JCS(payload)`` and the broker's ``payload_jcs`` are byte-identical.

    ``json.dumps(payload, sort_keys=True, separators=(",",":"),
    ensure_ascii=False).encode("utf-8")``.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
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


def _is_pos_i63(value: Any) -> bool:
    # Evidence-head counters: strictly positive, i64 range (matches the broker's
    # i64 fields and the ledger's ``>= 1`` CHECK constraints). bool excluded.
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value < 2 ** 63


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

    ``receipt_key_id`` and ``supervisor_attestation_key_id`` are the signer's
    pinned identity: they are placed INSIDE the signed §4.9 payload and the
    broker checks them against its own pinned manifest ids.
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
    """Validate the evidence body against the fixed §4.9 source shape; raise
    ``_Refuse`` on ANY violation. This is the ONLY door through which turn facts
    enter, and it admits NO inline artifact bytes and NO caller-supplied
    store-derived ``*_sha256`` claim."""
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
    for field in EVIDENCE_DIGEST_FIELDS:
        if not _is_sha256_hex(evidence[field]):
            raise _Refuse(REASON_MALFORMED)
    for field in EVIDENCE_TS_FIELDS:
        if not _is_u64_ms(evidence[field]):
            raise _Refuse(REASON_MALFORMED)
    for field in EVIDENCE_COUNT_FIELDS:
        if not _is_pos_i63(evidence[field]):
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
    ``brops.governed-receipt-envelope.v1`` (§4.9) or a typed refusal.

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

        On success returns the §4.9 envelope:
        ``{"artifact_type", "status": "signed", "payload": <flat 23-key dict>,
        "signature_b64": <sign_fn output>}`` — ``key_id``, the attestation key
        id and the attestation-evidence digest all live INSIDE ``payload`` and
        are therefore covered by the signature.
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
            # (4) recompute every store-derived hash from the STORE bytes named
            #     by the handle, and deep-verify the protected-chain handles.
            derived = self._derive_hashes(evidence)
            output_bytes = self._derive_output_bytes(evidence)
            request_sha256 = self._recompute_request_sha256(evidence, derived)
            # The chain documents are checked AFTER the recompute so the record's own
            # `request_sha256` can be held against the digest the SIGNER derived from store
            # bytes, rather than against a transported value nobody carries (the signer never
            # trusts one). That makes this the stronger check, not a weaker one.
            self._verify_chain_handles(evidence, {"request_sha256": request_sha256})
            attestation_evidence_sha256 = _sha256_hex(evidence_jcs)
            # (5) construct the canonical §4.9 payload from trusted inputs.
            payload = self._build_envelope_payload(
                evidence,
                derived,
                output_bytes=output_bytes,
                request_sha256=request_sha256,
                attestation_evidence_sha256=attestation_evidence_sha256,
            )
            # (6) sign the EXACT JCS bytes of our OWN payload — never the
            #     caller's bytes. Same encoding the Rust broker reconstructs.
            message = _jcs_bytes(payload)
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
            "payload": payload,
            "signature_b64": signature_b64,
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
        # run/attempt/task already shape-validated as capped non-empty strings.
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
        challenge_accepted_at = evidence["challenge_accepted_at_ms"]
        # requested <= challenge-accepted <= completed, and not in the future.
        if requested_at > completed_at:
            raise _Refuse(REASON_TIMESTAMP_INVALID)
        if challenge_accepted_at > completed_at:
            raise _Refuse(REASON_TIMESTAMP_INVALID)
        now = self._clock_ms()
        if not isinstance(now, int) or isinstance(now, bool):
            raise SignerError("clock_ms must return an int (epoch ms)")
        if completed_at > now + self._config.max_future_skew_ms:
            raise _Refuse(REASON_TIMESTAMP_INVALID)

    def _derive_hashes(self, evidence: Mapping[str, Any]) -> Dict[str, str]:
        """Read each DERIVE artifact from the store BY HANDLE, confirm
        ``sha256(bytes) == handle``, and DERIVE the ``*_sha256`` from the exact
        bytes. No caller-supplied hash is ever trusted."""
        derived: Dict[str, str] = {}
        for handle_field, hash_field in HANDLE_TO_DERIVED_HASH.items():
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

    #: What each published chain document must AGREE with the attested evidence about
    #: (audit round 3, R3-01). Only fields the document and the evidence both carry; a
    #: document is not required to repeat everything, but where it speaks it must not differ.
    _CHAIN_AGREEMENT = {
        "record_handle": (
            "brops.governed-turn-record.v1",
            ("run_id", "task_id", "execution_attempt_id", "workspace_id", "install_id",
             "request_nonce", "receipt_id", "supervisor_id", "request_sha256",
             "system_handle", "history_handle", "generation_config_handle",
             "output_handle", "containment_evidence_handle", "decision"),
        ),
        "execution_receipt_handle": (
            "brops.execution-receipt.v1",
            ("run_id", "execution_attempt_id", "output_handle"),
        ),
        "lease_handle": (
            None,  # the lease payload has no protocol tag of its own
            ("execution_attempt_id",),
        ),
    }

    def _verify_chain_handles(
        self, evidence: Mapping[str, Any], recomputed: Mapping[str, Any] | None = None
    ) -> None:
        """Independently re-verify the protected-chain documents (§7).

        **audit round 3, R3-01 (P1).** This used to be three existence checks. That is worth
        restating plainly, because the signer runs as a SEPARATE OS principal for exactly one
        reason — to re-verify the chain independently of the supervisor — and a presence check
        re-verifies nothing. With it, the authenticity of the whole chain rested on a single
        supervisor signature, and the signer's isolation bought custody of a key and no second
        opinion at all.

        So the signer now READS each document and requires it to AGREE with the attested
        evidence on every field they share. The supervisor builds these documents from its own
        rows and signs the evidence separately; if the two ever disagree — a record about a
        different run, a receipt naming another attempt, an output handle that does not match
        the one being signed — the signer refuses, and it does so without trusting the
        supervisor's summary of its own work.

        What this does NOT do, stated so nobody reads more into it than is there: it cannot
        detect a supervisor that lies CONSISTENTLY in both the evidence and the documents. A
        second opinion catches disagreement, not a coherent forgery. Catching that needs the
        signer to hold an independent source for the facts, which the §5 protocol does not give
        it today.
        """
        for handle_field in EVIDENCE_CHAIN_HANDLE_FIELDS:
            handle = evidence[handle_field]
            raw = self._store.read_verified(handle)
            if raw is None:
                raise _Refuse(REASON_HANDLE_MISSING)

            protocol, shared = self._CHAIN_AGREEMENT[handle_field]
            try:
                document = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                # A chain document the signer cannot read is one it cannot check. Refusing is
                # the only honest outcome; accepting it would restore the presence check.
                raise _Refuse(REASON_HANDLE_MISSING)
            if not isinstance(document, Mapping):
                raise _Refuse(REASON_HANDLE_MISSING)
            if protocol is not None and document.get("protocol") != protocol:
                raise _Refuse(REASON_HANDLE_MISSING)

            for field in shared:
                if field not in document:
                    # REQUIRED, not merely "checked where present". Skipping absent fields would
                    # let a document carrying nothing but its protocol tag agree vacuously — a
                    # hole exactly the shape of the presence check this replaces.
                    raise _Refuse(
                        "%s:%s.%s_missing" % (REASON_CHAIN_DISAGREEMENT, handle_field, field))
                expected = (recomputed or {}).get(field, evidence.get(field))
                if document[field] != expected:
                    # The field name is part of the reason: a refusal that does not say WHICH
                    # account differs sends the operator to read two documents by hand.
                    raise _Refuse("%s:%s.%s" % (REASON_CHAIN_DISAGREEMENT, handle_field, field))

    def _derive_output_bytes(self, evidence: Mapping[str, Any]) -> int:
        """The exact reply byte-length, DERIVED from the store bytes named by
        ``output_handle`` (never a caller-supplied ``output_bytes``). The broker
        length-gates ``len(output) == output_bytes`` over the raw bytes (§4.6)."""
        data = self._store.read_verified(evidence["output_handle"])
        if data is None:  # pragma: no cover - _derive_hashes already read it
            raise _Refuse(REASON_HANDLE_MISSING)
        return len(data)

    def _recompute_request_sha256(
        self, evidence: Mapping[str, Any], derived: Mapping[str, str]
    ) -> str:
        """RECOMPUTE the canonical governed-request digest (§2.2) from the
        signer's OWN derived component hashes + authoritative ids/timestamp,
        using the SAME JCS formula as ``receipt.rs::request_envelope_sha256``.
        The broker independently recomputes this from its trusted ``Expected``
        and requires equality, so a forged request_sha256 can never survive — and
        the signer never trusts a transported one."""
        request_envelope = {
            "protocol": REQUEST_PROTOCOL,
            "workspace_id": evidence["workspace_id"],
            "install_id": evidence["install_id"],
            "request_nonce": evidence["request_nonce"],
            "system_sha256": derived["system_sha256"],
            "history_sha256": derived["history_sha256"],
            "generation_config_sha256": derived["generation_config_sha256"],
            # requested_at is a STRING field in the request envelope (§2.2); the
            # canonical decimal of the epoch-ms integer.
            "requested_at": str(evidence["requested_at"]),
        }
        return _sha256_hex(_jcs_bytes(request_envelope))

    def _build_envelope_payload(
        self,
        evidence: Mapping[str, Any],
        derived: Mapping[str, str],
        *,
        output_bytes: int,
        request_sha256: str,
        attestation_evidence_sha256: str,
    ) -> Dict[str, Any]:
        """Assemble the canonical §4.9 ``brops.governed-receipt-envelope.v1``
        payload from the signer's OWN trusted inputs: pinned config identity,
        authoritative attested small facts, freshly derived digests, and the
        recomputed request digest. The caller supplies no receipt bytes and no
        store-derived hash. Field sources:

          * ``artifact_type``                  — frozen §4.9 const.
          * ``key_id``                         — signer config (pinned identity).
          * ``supervisor_attestation_key_id``  — signer config (pinned identity).
          * ``attestation_evidence_sha256``    — sha256 of the JCS evidence the
                                                 supervisor attested (signer-computed).
          * ``request_sha256``                 — recomputed request-envelope digest.
          * ``output_sha256`` / ``output_bytes`` — derived from the store output bytes.
          * ``record_handle`` / ``lease_handle`` / ``execution_receipt_handle`` —
                                                 deep-verified protected-chain handles.
          * ``evidence_final_event_hash`` and the three ``evidence_*`` counters,
            ``challenge_accepted_at_ms`` — attested evidence-head facts.
          * ``completed_at_ms``                — attested ``completed_at``.
          * the remaining ids                  — attested small facts.
        """
        cfg = self._config
        payload: Dict[str, Any] = {
            # --- 17 string fields ---
            "artifact_type": ENVELOPE_ARTIFACT_TYPE,
            "key_id": cfg.receipt_key_id,
            "receipt_id": evidence["receipt_id"],
            "run_id": evidence["run_id"],
            "execution_attempt_id": evidence["execution_attempt_id"],
            "task_id": evidence["task_id"],
            "workspace_id": evidence["workspace_id"],
            "install_id": evidence["install_id"],
            "request_nonce": evidence["request_nonce"],
            "request_sha256": request_sha256,
            "record_handle": evidence["record_handle"],
            "lease_handle": evidence["lease_handle"],
            "execution_receipt_handle": evidence["execution_receipt_handle"],
            "output_sha256": derived["output_sha256"],
            "evidence_final_event_hash": evidence["evidence_final_event_hash"],
            "supervisor_attestation_key_id": cfg.supervisor_attestation_key_id,
            "attestation_evidence_sha256": attestation_evidence_sha256,
            # --- 6 integer fields (bare JSON integers) ---
            "output_bytes": output_bytes,
            "challenge_accepted_at_ms": evidence["challenge_accepted_at_ms"],
            "completed_at_ms": evidence["completed_at"],
            "evidence_event_count": evidence["evidence_event_count"],
            "evidence_last_sequence": evidence["evidence_last_sequence"],
            "evidence_head_sequence": evidence["evidence_head_sequence"],
        }
        # Structural self-check: EXACTLY the 23 §4.9 keys, correctly typed.
        if set(payload.keys()) != set(ENVELOPE_PAYLOAD_FIELDS):  # pragma: no cover
            raise SignerError("recomputed envelope field-set drift")
        for key in ENVELOPE_STRING_KEYS:  # pragma: no cover - defensive
            if not isinstance(payload[key], str):
                raise SignerError("envelope string field %s is not a str" % key)
        for key in ENVELOPE_INTEGER_KEYS:  # pragma: no cover - defensive
            if not isinstance(payload[key], int) or isinstance(payload[key], bool):
                raise SignerError("envelope integer field %s is not an int" % key)
        return payload
