# BroPS / OS — Operator Guide

> **Scope.** This guide covers installing, provisioning, updating, backing up, and removing the
> **BroPS desktop cockpit** (`apps/desktop/`) — the human-facing half of `menqstudio/OS`
> (Tauri 2 + Rust + SQLite + React 19). Windows is the primary release platform; Linux is also
> built and tested.
>
> **Honesty contract.** Every section marks what **exists today** vs. what is **PLANNED**. The
> governed-execution **Windows broker** (services, per-service SIDs, NTFS/CNG DACLs, AppContainer
> executor, WDAC) is a *normative, unaudited design target* — it is **not implemented**. Where an
> operator step depends on it, the step is labelled **PLANNED (broker)** and points at
> [`docs/design/WINDOWS_BROKER_DESIGN.md`](design/WINDOWS_BROKER_DESIGN.md) (currently on the
> `docs/windows-broker-design` branch). Do not provision services or ACLs from this guide that the
> code does not yet create.

---

## 1. What you are operating

| Fact | Value |
|---|---|
| Product name | **BroPS** (bundle `productName`) |
| Version | `0.1.0` |
| App identifier | `studio.menq.brops` |
| Stack | Tauri 2 shell · Rust host (`brops-core`, `rusqlite` bundled) · React 19 + TypeScript + Vite webview |
| Data store | one local SQLite file, `brops.db` (+ `-wal` / `-shm`) |
| AI execution | local `claude` CLI (default), Anthropic API, or Ollama — see §5 |
| Trust boundary | **webview → Rust host**; single-user local app |

There is **no server, no service, and no network listener** in the shipping app today. It is a
single desktop process that owns one SQLite database. (The multi-service governed-execution broker
in §7 is PLANNED and separate.)

---

## 2. Install

### 2.1 From a release installer (Windows — primary)

The `release` workflow (`apps/desktop/.github/workflows/release.yml`) builds, per tag `v*` or manual
`workflow_dispatch`:

- **Windows:** an **NSIS `.exe`** and a **WiX `.msi`** (`src-tauri/target/release/bundle/{nsis,msi}/`)
- **Linux:** a `.deb` and an `.AppImage`

Install on Windows by running either the `.exe` or the `.msi`. Both install per-user and place a
Start-menu / desktop entry for **BroPS**.

> **Code signing — not configured (known gap).** `tauri.conf.json` declares no Windows signing
> certificate, so the produced installers are **unsigned**. Expect a **SmartScreen / "unknown
> publisher"** prompt on first run (choose *More info → Run anyway* if you trust the build).
> Authenticode signing of the installers and TCB binaries is **PLANNED** and is also a prerequisite
> for the WDAC policy in §7.

### 2.2 From source (developer / self-build)

```bash
cd apps/desktop
npm ci
npm run tauri build     # produces the same installers locally
# …or run a dev build:
npm run tauri dev
```

Build prerequisites: Node 20, a stable Rust toolchain, and (Linux only) the webview system
libraries `libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev libssl-dev`.

### 2.3 First-run provisioning (automatic)

On first launch the host creates and initialises its own state — no manual provisioning:

1. Creates the app-data directory (`app_data_dir()` for `studio.menq.brops`).
2. **(Unix only)** sets that directory to `0700` **before** opening the DB.
3. Takes an **exclusive single-instance advisory lock** on a lock file in that directory (a second
   instance aborts cleanly rather than touching live state).
4. Opens/creates `brops.db`, runs schema migrations (currently up to `0014_receipt_verification`),
   and seeds baseline rows.
5. **(Unix only)** sets `brops.db` and its `-wal`/`-shm` to `0600`.
6. Reconciles any execution claim abandoned by a crashed prior session (fail-closed) and sweeps
   stale AI sandbox directories.

> **Windows data-at-rest gap (honest).** The `0700`/`0600` hardening in steps 2 and 5 is
> **Unix-only** (`#[cfg(not(unix))]` is a no-op). On Windows the database inherits the ACL of the
> per-user app-data directory. Explicit owner-only DACL enforcement on the DB is **PLANNED**. Until
> then, protect the machine account itself (full-disk encryption / a locked user profile).

