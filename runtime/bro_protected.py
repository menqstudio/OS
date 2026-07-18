from __future__ import annotations

import hashlib
import json
import os
import pathlib
from dataclasses import dataclass

from bro_workspace import matches_pattern

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


def is_digest_member(manifest: ProtectedManifest, relative: str) -> bool:
    # Non-source build artifacts are never a source of truth. Excluding them keeps
    # the control-plane digest deterministic with respect to bytecode compilation:
    # otherwise a cold-cache checkout writes runtime/__pycache__/*.pyc after the
    # binding digest is captured, flipping bound != current and spuriously RED-denying
    # an otherwise-authorized action (a fail-closed-too-eager availability bug).
    parts = relative.split("/")
    if "__pycache__" in parts or relative.endswith((".pyc", ".pyo")):
        return False
    if any(matches_pattern(relative, p) for p in manifest.unprotected_exceptions):
        return False
    return any(matches_pattern(relative, p) for p in manifest.digest_roots)


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
