"""Wave 3b — brops.receipt.v1 canonical byte formulas (single source of truth).

The desktop verifier (Rust `brops-core::receipt`) and this Python signer must agree
**byte-for-byte** on every hashed artifact, or the desktop's `bind` against its own
`Expected` fails and the turn Blocks. This module is the one place those formulas live,
so the signer, the supervisor attestation, and the content-addressed store all hash the
same way, and the cross-language parity suite can pin each one.

Design: `docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md` §4.0a (artifact canonical-byte
formulas) and §4 (the receipt/request envelopes). Reuses the engine's JCS canonicalizer
`bro_signature.canonical_bytes` (`json.dumps(sort_keys=True, separators=(",", ":"),
ensure_ascii=False).encode("utf-8")`) — identical to Rust `receipt.rs::jcs_bytes`
(`serde_json::to_vec(&BTreeMap<String,String>)`).

Nothing here signs, reads a key, or touches the filesystem — it is pure and I/O-free.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any, Mapping, Sequence

from bro_signature import canonical_bytes  # reuse the engine JCS canonicalizer

# Domain-separation tags (design §1.9, §4). Must equal the Rust constants
# (`receipt.rs::RECEIPT_PROTOCOL` / `REQUEST_PROTOCOL`).
RECEIPT_PROTOCOL = "brops.receipt.v1"
REQUEST_PROTOCOL = "brops.request.v1"

# The receipt envelope's exact field set (design §4; Rust `RECEIPT_FIELDS`). Order here
# is irrelevant — JCS sorts — but the set must match exactly (no missing/unknown key).
RECEIPT_FIELDS = (
    "builder_id",
    "completed_at",
    "containment_evidence_sha256",
    "decision",
    "executor_id",
    "generation_config_sha256",
    "history_sha256",
    "install_id",
    "key_id",
    "output_sha256",
    "policy_bundle_sha256",
    "policy_id",
    "policy_version",
    "protocol",
    "receipt_id",
    "request_nonce",
    "request_sha256",
    "requested_at",
    "supervisor_id",
    "system_sha256",
    "workspace_id",
)

# The canonical request envelope's field set (design §2.2; Rust `request_envelope_sha256`).
_REQUEST_FIELDS = (
    "protocol",
    "workspace_id",
    "install_id",
    "request_nonce",
    "system_sha256",
    "history_sha256",
    "generation_config_sha256",
    "requested_at",
)

# The subset of receipt fields that MUST be a lowercase 64-hex sha256 (Rust `HASH_FIELDS`).
_HASH_FIELDS = frozenset(
    {
        "containment_evidence_sha256",
        "generation_config_sha256",
        "history_sha256",
        "output_sha256",
        "policy_bundle_sha256",
        "request_sha256",
        "system_sha256",
    }
)


def sha256_hex(data: bytes) -> str:
    """Lowercase-hex SHA-256 of exact bytes."""
    return hashlib.sha256(data).hexdigest()


def b64url(data: bytes) -> str:
    """base64url, no padding (the desktop wire encoding; design §4). The Rust strict
    decoder rejects padding, so we strip it here."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


# ---------------------------------------------------------------------------
# §4.0a per-artifact canonical-byte formulas — each pinned to the merged desktop code.
# ---------------------------------------------------------------------------

def system_bytes(system: str) -> bytes:
    """`system` = raw UTF-8 bytes of the system string (no normalization).
    Merged desktop: `ai.rs` `sha256_hex(system.as_bytes())`."""
    return system.encode("utf-8")


def history_bytes(history: Sequence[Mapping[str, str]]) -> bytes:
    """`history` = compact JSON of `[{content, role}, ...]`, keys lexicographically
    ordered, no whitespace (JCS for this shape). Merged desktop:
    `ai.rs::governed_history_sha256` (`BTreeMap{role,content}` -> `serde_json::to_vec`)."""
    normalized = [{"content": str(m["content"]), "role": str(m["role"])} for m in history]
    return canonical_bytes(normalized)


