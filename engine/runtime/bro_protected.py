from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
from dataclasses import dataclass

from bro_workspace import matches_pattern

# Bytecode-shadowing defence, part 1 (see also assert_no_bytecode_shadow):
# the control-plane digest deliberately excludes __pycache__/*.pyc (they are
# non-deterministic build artifacts, see is_digest_member), which means a forged
# .pyc under a digest root is INVISIBLE to verify_control_plane_digest while
# CPython may still import it in place of the verified .py source.
#
# This process-wide flag stops THIS process minting fresh bytecode under the
# digest roots from here on. It is deliberately NOT the control: it runs when this
# module is imported, which is already too late for every module imported before it
# (bro_audit_log, bro_authority, bro_authorization, bro_contracts,
# bro_execution_lease, bro_freeze, bro_policy ... and for bro_protected itself,
# whose cache CPython writes before it executes this line). Closing the WRITE half
# of that window needs the INTERPRETER to start with -B or
# PYTHONDONTWRITEBYTECODE=1, which engine/.claude/settings.json now does for every
# wired hook command. Caches written by some OTHER process are what
# assert_no_bytecode_shadow is for; it is called from verify_control_plane_digest
# below and, independently, from the wall's own paths in bro_control_plane.
#
# What stays open (docs/PHASE_10_PRODUCTION_ITEMS.md, O-1): neither -B nor this
# flag stops CPython READING an existing .pyc, and imports happen before any
# assertion can run — so a cache forged before the wall process starts can shadow
# the very code that would detect it. That residue is not closeable from inside
# Python.
sys.dont_write_bytecode = True

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST_REL = "config/protected-control-plane.json"

STANDARD = "standard-builder"
SECURITY = "security-maintenance"
TASK_CLASSES = {STANDARD, SECURITY}
MIN_SECURITY_INDEPENDENCE = 4

DIGEST_MISMATCH = "control plane changed after session authority was issued"


class ProtectedScopeError(Exception):
    pass


@dataclass(frozen=True)
class ProtectedManifest:
    protected_roots: tuple[str, ...]
    digest_roots: tuple[str, ...]
    unprotected_exceptions: tuple[str, ...]


def _case_insensitive_fs() -> bool:
    return os.name == "nt"


