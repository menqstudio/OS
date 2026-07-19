# BroPS Security Model

BroPS is a **single-user local desktop app** (Tauri 2 + Rust + SQLite, React webview). The trust boundary that matters is **webview → Rust host**: the webview renders Markdown and other content, so the Rust command surface treats every argument from it as untrusted. This document describes the enforced protections and the known limitations.

_Last updated: 2026-07-19. Primary platform: Linux (Debian). Reflects 10 rounds of security remediation._

## Threat model

- **In scope:** a compromised/XSS'd webview trying to read or write arbitrary files, run commands, exfiltrate prompts over the network, or exhaust memory/processes; a malicious/misconfigured `claude` binary or Ollama endpoint; another local user on a shared machine reading temp files or process arguments; prompt-injection in chat content.
- **Out of scope:** an attacker who already has the user's OS account and can run arbitrary code as them (they don't need BroPS); kernel/hardware attacks.

## Filesystem access (Files workspace)

- All `list_dir` / `read_file` / `write_file` paths are **canonicalized** (`..` and symlinks resolved) and **confined to one root**. Default root is a dedicated **`~/BroPS`** workspace, not the whole home directory. Override with `BROPS_FILES_ROOT`.
- A path that escapes the root — via traversal or a symlink pointing outside — is **rejected**.
- A **sensitive-path denylist** is always enforced (even inside a broad root): `.ssh`, `.aws`, `.gnupg`, `.git`, `.docker`, `.kube`, `.config`, … directories and `.bashrc`, `.env*`, `.netrc`, `*credential*`, `*.pem`, `id_*`, … files (case-insensitive). Denied paths can't be read, written, **or listed**.
- Editing is limited to **existing regular files** (no create; directories/devices/FIFOs rejected). Reads are **bounded** (≤ 2 MiB, streamed with a hard cap so a device like `/dev/zero` can't OOM). Writes are **atomic** (O_EXCL temp + fsync + rename), size-capped, and **preserve the original file's permissions** (a `0600` secret stays `0600`).
- Directory listings use `symlink_metadata`, so a symlink can't leak its target's size/mtime/dir-flag.

## AI subprocess isolation (local `claude` CLI)

- Chat is a **pure text completion**: launched with `--tools ""` (all built-in tools off), `--strict-mcp-config` (no MCP servers), `--setting-sources project` (no user hooks/plugins/MCP), and `--no-session-persistence`. A prompt-injection in a message cannot read/write files or run commands through the coding agent.
- Runs in a **unique, owner-only (0700) sandbox directory** created fresh per process (random nonce; refuses a pre-planted dir/symlink), so no nearby project's `.claude/settings.json` or `.mcp.json` is loaded.
- **No confidential text in argv:** the conversation transcript is written to the child's **stdin** and the system prompt to a **0600 file** (`--append-system-prompt-file`), so neither appears in `/proc/<pid>/cmdline`.
- The transcript is serialized as a **JSON array**, so message content can't forge fake `User:`/`Assistant:` turns.
- Every subprocess uses `kill_on_drop` (no orphans on timeout), an **absolute request deadline**, and **byte caps** on stdout/stderr (the deadline bounds time, the caps bound memory).
- Stale sandbox directories from crashed prior runs are swept at startup — only our own marker-tagged dirs whose owning process is **no longer alive** (Linux `/proc`), never a live sibling instance's.

## Input & output bounds

- Requests are validated **before** dispatch: system ≤ 256 KiB, one message ≤ 1 MiB, total conversation ≤ 8 MiB (overflow-safe), ≤ 1000 messages, roles restricted to `user`/`assistant`, at least one user turn.
- HTTP provider responses are read with an explicit **8 MiB body cap** (64 KiB for error bodies) — no unbounded `resp.json()`/`resp.text()`.

## Network

- **Ollama is loopback-only by default.** `BROPS_OLLAMA_URL` must resolve to `localhost` / `127.0.0.0/8` / `::1`; embedded credentials, fragments, and non-`http(s)` schemes are rejected. A remote host requires explicit **`BROPS_ALLOW_REMOTE_OLLAMA=1`** (fail-closed — only `1`/`true`/`yes`/`on`) **and HTTPS**. Both the send and status-probe paths use a **no-redirect client** so a 3xx can't relay a prompt elsewhere.
- The Anthropic endpoint is a fixed constant (not env-controlled).
- No secrets are stored in SQLite; API keys come only from the environment.

## Data at rest

- The app data directory is set **`0700` before the database is opened**; the SQLite DB and its WAL/SHM are set **`0600`**. A permission-hardening failure aborts startup rather than running with weak permissions. (Unix.)

## Supply chain / CI

- GitHub Actions are **pinned to full commit SHAs** (`actions/checkout`, `actions/setup-node`, `dtolnay/rust-toolchain`).
- CI runs the frontend build, the data-core tests, the host tests, **`clippy -D warnings`**, and a **release build** on every push.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `BROPS_FILES_ROOT` | `~/BroPS` | Root directory the Files workspace may access. |
| `BROPS_AI_PROVIDER` | auto | Force `claude-cli` \| `anthropic` \| `ollama`. |
| `BROPS_CLAUDE_BIN` | `claude` | Path to the `claude` binary. |
| `BROPS_CLAUDE_MODEL` | CLI default | Model for the local CLI. |
| `ANTHROPIC_API_KEY` | — | If set (and provider not forced), use the metered Anthropic API. |
| `BROPS_ANTHROPIC_MODEL` | `claude-sonnet-5` | Anthropic model id. |
| `BROPS_OLLAMA_URL` | `http://localhost:11434` | Ollama base URL (loopback-only unless remote is allowed). |
| `BROPS_ALLOW_REMOTE_OLLAMA` | off | Set `1`/`true` to allow a non-local Ollama host (requires HTTPS). Fail-closed. |
| `BROPS_OLLAMA_MODEL` | `llama3.2` | Ollama model tag. |

## Known limitations

- **Windows:** the explicit `0700`/`0600` permissions and the sandbox owner-only mode are **Unix-only**. On Windows the sandbox relies on the per-user temp ACL; explicit user-only DACL enforcement is not implemented (the project is Linux-first).
- **TOCTOU:** filesystem confinement uses canonicalize-then-open with `O_EXCL`/perms-preservation rather than descriptor-relative `openat2`/`cap-std`. A residual time-of-check/time-of-use window exists; it is acceptable for the single-user local threat model.
- **Sandbox liveness on non-Linux:** stale-sandbox cleanup falls back to a 1-hour age heuristic where `/proc`-based liveness isn't available.

## Reporting

This is a personal project. Report security concerns to the owner (Gev) directly.