### 2.4 Data locations

| Item | Windows | Linux |
|---|---|---|
| App-data dir (holds `brops.db`) | `%APPDATA%\studio.menq.brops\` | `~/.local/share/studio.menq.brops/` |
| SQLite DB | `…\studio.menq.brops\brops.db` | `…/studio.menq.brops/brops.db` |
| Files workspace root | `%USERPROFILE%\BroPS\` | `~/BroPS/` |

Exact resolution is Tauri's `app_data_dir()` for the identifier; the table gives the platform
defaults. Override the Files root with `BROPS_FILES_ROOT` (§5).

---

## 3. Configuration (environment variables)

All runtime configuration is via environment variables read by the host at start. There is no admin
UI for these; the Settings screen shows the resolved provider **read-only**.

| Variable | Default | Purpose |
|---|---|---|
| `BROPS_FILES_ROOT` | `~/BroPS` | Root the Files workspace may access. Refused if it resolves to the home dir or a filesystem root. |
| `BROPS_AI_PROVIDER` | auto | Force `claude` \| `anthropic` \| `ollama`. |
| `BROPS_CLAUDE_BIN` | `claude` | Path to the `claude` binary if not on `PATH`. |
| `BROPS_CLAUDE_MODEL` | CLI default | Model for the local CLI. |
| `ANTHROPIC_API_KEY` | — | If set (and provider not forced), selects the metered Anthropic API. Never auto-selected for governed execution. |
| `BROPS_ANTHROPIC_MODEL` | `claude-sonnet-5` | Anthropic model id. |
| `BROPS_OLLAMA_URL` | `http://localhost:11434` | Ollama base URL. Loopback-only unless remote is explicitly allowed. |
| `BROPS_ALLOW_REMOTE_OLLAMA` | off | Set `1`/`true` to allow a non-local Ollama host (**requires HTTPS**). Fail-closed. |
| `BROPS_OLLAMA_MODEL` | `llama3.2` | Ollama model tag. |
| `BROPS_ALLOW_UNGOVERNED` | off | Must be explicitly `1` to permit ungoverned execution paths that require it. |

Secrets (`ANTHROPIC_API_KEY`) are read **only** from the environment and are never written to
SQLite. Set them in the user/session environment before launching BroPS.

---

## 4. Service + ACL setup — **PLANNED (broker)**

> **Nothing in this section is implemented.** The shipping app runs as a single unprivileged
> desktop process and registers **no Windows service and no custom ACLs**. This section documents
> the *target* provisioning so operators understand the roadmap and do not hand-provision anything
> the runtime cannot yet consume. Source of truth:
> [`docs/design/WINDOWS_BROKER_DESIGN.md`](design/WINDOWS_BROKER_DESIGN.md) (§1, §3, §8).

The PLANNED governed-execution broker replaces "trust the process" with OS-enforced separation:

- **Eight distinct principals** — six Windows services (`BropsSigner`, `BropsSupervisor`,
  `BropsRecorder`, `BropsChallengeAuthority`, `BropsSidecar`, `BropsLauncher`) with per-service SIDs
  (`NT SERVICE\…`), plus a per-turn `brops-executor` local account reduced to an empty-capability
  **AppContainer** token. Interactive logon is denied to every service principal; the executor
  account is denied interactive/remote/network logon.
- **ACL matrix** — private-key stores (CNG persisted keys / DPAPI-machine) and the content-addressed
  evidence store are locked by NTFS/registry/CNG DACLs owned by a TCB principal
  (`TrustedInstaller` / `brops-admin`), with explicit deny-write to every runtime and login SID and
  inheritance severed (`PROTECTED_DACL`). Signer/supervisor/recorder run WRITE_RESTRICTED.
- **Named-pipe peer auth** — each IPC endpoint checks the connecting SID against a frozen allowlist
  (server side) and the client verifies the server SID (client side).
