from __future__ import annotations

import hashlib
import hmac
import json
import os
import pathlib
import re
import shlex
import time
from dataclasses import dataclass
from typing import Any


class SecurityError(ValueError):
    pass


READ_ONLY_GIT = {"status", "diff", "log", "show", "rev-parse", "ls-files", "cat-file"}
MUTATING_GIT = {
    "add", "am", "apply", "branch", "checkout", "cherry-pick", "clean", "commit",
    "config", "merge", "mv", "push", "rebase", "remote", "reset", "restore",
    "revert", "rm", "stash", "submodule", "switch", "tag", "update-ref", "worktree",
}
# `git -c key=value` (and --config-env) can carry CODE EXECUTION through many keys:
# core.fsmonitor / core.pager / core.hooksPath / core.editor / sequence.editor /
# core.sshcommand / diff.external / *.textconv / filter.*.clean|smudge /
# uploadpack.packObjectsHook / gpg.program, plus credential exfil (http.extraheader,
# credential.helper) and repository redirection (url.*.insteadOf, remote.*.url,
# alias.*). A denylist of "dangerous" keys can never be complete, so we allowlist:
# only these display/format-only keys keep a read-only subcommand read-only; any other
# injected config makes the command dangerous (no longer classified read-only).
READ_SAFE_CONFIG = frozenset({
    "color.ui", "color.diff", "color.status", "color.branch", "color.decorate",
    "core.quotepath", "core.abbrev", "log.date", "i18n.logoutputencoding", "diff.noprefix",
})
GLOBAL_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
READ_ONLY_SHELL = {
    "cat", "echo", "get-childitem", "get-content", "ls", "pwd", "select-string",
    "test-path", "type", "where", "where-object", "whoami",
}
# The read-only verbs whose positional arguments are filesystem paths. Their
# targets are surfaced on CommandInfo so the workspace and scope gates can
# contain READS too: `cat /etc/passwd` must be denied exactly like a direct
# Read of an absolute path, not sail through with empty targets. Verbs whose
# arguments are text (echo) or executable names (where) carry no path targets.
READ_TARGET_SHELL = frozenset({
    "cat", "get-childitem", "get-content", "ls", "select-string", "test-path", "type",
})
# `find` is deliberately NOT in READ_ONLY_SHELL: it executes and mutates inside a
# single shell segment that split_shell cannot see (`find . -delete` removes
# files; `-exec/-execdir/-ok/-okdir` run arbitrary commands; `-fls/-fprint/
# -fprint0/-fprintf` write files). analyze_find gates it behind an argument
# inspector: the action flags below are never read-only, every other flag must be
# on the read-only allowlist, and anything unrecognized is fail-closed mutating —
# an allowlist like READ_SAFE_CONFIG, never a denylist.
FIND_DENIED_ACTIONS = frozenset({
    "-delete", "-exec", "-execdir", "-fls", "-fprint", "-fprint0", "-fprintf",
    "-ok", "-okdir",
})
# Read-only find options/tests/actions that take NO argument (compared lowercase,
# so -H/-L/-P fold into -h/-l/-p; all are read-only symlink options).
FIND_READ_ONLY_FLAGS = frozenset({
    "--help", "--version", "-a", "-and", "-d", "-daystart", "-depth", "-empty",
    "-executable", "-false", "-follow", "-h", "-help", "-l", "-ls", "-mount",
    "-nogroup", "-noleaf", "-not", "-nouser", "-o", "-or", "-p", "-print",
    "-print0", "-prune", "-readable", "-true", "-version", "-writable", "-xdev",
})
# Read-only find tests that consume exactly ONE following argument (the argument
# is a pattern/number/format, not a search root, so it is not a path target).
# -printf writes to stdout only; the file-writing -fprintf stays denied above.
FIND_READ_ONLY_ARG_FLAGS = frozenset({
    "-amin", "-anewer", "-atime", "-cmin", "-cnewer", "-ctime", "-fstype",
    "-gid", "-group", "-ilname", "-iname", "-inum", "-ipath", "-iregex",
    "-iwholename", "-links", "-lname", "-maxdepth", "-mindepth", "-mmin",
    "-mtime", "-name", "-newer", "-path", "-perm", "-printf", "-regex",
    "-regextype", "-samefile", "-size", "-type", "-uid", "-used", "-user",
    "-wholename", "-xtype",
})
# Executables that are read-only ONLY after their arguments pass an inspector.
ARG_INSPECTED_READ_ONLY = frozenset({"find"})
SHELL_MUTATORS = {
    "rm", "del", "erase", "rmdir", "remove-item", "set-content", "add-content",
    "out-file", "new-item", "move-item", "copy-item", "mv", "cp", "mkdir", "touch",
}
SHELL_WRAPPERS = {"bash", "cmd", "pwsh", "powershell", "python", "python3", "sh", "wsl"}


