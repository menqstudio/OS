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
configuration, never by an agent), so outside CI the trust root cannot be swapped by
environment variables alone — PROVIDED the pin file belongs to a principal this
process cannot impersonate. A file the reading account can REWRITE is one write away
from being any anchor that account likes, so it is refused unless the deployment
acknowledges having no principal separation. "Can rewrite" is asked of the operating
system, not guessed from ownership: on Windows an AccessCheck of the file's real
security descriptor against this process's real token, plus the privileges that
override any descriptor; on POSIX the file's mode and owner, the kernel's own access
answer, and whether the containing directory would let the file simply be replaced.
Asking instead whether the owner is literally this process's account answers NO for an
administrator — whose files are owned by BUILTIN\\Administrators — and so silently
exempted exactly the configuration where the danger is real
(BRO_OPERATOR_ROOT_PIN_SELF_OWNED=acknowledged, audit F-06); an acknowledged
self-owned anchor is exactly as strong as the account that holds it, and callers are
told so rather than left with the unqualified claim. A registry that is not marked production may not
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
# (audit F-06) An anchor the reading account OWNS is an anchor that account can
# rewrite, so a self-owned pin is refused by default. Some deployments genuinely have
# no principal separation to offer — a single-user laptop, a CI container that runs
# everything as one uid. Those may set this to `acknowledged`, which does not make the
# anchor stronger; it makes the weakness explicit and reportable instead of silent.
ENV_PIN_SELF_OWNED_ACK = "BRO_OPERATOR_ROOT_PIN_SELF_OWNED"
PIN_SELF_OWNED_ACK_VALUE = "acknowledged"

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
    # O-4. The control-room command itself, so an owner-issued command can be a signed
    # artifact instead of two strings out of the caller's own JSON. Registering the type
    # provisions NOTHING and weakens nothing: `verify_artifact` still requires the
    # presented key to carry "control-room-command" in its OWN allowed_artifact_types,
    # the committed config/trusted-keys.json grants it to no key, and no key material is
    # shipped or generated here. What the entry buys is that the owner CAN be given one —
    # before it, `_parse_key` refused any registry entry naming the type, so the closure
    # could not be provisioned from configuration at all. Until the owner mints an
    # offline key and pins it, an owner-issued command remains a refusal by name.
    "control-room-command": OPERATOR,
    # O-5. The operator's statement of the evidence high-water mark for one task, read
    # from BRO_EVIDENCE_FLOOR_ANCHOR when a floor was deleted and re-provisioned. It is
    # an authorisation about state the policed builder can write, so it may only come
    # from the owner-held operator authority. The same rule applies: a registered type is
    # not a provisioned key. With no pinned key allowed to sign it, `_signed_floor_anchor`
    # refuses every presented anchor — exactly as it did before this entry existed.
    "evidence-floor-anchor": OPERATOR,
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

# The individual rights that let their holder change what the pin file says, ordered
# from the most direct rewrite to the indirect routes (delete and recreate, rewrite
# the DACL, take ownership and then rewrite the DACL). Named one by one so a refusal
# can report WHICH right the reading process holds instead of "write access".
_WINDOWS_REWRITE_RIGHTS = (
    ("FILE_WRITE_DATA", 0x00000002),
    ("FILE_APPEND_DATA", 0x00000004),
    ("DELETE", 0x00010000),
    ("WRITE_DAC", 0x00040000),
    ("WRITE_OWNER", 0x00080000),
)

# Privileges that make the DACL irrelevant: their holder can take ownership of any
# object, or restore over it, and then rewrite it at will. `AccessCheck` deliberately
# does not consider privileges, so they are asked for separately — otherwise this
# refusal would once again fail to apply to the account that most obviously CAN
# rewrite the anchor. Presence, not enabled state, disqualifies it: a token may enable
# any privilege it holds without asking anyone.
_WINDOWS_OVERRIDE_PRIVILEGES = ("SeTakeOwnershipPrivilege", "SeRestorePrivilege")