- **Installer** (runs as SYSTEM/`TrustedInstaller`) is the only component holding
  `SeRestorePrivilege`/`SeTakeOwnershipPrivilege`; all provisioning is idempotent and re-verified
  after apply (§8.1 of the design).

**Gate behaviour today:** `platform_governed_execution_supported()` returns **false** on Windows,
so no lease is issued and every governed turn fail-closes (see §6 and the User Guide). An operator
cannot enable governed "Verified" execution on Windows yet — the flip is gated on the broker being
implemented **and** its Windows CI isolation proof (`isolation_proof.ps1`, design §10) passing.

---

## 5. AI provider setup

Three providers, selected by `BROPS_AI_PROVIDER` (or auto-detected):

1. **`claude` (default)** — the local `claude` CLI, i.e. the operator's own Claude Code
   subscription (no API key, streamed token-by-token). Ensure `claude` is on the app's `PATH`, or
   set `BROPS_CLAUDE_BIN` to its absolute path. Chat runs the CLI as a **tool-free text completion**
   in a per-process sandbox (`--tools ""`, `--strict-mcp-config`, `--no-session-persistence`).
2. **`anthropic`** — the metered Anthropic API. Requires `ANTHROPIC_API_KEY` in the environment;
   endpoint is a fixed constant (not env-controlled).
3. **`ollama`** — a local model server. Loopback-only unless `BROPS_ALLOW_REMOTE_OLLAMA=1` **and**
   an HTTPS URL are both set.

Provider resolution is **fail-closed**: an unknown/misconfigured provider is a hard error, and an
ambient `ANTHROPIC_API_KEY` never silently selects a provider for a governed turn.

Verify the resolved provider in the app's **Settings** screen (read-only) or via the `ai_status`
command surface.

---

## 6. Governed vs. ungoverned execution (operational meaning)

- **Ungoverned providers** (`claude` CLI / `anthropic` / `ollama`) produce normal streamed replies.
  This is the working daily path.
- **Governed execution** (turns routed through the engine wall to earn a signed, desktop-verified
  receipt) is **fail-closed and currently Blocks every turn.** The signed **Receipt Protocol v1**
  verifier is merged (Waves 1–3a), but production "Verified" (`trusted_verified`) requires the
  **isolated signer** (Wave 3b), which is **in progress and not merged**. Until the full
  3b-1 → 3b-2 → 3b-3 chain is green, a governed turn yields a transient *"Governed reply blocked
  (unverified)"* notice and **no persisted message** — by design, not a bug.

Operationally: do not present governed mode as a working feature to users yet. Live status:
[`NEXT_CHAT.md`](../NEXT_CHAT.md) and [`config/current_state.json`](../config/current_state.json).

---

## 7. Update & rollback

### 7.1 Application update (today)

There is **no in-app auto-updater** (`tauri-plugin-updater` is not configured — **PLANNED**).
Update manually:

1. **Back up first** (§8).
2. Install the new `.msi`/`.exe` over the existing install (MSI performs an in-place upgrade keyed
   on the product/upgrade code; NSIS reinstalls per-user).
3. Launch once. Schema migrations run **forward-only** and automatically to the version the new
   binary expects.

### 7.2 Rollback (today)

SQLite migrations are **forward-only** — there is no automatic down-migration. To roll back to an
older BroPS build safely you must also restore the **matching `brops.db` backup** taken *before* the
upgrade:

1. Close BroPS completely (release the single-instance lock).
2. Reinstall the older BroPS build.
3. Restore the pre-upgrade `brops.db` (+ `-wal`/`-shm`) from backup (§8.2).

> Restoring a *newer* DB under an *older* binary is unsupported — a DB migrated to a higher schema
> may not open on an older build. Always pair a rollback with the DB backup from the same version.

### 7.3 Broker update / rollback — **PLANNED (broker)**