@dataclass(frozen=True)
class CommandInfo:
    executable: str
    subcommand: str | None
    mutating: bool
    push: bool
    targets: tuple[str, ...]
    dangerous_config: bool = False
    recognized_read_only: bool = False


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def verify_signed_document(doc: dict[str, Any], key_env: str) -> dict[str, Any]:
    if set(doc) != {"payload", "signature"} or not isinstance(doc["payload"], dict):
        raise SecurityError("signed document must contain payload and signature only")
    key = os.getenv(key_env, "").encode()
    if len(key) < 32:
        raise SecurityError(f"{key_env} must contain at least 32 bytes")
    expected = hmac.new(key, canonical_bytes(doc["payload"]), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(doc["signature"])):
        raise SecurityError("invalid signature")
    return doc["payload"]


def split_shell(command: str) -> list[str]:
    out, buf, quote, esc = [], [], None, False
    i = 0
    while i < len(command):
        c = command[i]
        if esc:
            buf.append(c)
            esc = False
            i += 1
            continue
        if c == "\\" and quote != "'":
            esc = True
            buf.append(c)
            i += 1
            continue
        # Command substitution ($(...) and backticks) runs in unquoted and
        # double-quoted context but never inside single quotes. It defeats the
        # static command analysis the capability and scope gates depend on — a
        # read-only leading executable can carry a hidden mutation, e.g.
        # `cat $(rm -rf x)` — so it is denied wherever it would execute.
        if quote != "'" and (c == "`" or command.startswith("$(", i)):
            raise SecurityError("shell redirection/substitution is denied")
        if quote:
            buf.append(c)
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"":
            quote = c
            buf.append(c)
            i += 1
            continue
        if c in "><":
            raise SecurityError("shell redirection/substitution is denied")
        op = None
        for candidate in ("&&", "||", ";", "|", "\n"):
            if command.startswith(candidate, i):
                op = candidate
                break
        if op:
            if "".join(buf).strip():
                out.append("".join(buf).strip())
            buf = []
            i += len(op)
            continue
        buf.append(c)
        i += 1
    if quote:
        raise SecurityError("unterminated quote")
    if "".join(buf).strip():
        out.append("".join(buf).strip())
    return out


def _tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=False)
    except ValueError as exc:
        raise SecurityError(str(exc)) from exc


def _exe(token: str) -> str:
    normalized = token.strip("\"'").replace("\\", "/")
    return pathlib.PurePath(normalized).name.lower().removesuffix(".exe")