# `os.access` answers with the REAL uid/gid unless the platform can be asked for the
# effective ones. A process that dropped privileges only in its effective ids is
# exactly the case where the difference decides whether it can rewrite the anchor, so
# ask for effective ids wherever the platform offers them.
_POSIX_EFFECTIVE_IDS = os.access in getattr(os, "supports_effective_ids", frozenset())


def _self_owned_pin_acknowledged() -> bool:
    """True when the deployment has explicitly accepted a self-owned trust anchor (F-06).

    Read from the live environment rather than a passed-in mapping so the same answer
    holds for every pin-file read on this process, including the registry floor.
    """
    return os.environ.get(ENV_PIN_SELF_OWNED_ACK, "").strip() == PIN_SELF_OWNED_ACK_VALUE


def _windows_process_user_sid(env_name: str, path: pathlib.Path):
    """The SID of the account this process runs as, for the F-06 self-ownership refusal.

    The SID bytes are COPIED into a buffer the caller owns; returning a pointer into
    the token-information block would dangle the moment that block is collected, and a
    dangling comparison is one that silently never matches. Any failure raises rather
    than returning a value that would quietly disable the check.
    """
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
    advapi32.GetLengthSid.restype = wintypes.DWORD

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
        raise SignatureError(
            f"cannot open this process's token to check {env_name} ownership: {path}")
    try:
        size = wintypes.DWORD(0)
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser
        if size.value == 0:
            raise SignatureError(
                f"cannot size this process's token user for the {env_name} check: {path}")
        buf = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(token, 1, buf, size, ctypes.byref(size)):
            raise SignatureError(
                f"cannot read this process's token user for the {env_name} check: {path}")
        # TOKEN_USER is { SID_AND_ATTRIBUTES { PSID Sid; DWORD Attributes; } } — the
        # first pointer-sized field is the SID pointer, into this same buffer.
        sid_ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p)).contents
        if not sid_ptr.value:
            raise SignatureError(
                f"this process's token carries no user SID for the {env_name} check: {path}")
        length = advapi32.GetLengthSid(sid_ptr)
        if length == 0:
            raise SignatureError(
                f"cannot size this process's user SID for the {env_name} check: {path}")
        copy = ctypes.create_string_buffer(length)
        ctypes.memmove(copy, sid_ptr, length)
        return copy
    finally:
        kernel32.CloseHandle(token)


def _windows_account_label(sid_ptr) -> str:
    """``DOMAIN\\name (S-1-5-…)`` for a SID, or the SID text alone if it does not resolve.

    Used only to make a refusal readable — a reader who sees "granted through
    BUILTIN\\Administrators" can act on it, one who sees "granted" cannot. A lookup
    failure must never change a decision, so it degrades to the SID string instead of
    raising; the decision is taken before this is ever called.
    """
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.LookupAccountSidW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_void_p, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
    advapi32.LookupAccountSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    text = "<unprintable SID>"
    printed = wintypes.LPWSTR()
    if advapi32.ConvertSidToStringSidW(sid_ptr, ctypes.byref(printed)):
        text = printed.value
        kernel32.LocalFree(ctypes.cast(printed, ctypes.c_void_p))
    name = ctypes.create_unicode_buffer(256)
    name_len = wintypes.DWORD(256)
    domain = ctypes.create_unicode_buffer(256)
    domain_len = wintypes.DWORD(256)
    use = wintypes.DWORD()
    if advapi32.LookupAccountSidW(None, sid_ptr, name, ctypes.byref(name_len),
                                  domain, ctypes.byref(domain_len), ctypes.byref(use)):
        prefix = f"{domain.value}\\" if domain.value else ""
        return f"{prefix}{name.value} ({text})"
    return text


