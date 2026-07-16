from __future__ import annotations

import fnmatch
import json
import os
import pathlib
import re
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[1]

_DEVICE = re.compile(r"^\\\\[.?]\\")
_DRIVE = re.compile(r"^[A-Za-z]:")
_URL = re.compile(r"^(?:https?|git|ssh)://(?:[^@/]+@)?([\w.\-]+)(?::\d+)?/(.+?)(?:\.git)?/?$")
_SCP = re.compile(r"^(?:[\w.\-]+@)?([\w.\-]+):(?:/)?(.+?)(?:\.git)?/?$")


class WorkspaceError(Exception):
    pass


@dataclass(frozen=True)
class Workspace:
    workspace_id: str
    repository: str
    root: pathlib.Path
    allowed_paths: tuple[str, ...]
    prohibited_paths: tuple[str, ...]
    allowed_remotes: tuple[str, ...]
    allowed_remote_repository: str
    control_plane_digest: str


def matches_pattern(relative: str, pattern: str, *, case_sensitive: bool = True) -> bool:
    """Glob match over a POSIX relative path.

    Access control passes case_sensitive=False on Windows because NTFS is
    case-insensitive: RUNTIME/x.py must deny exactly as runtime/x.py does.
    Digest membership always matches case-sensitively so the digest is
    identical on Windows and Linux.
    """
    rel = relative.replace("\\", "/")
    pat = pattern.replace("\\", "/")
    if not case_sensitive:
        rel = rel.lower()
        pat = pat.lower()
    if fnmatch.fnmatchcase(rel, pat):
        return True
    if pat.startswith("**/"):
        bare = pat[3:]
        if fnmatch.fnmatchcase(rel, bare):
            return True
        segments = rel.split("/")
        return any(fnmatch.fnmatchcase("/".join(segments[i:]), bare)
                   for i in range(1, len(segments)))
    return False


def _case_insensitive_fs() -> bool:
    return os.name == "nt"


def normalize_remote(url: str) -> str:
    raw = url.strip()
    match = _URL.match(raw) or _SCP.match(raw)
    if not match:
        raise WorkspaceError(f"unrecognized remote URL: {url}")
    host = match.group(1).lower()
    if host != "github.com":
        raise WorkspaceError(f"remote host not allowed: {host}")
    parts = [x for x in match.group(2).split("/") if x]
    if len(parts) != 2:
        raise WorkspaceError(f"remote is not owner/repo: {match.group(2)}")
    return f"{parts[0].lower()}/{parts[1].lower()}"


def _real(value: str) -> pathlib.Path:
    try:
        return pathlib.Path(os.path.realpath(value))
    except (OSError, ValueError) as exc:
        raise WorkspaceError(f"cannot resolve path: {exc}") from exc


def _reject_exotic(raw: str) -> None:
    if "\x00" in raw:
        raise WorkspaceError("path contains NUL byte")
    if _DEVICE.match(raw):
        raise WorkspaceError("device/namespace path denied")
    tail = raw[2:] if _DRIVE.match(raw) else raw
    if ":" in tail:
        raise WorkspaceError("alternate data stream or drive-relative path denied")