def analyze_git(tokens: list[str]) -> CommandInfo:
    i, dangerous = 1, False
    while i < len(tokens):
        t = tokens[i].strip("\"'")
        if not t.startswith("-"):
            break
        name = t.split("=", 1)[0]
        value = t.split("=", 1)[1] if "=" in t else None
        if name in GLOBAL_WITH_ARG:
            if value is None:
                i += 1
                if i >= len(tokens):
                    raise SecurityError(f"missing argument for {name}")
                value = tokens[i].strip("\"'")
            if name in {"-c", "--config-env"}:
                key = value.split("=", 1)[0].lower()
                # Allowlist, not denylist: anything not provably display-only is dangerous.
                if key not in READ_SAFE_CONFIG:
                    dangerous = True
            i += 1
            continue
        if t in {"--no-pager", "--bare", "--version", "--help"}:
            i += 1
            continue
        raise SecurityError(f"ambiguous git global option: {t}")
    sub = tokens[i].strip("\"'").lower() if i < len(tokens) else None
    args = tuple(x.strip("\"'") for x in tokens[i + 1 :])
    read_only = bool(sub in READ_ONLY_GIT and not dangerous)
    mutating = bool(not read_only)
    return CommandInfo("git", sub, mutating, sub == "push", args, dangerous, read_only)


def analyze_find(tokens: list[str]) -> CommandInfo:
    """Classify `find` by inspecting every argument (allowlist, fail-closed).

    Read-only ONLY when each flag is a recognized read-only test/option. The
    action flags that delete, execute or write files (FIND_DENIED_ACTIONS) and
    any unrecognized flag make the whole invocation mutating; since a mutating
    `find` maps to no known capability it carries UNKNOWN downstream and is
    denied outright. Positional arguments are the search roots and become
    scope/workspace targets so even a read-only `find` is containment-checked.
    """
    paths: list[str] = []
    mutating = False
    i = 1
    while i < len(tokens):
        token = tokens[i].strip("\"'")
        low = token.lower()
        if low in {"(", ")", "!", ","}:
            i += 1
            continue
        if low in FIND_DENIED_ACTIONS:
            mutating = True
            i += 1
            continue
        if low in FIND_READ_ONLY_ARG_FLAGS:
            i += 2
            continue
        if low in FIND_READ_ONLY_FLAGS:
            i += 1
            continue
        if low.startswith("-"):
            # Unrecognized flag: could be an action variant; fail closed.
            mutating = True
            i += 1
            continue
        paths.append(token)
        i += 1
    return CommandInfo("find", None, mutating, False, tuple(paths) or (".",), False, not mutating)


def analyze_command(command: str) -> list[CommandInfo]:
    result = []
    for segment in split_shell(command):
        tokens = _tokens(segment)
        if not tokens:
            continue
        exe = _exe(tokens[0])
        if exe == "git":
            result.append(analyze_git(tokens))
            continue
        if exe == "find":
            result.append(analyze_find(tokens))
            continue
        low = [t.strip("\"'").lower() for t in tokens]
        if exe in SHELL_WRAPPERS:
            result.append(CommandInfo(exe, low[1] if len(low) > 1 else None, True, False, tuple(), False, False))
            continue
        if exe in READ_ONLY_SHELL:
            # Read targets are populated (path-taking verbs) so the workspace and
            # scope gates see what is being read; empty targets made reads invisible
            # to every containment check.
            targets = (tuple(t.strip("\"'") for t in tokens[1:] if not t.strip("\"'").startswith("-"))
                       if exe in READ_TARGET_SHELL else ())
            result.append(CommandInfo(exe, low[1] if len(low) > 1 else None, False, False, targets, False, True))
            continue
        mutating = exe in SHELL_MUTATORS or exe == "gh" or exe not in READ_ONLY_SHELL
        targets = tuple(t.strip("\"'") for t in tokens[1:] if not t.startswith("-")) if mutating else ()
        result.append(CommandInfo(exe, low[1] if len(low) > 1 else None, mutating, False, targets, False, False))
    return result


def validate_exact_push(command: str, branch: str) -> None:
    segments = split_shell(command)
    if len(segments) != 1:
        raise SecurityError("release push must be a single shell segment")
    tokens = _tokens(segments[0])
    normalized = [token.strip("\"'") for token in tokens]
    if len(normalized) != 4 or _exe(normalized[0]) != "git" or normalized[1].lower() != "push":
        raise SecurityError("release push must be exactly: git push origin HEAD:<branch>")
    if normalized[2] != "origin" or normalized[3] != f"HEAD:{branch}":
        raise SecurityError("release push remote/refspec binding mismatch")


