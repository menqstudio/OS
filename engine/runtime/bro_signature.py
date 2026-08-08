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

WHERE the registry is read from is a deployment question, not a source-tree one.
`load_trusted_keys` read `<root>/config/trusted-keys.json` and every engine caller
passed the engine's own tree, so a deployment that provisions its trust material
elsewhere — the desktop install mints keys, a signed registry, the out-of-registry
pin and a floor under the app data directory — was invisible, and the development
registry committed in `engine/config/` answered for everything instead (O-3).
BRO_TRUSTED_REGISTRY_ROOT names the deployment's registry root; unset, behaviour is
byte-for-byte what it was. Redirecting the READ is safe precisely because the ANCHOR
does not move with it: the pin still comes from outside the registry, under its own
custody rules, and `resolve_registry_root` refuses an override that contains the pin
or the floor, so one variable can never hand over the registry and the thing that
authenticates it.
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

# The custody machinery — "can the account reading this rewrite it?" — is shared with
# the evidence anti-rollback floor (audit R-06) and the protected evidence store
# (design §4.0), both of which had the same defect this module's F-06 fix closed and
# neither of which ran any check at all on Windows. It lives in `bro_custody` so the
# three sites cannot drift. Nothing about THIS module's rules changed in the move: the
# shared code raises the caller's error type and the caller keeps the prose, so every
# refusal below is the one that shipped. The acknowledgement constants are re-exported
# from here because callers and tests import them from this module.
from bro_custody import (
    ENV_PIN_SELF_OWNED_ACK,
    PIN_SELF_OWNED_ACK_VALUE,
    WINDOWS_DIRECTORY_REWRITE_RIGHTS,
    WINDOWS_DIRECTORY_WRITE_MASK,
    platform_name,
    posix_rewrite_verdict,
    refuse_windows_writable,
    self_owned_acknowledged as _self_owned_pin_acknowledged,
    windows_rewrite_grant,
    windows_token_override_privilege,
)

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
# (ENV_PIN_SELF_OWNED_ACK / PIN_SELF_OWNED_ACK_VALUE are imported from `bro_custody`
# above. One acknowledgement covers the pin, the evidence floor and the evidence store:
# a deployment either has a second principal to offer or it does not, and splitting the
# variable per site would let a deployment acknowledge one and be silently exempted
# from the others.)

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

# WHERE the registry is read from (O-3). `load_trusted_keys` reads
# `<root>/config/trusted-keys.json`, and every engine caller passes the engine's OWN
# tree, so a deployment that provisions its trust material somewhere else — the desktop
# install mints keys, a signed registry, the out-of-registry operator pin and an
# anti-rollback floor under the app data directory — was invisible to the engine, and
# the development registry committed at `engine/config/trusted-keys.json` answered for
# everything instead. This names the deployment's registry root.
#
# Redirecting WHERE the registry is read is safe only because the ANCHOR does not move
# with it. The operator-root pin comes from outside the registry (ENV_PIN_FILE, with its
# own custody rules) and the registry payload is never the pin; a redirect that could
# also select its own anchor would hand an attacker the whole trust root, so the two are
# kept independent and `resolve_registry_root` refuses an override that contains the pin
# or the anti-rollback floor. Everything the registry has to clear — the operator
# signature under the external pin, the production binding, the rollback floor, the
# operator entry — is unchanged and runs against whatever this variable selects.
#
# NOT `BRO_REGISTRY_ROOT`: that name is already taken by `bridge/engine_sidecar.py`,
# where it is a presence-only provisioning check whose value nothing reads. Giving the
# engine's trust root the name a shipped surface already uses for something else would
# silently turn "I set this so the sidecar's provisioning check passes" into "I moved
# the trust root", which is exactly the class of change this variable must never make.
ENV_REGISTRY_ROOT = "BRO_TRUSTED_REGISTRY_ROOT"

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