The design specifies transactional, TCB-owned broker updates (stage → hash/Authenticode verify →
re-pin WDAC → atomic swap → rewrite pin manifest) with rollback restoring the prior binaries + pin
manifest + WDAC policy, and a failed update leaving the old, still-pinned binaries in place
(design §8.2). None of this exists yet.

---

## 8. Backup & restore

The entire application state is the SQLite database. There is no external service or cloud state.

### 8.1 Backup

1. **Fully quit BroPS** so the WAL is checkpointed and the single-instance lock is released.
2. Copy the whole app-data directory (or at minimum `brops.db`, `brops.db-wal`, `brops.db-shm`):
   - Windows: `%APPDATA%\studio.menq.brops\`
   - Linux: `~/.local/share/studio.menq.brops/`
3. Optionally also copy the **Files workspace** (`~/BroPS` or `BROPS_FILES_ROOT`) — those are real
   user files the app edits, not app state.

Copying while the app is running can capture a torn WAL; always quit first. (A hot backup via
`VACUUM INTO`/`sqlite3 .backup` is possible if you have the SQLite CLI, but quitting is simplest.)

### 8.2 Restore

1. Quit BroPS.
2. Replace the app-data directory contents with the backup (`brops.db` + `-wal` + `-shm` together).
3. Relaunch. Confirm the schema matches the installed binary (restore into the **same or newer**
   BroPS version, never an older one — see §7.2).

Secrets are **not** in the backup (API keys live only in the environment), so no secret material is
exposed by copying `brops.db`.

---

## 9. Uninstall

### 9.1 Application (today)

1. Quit BroPS.
2. Windows: **Settings → Apps → BroPS → Uninstall** (or *Add/Remove Programs*); the MSI/NSIS
   uninstaller removes the binaries and shortcuts.
3. The uninstaller does **not** delete your data. To remove it, delete the app-data directory
   (`%APPDATA%\studio.menq.brops\`) and, if desired, the Files workspace (`~/BroPS`). Keep a backup
   first if the conversation/knowledge history matters.

### 9.2 Broker teardown — **PLANNED (broker)**

The design's uninstall (design §8.3) stops the services, removes the WDAC/AppLocker policy, deletes
the service registrations and the `brops-executor` account, and securely deletes the CNG/DPAPI key
containers, leaving the evidence store TCB-owned/deny-all for a clean reinstall. Not implemented.

---

## 10. Operational health checks

| Check | How | Healthy result |
|---|---|---|
| App starts & DB opens | Launch BroPS | Window opens; Home populates; no startup abort |
| Single-instance lock | Launch a second copy | Second instance exits without touching state |
| AI provider resolved | Settings screen / `ai_status` | Correct provider + `ready: true`; `governed:false` on ungoverned |
| Governed path | Attempt a governed turn | Fail-closed *"Governed reply blocked (unverified)"* (expected today) |
| Files confinement | Browse Files | Cannot escape the root; sensitive paths (`.ssh`, `.env`, `*.pem`, …) not listed |
| CI green | `.github/workflows/ci.yml` | Frontend build + Rust core/host tests + clippy `-D warnings` + release build pass |

---

## 11. Security posture summary (for operators)

Exists today (see [`apps/desktop/SECURITY.md`](../apps/desktop/SECURITY.md) for the full model):

- Files workspace confined to one root with a sensitive-path denylist; reads bounded (≤2 MiB),
  writes atomic and permission-preserving.
- AI subprocess runs tool-free in a fresh owner-only sandbox with no confidential text in argv.
- Ollama loopback-only by default; Anthropic endpoint fixed; response bodies capped.
- Durable approval with a renderer-independent **native OS confirmation dialog**; self-approval
  refused across restarts; pre-dispatch execution claim so one grant starts exactly one run.
- CI: SHA-pinned actions, `clippy -D warnings`, release build on every push.

Known gaps (honest): Windows lacks the Unix `0700`/`0600` data hardening and owner-only sandbox
(Windows equivalents are **PLANNED (broker)**); installers are **unsigned**; a residual filesystem
TOCTOU window is accepted for the single-user threat model.