def _windows_pin_rewrite_grant(path: pathlib.Path, env_name: str,
                               descriptor, owner, dacl):
    """Can the process reading this pin rewrite it? Returns (right, principal) or None.

    (audit F-06, Windows) The question this must answer is NOT "is the file's owner
    literally my user SID?". That was a proxy, and it fails open in exactly the
    configuration where the danger is real: a process running as an administrator
    stamps BUILTIN\\Administrators — not its user SID — as the owner of every file it
    creates, so the proxy compares unequal and the refusal silently does not apply to
    the account that most obviously can rewrite the anchor.

    `AccessCheck` asks the real question. It evaluates the file's whole security
    descriptor against this process's whole token — user SID, every group SID, their
    deny-only flags, and the rights an owner holds implicitly whether or not any ACE
    grants them — which is precisely the evaluation the kernel performs when the file
    is opened for writing. `GetEffectiveRightsFromAclW` was the alternative and was
    rejected: it answers per trustee, so it cannot see "granted to me through a group
    I am in" unless the caller re-derives group membership itself and re-implements the
    union; it reads only the DACL, so it misses the owner's implicit WRITE_DAC; and its
    own documentation warns the result is wrong when deny ACEs and group grants
    interact. Reimplementing the access algorithm to make an access decision is how the
    first version of this check went wrong.

    Fail closed: an `AccessCheck` that cannot be performed raises rather than reporting
    "no write".
    """
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.DuplicateTokenEx.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, ctypes.c_int,
        ctypes.c_int, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.DuplicateTokenEx.restype = wintypes.BOOL
    advapi32.AccessCheck.argtypes = [
        ctypes.c_void_p, wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.BOOL)]
    advapi32.AccessCheck.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    advapi32.EqualSid.restype = wintypes.BOOL

    class GenericMapping(ctypes.Structure):
        _fields_ = [("GenericRead", wintypes.DWORD), ("GenericWrite", wintypes.DWORD),
                    ("GenericExecute", wintypes.DWORD), ("GenericAll", wintypes.DWORD)]

    class Luid(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", ctypes.c_long)]

    class LuidAndAttributes(ctypes.Structure):
        _fields_ = [("Luid", Luid), ("Attributes", wintypes.DWORD)]

    class PrivilegeSet(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Control", wintypes.DWORD),
                    ("Privilege", LuidAndAttributes * 16)]

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

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

    # FILE_GENERIC_READ / _WRITE / _EXECUTE / FILE_ALL_ACCESS, so AccessCheck can
    # resolve any GENERIC_* bits an ACE carries into the file-specific rights asked for.
    mapping = GenericMapping(0x00120089, 0x00120116, 0x001200A0, 0x001F01FF)

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(),
            0x0008 | 0x0002,  # TOKEN_QUERY | TOKEN_DUPLICATE
            ctypes.byref(token)):
        raise SignatureError(
            f"cannot open this process's token to check who can rewrite "
            f"{env_name}: {path}")
    try:
        impersonation = wintypes.HANDLE()
        if not advapi32.DuplicateTokenEx(
                token, 0x0008 | 0x0002, None,
                2,   # SecurityImpersonation — AccessCheck requires an impersonation token
                2,   # TokenImpersonation
                ctypes.byref(impersonation)):
            raise SignatureError(
                f"cannot impersonate this process's own token to check who can "
                f"rewrite {env_name} (error {ctypes.get_last_error()}): {path}")
        try:
            granted_right = None
            for right_name, right_mask in _WINDOWS_REWRITE_RIGHTS:
                granted = wintypes.DWORD()
                allowed = wintypes.BOOL()
                privileges = PrivilegeSet()
                privileges_size = wintypes.DWORD(ctypes.sizeof(privileges))
                if not advapi32.AccessCheck(
                        descriptor, impersonation, right_mask, ctypes.byref(mapping),
                        ctypes.byref(privileges), ctypes.byref(privileges_size),
                        ctypes.byref(granted), ctypes.byref(allowed)):
                    raise SignatureError(
                        f"cannot evaluate this process's {right_name} access to "
                        f"{env_name} (error {ctypes.get_last_error()}): {path}")
                if allowed:
                    granted_right = (right_name, right_mask)
                    break
            if granted_right is None:
                return None
            right_name, right_mask = granted_right
        finally:
            kernel32.CloseHandle(impersonation)

        # The decision is made. Everything below only NAMES the principal the grant
        # arrives through, so the refusal tells its reader what to change.
        user = _windows_process_user_sid(env_name, path)
        if advapi32.EqualSid(owner, user):
            return right_name, (f"its owner, which is the very account reading it "
                                f"({_windows_account_label(owner)})")
        held = [user]
        size = wintypes.DWORD(0)
        advapi32.GetTokenInformation(token, 2, None, 0, ctypes.byref(size))  # TokenGroups
        groups = ctypes.create_string_buffer(max(size.value, 8))
        if advapi32.GetTokenInformation(token, 2, groups, size, ctypes.byref(size)):
            count = ctypes.cast(groups, ctypes.POINTER(wintypes.DWORD)).contents.value
            entries = ctypes.cast(
                ctypes.addressof(groups) + ctypes.sizeof(ctypes.c_void_p),
                ctypes.POINTER(SidAndAttributes))
            for index in range(count):
                entry = entries[index]
                if entry.Attributes & 0x10:  # SE_GROUP_USE_FOR_DENY_ONLY grants nothing
                    continue
                held.append(ctypes.c_void_p(entry.Sid))
        if dacl:
            ace_count = ctypes.cast(dacl, ctypes.POINTER(Acl)).contents.AceCount
            for index in range(ace_count):
                ace_ptr = ctypes.c_void_p()
                if not advapi32.GetAce(dacl, index, ctypes.byref(ace_ptr)):
                    continue
                header = ctypes.cast(ace_ptr, ctypes.POINTER(AceHeader)).contents
                if header.AceType != 0 or header.AceFlags & 0x08:
                    continue
                ace = ctypes.cast(ace_ptr, ctypes.POINTER(AccessAllowedAce)).contents
                if not ace.Mask & right_mask:
                    continue
                sid = ctypes.c_void_p(ace_ptr.value + AccessAllowedAce.SidStart.offset)
                for principal in held:
                    if advapi32.EqualSid(sid, principal):
                        return right_name, (
                            f"an access-allowed ACE for {_windows_account_label(sid)}, "
                            f"a principal this process's token carries")
        # groups is kept alive until here: `held` holds pointers INTO it.
        del groups
        return right_name, ("this process's token (no single access-allowed ACE "
                            "accounts for it, so it arrives through an implicit or "
                            "inherited grant)")
    finally:
        kernel32.CloseHandle(token)


