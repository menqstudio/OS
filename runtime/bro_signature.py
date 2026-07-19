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

The trusted key registry is signed by the offline operator root key, but the
registry may NOT name its own anchor: the operator-root public key is pinned from
outside the tree (BRO_OPERATOR_ROOT_PUBKEY_FILE for production, or
BRO_OPERATOR_ROOT_PUBKEY for CI). Otherwise an attacker who can write
config/trusted-keys.json simply replaces the whole document — a new operator key,
self-signed, listed as its own operator entry — and every downstream signature
verifies. With the anchor external and unforgeable, writing the registry is not
enough to introduce a key. Every artifact type is bound to an authority type, so a
builder key cannot sign a verifier receipt even if the builder is otherwise
legitimate.
"""

from __future__ import annotations

import json
import os
import pathlib
import stat
import time
from collections.abc import Mapping
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

# The operator-root public key is pinned from OUTSIDE the registry. Production
# points BRO_OPERATOR_ROOT_PUBKEY_FILE at an operator-controlled file; CI passes
# the raw key in BRO_OPERATOR_ROOT_PUBKEY. The registry payload is never the pin.
ENV_PIN = "BRO_OPERATOR_ROOT_PUBKEY"
ENV_PIN_FILE = "BRO_OPERATOR_ROOT_PUBKEY_FILE"

OPERATOR = "operator-root"
ISSUER = "issuer"
EVIDENCE = "evidence-recorder"
BUILDER = "builder"
VERIFIER = "verifier"
RELEASE = "release"
# A dedicated owner-controlled authority for attesting that an interrupted or
# quarantined mutation has been recovered. It is separate from operator-root so the
# offline trust anchor is not used per recovery, and separate from the builder/issuer
# so the policed builder process cannot mint its own recovery proof.
RECOVERY = "recovery"
AUTHORITY_TYPES = {OPERATOR, ISSUER, EVIDENCE, BUILDER, VERIFIER, RELEASE, RECOVERY}

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
    # The proof that a recovery actually happened is an authorisation, not a claim,
    # so it comes from the owner-held recovery authority — never the builder, which
    # would otherwise clear its own interrupted mutation with an arbitrary token.
    "recovery-proof": RECOVERY,
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
    # The agent identity this key speaks for. Optional for backward compatibility
    # (older registries omit it), but the completion path REQUIRES it for the
    # builder and verifier keys so a signer cannot claim an identity that is not
    # cryptographically bound to its key.
    subject_agent_id: str | None = None


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
    subject = entry.get("subject_agent_id")
    if subject is not None and (not isinstance(subject, str) or not subject):
        raise SignatureError(f"key {entry['key_id']} has an invalid subject_agent_id")
    return TrustedKey(
        key_id=entry["key_id"],
        public_key=entry["public_key"],
        authority_type=entry["authority_type"],
        allowed_artifact_types=tuple(artifacts),
        not_before_epoch=entry["not_before_epoch"],
        not_after_epoch=entry["not_after_epoch"],
        status=entry["status"],
        issued_by=entry["issued_by"],
        subject_agent_id=subject,
    )


def _pin_from_file(raw_path: str, root: pathlib.Path) -> str:
    """Read the operator-root pin from an operator-controlled file.

    The file must be an absolute path to a regular, non-symlink file that lives
    OUTSIDE the repository and is not group/other-writable — otherwise whoever can
    write the tree (the very attacker the pin defends against) could write the pin
    too. The writability check is POSIX-only; CI on Windows uses the env pin.

    Containment is enforced against the *lexical* path before any resolution and
    against every path component: a path lexically inside the repo is rejected even
    when a symlink parent would redirect it outside (a repo-controlled link must not
    be able to select the anchor), and a symlink at ANY component — not only the
    final file — is refused so no intermediate link can point the pin elsewhere.
    """
    path = pathlib.Path(raw_path)
    if not path.is_absolute():
        raise SignatureError(f"{ENV_PIN_FILE} must be an absolute path: {raw_path!r}")
    # (1) Lexical containment BEFORE resolving: normalise `.`/`..` without touching
    # the filesystem and reject anything under the repo (compared against both the
    # lexical root and its resolved form), so a repo-controlled symlink cannot be
    # laundered into an "external" anchor.
    lexical = pathlib.Path(os.path.normpath(str(path)))
    for boundary in {root, root.resolve()}:
        if lexical == boundary or boundary in lexical.parents:
            raise SignatureError(f"{ENV_PIN_FILE} must be outside the repository: {path}")
    # (2) No symlink at ANY component, walked from the filesystem root down to the
    # file, so no intermediate or final link can redirect the anchor.
    for component in (*reversed(path.parents), path):
        if component.is_symlink():
            raise SignatureError(f"{ENV_PIN_FILE} path component is a symlink: {component}")
    try:
        info = path.lstat()
    except OSError as exc:
        raise SignatureError(f"cannot stat {ENV_PIN_FILE}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise SignatureError(f"{ENV_PIN_FILE} must be a regular file: {path}")
    # (3) Resolved containment, defence in depth (no symlinks remain to follow).
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved == root_resolved or root_resolved in resolved.parents:
        raise SignatureError(f"{ENV_PIN_FILE} must be outside the repository: {path}")
    if os.name == "posix" and (info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
        raise SignatureError(f"{ENV_PIN_FILE} must not be group/other-writable: {path}")
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SignatureError(f"cannot read {ENV_PIN_FILE}: {exc}") from exc


def resolve_operator_root_pin(env: Mapping[str, str] | None = None,
                              root: pathlib.Path = ROOT) -> str:
    """Resolve the operator-root public key from an out-of-registry pin.

    The registry may not name its own trust anchor (that let an attacker who could
    write config/trusted-keys.json replace the whole document — new operator key,
    self-signed — with every downstream verify still passing). The anchor comes from
    a file the operator controls (BRO_OPERATOR_ROOT_PUBKEY_FILE, production) or an
    environment variable (BRO_OPERATOR_ROOT_PUBKEY, CI). If both are set they must
    name the same key; a mismatch, or neither being set, is a hard failure. There is
    no precedence order and no fallback to the registry payload.
    """
    env = os.environ if env is None else env
    raw_file = env.get(ENV_PIN_FILE)
    file_key = _pin_from_file(raw_file, root) if raw_file else None
    raw_env = env.get(ENV_PIN)
    env_key = raw_env.strip() if raw_env else None
    if file_key and env_key and file_key != env_key:
        raise SignatureError(
            f"operator-root pin mismatch between {ENV_PIN_FILE} and {ENV_PIN}")
    pin = file_key or env_key
    if not pin:
        raise SignatureError(
            f"no operator-root pin: set {ENV_PIN_FILE} (production) or {ENV_PIN} "
            "(CI); the registry may not name its own trust anchor")
    _public_key(pin)  # reject a malformed pin before it is trusted
    return pin


def load_trusted_keys(root: pathlib.Path = ROOT,
                      operator_public_key: str | None = None) -> dict[str, TrustedKey]:
    """Load the registry, refusing it unless the offline operator signed it.

    A registry that is merely present is not trusted. The operator-root anchor is
    pinned from OUTSIDE the registry (see ``resolve_operator_root_pin``): without
    that, an attacker who can write the file simply supplies their own operator key
    in the payload, self-signs, and every downstream signature verifies against it.
    A caller may inject an already-resolved pin as ``operator_public_key``; when it
    is None the pin is resolved from the external environment, never the payload.
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
    if operator_public_key is not None:
        pin = operator_public_key
    else:
        pin = resolve_operator_root_pin(root=root)
    # The payload may still carry operator_public_key for provenance, but it is not
    # the anchor: if it disagrees with the external pin, the registry is lying about
    # its root and must be refused.
    declared = payload.get("operator_public_key")
    if isinstance(declared, str) and declared and declared != pin:
        raise SignatureError(
            "registry operator_public_key does not match the external operator pin")
    verify_detached(payload, document["signature"], pin)

    entries = payload.get("keys")
    if not isinstance(entries, list) or not entries:
        raise SignatureError("trusted key registry contains no keys")
    keys: dict[str, TrustedKey] = {}
    for entry in entries:
        key = _parse_key(entry)
        if key.key_id in keys:
            raise SignatureError(f"duplicate key id: {key.key_id}")
        keys[key.key_id] = key
    if not any(k.authority_type == OPERATOR and k.public_key == pin
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
