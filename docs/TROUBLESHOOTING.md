# BroPS / OS — Troubleshooting

Practical fixes for the **BroPS desktop app** (Tauri 2 + Rust + SQLite + React). Grouped by symptom.
Windows is the primary platform; Linux notes are included where behaviour differs. Where a symptom
is **expected current behaviour** (not a bug), it is labelled **By design**.

---

## 1. Install & launch

### "Windows protected your PC" / SmartScreen / unknown publisher
- **Cause:** the installers are **unsigned** — Authenticode code signing is not yet configured
  (PLANNED). **By design (gap), not malware.**
- **Fix:** if you trust the build, choose **More info → Run anyway**. Prefer installers you built
  yourself or downloaded from the project's own release artifacts.

### The app won't start / exits immediately
- **Another instance is already running.** BroPS takes an **exclusive single-instance lock**; a
  second copy aborts on purpose. Close the first instance (check the tray/taskbar) and retry.
- **Stale lock after a crash.** Fully quit BroPS (end any lingering `brops` process), then relaunch
  — the lock is released when the process exits.
- **(Linux) Startup aborted on a permissions failure.** On Unix the app **refuses to run** if it
  can't set its data directory to `0700` / the DB to `0600`. Fix the ownership/permissions of
  `~/.local/share/studio.menq.brops/` so your user owns it, then relaunch.
- **(Linux) Missing webview libraries.** Install `libwebkit2gtk-4.1`, `libgtk-3`, `librsvg2`.

### The window is blank / "Backend unavailable" banner
- You are viewing the **frontend without the desktop backend** (a browser preview, or `npm run dev`
  opened in a browser). **By design** — data actions are disabled in preview. Use the installed
  desktop app, or `npm run tauri dev`, to get the real backend.

---

## 2. AI replies

### "Governed reply blocked (unverified)" — no message appears
- **By design, and expected today.** The governed "Verified" execution path is **fail-closed**: it
  refuses rather than showing you a reply it could not verify. The chain itself is merged and
  machine-proven on Linux and Windows, and CI runs both on every pull request — what refuses is the
  **shipped application**, on purpose. Opening that gate needs an independent audit and the Owner's
  approval, so it will not change by itself. Nothing is broken.

- **What to do:** nothing will make a governed reply appear. For an ordinary reply the app needs an
  **ungoverned** provider — the local `claude` CLI, the Anthropic API, or Ollama — and every one of
  them is refused unless `BROPS_ALLOW_UNGOVERNED=1` is set in the environment BroPS was launched
  from (development only; the `dev-ungoverned` build sets it). Check the resolved provider in
  **Settings**; `governed` should read *false* for a working ungoverned reply.

### No reply at all / provider not ready
- Open **Settings** (or the `ai_status` surface) and read `ready` and `detail`.
- **`claude` CLI not found:** ensure `claude` is on the app's `PATH`, or set `BROPS_CLAUDE_BIN` to
  its absolute path, then restart BroPS (env vars are read at launch).
- **Anthropic selected but failing:** confirm `ANTHROPIC_API_KEY` is set in the environment BroPS
  was launched from (not just a different shell). Optionally set `BROPS_ANTHROPIC_MODEL`.
- **"no AI provider configured":** nothing is allowed. Set `BROPS_ALLOW_UNGOVERNED=1` (development
  only) to use the local `claude` CLI, or see the governed section above.
- **Unknown / misconfigured provider:** provider resolution is **fail-closed** — a bad
  `BROPS_AI_PROVIDER` is a hard error rather than a silent fallback. The accepted values are
  `governed-engine` (needs `BROPS_ALLOW_GOVERNED_ENGINE=1`) and `claude-cli` / `anthropic` /
  `ollama` (each needs `BROPS_ALLOW_UNGOVERNED=1`). The value is `claude-cli`, **not** `claude`:
  `claude` is refused as unknown.

### Ollama replies fail or are refused
- **Loopback-only by default.** `BROPS_OLLAMA_URL` must resolve to `localhost` / `127.0.0.0/8` /
  `::1`. Embedded credentials, URL fragments, and non-`http(s)` schemes are rejected.
- **Remote host:** requires **both** `BROPS_ALLOW_REMOTE_OLLAMA=1` **and** an **HTTPS** URL.
  Anything less is fail-closed.
- Confirm the Ollama server is up and the `BROPS_OLLAMA_MODEL` tag is pulled.

### Reply is cut off / stops early
- Output is **byte-capped and deadline-bounded** to prevent runaway memory/time (response bodies
  are capped; the subprocess has an absolute deadline). Very long generations can hit the cap — ask
  for a shorter answer or split the request.

---

## 3. Command runs & approvals

### A run step won't execute
- The step likely **requires approval** and hasn't been approved. Approve it in **Approvals**.
- If the step was **rejected**, that is **terminal by design** — it will never run. Create a new
  step/run instead.

### I can't approve my own request
- **By design.** Self-approval is refused (durably, even across restarts). A different principal
  must approve. Note the **Approve** action is a **native OS dialog** — approve there, not via a
  page button (there is none to forge).

### Approval dialog didn't appear
- The confirmation is a **native OS dialog** driven by the backend. If your window manager
  suppressed it, bring BroPS to the foreground and retry the approve action; check it's not behind
  the main window.