def _windows_token_override_privilege(env_name: str, path: pathlib.Path):
    """The first ownership-override privilege this process's token holds, or None.

    `AccessCheck` answers "does the DACL let me in", and deliberately ignores
    privileges. A token holding SeTakeOwnershipPrivilege or SeRestorePrivilege does not
    need the DACL to let it in: it takes ownership, rewrites the DACL, and then writes.
    Asking only the DACL would leave the refusal not applying to precisely the account
    that can rewrite ANY pin — the Windows counterpart of the POSIX branch's "running
    as root fails this too, and correctly so".
    """
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL

    class Luid(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", ctypes.c_long)]

    class LuidAndAttributes(ctypes.Structure):
        _fields_ = [("Luid", Luid), ("Attributes", wintypes.DWORD)]

    advapi32.LookupPrivilegeValueW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(Luid)]
    advapi32.LookupPrivilegeValueW.restype = wintypes.BOOL

    wanted = []
    for name in _WINDOWS_OVERRIDE_PRIVILEGES:
        luid = Luid()
        if not advapi32.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
            raise SignatureError(
                f"cannot resolve {name} while checking who can rewrite "
                f"{env_name}: {path}")
        wanted.append((name, luid.LowPart, luid.HighPart))

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
        raise SignatureError(
            f"cannot open this process's token to check its privileges over "
            f"{env_name}: {path}")
    try:
        size = wintypes.DWORD(0)
        advapi32.GetTokenInformation(token, 3, None, 0, ctypes.byref(size))  # TokenPrivileges
        buf = ctypes.create_string_buffer(max(size.value, 8))
        if not advapi32.GetTokenInformation(token, 3, buf, size, ctypes.byref(size)):
            raise SignatureError(
                f"cannot read this process's privileges for the {env_name} "
                f"check: {path}")
        count = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD)).contents.value
        entries = ctypes.cast(ctypes.addressof(buf) + ctypes.sizeof(wintypes.DWORD),
                              ctypes.POINTER(LuidAndAttributes))
        for index in range(count):
            luid = entries[index].Luid
            for name, low, high in wanted:
                if luid.LowPart == low and luid.HighPart == high:
                    return name
        return None
    finally:
        kernel32.CloseHandle(token)