def normalize_target(root: pathlib.Path, raw: str) -> str:
    raw = raw.strip().strip("\"'")
    if not raw or raw in {".", "./"}:
        return "."
    if re.match(r"^[A-Za-z]:[\\/]", raw) or raw.startswith(("\\\\", "/")):
        raise SecurityError("absolute path denied")
    candidate = (root / raw).resolve(strict=False)
    rr = root.resolve()
    try:
        rel = candidate.relative_to(rr)
    except ValueError as exc:
        raise SecurityError("path escapes repository") from exc
    return rel.as_posix()


def path_allowed(path: str, allowed: list[str], prohibited: list[str]) -> bool:
    """Match a normalized repo-relative path against scope patterns.

    One glob implementation with the workspace layer (bro_workspace.matches_pattern),
    so a prohibition like `**/*.env` actually fires against `src/.env` instead of
    being dead prefix text. The old `pattern in {".", "*"}` match-all shortcut is
    gone: `.` matches only the repository root itself, and a wildcard-only ALLOW
    pattern (`*`, `**`, ...) grants nothing — a scope must name what it permits,
    it cannot disable confinement. Wildcard-only PROHIBITIONS keep their glob
    semantics (blocking more is fail-closed). Literal directory patterns keep
    their prefix semantics via matches_pattern's bare-directory rule.
    Contract-supplied scopes are provably literal (safe_repo_path rejects glob
    metacharacters); the glob path here covers every other caller consistently.
    """
    # Deferred import: bro_workspace is stdlib-only and imports nothing from this
    # module, so there is no cycle; deferring keeps this module's import surface flat.
    from bro_workspace import matches_pattern

    def match(pattern: str, *, granting: bool) -> bool:
        pattern = pattern.rstrip("/")
        if not pattern or pattern == ".":
            return path == "."
        if granting and set(pattern) <= {"*", "/"}:
            return False
        return path == pattern or matches_pattern(path, pattern)

    return (any(match(item, granting=True) for item in allowed)
            and not any(match(item, granting=False) for item in prohibited))


def enforce_scope(root: pathlib.Path, targets: list[str], allowed: list[str], prohibited: list[str]) -> None:
    if not targets:
        raise SecurityError("mutation targets could not be determined")
    for raw in targets:
        path = normalize_target(root, raw)
        if not path_allowed(path, allowed, prohibited):
            raise SecurityError(f"target outside task scope: {path}")


