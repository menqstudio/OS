# BroPS / OS — Operator Guide

> **Scope.** This guide covers installing, provisioning, updating, backing up, and removing the
> **BroPS desktop cockpit** (`apps/desktop/`) — the human-facing half of `menqstudio/OS`
> (Tauri 2 + Rust + SQLite + React 19).
>
> **Windows is the only platform the app can currently run on.** Linux still builds and its tests
> run, but since first-launch trust provisioning landed, the POSIX branch of sealing the trust
> anchor returns `Unsupported` and **startup aborts**. §2.3 says exactly what a POSIX deployment
> would have to provide. Do not read the Linux column of any table here as a supported install.
>
> **Honesty contract.** Every section marks what **exists today** vs. what is **PLANNED**. The
> governed-execution **Windows broker** (services, per-service SIDs, NTFS/CNG DACLs, AppContainer
> executor, WDAC) is a *normative, unaudited design target* — it is **not implemented**. Where an
> operator step depends on it, the step is labelled **PLANNED (broker)** and points at
> [`docs/design/WINDOWS_BROKER_DESIGN.md`](design/WINDOWS_BROKER_DESIGN.md), which is on `main`.
> The **trust anchor** in §2.3 is a separate, implemented thing — do not confuse the two. Do not
> provision services or ACLs from this guide that the code does not yet create.

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
| Trust boundary | **webview → Rust host**, and **the app's account → the machine-wide trust anchor** (§2.3); single-user local app |
| Trust material | minted on this machine at first launch; the operator root is destroyed at install |

There is **no server and no network listener** in the shipping app. It is a single desktop process
that owns one SQLite database, plus a machine-wide trust anchor it deliberately cannot write.
(The multi-service governed-execution broker in §4/§7 is PLANNED and separate.) The one Windows
**service** in the design — the audit signer that holds the `audit-anchor` key — is built but
ships in no installer, so a stock install runs no service either; see §2.3.

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

### 2.3 First-run provisioning (automatic) — **including trust provisioning**

On first launch the host creates and initialises its own state — no manual provisioning, and **no
owner ceremony**. The order below is the order in `run()`'s `setup` hook
(`apps/desktop/src-tauri/src/lib.rs`) and it is load-bearing:

1. Creates the app-data directory (`app_data_dir()` for `studio.menq.brops`).
2. **(Unix only)** sets that directory to `0700` — **before** anything is written into it.
3. **Mints (or verifies) the local trust store** — `provision_local_trust`. This runs **before the
   database is opened**, and **a failure aborts startup**: there is no degraded mode, and a partial
   mint is removed rather than kept. See below for what it writes and where.
4. Takes an **exclusive single-instance advisory lock** on a lock file in that directory (a second
   instance aborts cleanly rather than touching live state).
5. Opens/creates `brops.db`, runs forward-only schema migrations, and seeds baseline rows.
6. **(Unix only)** sets `brops.db` and its `-wal`/`-shm` to `0600`.
7. Reconciles any execution claim abandoned by a crashed prior session (fail-closed) and sweeps
   stale AI sandbox directories.

**What step 3 does.** `brops-provision` mints one Ed25519 keypair for each of the nine authorities
the engine knows, signs a `trusted-key-registry` and a `conductor-session` artifact with
`operator-root`, and then **destroys the operator-root private half before it returns**. Eight
delegated keys are retained; `control-room` and `evidence-floor` are the two the app legitimately
needs afterwards, and neither can sign a registry, a conductor session or an audit head. Nothing
expires (`not_after_epoch` is 9999-12-31), so nothing is ever asked of the person who installed it.
On a later launch the step **verifies** what is on disk and returns; it never re-mints over a
working install.

**Where it writes.** Two halves, and the split is the whole security argument:

| Half | Windows | Linux (specified; see the platform warning) | Holds |
|---|---|---|---|
| App-side trust store | `%APPDATA%\studio.menq.brops\trust\` | `~/.local/share/studio.menq.brops/trust/` | `keys/` (the 8 retained private halves), `artifacts/conductor-session.json`, `POSTURE.txt` |
| Machine-wide **trust anchor** | `%ProgramData%\BroPS\trust-anchor\` | `<POSIX_MACHINE_ROOT>/trust-anchor/` | `operator-root.pub` (the pin), `registry-min` (anti-rollback floor), `registry/config/trusted-keys.json`, `PROVISIONING.json`, `CUSTODY.txt` |
| Audit signer (Windows, when installed) | under `%ProgramData%\BroPS\` | — | the `audit-anchor` key and its published custody record |

The anchor is **sealed**: a PROTECTED DACL whose OWNER RIGHTS (`S-1-3-4`) ACE grants read+execute
only — replacing the owner's implicit `WRITE_DAC` rather than adding to it, so no elevation and no
second account are needed — applied to the anchor's files, its directory, and **every ancestor up
to the machine root**. Every launch re-measures with the OS's own answer and refuses if the seal no
longer holds. **The seal is one-way for the account that applied it:** removing the anchor
afterwards needs an administrator.

> #### ⚠️ Install ordering — the audit signer must be registered BEFORE the app's first launch
>
> Provisioning admits the audit signer's published public key to the registry **while the registry
> is being signed**, and the operator root is destroyed as that returns. **The registry seals when
> provisioning returns**, so a signer key that was not admitted at that moment can never be admitted
> afterwards — there is no key left to re-sign the registry with. If this machine is to have an
> audit-head anchor (residual item O-2), register the signer service **first**, then launch the app.
> Reversing the order means re-provisioning the machine.
>
> **Today nothing does this for you:** the signer's two binaries (`brops-audit-signer`,
> `brops-anchor-relay`) are **in no installer**, `tauri.conf.json` declares no `externalBin` or
> extra resources, and the elevated registration routine (`audit-signer/src/register.rs`, which
> prints the exact `sc.exe` plan) has no entry point outside tests. On a stock install the machine
> therefore has **no** audit signer: `published_anchor_custody` returns `None`, provisioning proceeds
> without an anchor, and every keyed `bro_audit_log.verify()` then fails closed — which is correct,
> and is not something to paper over.

> #### ⚠️ Platform: Windows only, today
>
> `anchor::seal` returns `Unsupported` on POSIX **by construction** — a POSIX owner may always
> `chmod` a directory it owns and there is no OWNER RIGHTS equivalent — so **first-launch
> provisioning aborts startup on Linux**. The POSIX design is written down (the anchor directory
> created at `<POSIX_MACHINE_ROOT>/trust-anchor` (read `anchor::POSIX_MACHINE_ROOT` for the current
> literal rather than copying one out of a document), mode `0755`, owned by a **different** uid — root or a
> dedicated `brops-anchor` account — with every ancestor likewise, and provisioning run once as that
> account by the installer, before the app runs as its own unprivileged uid) but **that branch has
> never executed.** Do not treat the Linux column above as a supported install.

> **Windows data-at-rest gap (honest).** The `0700`/`0600` hardening in steps 2 and 6 is
> **Unix-only** (`secure_data_dir` / `secure_owner_only_file` have no non-unix branch). On Windows
> the database **and the retained private keys** inherit the ACL of the per-user app-data directory
> — per-user by default, plus SYSTEM and Administrators. This is recorded rather than fixed: it is
> stated in `PROVISIONING.json`, in `POSTURE.txt` and on stderr at first launch. Explicit owner-only
> DACL enforcement on those files is **PLANNED**. Until then, protect the machine account itself
> (full-disk encryption / a locked user profile).

> **What the posture claims.** Trust material minted on the user's own machine defends against an
> attacker who arrives **later**. It does **not** defend against one who already owned the machine
> at install time — that attacker witnesses the mint or performs it. An SSH host key makes the same
> trade. The chain proves *integrity over time on this machine*, not *provenance from a vendor*.

### 2.4 Data locations

| Item | Windows | Linux |
|---|---|---|
| App-data dir (holds `brops.db`) | `%APPDATA%\studio.menq.brops\` | `~/.local/share/studio.menq.brops/` |
| SQLite DB | `…\studio.menq.brops\brops.db` | `…/studio.menq.brops/brops.db` |
| App-side trust store | `…\studio.menq.brops\trust\` | `…/studio.menq.brops/trust/` |
| Machine-wide trust anchor | `%ProgramData%\BroPS\trust-anchor\` | `<POSIX_MACHINE_ROOT>/trust-anchor/` (never executed) |
| Files workspace root | `%USERPROFILE%\BroPS\` | `~/BroPS/` |

Exact resolution is Tauri's `app_data_dir()` for the identifier; the table gives the platform
defaults. Override the Files root with `BROPS_FILES_ROOT` (§5). The trust anchor's location is
**not** overridable by the application — that is the point of it.

**Backup and uninstall treat the anchor differently.** It is machine-wide, outside the app-data
directory, and sealed against the account that made it, so §8's "copy the app-data directory" does
not capture it and §9's uninstaller does not remove it. See those sections.

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
| `BROPS_ALLOW_GOVERNED_ENGINE` | off | Required alongside `BROPS_AI_PROVIDER=governed-engine`. |
| `BROPS_PROJECT_DIR` | unset | **Grants Bro file and shell access to this directory** and turns on the conductor mode described in §5. Unset means a tool-free sandboxed chat. |
| `BROPS_GOVERNANCE_STATE_DIR` | unset | Required for the governance mirror to read anything. Must be an **absolute** path to an existing directory — the sidecar refuses to create one and then report it as empty. Independent of the AI provider: a mirror read is not a governed turn. |
| `BROPS_GOVERNANCE_EVIDENCE_STORE` | unset | Optional; must exist if set. |
| `BROPS_GOVERNANCE_REGISTRY_ROOT` | unset | Optional; set-but-unloadable is a refusal, never a silent unkeyed downgrade. |

Secrets (`ANTHROPIC_API_KEY`) are read **only** from the environment and are never written to
SQLite. Set them in the user/session environment before launching BroPS.

### 3.1 Engine trust environment — **what provisioning writes, and where it is applied**

These are read by the **engine** (`engine/runtime/bro_signature.py`, `bro_policy.py`,
`bro_audit_log.py`), not by the desktop host. `Provisioned::engine_env()` *computes* the first
five — `BRO_TRUSTED_REGISTRY_ROOT` **included since 2026-08-09**, when it was added and the wiring
landed — and `provision_local_trust` **records** them.

They are still never applied to the desktop process itself. They are set on the **child**, at the
one seam in this application that launches the engine (`ai::governed_sidecar_call`, which both the
governed AI turn and the read-only governance mirror go through), by
`apps/desktop/src-tauri/src/engine_trust.rs`. That module applies the set **whole or not at all**
and refuses by name — never silently overriding, and never being silently overridden — when the
ambient environment already carries a different anchor. Read its header for the precedence rule.

| Variable | What it names | Provisioning's value |
|---|---|---|
| `BRO_OPERATOR_ROOT_PUBKEY_FILE` | the out-of-registry operator-root pin (absolute, non-symlink, not group/other-writable) | `<anchor>/operator-root.pub` — returned by `engine_env()` and set on the engine child |
| `BRO_OPERATOR_REGISTRY_MIN_FILE` | the anti-rollback floor, so a superseded but still-signed registry cannot be replayed | `<anchor>/registry-min` — returned and set on the engine child |
| `BRO_CONDUCTOR_SESSION_TOKEN` | the operator-signed `conductor-session` artifact the wall requires (O-3) | `<trust>/artifacts/conductor-session.json` — returned and set on the engine child |
| `BRO_SESSION_ID` | the session the artifact above is bound to | minted at install — returned and set on the engine child |
| `BRO_TRUSTED_REGISTRY_ROOT` | **where the engine reads `config/trusted-keys.json` from** | `<anchor>/registry` — returned and set on the engine child. **This is the one that was missing**: without it the other four point the engine's anchor at a registry it never reads |
| `BRO_AUDIT_ANCHOR_SIGNER` / `BRO_AUDIT_ANCHOR_KEY_ID` | the audit-head signing command and its key id (O-2). Deliberately two variables: half a configuration is refused loudly rather than degrading to an unanchored ledger | unset on a stock install (there is no signer) |
| `BRO_OPERATOR_ROOT_PIN_SELF_OWNED` | the acknowledgement that short-circuits **every** custody rule at once. Honoured **only when the CI system set `BRO_ENV=ci`**: ungated it handed the short-circuit to anyone who could set the verifying process's environment, which is exactly the capability the F-06 attack it defends against already needed. Outside CI it is a hard, named refusal | **no longer set anywhere**, and setting it again would re-disable the checks the anchor now passes on their merits |
| `BRO_OPERATOR_ROOT_PIN_SELF_OWNED_FILE` | the production form of the same acknowledgement: a file whose entire content is `acknowledged`. It is deliberately **not** custody-checked (the acknowledgement exists for deployments with no second principal, so holding it to the rule it disables would be circular); it raises the cost from one `export` to a file the operator wrote, and puts the posture on disk where a deployment audit finds it | **not set**. `engine_trust::resolve` refuses to export any trust material at all while **either** name is present |

> **What changed, stated plainly.** Until 2026-08-09 this section said the opposite, and it was
> right to: nothing exported any of these, so the engine read the committed development registry at
> `engine/config/trusted-keys.json` (`production: false`, with its "DEVELOPMENT REGISTRY" warning)
> and the trust material the app minted was invisible to it. The export now happens, at the seam
> named above, and `apps/desktop/src-tauri/tests/o3_conductor_session.rs` proves it against the real
> Python engine in both directions: the installer-minted `conductor-session` is **accepted** by
> `bro_policy.verify_conductor_session_token` with the engine's own tree as `root`, and the same
> token is **refused** the moment `BRO_TRUSTED_REGISTRY_ROOT` is dropped or pointed at another
> install.
>
> It is still not unconditional, and that is deliberate: `bro_signature` hard-fails when a file pin
> and the CI `BRO_OPERATOR_ROOT_PUBKEY` disagree, so an environment that already carries a different
> anchor makes the governed call **refuse by name** rather than have either side silently win.
>
> `BRO_TRUSTED_REGISTRY_ROOT` is fail-closed when you do set it: absolute path only, no symlink at
> **any** component, must hold `config/trusted-keys.json` as a regular file, must be a directory the
> reading account cannot rewrite, and must contain **neither the pin nor the floor** — a redirect
> that carried the anchor along would hand over the registry and the thing that authenticates it in
> one variable. While it is set, a caller naming a *third* root is refused by name rather than
> quietly served a different registry from the rest of the process.

> **And there is no production registry to point at.** `broctl build-registry` hardcodes
> `"production": false`, `broctl keygen --production` refuses by name, and `bro_signature` refuses a
> non-production registry whenever the pin comes from the production `_FILE` path. An **engine-only**
> deployment therefore has no path to a production registry at all; how one is minted is an
> Owner/architecture decision, not a missing function.

---

## 4. Service + ACL setup — **PLANNED (broker)**

> **Nothing in this section is implemented, and it is a different subject from §2.3.** The
> governed-execution *broker* below — its services, per-service SIDs, CNG stores, AppContainer
> executor and WDAC policy — does not exist. Do not confuse it with the **trust anchor** in §2.3,
> which *is* real on Windows: first-launch provisioning applies a PROTECTED DACL to
> `%ProgramData%\BroPS\trust-anchor` and its ancestors, unelevated, with no service involved. So
> the shipping app registers **no Windows service**, but it is no longer true that it applies **no
> custom ACLs**. Separately, the audit-signer service (§2.3's install-ordering warning) *is* built
> and *is* designed to be registered by an elevated installer — but no installer ships it. Source of
> truth for the broker: [`docs/design/WINDOWS_BROKER_DESIGN.md`](design/WINDOWS_BROKER_DESIGN.md)
> (§1, §3, §8). Do not hand-provision anything the runtime cannot yet consume.

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

**Gate behaviour today:** every governed turn fail-closes and no lease is issued (see §6 and the
User Guide). An operator cannot enable governed "Verified" execution on Windows — the flip is gated
on the broker being implemented **and** its Windows CI isolation proof (`isolation_proof.ps1`,
design §10) passing, **and** an independent audit, **and** the Owner's approval.

> **Naming, because this trips people up.** The design calls the gate
> `platform_governed_execution_supported()` (§0.1 / §7.1 / §10). **No function of that name exists
> in the tree** — it is a specification symbol, and `config/spec-conformance.json` records §0.1 as
> `partial`: *"the platform gate as specified; it is a hardcoded false."* The hardcoded false is
> three real refusals, and those are what to cite:
> `governed_verification_unconfigured()` (`src/commands.rs`) returns `Some(…)` unconditionally and
> fires *before the model is called*; `connect_broker()` (`src/governed_turn.rs`) returns
> `UnsupportedPlatform` on every host but Linux; and the broker's own
> `build_governed_executor` falls back to `UpstreamBlockedExecutor` unless a complete
> `BROPS_BROKER_CONFIG` parses.

---

## 5. AI provider setup

Three providers, selected by `BROPS_AI_PROVIDER` (or auto-detected):

1. **`claude-cli` (default)** — the local `claude` CLI, i.e. the operator's own Claude Code
   subscription (no API key, streamed token-by-token). Ensure `claude` is on the app's `PATH`, or
   set `BROPS_CLAUDE_BIN` to its absolute path.

   **Two modes, and the difference is the whole security posture.** With `BROPS_PROJECT_DIR`
   **unset** the turn is a tool-free text completion in a per-process sandbox — `--tools ""`,
   `--strict-mcp-config`, `--setting-sources ""`, `--no-session-persistence` — so a
   prompt-injection cannot read a file or run a command.

   With `BROPS_PROJECT_DIR` **set to a real directory**, Bro becomes the conductor and receives
   `Read Edit Write Grep Glob Bash Task` in `acceptEdits` mode, with `cwd` at that project. `Task`
   is what lets him hand work to specialists. Bash is bounded by a deny list — no delete, no `git
   push`, no dependency install, no nested shell — and those are blast-radius limits rather than
   capability limits. The three capability tiers (`reader`, `runner`, `builder`) are passed inline
   via `--agents`, and the CLI's own built-in agent types are denied at argv so a specialist cannot
   be spawned outside the tier model. **Setting `BROPS_PROJECT_DIR` grants file and shell access to
   that directory. Treat it as such.**
2. **`anthropic`** — the metered Anthropic API. Requires `ANTHROPIC_API_KEY` in the environment;
   endpoint is a fixed constant (not env-controlled).
3. **`ollama`** — a local model server. Loopback-only unless `BROPS_ALLOW_REMOTE_OLLAMA=1` **and**
   an HTTPS URL are both set.
4. **`governed-engine`** — routes the turn through the bridge into the engine's governed chain.
   Requires `BROPS_ALLOW_GOVERNED_ENGINE=1` as well as the provider name; without it the provider
   is refused by name. **On the shipped build every governed turn is then refused anyway**, because
   verification is unprovisioned by construction and the broker falls back to
   `UpstreamBlockedExecutor` — which it does *unless* `$BROPS_BROKER_CONFIG` names a deployment
   config with a TCB-root-signed manifest, and nothing in the shipped app sets it. §4's naming note
   already stated that condition correctly; this line said "keeps", flatly, until 2026-08-09. See §4
   and §6.

Provider resolution is **fail-closed**: an unknown/misconfigured provider is a hard error, and an
ambient `ANTHROPIC_API_KEY` never silently selects a provider for a governed turn.

Verify the resolved provider in the app's **Settings** screen (read-only) or via the `ai_status`
command surface.

---

## 6. Governed vs. ungoverned execution (operational meaning)

- **Ungoverned providers** (`claude-cli` / `anthropic` / `ollama`) produce normal streamed replies.
  This is the working daily path. Note that `claude-cli` with `BROPS_PROJECT_DIR` set is
  *contained* — a sandbox, a bounded shell, a tier-bounded specialist — but it is **not governed**:
  no lease, no signed receipt, and path scope is stated rather than enforced. The UI does not call
  it governed, and neither should you.
- **Governed execution** (turns routed through the engine wall to earn a signed, desktop-verified
  receipt) is **fail-closed and currently Blocks every turn.** A governed turn yields a transient
  *"Governed reply blocked (unverified)"* notice and **no persisted message** — by design, not a bug.

  What changed since this section was first written, and what did not: the isolated signer and the
  full Wave 3b chain **are merged and machine-proven**, on Linux (7 services, real uids, a setuid
  launcher) and on Windows (named pipes, cross-account, distinct service accounts), and CI runs
  both on every PR. What still refuses is the **shipped application**, deliberately:
  `governed_verification_unconfigured()` returns `Some(…)` unconditionally (before the model is
  called), `connect_broker()` returns `UnsupportedPlatform` off Linux, and the broker keeps
  `UpstreamBlockedExecutor`. See §4's naming note.

  **A proof kit that runs is not a shipped guarantee.** Opening the gate needs an independent audit
  of the whole chain **and** the Owner's approval — a green CI run is neither. Five engine residual
  items remain OPEN, three of them waiting on an artifact only the Owner can mint.

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

> **The trust store is not re-minted by an update.** Provisioning is idempotent: because
> `PROVISIONING.json` is present in the anchor, the new build **verifies** the existing store
> against it and returns. A verification failure aborts startup as `Corrupt` and is never silently
> repaired — it means the app-side store and the anchor disagree, which is either damage or
> tampering, and replacing it would destroy the evidence of which.

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

The application's *user* state is the SQLite database. There is no external service or cloud state.
Its *trust* state is not in the database and does not move with it — see §8.3.

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

### 8.3 The trust store and the anchor — read before you copy anything

- The app-side trust store (`…\studio.menq.brops\trust\`) **does** hold private key material.
  Copying the app-data directory copies it. Treat that backup as key material: it is exactly the
  set of delegated keys this machine can sign with.
- The **anchor** (`%ProgramData%\BroPS\trust-anchor\`) is **not** in the app-data directory and is
  not captured by §8.1. It is also sealed against the account that made it, so an ordinary backup
  tool running as that account may not be able to read every part of it.
- **Restoring an app-side store under a different anchor does not work, and must not.**
  `PROVISIONING.json` (in the anchor) carries the sha256 of every app-side file — the half the app
  can rewrite is vouched for by the half it cannot — so a mismatched pair is refused at startup as
  `Corrupt`, never silently repaired and never re-minted over. If you are moving to a new machine,
  let it provision its own trust; do not transplant one.

---

## 9. Uninstall

### 9.1 Application (today)

1. Quit BroPS.
2. Windows: **Settings → Apps → BroPS → Uninstall** (or *Add/Remove Programs*); the MSI/NSIS
   uninstaller removes the binaries and shortcuts.
3. The uninstaller does **not** delete your data. To remove it, delete the app-data directory
   (`%APPDATA%\studio.menq.brops\`) and, if desired, the Files workspace (`~/BroPS`). Keep a backup
   first if the conversation/knowledge history matters.
4. **The trust anchor survives the uninstall, and an ordinary user cannot remove it.**
   `%ProgramData%\BroPS\trust-anchor\` was sealed one-way by the account that created it, so
   deleting it requires an **administrator**. Leaving it in place is harmless and is what makes a
   reinstall verify against the same anchor; removing it means the next launch mints a fresh trust
   store, which is a different machine identity. If an audit signer was registered
   (`brops-audit-signer`), removing it is likewise an elevated, separate step — no uninstaller does
   it, because no installer created it.

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
| Trust provisioning | First launch, on stderr | `BroPS provisioned its local trust store at …` plus the posture, the operator-root line and the **measured** custody proof. A startup abort naming a path means provisioning refused — read the message; it names what failed |
| Anchor custody still holds | Every launch | Silent. `prove_unwritable` re-measures against the OS on each start and aborts startup if the seal no longer holds — so "the app opened" *is* the check |
| Anchor present | Inspect `%ProgramData%\BroPS\trust-anchor\` | `operator-root.pub`, `registry-min`, `registry/config/trusted-keys.json`, `PROVISIONING.json`, `CUSTODY.txt`; readable, and **not** writable by your account |
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

Added since this list was written — real on Windows, not planned:

- The engine's trust material is **minted at first launch and the operator root is destroyed**, so
  no key that can sign the trusted-key registry survives on the machine (§2.3).
- The pin, the anti-rollback floor, the registry and the provisioning manifest live in a
  **machine-wide anchor the app's own account cannot write**, sealed to the volume root and
  re-measured against the OS on every launch.
- The `audit-anchor`, `control-room` and `evidence-floor` authorities are **split**: the audit log's
  head can only be signed by a principal the ledger's writer cannot become, while the two routine
  authorities stay online and can sign nothing else.

Known gaps (honest):

- **Windows-only.** Provisioning refuses on POSIX and aborts startup there (§2.3).
- **`broctl` cannot mint a production registry at all.** *(This bullet used to read "the engine does
  not see any of it — nothing exports the provisioned environment". That was fixed on 2026-08-09: the
  five variables are applied to the engine child at `ai::governed_sidecar_call`, §3.1.)* What remains
  under this heading is the ceremony: `broctl build-registry` hardcodes `production: false`, so the
  only *production* registry any deployment has is the one first-launch provisioning mints for itself.
- **No audit signer ships.** The second principal O-2 needs is built but is in no installer, so a
  stock install has no audit-head anchor and keyed ledger verification fails closed (§2.3).
- Windows lacks the Unix `0700`/`0600` data hardening and owner-only sandbox — the retained private
  keys inherit the app-data ACL (Windows equivalents are **PLANNED (broker)**).
- Installers are **unsigned**; a residual filesystem TOCTOU window is accepted for the single-user
  threat model.
- The boundary is the app's **unelevated token**: on a machine whose user is a local administrator,
  one UAC consent gives full control. Provisioning refuses outright if its token holds
  `SeTakeOwnership` or `SeRestore`, rather than proceeding and claiming an anchor it does not have.