def _refuse_non_owner_writable_windows(path: pathlib.Path, env_name: str) -> None:
    """Windows analogue of the POSIX group/other-writable and self-owned refusals.

    Two separate questions, in this order:

    1. Can THIS process rewrite the pin? Answered against the real security descriptor
       with the real process token (`_windows_pin_rewrite_grant`), plus the privileges
       that override any descriptor (`_windows_token_override_privilege`). A yes is
       refused unless the deployment has acknowledged having no principal separation.
    2. Can anyone ELSE rewrite it? Answered by walking the DACL and rejecting any
       access-allowed ACE that grants a write-capable right (data, attributes, delete,
       DACL or owner change) to a principal other than the file's owner, SYSTEM, or the
       built-in Administrators group.

    Question 2 skips the owner, OWNER RIGHTS, SYSTEM and Administrators as
    owner-equivalent or already-trusted — which is exactly why question 1 cannot be
    folded into it, and why question 1 must not be asked as "is the owner me": under an
    administrator token the owner is BUILTIN\\Administrators and every route by which
    this process can rewrite the file runs through an ACE question 2 deliberately
    ignores.

    Fail closed throughout: an unreadable DACL, a NULL DACL (everyone writes), a
    missing owner, an access check that cannot be performed, or an ACE shape this check
    cannot reason about all refuse the pin rather than assume it is protected.
    """
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
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
    group = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    owner_rights = ctypes.c_void_p()
    status = advapi32.GetNamedSecurityInfoW(
        str(path), 1,  # SE_FILE_OBJECT
        # OWNER | GROUP | DACL. The group is not consulted by any rule here; it is
        # requested because AccessCheck refuses a descriptor that lacks an owner or a
        # primary group, and the effective-rights question below is asked with it.
        0x1 | 0x2 | 0x4,
        ctypes.byref(owner), ctypes.byref(group), ctypes.byref(dacl), None,
        ctypes.byref(descriptor))
    if status != 0:
        raise SignatureError(f"cannot read the {env_name} ACL (error {status}): {path}")
    try:
        if not owner.value:
            raise SignatureError(f"{env_name} has no owner: {path}")
        if not dacl.value:
            raise SignatureError(
                f"{env_name} has a NULL DACL, so it is writable by everyone: {path}")
        # (audit F-06) The pin exists to survive an attacker who can write the repository
        # tree. If the account READING the pin can also WRITE it, this whole check proves
        # nothing about that attacker: the anchor is one write away from being whatever
        # that account wants. "Is the owner literally my user SID?" was the question asked
        # here before, and it is only a proxy for that — it answers NO for an
        # administrator, whose files are owned by BUILTIN\Administrators rather than by
        # the user SID, and for anyone granted write through a group or an explicit ACE.
        # In every one of those cases the account can still rewrite the anchor, so the
        # proxy made the refusal silently not apply where the danger is real. Ask the
        # real question of the real security descriptor instead.
        if not _self_owned_pin_acknowledged():
            grant = _windows_pin_rewrite_grant(path, env_name, descriptor, owner, dacl)
            if grant is not None:
                right, principal = grant
                raise SignatureError(
                    f"{env_name} can be rewritten by the very account reading it: this "
                    f"process's token is granted {right} on it through {principal}. An "
                    f"anchor its reader can rewrite is not an anchor; it must belong to a "
                    f"principal this process cannot impersonate, or the deployment must "
                    f"set {ENV_PIN_SELF_OWNED_ACK}={PIN_SELF_OWNED_ACK_VALUE} to "
                    f"acknowledge that it has no principal separation: {path}")
            privilege = _windows_token_override_privilege(env_name, path)
            if privilege is not None:
                raise SignatureError(
                    f"{env_name} can be rewritten by the very account reading it: this "
                    f"process's token holds {privilege}, which lets it take ownership of "
                    f"the file and rewrite the DACL, so no ACL on it can keep this "
                    f"process out. Run the verifier under an account without that "
                    f"privilege (an elevated administrator always holds it), or set "
                    f"{ENV_PIN_SELF_OWNED_ACK}={PIN_SELF_OWNED_ACK_VALUE} to acknowledge "
                    f"that this deployment has no principal separation: {path}")
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
        # (audit F-06) Owner-only writability says nothing when the OWNER is us. The pin
        # exists to survive an attacker who can write the repository tree — that attacker
        # is this very process, and a file it owns at mode 0644 passes the check above
        # trivially while remaining one `open(..., "w")` away from any anchor it likes
        # (an owner can also chmod the mode bits back afterwards). The anchor must belong
        # to a principal this process cannot impersonate. Running as root fails this too,
        # and correctly so: root can rewrite any file, so no file pin is an anchor for it.
        if not _self_owned_pin_acknowledged():
            if info.st_uid == os.geteuid():
                raise SignatureError(
                    f"{env_name} is owned by the very account reading it (uid {info.st_uid}), "
                    f"which can rewrite it at will; the anchor must belong to another "
                    f"principal (e.g. root, or a dedicated operator account), or the "
                    f"deployment must set {ENV_PIN_SELF_OWNED_ACK}={PIN_SELF_OWNED_ACK_VALUE} "
                    f"to acknowledge that it has no principal separation: {path}")
            # The owner comparison above is a PROXY for the real question — "can the
            # account reading this pin rewrite it?" — and the same blind spot the Windows
            # branch had (audit F-06) exists here in two forms the proxy answers no to
            # while the real answer is yes. Ask the kernel directly.
            #
            # (a) Write permission that does not come from ownership: root, which can
            #     write any file regardless of uid or mode; a POSIX ACL entry; a setuid
            #     context. `os.access` evaluates the same rule the kernel does, with the
            #     effective ids where the platform supports asking for them.
            if os.access(path, os.W_OK, effective_ids=_POSIX_EFFECTIVE_IDS):
                raise SignatureError(
                    f"{env_name} is owned by uid {info.st_uid}, but the account reading it "
                    f"(euid {os.geteuid()}) has write permission on it anyway"
                    + (" — running as root, which can rewrite any file, so no file pin is "
                       "an anchor for this process" if os.geteuid() == 0 else "") +
                    f"; the anchor must belong to a principal this process cannot write as, "
                    f"or the deployment must set "
                    f"{ENV_PIN_SELF_OWNED_ACK}={PIN_SELF_OWNED_ACK_VALUE} to acknowledge "
                    f"that it has no principal separation: {path}")
            # (b) The file's own mode is irrelevant if its DIRECTORY is writable: the pin
            #     is then one unlink-and-recreate away from saying anything, no matter who
            #     owns it or how tightly it is chmod'ed. A sticky directory is exempt
            #     UNLESS this process owns it, because sticky is exactly the rule that
            #     stops a non-owner unlinking another account's file.
            parent = path.parent
            try:
                parent_info = parent.stat()
            except OSError as exc:
                raise SignatureError(
                    f"cannot stat the directory holding {env_name}: {exc}") from exc
            sticky = bool(parent_info.st_mode & stat.S_ISVTX)
            if (os.access(parent, os.W_OK | os.X_OK, effective_ids=_POSIX_EFFECTIVE_IDS)
                    and (not sticky or parent_info.st_uid == os.geteuid())):
                raise SignatureError(
                    f"{env_name} itself is owned by uid {info.st_uid}, but its directory "
                    f"{parent} (uid {parent_info.st_uid}, mode {parent_info.st_mode & 0o7777:04o}) "
                    f"is writable by the account reading it, which can therefore unlink the "
                    f"pin and put its own in its place regardless of the file's mode; put "
                    f"the anchor in a directory this process cannot write, or set "
                    f"{ENV_PIN_SELF_OWNED_ACK}={PIN_SELF_OWNED_ACK_VALUE} to acknowledge "
                    f"that this deployment has no principal separation: {path}")
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