---

## 4. Files workspace

### "Can't open / not found" for a file I can see on disk
- **Confined to one root.** The Files browser only reaches `~/BroPS` (or `BROPS_FILES_ROOT`). A path
  outside the root — or reachable only via `..`/symlink escape — is **rejected by design**. Move
  the file under the workspace root or point `BROPS_FILES_ROOT` at the right directory (it may not
  be your home dir or a filesystem root — those are refused).

### A file/folder is invisible or won't open
- **Sensitive-path denylist.** `.ssh`, `.aws`, `.gnupg`, `.git`, `.config`, `.env*`, `*.pem`,
  `id_*`, `*credential*`, etc. are **never listed, read, or written**, even inside a broad root.
  **By design.**

### Can't edit a file
- Editing is limited to **existing regular files**; you can't create new files, and directories /
  devices are rejected. Reads/edits over ~2 MB or of binary files are refused (bounded, to avoid
  hangs/OOM).

---

## 5. Data, backup & migrations

### Where is my data?
- One SQLite DB: `%APPDATA%\studio.menq.brops\brops.db` (Windows) or
  `~/.local/share/studio.menq.brops/brops.db` (Linux), plus `-wal`/`-shm` sidecars.

### My backup copy is corrupt / partial
- You likely copied while the app was **running** (torn WAL). **Fully quit BroPS first**, then copy
  `brops.db` **together with** its `-wal` and `-shm` files.

### After downgrading BroPS, the DB won't open
- Migrations are **forward-only**. A DB migrated by a newer build may not open on an older build.
  Restore the `brops.db` backup taken **before** you upgraded, matched to that older version
  (Operator Guide §7.2), or move back to the newer build.

### Startup complains about an abandoned execution / claim
- On launch the app **reconciles** any step execution claimed by a crashed prior session
  (fail-closed) under the single-instance lock. This is automatic recovery — no action needed; a
  wedged run is settled rather than left stuck.

---

## 6. "This screen is empty / says Not yet connected"

- No sidebar screen is a "Not yet connected" placeholder any more — **Research** and **Library**
  were, and both now read your local database. An empty screen is genuinely empty (create the
  first item). The **Bridge** panel is the exception in kind: it mirrors the engine, so with no
  engine provisioned it says *blocked* or *unreachable*, which is not the same as empty.

---

## 7. Governed-execution broker (Windows) — why it's "unsupported"

- If any tooling reports `platform_governed_execution_supported() == false` on Windows, that is
  **correct and current** — though nothing can really report it, because **no function of that name
  exists in the tree**. It is the specification symbol from `WINDOWS_BROKER_DESIGN.md` §0.1, recorded
  as `partial` in `config/spec-conformance.json`. What actually refuses on Windows is
  `connect_broker()` returning `UnsupportedPlatform`, on top of
  `governed_verification_unconfigured()` returning `Some(…)` on every platform while any of its five
  compile-time inputs is absent — and all are.
  The Windows governed-execution **broker** is **built and exercised in CI, and neither shipped nor
  wired**: the `brops-win-broker` and `brops-win-live` crates exist, and CI runs their tests and both
  proof harnesses' self-tests on `windows-latest`. They are a proof kit. No installer carries them,
  the desktop app never connects to their pipes, and parts of the design (WDAC, the AppContainer
  executor) are not built — so no lease is issued and governed "Verified" mode stays fail-closed.
  *(This said the broker was "PLANNED … not implemented" three sections below a paragraph calling the
  chain machine-proven on Windows.)* See
  [`docs/design/WINDOWS_BROKER_DESIGN.md`](design/WINDOWS_BROKER_DESIGN.md), a normative **unaudited**
  target that the implementation plan beside it supersedes in places. There is nothing to "turn on".

---

## 8. Language & theme

- Wrong language or theme: change both in **Settings** (Հայերեն / English / Русский; Dark / Light).
  Preferences are applied at runtime.

---

## 9. Verifying a build is healthy (developers)

```bash
cd apps/desktop
npm run build                                                 # tsc --noEmit + vite build
cargo test -p brops-core --manifest-path src-tauri/Cargo.toml  # data-core tests
```

CI (the repository-root `.github/workflows/ci.yml`) runs neither `clippy` nor a release build —
the workflow that names them is the vendored `apps/desktop/.github/workflows/ci.yml`, which GitHub
never executes from that path. What CI does run, and what to run locally before a pull request, is
in the root `CLAUDE.md` §4: the engine suite (`BRO_ENV=ci`), `cargo test --workspace`,
`npm run typecheck && npm test`, and the `tools/check_*.py` gates.

---

## 10. Still stuck / reporting issues

- **Security issues:** report **privately** — GitHub Security tab → *Report a vulnerability* — do
  **not** open a public issue for a vulnerability (see `apps/desktop/SECURITY.md`).
- **Live project status** (what's merged vs. in progress): [`NEXT_CHAT.md`](../NEXT_CHAT.md) and
  [`config/current_state.json`](../config/current_state.json).
- Include: your OS, whether you used the `.msi`/`.exe`/source build, the resolved AI provider from
  Settings, and the exact on-screen message.
