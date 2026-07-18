"""Asymmetric artifact authority.

The audit's central finding was not that signing was missing but that it was
symmetric. `bro_security.verify_signed_document` is HMAC, so the verifying key is
the signing key, and the hook that verifies a verifier receipt runs inside the
agent's own process. A builder therefore holds the key that mints its own GREEN
receipt, and `validate_verifier_assignment` and `independence_level` describe a
separation the cryptography cannot enforce.

Ed25519 fixes that shape. This module only ever verifies, and only ever loads
public keys. Private keys belong to the issuer, the evidence recorder, the
verifier and the offline operator, each outside any agent process. Nothing here
can produce a signature, which is the point: an enforcement point that could sign
is an enforcement point that could forge.

The trusted key registry is itself signed by the offline operator root key, so an
attacker who can write the registry still cannot introduce a key. Every artifact
type is bound to an authority type, so a builder key cannot sign a verifier
receipt even if the builder is otherwise legitimate.
"""

from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass
from typing import Any

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
except ImportError as exc:  # pragma: no cover - exercised by the dependency gate
    raise ImportError(
        "cryptography is required for asymmetric artifact authority") from exc

ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTRY_REL = "config/trusted-keys.json"

OPERATOR = "operator-root"
ISSUER = "issuer"
EVIDENCE = "evidence-recorder"
BUILDER = "builder"
VERIFIER = "verifier"
RELEASE = "release"
AUTHORITY_TYPES = {OPERATOR, ISSUER, EVIDENCE, BUILDER, VERIFIER, RELEASE}

ACTIVE = "active"
REVOKED = "revoked"

# A builder may sign its own completion claim; a claim is not an authorisation.
# It may never sign a verifier receipt, which is one.
ARTIFACT_AUTHORITY = {
    "task-contract": ISSUER,
    "agent-profile": ISSUER,
    "mode-grant": ISSUER,
    "execution-lease": ISSUER,
    # The prepared recovery record is consumed in-process at the same mutation
    # transaction boundary as the execution lease (bro_control_plane.prepare_mutation
    # sits beside reserve_execution_lease), and Ed25519 only closes the forge gap if
    # the signer is external to the builder — the same per-action authorizer that
    # issues the lease. It therefore takes the issuer authority, like the lease.
    "recovery-record": ISSUER,
    "protected-authority": OPERATOR,
    "workspace-binding": OPERATOR,
    "evidence-event": EVIDENCE,
    # The head anchors where a chain ends. It must come from the recorder, never
    # the builder, or the builder signs a head describing whichever prefix suits it.
    "evidence-head": EVIDENCE,
    "completion-manifest": BUILDER,
    "verifier-receipt": VERIFIER,
    "release-grant": RELEASE,
    "trusted-key-registry": OPERATOR,
}


class SignatureError(Exception):
    pass


@dataclass(frozen=True)
class TrustedKey:
    key_id: str
    public_key: str
    authority_type: str
    allowed_artifact_types: tuple[str, ...]
    not_before_epoch: int
    not_after_epoch: int
    status: str
    issued_by: str


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _public_key(hex_key: str) -> Ed25519PublicKey:
    try:
        raw = bytes.fromhex(hex_key)
    except ValueError as exc:
        raise SignatureError(f"public key is not hex: {exc}") from exc
    if len(raw) != 32:
        raise SignatureError(f"ed25519 public key must be 32 bytes, got {len(raw)}")
    try:
        return Ed25519PublicKey.from_public_bytes(raw)
    except Exception as exc:  # noqa: BLE001 - library raises assorted types
        raise SignatureError(f"unusable public key: {exc}") from exc


def verify_detached(payload: dict[str, Any], signature_hex: str,
                    public_key_hex: str) -> None:
    try:
        signature = bytes.fromhex(signature_hex)
    except (ValueError, TypeError) as exc:
        raise SignatureError(f"signature is not hex: {exc}") from exc
    try:
        _public_key(public_key_hex).verify(signature, canonical_bytes(payload))
    except InvalidSignature as exc:
        raise SignatureError("signature does not match payload") from exc


