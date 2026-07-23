# BroPS Security Model

BroPS is a **single-user local desktop app** (Tauri 2 + Rust + SQLite, React webview). The trust boundary that matters is **webview → Rust host**: the webview renders Markdown and other content, so the Rust command surface treats every argument from it as untrusted. This document describes the enforced protections and the known limitations.

_Last updated: 2026-07-22. Primary platform: Linux (Debian); also built/tested on Windows. Reflects the original 10 rounds of BroPS remediation **plus** the OS-monorepo governed-execution hardening (Waves 1–3a). Live status: root [`NEXT_CHAT.md`](../../NEXT_CHAT.md)._

## Governed-execution & approval hardening (OS monorepo — Waves 1–3a)

Merged on top of the base model below, as part of closing the Challenger Deep audit's P0/P1 findings:

- **Provider fail-closed (Wave 1 / T-012):** `resolve()` returns a `Result`; there is **no silent governed→ungoverned fallback**. Unknown/misconfigured provider or missing config is a hard error; ambient `ANTHROPIC_API_KEY` never auto-selects; ungoverned execution requires an explicit `BROPS_ALLOW_UNGOVERNED=1`.
- **Webview message provenance (Wave 2a / T-013):** the `post_message` role allowlist is restricted to `["user"]` — a compromised renderer can no longer mint `agent` messages. A server-generated answer is held under a one-time `result_id` and persisted in one transaction; the webview never carries an agent body.
- **Capability boundary (T-010):** every webview-reachable command is declared in the app manifest and **deny-by-default** in `capabilities/default.json`; the 4 L2 hard-delete commands are **denied** (fail-closed); a CI invariant (`tools/check_capabilities.py`) enforces registered == manifest == policy == grants and "L2 must be protected-or-denied".
- **Durable approval + native confirmation (T-011):** approval origin/nonce/request-digest are **durable** (migrations 0012/0013); self-approval is refused by durable `origin_principal` even across restarts; the only approve path is a **renderer-independent native OS dialog**; nonce is compare-and-consumed; the confirmation binds a canonical `RunExecutionScope` digest; a **pre-dispatch execution claim** makes one grant start exactly one provider run; crash recovery reconciles abandoned claims fail-closed; a single-instance **advisory file lock** is taken before the DB opens.
- **Receipt Protocol v1 (Wave 3, in progress):** a governed turn's self-asserted `receipt.verified: bool` is being replaced by an **Ed25519 signature the desktop verifies** against a pinned key (RFC 8785 JCS envelope, strict decode, `verify_strict`, fail-closed — "no verified signature ⇒ no result"). The **slice-1 protocol core** (`brops-core::receipt` — verify-only, type-state `parse→verify→bind→resolve_3a`, `Wave3aTrustState` with no "Verified" variant) is **merged** (PR #24, zero-trust GREEN, merge `6c920d0`). The **slice-2 storage & atomicity layer** (`brops-core::receipt_store` + migration 0014 — one `BEGIN IMMEDIATE` verify→consume→persist, durable one-time nonce, `receipt_id` global uniqueness, two-timestamp freshness/skew, `ON DELETE RESTRICT` evidence that survives deletion by refusing it, a blocked verdict that still commits evidence, no "Verified" outcome) is **merged** (PR #26, zero-trust GREEN, merge `9b214e5`). The **slice-3 transport + receipt UI** (the desktop CALLS the verifier on a real governed turn: a one-time nonce challenge, buffered output, and signature verification — the bridge is transport-only, the self-asserted `verified` boolean is removed, and the desktop is the final authority; fail-closed strict 3a Blocks every governed turn until a trusted key exists, surfacing a turn-level notice with no persisted message) is **merged** (PR #28, merge `8a580028`, zero-trust GREEN after a YELLOW + two RED rounds) — Wave 3a is complete: the desktop verifier is wired into a real governed turn (one `PreparedGovernedTurn` source; exact structured `system`+`history` as the bridge signing authority; buffered `governed_turn`; a Blocked turn-level notice with no persisted message; bounded transport-failure evidence). The isolated signer that enables production "Verified" (Wave 3b) is still to come. Design: [`../../docs/design/WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md`](../../docs/design/WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md).

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

This is a personal project maintained by the owner (Gev). Please report security issues **confidentially** — do not open a public issue for a vulnerability.

- **Preferred:** use GitHub **Private Vulnerability Reporting** on this repository: go to the **Security** tab → **Report a vulnerability**. This opens a private advisory visible only to you and the maintainer.
- If private reporting is unavailable, contact the owner directly through the private contact channel listed on the repository owner's GitHub profile.

Please include reproduction steps and the affected component (webview, Rust host command, provider integration, etc.). Reports are reviewed on a best-effort basis; this is a single-maintainer project, so there is no formal SLA.
