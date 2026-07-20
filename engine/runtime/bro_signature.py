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

Three further bindings harden the anchor itself. The raw-env pins are honoured
only when the CI system marks the environment as CI (BRO_ENV=ci, set by workflow
configuration, never by an agent), so outside CI the trust root cannot be swapped
by environment variables alone. A registry that is not marked production may not
anchor a deployment whose pin comes from the production _FILE path. And the
registry is bound to an operator-pinned anti-rollback floor
(BRO_OPERATOR_REGISTRY_MIN[_FILE]): a superseded — but still operator-signed —
registry replayed from history is refused, which is what makes key revocation
stick.
"""

from __future__ import annotations

import hashlib
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

# Raw-env anchors are honoured ONLY when the CI system itself marks the
# environment as CI (BRO_ENV=ci, set by workflow configuration, never by an
# agent). Outside CI the file pin is the only trust anchor, so the root cannot
# be swapped by environment variables alone.
ENV_CI_FLAG = "BRO_ENV"
CI_FLAG_VALUE = "ci"

# Anti-rollback floor for the trusted-key registry, mirroring the operator pin
# pattern: production points BRO_OPERATOR_REGISTRY_MIN_FILE at an
# operator-controlled file (same containment and writability rules as the pubkey
# pin file), CI passes the raw value in BRO_OPERATOR_REGISTRY_MIN (gated by
# BRO_ENV=ci like the raw pubkey pin). The value is either the minimum acceptable
# integer registry_version/issued_at_epoch, or the sha256 hex digest of the exact
# authorized registry file. When neither is set the floor is not enforced — the
# only permissive default in this module, kept for backward compatibility, and
# explicitly weaker: without a floor a superseded, still operator-signed registry
# replays cleanly, so key revocation cannot be enforced.
ENV_REGISTRY_MIN = "BRO_OPERATOR_REGISTRY_MIN"
ENV_REGISTRY_MIN_FILE = "BRO_OPERATOR_REGISTRY_MIN_FILE"

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
    # The conductor session token binds the environment-derived conductor identity
    # (M-4) to a credential the operator issued. It is an authorisation of identity,
    # not a claim, so like the workspace binding it may only come from the
    # owner-held operator authority — never a key any agent process could hold.
    "conductor-session": OPERATOR,
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


# Access mask bits that allow modifying a pin file, its ACL, or its owner.
_WINDOWS_WRITE_MASK = (
    0x00000002      # FILE_WRITE_DATA
    | 0x00000004    # FILE_APPEND_DATA
    | 0x00000010    # FILE_WRITE_EA
    | 0x00000100    # FILE_WRITE_ATTRIBUTES
    | 0x00010000    # DELETE
    | 0x00040000    # WRITE_DAC
    | 0x00080000    # WRITE_OWNER
    | 0x10000000    # GENERIC_ALL
    | 0x40000000    # GENERIC_WRITE
)


def _refuse_non_owner_writable_windows(path: pathlib.Path, env_name: str) -> None:
    """Windows analogue of the POSIX group/other-writable refusal.

    Reads the file's DACL and rejects the pin when any access-allowed ACE grants a
    write-capable right (data, attributes, delete, DACL or owner change) to a
    principal other than the file's owner, SYSTEM, or the built-in Administrators
    group. Fail closed: an unreadable DACL, a NULL DACL (everyone writes), a
    missing owner, or an ACE shape this check cannot reason about all refuse the
    pin rather than assume it is protected.
    """
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetAce.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    advapi32.EqualSid.restype = wintypes.BOOL
    advapi32.CreateWellKnownSid.argtypes = [
        wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD)]
    advapi32.CreateWellKnownSid.restype = wintypes.BOOL
    advapi32.ConvertStringSidToSidW.argtypes = [
        wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    def well_known_sid(kind: int) -> ctypes.Array:
        size = wintypes.DWORD(68)  # SECURITY_MAX_SID_SIZE
        sid = ctypes.create_string_buffer(size.value)
        if not advapi32.CreateWellKnownSid(kind, None, sid, ctypes.byref(size)):
            raise SignatureError(
                f"cannot build a well-known SID for the {env_name} ACL check: {path}")
        return sid

    class AceHeader(ctypes.Structure):
        _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte),
                    ("AceSize", ctypes.c_ushort)]

    class AccessAllowedAce(ctypes.Structure):
        _fields_ = [("Header", AceHeader), ("Mask", ctypes.c_uint32),
                    ("SidStart", ctypes.c_uint32)]

    class Acl(ctypes.Structure):
        _fields_ = [("AclRevision", ctypes.c_ubyte), ("Sbz1", ctypes.c_ubyte),
                    ("AclSize", ctypes.c_ushort), ("AceCount", ctypes.c_ushort),
                    ("Sbz2", ctypes.c_ushort)]

    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    owner_rights = ctypes.c_void_p()
    status = advapi32.GetNamedSecurityInfoW(
        str(path), 1,  # SE_FILE_OBJECT
        0x1 | 0x4,     # OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION
        ctypes.byref(owner), None, ctypes.byref(dacl), None,
        ctypes.byref(descriptor))
    if status != 0:
        raise SignatureError(f"cannot read the {env_name} ACL (error {status}): {path}")
    try:
        if not owner.value:
            raise SignatureError(f"{env_name} has no owner: {path}")
        if not dacl.value:
            raise SignatureError(
                f"{env_name} has a NULL DACL, so it is writable by everyone: {path}")
        system = well_known_sid(22)  # WinLocalSystemSid
        admins = well_known_sid(26)  # WinBuiltinAdministratorsSid
        # OWNER RIGHTS (S-1-3-4): an ACE that by definition applies to the file's
        # current owner, so it is owner-equivalent, not a third-party grant.
        if not advapi32.ConvertStringSidToSidW("S-1-3-4", ctypes.byref(owner_rights)):
            raise SignatureError(
                f"cannot build the OWNER RIGHTS SID for the {env_name} ACL check: {path}")
        count = ctypes.cast(dacl, ctypes.POINTER(Acl)).contents.AceCount
        for index in range(count):
            ace_ptr = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace_ptr)):
                raise SignatureError(
                    f"cannot read ACE {index} of the {env_name} ACL: {path}")
            header = ctypes.cast(ace_ptr, ctypes.POINTER(AceHeader)).contents
            if header.AceFlags & 0x08:  # INHERIT_ONLY_ACE: not effective here
                continue
            if header.AceType in (1, 2, 3):  # deny/audit/alarm ACEs grant nothing
                continue
            if header.AceType != 0:  # not a plain ACCESS_ALLOWED_ACE
                raise SignatureError(
                    f"{env_name} carries ACE type {header.AceType}, which this "
                    f"check cannot prove harmless: {path}")
            ace = ctypes.cast(ace_ptr, ctypes.POINTER(AccessAllowedAce)).contents
            if not ace.Mask & _WINDOWS_WRITE_MASK:
                continue
            sid = ctypes.c_void_p(ace_ptr.value + AccessAllowedAce.SidStart.offset)
            if (advapi32.EqualSid(sid, owner) or advapi32.EqualSid(sid, system)
                    or advapi32.EqualSid(sid, admins)
                    or advapi32.EqualSid(sid, owner_rights)):
                continue
            raise SignatureError(
                f"{env_name} must not be writable by non-owner principals: {path}")
    finally:
        kernel32.LocalFree(owner_rights)
        kernel32.LocalFree(descriptor)


def _pin_from_file(raw_path: str, root: pathlib.Path,
                   env_name: str = ENV_PIN_FILE) -> str:
    """Read an operator pin (trust anchor or registry floor) from a file.

    The file must be an absolute path to a regular, non-symlink file that lives
    OUTSIDE the repository and is writable only by its owner (POSIX: not
    group/other-writable; Windows: an owner-only DACL) — otherwise whoever can
    write the tree (the very attacker the pin defends against) could write the pin
    too. On a platform with neither check the file pin is refused outright: "no
    permission model" is not "no permission requirement".

    Containment is enforced against the *lexical* path before any resolution and
    against every path component: a path lexically inside the repo is rejected even
    when a symlink parent would redirect it outside (a repo-controlled link must not
    be able to select the anchor), and a symlink at ANY component — not only the
    final file — is refused so no intermediate link can point the pin elsewhere.
    """
    path = pathlib.Path(raw_path)
    if not path.is_absolute():
        raise SignatureError(f"{env_name} must be an absolute path: {raw_path!r}")
    # (1) Lexical containment BEFORE resolving: normalise `.`/`..` without touching
    # the filesystem and reject anything under the repo (compared against both the
    # lexical root and its resolved form), so a repo-controlled symlink cannot be
    # laundered into an "external" anchor.
    lexical = pathlib.Path(os.path.normpath(str(path)))
    for boundary in {root, root.resolve()}:
        if lexical == boundary or boundary in lexical.parents:
            raise SignatureError(f"{env_name} must be outside the repository: {path}")
    # (2) No symlink at ANY component, walked from the filesystem root down to the
    # file, so no intermediate or final link can redirect the anchor.
    for component in (*reversed(path.parents), path):
        if component.is_symlink():
            raise SignatureError(f"{env_name} path component is a symlink: {component}")
    try:
        info = path.lstat()
    except OSError as exc:
        raise SignatureError(f"cannot stat {env_name}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise SignatureError(f"{env_name} must be a regular file: {path}")
    # (3) Resolved containment, defence in depth (no symlinks remain to follow).
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved == root_resolved or root_resolved in resolved.parents:
        raise SignatureError(f"{env_name} must be outside the repository: {path}")
    # (4) Owner-only writability, per platform; a platform with no check refuses.
    if os.name == "posix":
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise SignatureError(f"{env_name} must not be group/other-writable: {path}")
    elif os.name == "nt":
        _refuse_non_owner_writable_windows(path, env_name)
    else:
        raise SignatureError(
            f"{env_name} is refused on {os.name}: no owner-only permission check "
            "is available, and an unchecked pin file is not an anchor")
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SignatureError(f"cannot read {env_name}: {exc}") from exc


def _env_is_ci(env: Mapping[str, str]) -> bool:
    """True only when the CI system itself marked the environment (BRO_ENV=ci).

    The flag must be set by workflow configuration, outside any agent process; it
    gates the raw-env anchors, which are otherwise refused so the trust root
    cannot be swapped by environment variables alone.
    """
    return env.get(ENV_CI_FLAG, "").strip() == CI_FLAG_VALUE


def _resolve_operator_root_pin(env: Mapping[str, str],
                               root: pathlib.Path) -> tuple[str, bool]:
    """Resolve the pin; also report whether it came from the production file."""
    raw_file = env.get(ENV_PIN_FILE)
    file_key = _pin_from_file(raw_file, root, ENV_PIN_FILE) if raw_file else None
    raw_env = env.get(ENV_PIN)
    env_key = raw_env.strip() if raw_env else None
    if env_key and not _env_is_ci(env):
        raise SignatureError(
            f"{ENV_PIN} is honoured only in CI ({ENV_CI_FLAG}={CI_FLAG_VALUE}); "
            f"outside CI the anchor must come from {ENV_PIN_FILE}, so the trust "
            "root cannot be swapped by environment variables alone")
    if file_key and env_key and file_key != env_key:
        raise SignatureError(
            f"operator-root pin mismatch between {ENV_PIN_FILE} and {ENV_PIN}")
    pin = file_key or env_key
    if not pin:
        raise SignatureError(
            f"no operator-root pin: set {ENV_PIN_FILE} (production) or {ENV_PIN} "
            "(CI); the registry may not name its own trust anchor")
    _public_key(pin)  # reject a malformed pin before it is trusted
    return pin, file_key is not None


def resolve_operator_root_pin(env: Mapping[str, str] | None = None,
                              root: pathlib.Path = ROOT) -> str:
    """Resolve the operator-root public key from an out-of-registry pin.

    The registry may not name its own trust anchor (that let an attacker who could
    write config/trusted-keys.json replace the whole document — new operator key,
    self-signed — with every downstream verify still passing). The anchor comes from
    a file the operator controls (BRO_OPERATOR_ROOT_PUBKEY_FILE, production) or an
    environment variable (BRO_OPERATOR_ROOT_PUBKEY, CI only: it is refused unless
    the CI system set BRO_ENV=ci, so a raw env var alone can never establish the
    trust root outside CI). If both are set they must name the same key; a
    mismatch, or neither being set, is a hard failure. There is no precedence
    order and no fallback to the registry payload.
    """
    env = os.environ if env is None else env
    pin, _ = _resolve_operator_root_pin(env, root)
    return pin


def _parse_registry_floor(value: str, source: str) -> tuple[str, int | str]:
    """Parse an anti-rollback floor: a sha256 digest pin or an integer minimum.

    64 hex characters pin the sha256 of the exact authorized registry file; any
    other value must be a non-negative decimal integer, the minimum acceptable
    registry_version/issued_at_epoch. Anything else is refused — a floor that
    cannot be understood must not silently become no floor.
    """
    if len(value) == 64:
        try:
            bytes.fromhex(value)
        except ValueError as exc:
            raise SignatureError(
                f"{source} looks like a sha256 pin but is not hex: {value!r}") from exc
        return "sha256", value.lower()
    if value.isascii() and value.isdigit():
        return "minimum", int(value)
    raise SignatureError(
        f"{source} must be the sha256 hex digest of the authorized registry file "
        f"or a non-negative integer version/epoch floor, got: {value!r}")


def resolve_registry_floor(env: Mapping[str, str] | None = None,
                           root: pathlib.Path = ROOT) -> tuple[str, int | str] | None:
    """Resolve the operator-pinned registry anti-rollback floor.

    Mirrors the operator-root pin: BRO_OPERATOR_REGISTRY_MIN_FILE (production,
    same containment and owner-only writability rules as the pubkey pin file) or
    BRO_OPERATOR_REGISTRY_MIN (CI only, gated by BRO_ENV=ci). If both are set
    they must agree. Returns ("sha256", digest) or ("minimum", floor), or None
    when no floor is pinned — the only permissive default in this module, kept
    for backward compatibility, and explicitly weaker: without a floor a
    superseded, still operator-signed registry replays cleanly, so key
    revocation cannot be enforced.
    """
    env = os.environ if env is None else env
    raw_file = env.get(ENV_REGISTRY_MIN_FILE)
    file_floor = (_pin_from_file(raw_file, root, ENV_REGISTRY_MIN_FILE)
                  if raw_file else None)
    raw_env = env.get(ENV_REGISTRY_MIN)
    env_floor = raw_env.strip() if raw_env else None
    if env_floor and not _env_is_ci(env):
        raise SignatureError(
            f"{ENV_REGISTRY_MIN} is honoured only in CI "
            f"({ENV_CI_FLAG}={CI_FLAG_VALUE}); outside CI the floor must come "
            f"from {ENV_REGISTRY_MIN_FILE}")
    if file_floor and env_floor and file_floor != env_floor:
        raise SignatureError(
            f"registry floor mismatch between {ENV_REGISTRY_MIN_FILE} and "
            f"{ENV_REGISTRY_MIN}")
    floor = file_floor or env_floor
    if not floor:
        return None
    return _parse_registry_floor(
        floor, ENV_REGISTRY_MIN_FILE if file_floor else ENV_REGISTRY_MIN)


def load_trusted_keys(root: pathlib.Path = ROOT,
                      operator_public_key: str | None = None,
                      *, env: Mapping[str, str] | None = None) -> dict[str, TrustedKey]:
    """Load the registry, refusing it unless the offline operator signed it.

    A registry that is merely present is not trusted. The operator-root anchor is
    pinned from OUTSIDE the registry (see ``resolve_operator_root_pin``): without
    that, an attacker who can write the file simply supplies their own operator key
    in the payload, self-signs, and every downstream signature verifies against it.
    A caller may inject an already-resolved pin as ``operator_public_key``; when it
    is None the pin is resolved from the external environment, never the payload.

    Beyond the signature, the registry must clear two anchor-bound checks. When
    the pin comes from the production ``BRO_OPERATOR_ROOT_PUBKEY_FILE`` path
    (including an injected pin while that variable is set), the payload must be
    marked ``production: true`` — a development registry, whose private halves
    exist on a dev machine, may not anchor production. And when an anti-rollback
    floor is pinned (see ``resolve_registry_floor``), a registry below the floor —
    an older ``registry_version``/``issued_at_epoch``, or a file digest other than
    the pinned one — is refused even though it is operator-signed, so replaying a
    superseded registry cannot resurrect a revoked key.
    """
    env = os.environ if env is None else env
    path = root / REGISTRY_REL
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SignatureError(f"cannot read trusted key registry: {exc}") from exc
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SignatureError(f"invalid trusted key registry: {exc}") from exc
    if not isinstance(document, dict) or set(document) != {"payload", "signature"}:
        raise SignatureError("trusted key registry must be a signed document")
    payload = document["payload"]
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise SignatureError("unsupported trusted key registry schema")
    if operator_public_key is not None:
        pin = operator_public_key
        # An injected pin does not bypass the production binding: if the
        # environment names the production file pin, this is a production path.
        pinned_from_file = bool(env.get(ENV_PIN_FILE))
    else:
        pin, pinned_from_file = _resolve_operator_root_pin(env, root)
    # The payload may still carry operator_public_key for provenance, but it is not
    # the anchor: if it disagrees with the external pin, the registry is lying about
    # its root and must be refused.
    declared = payload.get("operator_public_key")
    if isinstance(declared, str) and declared and declared != pin:
        raise SignatureError(
            "registry operator_public_key does not match the external operator pin")
    verify_detached(payload, document["signature"], pin)

    if pinned_from_file and payload.get("production") is not True:
        raise SignatureError(
            "registry is not marked production=true, but the operator pin comes "
            f"from the production {ENV_PIN_FILE} path; a development registry may "
            "not anchor a production deployment")

    floor = resolve_registry_floor(env=env, root=root)
    if floor is not None:
        kind, bound = floor
        if kind == "sha256":
            digest = hashlib.sha256(raw).hexdigest()
            if digest != bound:
                raise SignatureError(
                    f"trusted key registry sha256 {digest} does not match the "
                    f"pinned digest {bound}; an operator signature alone does not "
                    "make a superseded registry current")
        else:
            marker = payload.get("registry_version", payload.get("issued_at_epoch"))
            if isinstance(marker, bool) or not isinstance(marker, int):
                raise SignatureError(
                    "an anti-rollback floor is pinned but the registry carries no "
                    "integer registry_version/issued_at_epoch to compare against")
            if marker < bound:
                raise SignatureError(
                    f"rolled-back trusted key registry: version {marker} is below "
                    f"the pinned floor {bound}; a superseded registry stays "
                    "superseded even though the operator signed it")

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
