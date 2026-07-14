from __future__ import annotations

import hashlib, hmac, json, os, pathlib, re, shlex, time
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
DANGEROUS_CONFIG = ("http.extraheader", "credential.helper", "core.sshcommand")
GLOBAL_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
READ_ONLY_SHELL = {
    "cat", "echo", "find", "get-childitem", "get-content", "ls", "pwd", "select-string",
    "test-path", "type", "where", "where-object", "whoami",
}
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
        if c in "><`":
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
                if (
                    key in DANGEROUS_CONFIG
                    or key.startswith("alias.")
                    or (key.startswith("url.") and key.endswith(".insteadof"))
                    or (key.startswith("remote.") and key.endswith(".url"))
                ):
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
        low = [t.strip("\"'").lower() for t in tokens]
        if exe in SHELL_WRAPPERS:
            result.append(CommandInfo(exe, low[1] if len(low) > 1 else None, True, False, tuple(), False, False))
            continue
        if exe in READ_ONLY_SHELL:
            result.append(CommandInfo(exe, low[1] if len(low) > 1 else None, False, False, tuple(), False, True))
            continue
        mutating = exe in SHELL_MUTATORS or exe == "gh" or exe not in READ_ONLY_SHELL
        targets = tuple(t.strip("\"'") for t in tokens[1:] if not t.startswith("-")) if mutating else ()
        result.append(CommandInfo(exe, low[1] if len(low) > 1 else None, mutating, False, targets, False, False))
    return result


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
    def match(pattern: str) -> bool:
        pattern = pattern.rstrip("/")
        return path == pattern or path.startswith(pattern + "/") or pattern in {".", "*"}

    return any(match(item) for item in allowed) and not any(match(item) for item in prohibited)


def enforce_scope(root: pathlib.Path, targets: list[str], allowed: list[str], prohibited: list[str]) -> None:
    if not targets:
        raise SecurityError("mutation targets could not be determined")
    for raw in targets:
        path = normalize_target(root, raw)
        if not path_allowed(path, allowed, prohibited):
            raise SecurityError(f"target outside task scope: {path}")


def consume_nonce(payload: dict[str, Any], ledger_dir: pathlib.Path) -> None:
    ledger_dir.mkdir(parents=True, exist_ok=True)
    nonce = str(payload.get("nonce", ""))
    if not re.fullmatch(r"[A-Za-z0-9._-]{16,128}", nonce):
        raise SecurityError("invalid nonce")
    path = ledger_dir / (hashlib.sha256(nonce.encode()).hexdigest() + ".used")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SecurityError("grant nonce already consumed") from exc
    with os.fdopen(fd, "w") as handle:
        json.dump({"nonce": nonce, "consumed_at_epoch": int(time.time())}, handle)