def _parse_key(entry: Any) -> TrustedKey:
    if not isinstance(entry, dict):
        raise SignatureError("trusted key entry must be an object")
    for field in ("key_id", "public_key", "authority_type", "status", "issued_by"):
        if not isinstance(entry.get(field), str) or not entry[field]:
            raise SignatureError(f"trusted key entry missing {field}")
    if entry["authority_type"] not in AUTHORITY_TYPES:
        raise SignatureError(f"unknown authority type: {entry['authority_type']}")
    if entry["status"] not in {ACTIVE, REVOKED}:
        raise SignatureError(f"unknown key status: {entry['status']}")
    artifacts = entry.get("allowed_artifact_types")
    if not isinstance(artifacts, list) or not artifacts:
        raise SignatureError(f"key {entry['key_id']} allows no artifact types")
    for artifact in artifacts:
        if artifact not in ARTIFACT_AUTHORITY:
            raise SignatureError(f"unknown artifact type: {artifact}")
        if ARTIFACT_AUTHORITY[artifact] != entry["authority_type"]:
            raise SignatureError(
                f"key {entry['key_id']} is {entry['authority_type']} and may not "
                f"be allowed to sign {artifact}, which requires "
                f"{ARTIFACT_AUTHORITY[artifact]}")
    for field in ("not_before_epoch", "not_after_epoch"):
        if not isinstance(entry.get(field), int):
            raise SignatureError(f"trusted key entry missing {field}")
    _public_key(entry["public_key"])
    return TrustedKey(
        key_id=entry["key_id"],
        public_key=entry["public_key"],
        authority_type=entry["authority_type"],
        allowed_artifact_types=tuple(artifacts),
        not_before_epoch=entry["not_before_epoch"],
        not_after_epoch=entry["not_after_epoch"],
        status=entry["status"],
        issued_by=entry["issued_by"],
    )


def load_trusted_keys(root: pathlib.Path = ROOT,
                      operator_public_key: str | None = None) -> dict[str, TrustedKey]:
    """Load the registry, refusing it unless the offline operator signed it.

    A registry that is merely present is not trusted. Without this check an
    attacker who can write the file simply adds their own key and every
    downstream signature verifies correctly against it.
    """
    path = root / REGISTRY_REL
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SignatureError(f"cannot read trusted key registry: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SignatureError(f"invalid trusted key registry: {exc}") from exc
    if not isinstance(document, dict) or set(document) != {"payload", "signature"}:
        raise SignatureError("trusted key registry must be a signed document")
    payload = document["payload"]
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise SignatureError("unsupported trusted key registry schema")
    root_key = operator_public_key or payload.get("operator_public_key")
    if not isinstance(root_key, str) or not root_key:
        raise SignatureError("trusted key registry names no operator root key")
    verify_detached(payload, document["signature"], root_key)

    entries = payload.get("keys")
    if not isinstance(entries, list) or not entries:
        raise SignatureError("trusted key registry contains no keys")
    keys: dict[str, TrustedKey] = {}
    for entry in entries:
        key = _parse_key(entry)
        if key.key_id in keys:
            raise SignatureError(f"duplicate key id: {key.key_id}")
        keys[key.key_id] = key
    if not any(k.authority_type == OPERATOR and k.public_key == root_key
               for k in keys.values()):
        raise SignatureError("the signing operator key is not present in the registry")
    return keys


def verify_artifact(document: dict[str, Any], artifact_type: str,
                    keys: dict[str, TrustedKey], *, now: int | None = None) -> dict:
    """Verify a signed artifact against the trusted registry.

    Rejects an unknown key, a revoked key, a key outside its validity window, a
    key whose authority may not sign this artifact type, and a payload that does
    not match its signature.
    """
    if artifact_type not in ARTIFACT_AUTHORITY:
        raise SignatureError(f"unknown artifact type: {artifact_type}")
    if not isinstance(document, dict) or set(document) != {"payload", "signature"}:
        raise SignatureError("signed artifact must contain payload and signature only")
    payload = document["payload"]
    if not isinstance(payload, dict):
        raise SignatureError("signed artifact payload must be an object")
    if payload.get("artifact_type") != artifact_type:
        raise SignatureError(
            f"artifact claims to be {payload.get('artifact_type')!r} but was "
            f"verified as {artifact_type!r}")
    key_id = payload.get("key_id")
    if not isinstance(key_id, str) or key_id not in keys:
        raise SignatureError(f"unknown signing key: {key_id!r}")
    key = keys[key_id]
    if key.status != ACTIVE:
        raise SignatureError(f"key {key_id} is {key.status}")
    if artifact_type not in key.allowed_artifact_types:
        raise SignatureError(
            f"key {key_id} ({key.authority_type}) may not sign {artifact_type}")
    moment = int(time.time()) if now is None else now
    if moment < key.not_before_epoch:
        raise SignatureError(f"key {key_id} is not valid yet")
    if moment >= key.not_after_epoch:
        raise SignatureError(f"key {key_id} expired at {key.not_after_epoch}")
    verify_detached(payload, document["signature"], key.public_key)
    return payload