def _windows_pin_rewrite_grant(path: pathlib.Path, env_name: str,
                               descriptor, owner, dacl):
    """The pin's spelling of ``bro_custody.windows_rewrite_grant``: (right, principal) or None.

    Kept as a name on this module because the F-06 tests drive it directly against
    descriptors they build themselves, and because a pin is a FILE — the default right list
    is the file one, not the directory one the evidence floor has to ask about.
    """
    return windows_rewrite_grant(path, env_name, descriptor, owner, dacl, SignatureError)


def _windows_token_override_privilege(env_name: str, path: pathlib.Path):
    """The pin's spelling of ``bro_custody.windows_token_override_privilege``."""
    return windows_token_override_privilege(env_name, path, SignatureError)


def _refuse_non_owner_writable_windows(path: pathlib.Path, env_name: str) -> None:
    """Windows analogue of the POSIX group/other-writable and self-owned refusals.

    The decision — an ``AccessCheck`` of the real descriptor against the real token, and
    separately the privileges ``AccessCheck`` ignores, then a DACL walk for third-party
    write — lives in ``bro_custody.refuse_windows_writable``; read it there for why
    ownership is the wrong question. What stays here is the wording, because "an anchor its
    reader can rewrite is not an anchor" is a sentence about a trust anchor and not about
    every protected path, and a reader who hits it must be told what to change.
    """
    refuse_windows_writable(
        path, env_name, SignatureError,
        ask_self=not _self_owned_pin_acknowledged(),
        on_rewrite=lambda right, principal: (
            f"{env_name} can be rewritten by the very account reading it: this "
            f"process's token is granted {right} on it through {principal}. An "
            f"anchor its reader can rewrite is not an anchor; it must belong to a "
            f"principal this process cannot impersonate, or the deployment must "
            f"set {ENV_PIN_SELF_OWNED_ACK}={PIN_SELF_OWNED_ACK_VALUE} to "
            f"acknowledge that it has no principal separation: {path}"),
        on_privilege=lambda privilege: (
            f"{env_name} can be rewritten by the very account reading it: this "
            f"process's token holds {privilege}, which lets it take ownership of "
            f"the file and rewrite the DACL, so no ACL on it can keep this "
            f"process out. Run the verifier under an account without that "
            f"privilege (an elevated administrator always holds it), or set "
            f"{ENV_PIN_SELF_OWNED_ACK}={PIN_SELF_OWNED_ACK_VALUE} to acknowledge "
            f"that this deployment has no principal separation: {path}"))


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
            # "Is the owner literally me?" is only a PROXY for the real question — "can the
            # account reading this pin rewrite it?" — and the same blind spot the Windows
            # branch had (audit F-06) exists here in two further forms the proxy answers no
            # to while the real answer is yes: running as root, and a writable containing
            # directory. All three are asked by `bro_custody.posix_rewrite_verdict`; the
            # wording stays here, because a reader has to be told WHICH one applies to them.
            verdict = posix_rewrite_verdict(path, info, env_name, SignatureError)
            if verdict is not None:
                if verdict.kind == "owner":
                    raise SignatureError(
                        f"{env_name} is owned by the very account reading it (uid {info.st_uid}), "
                        f"which can rewrite it at will; the anchor must belong to another "
                        f"principal (e.g. root, or a dedicated operator account), or the "
                        f"deployment must set {ENV_PIN_SELF_OWNED_ACK}={PIN_SELF_OWNED_ACK_VALUE} "
                        f"to acknowledge that it has no principal separation: {path}")
                if verdict.kind == "permission":
                    raise SignatureError(
                        f"{env_name} is owned by uid {info.st_uid}, but the account reading it "
                        f"(euid {os.geteuid()}) has write permission on it anyway"
                        + (" — running as root, which can rewrite any file, so no file pin is "
                           "an anchor for this process" if os.geteuid() == 0 else "") +
                        f"; the anchor must belong to a principal this process cannot write as, "
                        f"or the deployment must set "
                        f"{ENV_PIN_SELF_OWNED_ACK}={PIN_SELF_OWNED_ACK_VALUE} to acknowledge "
                        f"that it has no principal separation: {path}")
                raise SignatureError(
                    f"{env_name} itself is owned by uid {info.st_uid}, but its directory "
                    f"{verdict.parent} (uid {verdict.parent_uid}, mode {verdict.parent_mode:04o}) "
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


def _same_directory(left: pathlib.Path, right: pathlib.Path) -> bool:
    """Do two paths name the same directory? Lexically, or after resolution.

    Compared both ways because the callers spell their roots differently — a module
    constant, an env var, a test fixture — and a redirect that treated
    ``/opt/bro/engine`` and ``/opt/bro/engine/.`` as different roots would refuse a
    correctly configured deployment.
    """
    if pathlib.Path(os.path.normpath(str(left))) == pathlib.Path(os.path.normpath(str(right))):
        return True
    try:
        return left.resolve() == right.resolve()
    except OSError:  # pragma: no cover - resolve() is non-strict; a failure means "not equal"
        return False


def _refuse_writable_registry_root(directory: pathlib.Path, env_name: str) -> None:
    """Can the account reading the redirected registry rewrite the directory it lives in?

    The same question the operator pin asks of its file (audit F-06) and the evidence
    floor asks of its directory (audit R-06), asked of the registry root, through the
    same ``bro_custody`` decision so the three cannot drift. The DIRECTORY right list is
    used, not the file one: on a directory, "rewrite" also means adding an entry and —
    via FILE_DELETE_CHILD — deleting one without holding DELETE on it, and swapping the
    registry file out from under the reader is precisely the move.

    What this does and does not buy is worth stating, because the honest version is
    smaller than it looks. The registry is operator-signed, bound to an external pin,
    and floored against rollback, so an account that can write this directory still
    cannot introduce a key. What it CAN do is replace the registry with another the
    operator signed — a superseded one when no floor is pinned, or a different
    deployment's — and it can delete it and stop the engine. That is a downgrade and a
    denial, not a forgery, and it is what this refusal is for.

    A platform with neither branch REFUSES: "no permission model here" is not "no
    permission requirement", and an unchecked redirect is the thing being asked for.
    The single acknowledgement (``BRO_OPERATOR_ROOT_PIN_SELF_OWNED=acknowledged``) that
    already covers the pin, the evidence floor and the evidence store covers this too —
    a deployment either has a second principal to offer or it does not, and a
    single-user desktop that provisions its own trust into its own app data directory
    does not. It must say so here rather than be silently exempted.
    """
    if _self_owned_pin_acknowledged():
        return
    if platform_name() == "posix":
        info = directory.stat()
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise SignatureError(
                f"{env_name} is group/other-writable: {directory}; a trust store anyone "
                f"can replace is not a trust store")
        verdict = posix_rewrite_verdict(directory, info, env_name, SignatureError)
        if verdict is not None:
            if verdict.kind == "owner":
                raise SignatureError(
                    f"{env_name} is owned by the very account reading it (uid {verdict.st_uid}), "
                    f"which can replace the registry inside it at will; point it at a directory "
                    f"owned by another principal, or set "
                    f"{ENV_PIN_SELF_OWNED_ACK}={PIN_SELF_OWNED_ACK_VALUE} to acknowledge that "
                    f"this deployment has no principal separation: {directory}")
            if verdict.kind == "permission":
                raise SignatureError(
                    f"{env_name} is owned by uid {verdict.st_uid}, but the account reading it "
                    f"(euid {verdict.euid}) has write permission on it anyway"
                    + (" — running as root, which can write any directory, so no filesystem "
                       "permission keeps this process out" if verdict.euid == 0 else "") +
                    f", so it can replace the registry inside it; point it at a directory this "
                    f"process cannot write, or set "
                    f"{ENV_PIN_SELF_OWNED_ACK}={PIN_SELF_OWNED_ACK_VALUE} to acknowledge that "
                    f"this deployment has no principal separation: {directory}")
            raise SignatureError(
                f"{env_name} itself is owned by uid {verdict.st_uid}, but its parent "
                f"{verdict.parent} (uid {verdict.parent_uid}, mode {verdict.parent_mode:04o}) is "
                f"writable by the account reading it, which can therefore rename the whole "
                f"registry root away and put its own in its place regardless of this "
                f"directory's mode; put it under a directory this process cannot write, or set "
                f"{ENV_PIN_SELF_OWNED_ACK}={PIN_SELF_OWNED_ACK_VALUE} to acknowledge that this "
                f"deployment has no principal separation: {directory}")
    elif platform_name() == "nt":
        refuse_windows_writable(
            directory, env_name, SignatureError,
            rights=WINDOWS_DIRECTORY_REWRITE_RIGHTS,
            write_mask=WINDOWS_DIRECTORY_WRITE_MASK,
            on_rewrite=lambda right, principal: (
                f"{env_name} can be rewritten by the very account reading it: this "
                f"process's token is granted {right} on it through {principal}, so it can "
                f"replace the registry inside it. Point it at a directory under a principal "
                f"this process cannot impersonate, or set "
                f"{ENV_PIN_SELF_OWNED_ACK}={PIN_SELF_OWNED_ACK_VALUE} to acknowledge that "
                f"this deployment has no principal separation: {directory}"),
            on_privilege=lambda privilege: (
                f"{env_name} can be rewritten by the very account reading it: this "
                f"process's token holds {privilege}, which lets it take ownership of the "
                f"directory and rewrite the DACL, so no ACL on it can keep this process out. "
                f"Run the engine under an account without that privilege (an elevated "
                f"administrator always holds it), or set "
                f"{ENV_PIN_SELF_OWNED_ACK}={PIN_SELF_OWNED_ACK_VALUE} to acknowledge that "
                f"this deployment has no principal separation: {directory}"))
    else:
        raise SignatureError(
            f"{env_name} cannot be checked on {platform_name()}: this runtime has no way to "
            f"ask who may rewrite it there, and an unchecked trust store is not a trust "
            f"store. Set {ENV_PIN_SELF_OWNED_ACK}={PIN_SELF_OWNED_ACK_VALUE} only if this "
            f"deployment genuinely has no principal separation to offer: {directory}")


def _refuse_anchor_inside_registry_root(registry_root: pathlib.Path,
                                        env: Mapping[str, str], env_name: str) -> None:
    """The redirect may not select its own anchor.

    "The registry payload is never the pin" is what makes writing the registry
    insufficient to introduce a key. Moving WHERE the registry is read keeps that
    property only while the pin — and the anti-rollback floor, which is the other half
    of "this registry is the current one" — stay outside whatever the redirect selects.
    Otherwise one variable hands over the registry, the anchor that authenticates it and
    the floor that keeps it current, and the external anchor rule becomes decorative.

    Checked lexically AND after resolution, against both spellings of the registry root,
    so neither a ``..`` nor a symlink can launder an anchor into the redirected tree.
    """
    boundaries = {registry_root}
    try:
        boundaries.add(registry_root.resolve())
    except OSError:  # pragma: no cover - non-strict resolve; keep the lexical boundary
        pass
    for anchor_var in (ENV_PIN_FILE, ENV_REGISTRY_MIN_FILE):
        raw = env.get(anchor_var)
        if not raw:
            continue
        candidate = pathlib.Path(raw)
        forms = {pathlib.Path(os.path.normpath(str(candidate)))}
        try:
            forms.add(candidate.resolve())
        except OSError:  # pragma: no cover - an unresolvable anchor fails later, by name
            pass
        for form in forms:
            for boundary in boundaries:
                if form == boundary or boundary in form.parents:
                    raise SignatureError(
                        f"{anchor_var} lives inside {env_name} ({form} is under "
                        f"{boundary}): the registry may not name its own trust anchor, and "
                        f"a redirect that carries the anchor with it is the same defect by "
                        f"another route. Keep the operator pin and the anti-rollback floor "
                        f"outside the registry root")


def resolve_registry_root(root: pathlib.Path = ROOT,
                          *, env: Mapping[str, str] | None = None) -> pathlib.Path:
    """Where this deployment's trusted-key registry actually lives (O-3).

    Unset — the default, and every deployment that exists today — returns ``root``
    unchanged, having touched neither the filesystem nor the environment beyond one
    dictionary lookup. Nothing about an existing deployment changes.

    Set, it must clear custody rules at least as strong as the operator pin's, because a
    trust store selected by a variable is only as good as the rules on what may be
    selected: an absolute path (a relative one would mean "wherever this process happens
    to be"), no symlink at ANY component (an intermediate link would let something that
    can write one directory redirect the trust root), an existing directory that actually
    holds ``config/trusted-keys.json`` as a regular non-symlink file (so a typo refuses by
    name instead of surfacing later as "cannot read trusted key registry"), a directory
    the reading account cannot rewrite, and — the rule that keeps the redirect honest — no
    operator pin or anti-rollback floor inside it.

    The one thing this must never become is a redirect half the callers honour: a
    deployment where the hook consults the provisioned trust and the supervisor consults
    the stale committed one, with nothing saying so, is worse than no redirect at all. So
    when the override is set, a caller asking for the engine's own tree gets the override,
    a caller asking for the override gets the override, and a caller asking for anything
    else is REFUSED by name rather than quietly served a different registry from the one
    the rest of the process is using. Tests and tools that name a registry root are
    unaffected while the variable is unset, which is how they run.
    """
    env = os.environ if env is None else env
    raw = (env.get(ENV_REGISTRY_ROOT) or "").strip()
    if not raw:
        return root
    override = pathlib.Path(raw)
    if not override.is_absolute():
        raise SignatureError(f"{ENV_REGISTRY_ROOT} must be an absolute path: {raw!r}")
    # No symlink at ANY component, walked from the filesystem root down, exactly as the
    # pin file is walked: an intermediate link is a redirect inside the redirect.
    for component in (*reversed(override.parents), override):
        if component.is_symlink():
            raise SignatureError(
                f"{ENV_REGISTRY_ROOT} path component is a symlink: {component}")
    try:
        info = override.lstat()
    except OSError as exc:
        raise SignatureError(f"cannot stat {ENV_REGISTRY_ROOT}: {exc}") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise SignatureError(
            f"{ENV_REGISTRY_ROOT} must be a directory holding {REGISTRY_REL}: {override}")
    registry_file = override / REGISTRY_REL
    if registry_file.is_symlink():
        raise SignatureError(
            f"{ENV_REGISTRY_ROOT}/{REGISTRY_REL} is a symlink: {registry_file}; the "
            f"registry file itself may not redirect elsewhere")
    try:
        registry_info = registry_file.lstat()
    except OSError as exc:
        raise SignatureError(f"{ENV_REGISTRY_ROOT} holds no {REGISTRY_REL}: {exc}") from exc
    if not stat.S_ISREG(registry_info.st_mode):
        raise SignatureError(
            f"{ENV_REGISTRY_ROOT}/{REGISTRY_REL} must be a regular file: {registry_file}")
    _refuse_writable_registry_root(override, ENV_REGISTRY_ROOT)
    _refuse_anchor_inside_registry_root(override, env, ENV_REGISTRY_ROOT)
    if _same_directory(root, ROOT) or _same_directory(root, override):
        return override
    raise SignatureError(
        f"{ENV_REGISTRY_ROOT}={override} redirects this deployment's trusted-key "
        f"registry, but this caller asked for {root}. Serving it a different registry "
        f"from the one the rest of the process verifies against is how a deployment ends "
        f"up half-trusting two registries with nothing saying so, so it is refused: "
        f"either unset {ENV_REGISTRY_ROOT} or point the caller at the same root")


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

    WHERE the registry is read from is ``resolve_registry_root(root)``, not ``root``
    itself (O-3): a deployment that provisions its trust material outside the engine
    tree names that root in ``BRO_TRUSTED_REGISTRY_ROOT``, and every caller here
    consults the same store rather than half of them consulting the development
    registry committed at ``engine/config/trusted-keys.json``. With the variable unset
    this is ``root``, unchanged. None of the checks below are relaxed by the redirect —
    they are exactly what makes redirecting the READ safe, because the anchor that
    authenticates the registry does not move with it.
    """
    env = os.environ if env is None else env
    registry_root = resolve_registry_root(root, env=env)
    path = registry_root / REGISTRY_REL
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