def _contained(root: pathlib.Path, target: pathlib.Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def load_workspace(root: pathlib.Path = ROOT) -> Workspace:
    """The active binding is operator-controlled and lives OUTSIDE the repository.

    The in-repository registry is policy/spec only: an agent editing it cannot
    widen the scope of the running session.
    """
    raw = os.getenv("BRO_WORKSPACE_BINDING")
    if not raw:
        raise WorkspaceError("missing BRO_WORKSPACE_BINDING; no active workspace")
    binding_path = pathlib.Path(raw)
    if not binding_path.is_absolute():
        raise WorkspaceError("BRO_WORKSPACE_BINDING must be an absolute path")
    if _contained(_real(str(root)), _real(str(binding_path))):
        raise WorkspaceError("workspace binding must live outside the repository")
    try:
        value = json.loads(binding_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceError(f"cannot load workspace binding: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise WorkspaceError("unsupported workspace binding schema")
    if value.get("active") is not True:
        raise WorkspaceError("workspace binding is not active")
    for key in ("workspace_id", "repository", "root", "allowed_remote_repository"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise WorkspaceError(f"workspace binding missing {key}")
    digest = value.get("control_plane_digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise WorkspaceError("workspace binding carries no control_plane_digest")
    workspace_root = _real(value["root"])
    if not workspace_root.is_dir():
        raise WorkspaceError("workspace root does not exist")
    return Workspace(
        workspace_id=value["workspace_id"],
        repository=value["repository"].lower(),
        root=workspace_root,
        allowed_paths=tuple(value.get("allowed_paths") or ("**",)),
        prohibited_paths=tuple(value.get("prohibited_paths") or ()),
        allowed_remotes=tuple(value.get("allowed_remotes") or ("origin",)),
        allowed_remote_repository=value["allowed_remote_repository"].lower(),
        control_plane_digest=digest,
    )


def git_config_path(root: pathlib.Path) -> pathlib.Path:
    """Resolve the config path for a checkout, including a linked worktree.

    In a worktree `.git` is a file holding `gitdir: <path>`, and the config lives
    in the common dir shared with the main checkout. This matters because the
    architecture requires builders to run in isolated worktrees, so assuming
    `.git` is a directory would break the enforcement path in exactly the layout
    the design mandates. Parsed rather than shelled out to, so the gate does not
    depend on a git binary being present.
    """
    dot_git = root / ".git"
    if dot_git.is_dir():
        return dot_git / "config"
    if not dot_git.is_file():
        raise WorkspaceError(f"{root} is not a git checkout")
    try:
        text = dot_git.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkspaceError(f"cannot read {dot_git}: {exc}") from exc
    match = re.search(r"^gitdir:\s*(.+?)\s*$", text, re.MULTILINE)
    if not match:
        raise WorkspaceError(f"unparsable git link file: {dot_git}")
    gitdir = pathlib.Path(match.group(1))
    if not gitdir.is_absolute():
        gitdir = _real(str(root / gitdir))
    commondir = gitdir / "commondir"
    if not commondir.is_file():
        return gitdir / "config"
    try:
        common = commondir.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise WorkspaceError(f"cannot read {commondir}: {exc}") from exc
    base = pathlib.Path(common)
    if not base.is_absolute():
        base = _real(str(gitdir / base))
    return base / "config"


def verify_repository_binding(workspace: Workspace) -> None:
    """Enforcer-internal read of the git config.

    `.git/config` is a prohibited *agent* target; prohibited_paths constrain
    tool inputs, not this module's own reads.
    """
    config = git_config_path(workspace.root)
    try:
        text = config.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkspaceError(f"cannot read repository config: {exc}") from exc
    urls = re.findall(r"^\s*url\s*=\s*(.+?)\s*$", text, re.MULTILINE)
    if not urls:
        raise WorkspaceError("repository has no remote url")
    for url in urls:
        if normalize_remote(url) != workspace.allowed_remote_repository:
            raise WorkspaceError(f"remote {url} is outside the authorized repository")


def _relative(workspace: Workspace, target: pathlib.Path) -> str:
    return target.relative_to(workspace.root).as_posix()


def is_prohibited(workspace: Workspace, relative: str) -> bool:
    return any(matches_pattern(relative, p, case_sensitive=not _case_insensitive_fs())
               for p in workspace.prohibited_paths)


def is_allowed(workspace: Workspace, relative: str) -> bool:
    return any(matches_pattern(relative, p, case_sensitive=not _case_insensitive_fs())
               for p in workspace.allowed_paths)


def authorize_path(workspace: Workspace, raw: str,
                   cwd: pathlib.Path | None = None) -> pathlib.Path:
    if not isinstance(raw, str) or not raw.strip():
        raise WorkspaceError("empty or non-string path target")
    _reject_exotic(raw)
    base = _real(str(cwd)) if cwd else workspace.root
    candidate = raw if os.path.isabs(raw) else str(base / raw)
    resolved = _real(candidate)
    if not _contained(workspace.root, resolved):
        raise WorkspaceError(f"path escapes workspace: {raw}")
    relative = _relative(workspace, resolved)
    if relative != "." and not is_allowed(workspace, relative):
        raise WorkspaceError(f"path not in allowed_paths: {relative}")
    if is_prohibited(workspace, relative):
        raise WorkspaceError(f"prohibited path: {relative}")
    return resolved


def authorize_targets(workspace: Workspace, targets,
                      cwd: pathlib.Path | None = None) -> tuple[pathlib.Path, ...]:
    return tuple(authorize_path(workspace, target, cwd) for target in targets)