def _nonce_paths(payload: dict[str, Any], ledger_dir: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    nonce = str(payload.get("nonce", ""))
    if not re.fullmatch(r"[A-Za-z0-9._-]{16,128}", nonce):
        raise SecurityError("invalid nonce")
    digest = hashlib.sha256(nonce.encode()).hexdigest()
    return (
        ledger_dir / f"{digest}.reserved",
        ledger_dir / f"{digest}.used",
        ledger_dir / f"{digest}.ambiguous",
    )


def _reservation_binding(tool_use_id: str, command: str) -> tuple[str, str]:
    if not isinstance(tool_use_id, str) or not tool_use_id or len(tool_use_id) > 256:
        raise SecurityError("invalid tool_use_id")
    return (
        hashlib.sha256(tool_use_id.encode()).hexdigest(),
        hashlib.sha256(command.encode()).hexdigest(),
    )


def _read_reservation(
    payload: dict[str, Any],
    ledger_dir: pathlib.Path,
    tool_use_id: str,
    command: str,
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, dict[str, Any]]:
    reserved, used, ambiguous = _nonce_paths(payload, ledger_dir)
    if used.exists():
        raise SecurityError("grant nonce already consumed")
    if ambiguous.exists():
        raise SecurityError("grant nonce is quarantined for manual reconciliation")
    try:
        record = json.loads(reserved.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SecurityError("grant nonce reservation is missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise SecurityError("grant nonce reservation is unreadable") from exc
    tool_hash, command_hash = _reservation_binding(tool_use_id, command)
    if record.get("tool_use_id_sha256") != tool_hash or record.get("command_sha256") != command_hash:
        raise SecurityError("grant nonce reservation binding mismatch")
    return reserved, used, ambiguous, record


def reserve_nonce(
    payload: dict[str, Any],
    ledger_dir: pathlib.Path,
    tool_use_id: str,
    command: str,
) -> None:
    ledger_dir.mkdir(parents=True, exist_ok=True)
    reserved, used, ambiguous = _nonce_paths(payload, ledger_dir)
    if used.exists():
        raise SecurityError("grant nonce already consumed")
    if ambiguous.exists():
        raise SecurityError("grant nonce is quarantined for manual reconciliation")
    tool_hash, command_hash = _reservation_binding(tool_use_id, command)
    record = {
        "schema": 1,
        "nonce_sha256": reserved.stem,
        "tool_use_id_sha256": tool_hash,
        "command_sha256": command_hash,
        "expected_head_sha": payload.get("expected_head_sha"),
        "branch": payload.get("branch"),
        "reserved_at_epoch": int(time.time()),
    }
    try:
        fd = os.open(reserved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SecurityError("grant nonce already reserved") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, sort_keys=True)
    except Exception:
        try:
            reserved.unlink()
        except OSError:
            pass
        raise


def finalize_nonce(
    payload: dict[str, Any],
    ledger_dir: pathlib.Path,
    tool_use_id: str,
    command: str,
) -> None:
    reserved, used, _ambiguous, record = _read_reservation(
        payload, ledger_dir, tool_use_id, command
    )
    final = dict(record)
    final["finalized_at_epoch"] = int(time.time())
    try:
        fd = os.open(used, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SecurityError("grant nonce already consumed") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(final, handle, sort_keys=True)
    except Exception:
        try:
            used.unlink()
        except OSError:
            pass
        raise
    try:
        reserved.unlink()
    except OSError as exc:
        raise SecurityError("nonce finalized but reservation cleanup failed") from exc


def release_nonce_reservation(
    payload: dict[str, Any],
    ledger_dir: pathlib.Path,
    tool_use_id: str,
    command: str,
) -> None:
    reserved, _used, _ambiguous, _record = _read_reservation(
        payload, ledger_dir, tool_use_id, command
    )
    try:
        reserved.unlink()
    except OSError as exc:
        raise SecurityError("failed to release nonce reservation") from exc


def quarantine_nonce(
    payload: dict[str, Any],
    ledger_dir: pathlib.Path,
    tool_use_id: str,
    command: str,
    reason: str,
) -> None:
    reserved, _used, ambiguous, record = _read_reservation(
        payload, ledger_dir, tool_use_id, command
    )
    quarantined = dict(record)
    quarantined["quarantined_at_epoch"] = int(time.time())
    quarantined["reason"] = str(reason)[:1000]
    try:
        fd = os.open(ambiguous, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SecurityError("grant nonce is already quarantined") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(quarantined, handle, sort_keys=True)
    except Exception:
        try:
            ambiguous.unlink()
        except OSError:
            pass
        raise
    try:
        reserved.unlink()
    except OSError as exc:
        raise SecurityError("nonce quarantined but reservation cleanup failed") from exc


def consume_nonce(payload: dict[str, Any], ledger_dir: pathlib.Path) -> None:
    """Legacy helper kept for compatibility; new release flow uses reserve/finalize."""
    ledger_dir.mkdir(parents=True, exist_ok=True)
    nonce = str(payload.get("nonce", ""))
    if not re.fullmatch(r"[A-Za-z0-9._-]{16,128}", nonce):
        raise SecurityError("invalid nonce")
    path = ledger_dir / (hashlib.sha256(nonce.encode()).hexdigest() + ".used")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SecurityError("grant nonce already consumed") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"nonce_sha256": path.stem, "consumed_at_epoch": int(time.time())}, handle)