def output_bytes(output: str) -> bytes:
    """`output` = exact UTF-8 reply bytes, unmodified (no trim/normalization).
    Merged desktop: `ai.rs` `interpret_bridge_result` (no `trim()`)."""
    return output.encode("utf-8")


def generation_config_bytes(generation_config: str) -> bytes:
    """`generation_config` = raw canonical bytes of the generation-config string, exactly
    as the desktop serializes `GENERATION_CONFIG`. Merged desktop:
    `ai.rs` `sha256_hex(generation_config.as_bytes())`."""
    return generation_config.encode("utf-8")


def system_sha256(system: str) -> str:
    return sha256_hex(system_bytes(system))


def history_sha256(history: Sequence[Mapping[str, str]]) -> str:
    return sha256_hex(history_bytes(history))


def output_sha256(output: str) -> str:
    return sha256_hex(output_bytes(output))


def generation_config_sha256(generation_config: str) -> str:
    return sha256_hex(generation_config_bytes(generation_config))


def containment_evidence_bytes(containment_evidence: Mapping[str, Any]) -> bytes:
    """`containment_evidence` = exact JCS bytes of the containment-evidence object the
    supervisor produces (strict canonical JSON). Design §4.0a — frozen here in 3b-1."""
    return canonical_bytes(dict(containment_evidence))


def containment_evidence_sha256(containment_evidence: Mapping[str, Any]) -> str:
    return sha256_hex(containment_evidence_bytes(containment_evidence))


def policy_bundle_sha256(policy_bundle: bytes) -> str:
    """`policy_bundle` = exact bytes of the operator-provisioned policy bundle as loaded,
    byte-identical to what the desktop pins as `policy_bundle_sha256`. Design §4.0a."""
    return sha256_hex(policy_bundle)


def request_sha256(
    *,
    workspace_id: str,
    install_id: str,
    request_nonce: str,
    system_sha256: str,
    history_sha256: str,
    generation_config_sha256: str,
    requested_at: str,
) -> str:
    """`request_sha256` = sha256(JCS(canonical request envelope)) (design §2.2).
    Byte-identical to Rust `receipt.rs::request_envelope_sha256`."""
    envelope = {
        "protocol": REQUEST_PROTOCOL,
        "workspace_id": workspace_id,
        "install_id": install_id,
        "request_nonce": request_nonce,
        "system_sha256": system_sha256,
        "history_sha256": history_sha256,
        "generation_config_sha256": generation_config_sha256,
        "requested_at": requested_at,
    }
    return sha256_hex(canonical_bytes(envelope))


def receipt_envelope_bytes(fields: Mapping[str, str]) -> bytes:
    """Canonical JCS bytes of the 21-field `brops.receipt.v1` envelope.

    Validates the field set is exactly `RECEIPT_FIELDS` (no missing/unknown), every value
    is a non-empty string, `protocol == RECEIPT_PROTOCOL`, and each hash field is a
    lowercase 64-hex sha256 — the same invariants the Rust strict decoder enforces, so a
    signer can never emit a receipt the desktop would reject as non-canonical.
    """
    keys = set(fields)
    expected = set(RECEIPT_FIELDS)
    missing = expected - keys
    if missing:
        raise ValueError(f"receipt envelope missing field(s): {sorted(missing)}")
    unknown = keys - expected
    if unknown:
        raise ValueError(f"receipt envelope has unknown field(s): {sorted(unknown)}")
    for key in RECEIPT_FIELDS:
        value = fields[key]
        if not isinstance(value, str) or value == "":
            raise ValueError(f"receipt field `{key}` must be a non-empty string")
    if fields["protocol"] != RECEIPT_PROTOCOL:
        raise ValueError(f"receipt `protocol` must be `{RECEIPT_PROTOCOL}`")
    for key in _HASH_FIELDS:
        value = fields[key]
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"receipt field `{key}` must be a lowercase 64-hex sha256")
    return canonical_bytes(dict(fields))