def load_protected_manifest(root: pathlib.Path = ROOT) -> ProtectedManifest:
    try:
        raw = (root / MANIFEST_REL).read_bytes()
    except OSError as exc:
        raise ProtectedScopeError(f"cannot read protected manifest: {exc}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtectedScopeError(f"invalid protected manifest: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ProtectedScopeError("unsupported protected manifest schema")
    roots = value.get("protected_roots")
    digest_roots = value.get("digest_roots")
    exceptions = value.get("unprotected_exceptions")
    if not isinstance(roots, list) or not roots:
        raise ProtectedScopeError("protected manifest has no protected_roots")
    if not isinstance(digest_roots, list) or not digest_roots:
        raise ProtectedScopeError("protected manifest has no digest_roots")
    if not isinstance(exceptions, list):
        raise ProtectedScopeError("unprotected_exceptions must be a list")
    for entry in list(roots) + list(digest_roots) + list(exceptions):
        if not isinstance(entry, str) or not entry:
            raise ProtectedScopeError("protected manifest entries must be non-empty strings")
    return ProtectedManifest(tuple(roots), tuple(digest_roots), tuple(exceptions))


def is_protected(manifest: ProtectedManifest, relative: str) -> bool:
    case_sensitive = not _case_insensitive_fs()
    if any(matches_pattern(relative, p, case_sensitive=case_sensitive)
           for p in manifest.unprotected_exceptions):
        return False
    return any(matches_pattern(relative, p, case_sensitive=case_sensitive)
               for p in manifest.protected_roots)


def _digest_scope(manifest: ProtectedManifest, relative: str) -> bool:
    """Digest-root membership WITHOUT the bytecode carve-out: the pattern logic
    shared by is_digest_member (which additionally excludes bytecode) and
    assert_no_bytecode_shadow (which polices exactly what that exclusion hides)."""
    if any(matches_pattern(relative, p) for p in manifest.unprotected_exceptions):
        return False
    return any(matches_pattern(relative, p) for p in manifest.digest_roots)


def is_digest_member(manifest: ProtectedManifest, relative: str) -> bool:
    # Non-source build artifacts are never a source of truth. Excluding them keeps
    # the control-plane digest deterministic with respect to bytecode compilation:
    # otherwise a cold-cache checkout writes runtime/__pycache__/*.pyc after the
    # binding digest is captured, flipping bound != current and spuriously RED-denying
    # an otherwise-authorized action (a fail-closed-too-eager availability bug).
    # The flip side of that exclusion is the bytecode-shadowing gap policed by
    # assert_no_bytecode_shadow: a forged .pyc here would not perturb the digest.
    parts = relative.split("/")
    if "__pycache__" in parts or relative.endswith((".pyc", ".pyo")):
        return False
    return _digest_scope(manifest, relative)


def bytecode_shadow_offenders(root: pathlib.Path,
                              manifest: ProtectedManifest) -> list[str]:
    """Every compiled-bytecode path under a digest root, sorted.

    Split out of assert_no_bytecode_shadow so a caller that must report rather than
    raise (diagnostics, tests) shares the exact detection logic of the gate.
    """
    offenders: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = pathlib.Path(dirpath)
        for name in list(dirnames):
            relative = _relative_posix(root, here / name)
            if name == "__pycache__" and _digest_scope(manifest, f"{relative}/probe"):
                offenders.append(relative)
                dirnames.remove(name)  # the directory itself is the finding
        for name in filenames:
            if not name.endswith((".pyc", ".pyo")):
                continue
            relative = _relative_posix(root, here / name)
            if _digest_scope(manifest, relative):
                offenders.append(relative)
    return sorted(offenders)


def assert_no_bytecode_shadow(root: pathlib.Path, manifest: ProtectedManifest) -> None:
    """Bytecode-shadowing defence, part 2: fail closed if compiled bytecode exists
    under a digest root.

    The digest excludes __pycache__/*.pyc for determinism, so a crafted .pyc that
    CPython would import in place of a digest-verified .py source is invisible to
    verify_control_plane_digest. This is the compensating control for that
    exclusion, and it is a REFUSAL rather than a warning: at this point a stale
    cache, a legitimate cache and a forged cache are indistinguishable, and a
    shadow that cannot be ruled out is a denial.

    Called from verify_control_plane_digest (so no path can trust a digest without
    it) and, independently, from the wall's own entry paths in bro_control_plane.
    Enforcement interpreters additionally start with -B so a governed session never
    creates the condition itself.
    """
    offenders = bytecode_shadow_offenders(root, manifest)
    if offenders:
        raise ProtectedScopeError(
            "compiled bytecode under a digest root can shadow digest-verified "
            f"sources; run enforcement with `python -B` and remove: {offenders}")


#: Environment acknowledgement for a deployment that CANNOT make the control plane read-only.
#:
#: Deliberately not a boolean flag with a friendly name. Setting it says, in the operator's own
#: hand, that this deployment accepts the residual O-1 hole: an attacker who can write into the
#: control-plane tree before the process starts can plant a `.pyc` that CPython imports in place
#: of a digest-verified source, and no Python-level check can see it — the shadow is loaded before
#: any check exists to run.
WRITABLE_CONTROL_PLANE_ENV = "BRO_CONTROL_PLANE_WRITABLE_ACKNOWLEDGED"
# Named an ACKNOWLEDGEMENT rather than a token, which it is: a phrase the operator types to
# record a decision, carrying no authority and unlocking nothing an attacker could not already
# reach. The earlier name also read as a credential to the secret scanner, and a scanner that
# flags `..._TOKEN = "<long-hyphenated-value>"` is right about the shape — the fix is the
# accurate name, not an allowlist entry.
WRITABLE_CONTROL_PLANE_ACKNOWLEDGEMENT = "accepted-o1-residual-risk"


def control_plane_writable_by_me(root: pathlib.Path,
                                 manifest: ProtectedManifest) -> list[str]:
    """Every digest-scoped directory this process could still plant a `.pyc` into.

    The *read* half of O-1 has no fix inside Python. `-B` and `dont_write_bytecode` stop bytecode
    being WRITTEN; nothing stops CPython READING a `.pyc` that is already there, and it reads it
    during import — before any assertion in this module has had a chance to exist. So the only
    real defence is that a cache file cannot be created at all, which is a property of the
    FILESYSTEM, not of the interpreter.

    This function is how that property stops being a hope. It does not ask what the mode bits say;
    it tries to create a file and deletes it again, because that is the same question CPython's
    import machinery asks and the only one whose answer cannot be argued with — a read-only mount,
    an ACL, an immutable attribute and a full disk all answer it correctly, and none of them is
    legible from a `stat()` alone.

    Returns the writable directories, sorted. Empty means a `.pyc` cannot be planted here by this
    account, which is the condition `assert_no_bytecode_shadow` can only detect after the fact.
    """
    writable: list[str] = []
    for dirpath, dirnames, _filenames in os.walk(root, followlinks=False):
        here = pathlib.Path(dirpath)
        relative = _relative_posix(root, here) if here != root else "."
        # Only where a shadow would matter: a directory holding digest-scoped sources.
        probe_scope = f"{relative}/probe" if relative != "." else "probe"
        if not _digest_scope(manifest, probe_scope):
            continue
        probe = here / ".bro-write-probe"
        try:
            fd = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            # A leftover probe from an interrupted run. Something created a file here, so this
            # directory IS writable — treating EEXIST as "cannot write" would make a stale file
            # turn the gate green, which is the failure mode the gate exists to prevent.
            writable.append(relative)
            continue
        except OSError:
            continue          # cannot create here — exactly what we want
        os.close(fd)
        try:
            os.unlink(probe)
        except OSError:
            pass              # left behind, but the finding is that it was creatable
        writable.append(relative)
    return sorted(writable)


def assert_control_plane_not_writable(root: pathlib.Path,
                                      manifest: ProtectedManifest) -> None:
    """Refuse to trust a control plane this account can still write into (**O-1, read half**).

    `assert_no_bytecode_shadow` catches a shadow that is already present. It cannot catch one
    planted a moment later, and it cannot catch one that was loaded before this process started.
    Making the tree unwritable removes the whole class instead of racing it.

    A deployment that genuinely cannot do this — a developer checkout, a Windows box without a
    second account — may say so by exporting the acknowledgement, and the refusal names it. That is
    not a bypass dressed up as an option: an accepted risk somebody typed out is a different thing
    from one nobody noticed, and it is the difference between a deployment that has weighed O-1 and
    one that has not.
    """
    if os.getenv(WRITABLE_CONTROL_PLANE_ENV) == WRITABLE_CONTROL_PLANE_ACKNOWLEDGEMENT:
        return
    writable = control_plane_writable_by_me(root, manifest)
    if writable:
        raise ProtectedScopeError(
            "the control plane is writable by the account running enforcement, so a forged .pyc "
            "can be planted and CPython will import it in place of a digest-verified source — "
            "before any check in this process exists to notice. `-B` does not help: it stops "
            "bytecode being written, not read. Make these directories read-only for this account "
            f"(a read-only mount, or an owner the runner is not): {writable}. A deployment that "
            f"cannot do that must say so: {WRITABLE_CONTROL_PLANE_ENV}={WRITABLE_CONTROL_PLANE_ACKNOWLEDGEMENT}")


def _relative_posix(root: pathlib.Path, path: pathlib.Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ProtectedScopeError(f"path escapes control-plane root: {path}") from exc


def compute_control_plane_digest(root: pathlib.Path,
                                 manifest: ProtectedManifest) -> str:
    """Deterministic across Windows and Linux.

    os.walk(followlinks=False) never descends a symlinked directory. Any symlink
    under a digest root is rejected rather than resolved, an unreadable protected
    file fails closed, and a duplicate normalized path fails closed.
    """
    members: list[tuple[str, pathlib.Path]] = []
    seen: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = pathlib.Path(dirpath)
        for name in list(dirnames):
            entry = here / name
            relative_dir = _relative_posix(root, entry)
            if entry.is_symlink() and is_digest_member(manifest, f"{relative_dir}/probe"):
                raise ProtectedScopeError(
                    f"symlink/junction under a digest root is not permitted: {relative_dir}")
        for name in filenames:
            path = here / name
            relative = _relative_posix(root, path)
            if not is_digest_member(manifest, relative):
                continue
            if path.is_symlink():
                raise ProtectedScopeError(
                    f"symlink/junction under a digest root is not permitted: {relative}")
            key = relative.lower() if _case_insensitive_fs() else relative
            if key in seen:
                raise ProtectedScopeError(
                    f"duplicate normalized protected path: {relative} vs {seen[key]}")
            seen[key] = relative
            members.append((relative, path))

    digest = hashlib.sha256()
    for relative, path in sorted(members, key=lambda item: item[0]):
        try:
            content = hashlib.sha256(path.read_bytes()).digest()
        except OSError as exc:
            raise ProtectedScopeError(
                f"protected file is unreadable; failing closed: {relative}: {exc}") from exc
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
    return digest.hexdigest()


def verify_control_plane_digest(root: pathlib.Path, manifest: ProtectedManifest,
                                bound_digest: str) -> str:
    # O-1: the digest covers .py sources only (is_digest_member excludes
    # __pycache__/*.pyc), so "current == bound" proves the SOURCES are unchanged and
    # says nothing about what CPython would actually import. Asserting no bytecode
    # shadow FIRST is what turns the digest into a statement about executing code
    # rather than about files on disk. It lives here, in the one function every
    # digest-trusting path goes through, so that no caller can trust a digest
    # without it — including callers that do not exist yet.
    assert_no_bytecode_shadow(root, manifest)
    if not isinstance(bound_digest, str) or len(bound_digest) != 64:
        raise ProtectedScopeError("workspace binding carries no control_plane_digest")
    current = compute_control_plane_digest(root, manifest)
    if current != bound_digest:
        raise ProtectedScopeError(
            f"{DIGEST_MISMATCH}; bound={bound_digest[:12]} current={current[:12]}")
    return current


def _norm(value: str) -> str:
    normalized = value.replace("\\", "/")
    return normalized.lower() if _case_insensitive_fs() else normalized


def authorize_protected_scope(manifest: ProtectedManifest, authority: dict,
                              relative_targets) -> list[str]:
    """Returns the protected paths this call touches, or raises.

    `authority` is the external owner-issued artifact, NOT the task contract:
    a task contract that carried its own protected scope could grant itself
    control-plane access.
    """
    task_class = authority.get("task_class")
    if task_class not in TASK_CLASSES:
        raise ProtectedScopeError(f"missing or unknown task_class: {task_class!r}")

    protected = sorted({r for r in relative_targets if is_protected(manifest, r)})
    if not protected:
        return []

    if task_class == STANDARD:
        raise ProtectedScopeError(
            f"standard-builder task may not touch protected paths: {protected}")

    if authority.get("owner_approval") is not True:
        raise ProtectedScopeError(
            "security-maintenance task requires explicit owner approval")

    scope = authority.get("protected_scope")
    if not isinstance(scope, list) or not scope:
        raise ProtectedScopeError(
            "security-maintenance task requires an explicit protected_scope")
    for entry in scope:
        if not isinstance(entry, str) or any(ch in entry for ch in "*?["):
            raise ProtectedScopeError(
                f"protected_scope must contain exact paths, not patterns: {entry!r}")

    level = (authority.get("verification") or {}).get("independence_level")
    if not isinstance(level, int) or level < MIN_SECURITY_INDEPENDENCE:
        raise ProtectedScopeError(
            f"security-maintenance task requires verifier independence >= "
            f"L{MIN_SECURITY_INDEPENDENCE}")

    allowed = {_norm(p) for p in scope}
    for relative in protected:
        if _norm(relative) not in allowed:
            raise ProtectedScopeError(
                f"path is protected and not in the approved protected_scope: {relative}")
    return protected
