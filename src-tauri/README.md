# src-tauri — BroPS desktop host

- **Purpose:** The Tauri 2 + Rust desktop host and the local SQLite data core.
- **Owner:** Gev.
- **Related:** [../IMPLEMENTATION_EXECUTION_HANDOFF.md](../IMPLEMENTATION_EXECUTION_HANDOFF.md), [../docs/architecture/DESKTOP_ARCHITECTURE.md](../docs/architecture/DESKTOP_ARCHITECTURE.md), [../docs/architecture/DATABASE_SCHEMA.md](../docs/architecture/DATABASE_SCHEMA.md).
- **Last updated:** 2026-07-19.

## Layout

- `core/` — `brops-core`: SQLite schema, forward-only migrations, and typed repositories. **UI- and Tauri-independent**, so it builds and tests on its own.
- `src/` — the Tauri host: `AppState` (a locked `rusqlite::Connection`) and the typed `#[tauri::command]` surface. React reaches the database only through these commands.
- `schema/0001_initial.sql` — the initial migration.
- `tauri.conf.json`, `capabilities/` — desktop configuration and the minimal capability allowlist.

## What is verified

The data core is built and tested — projects/tasks CRUD, foreign-key enforcement, status validation, migration idempotency, and audit recording:

```bash
cargo test -p brops-core     # 6 tests, GREEN
```

## Build prerequisites (host GUI)

Building the full desktop binary needs a **C toolchain** and **system webview libraries**, which are not present in the authoring sandbox and require OS packages:

- **Linux:** `build-essential`, `libwebkit2gtk-4.1-dev`, `libgtk-3-dev`, `librsvg2-dev`, `libssl-dev` (via `apt`, needs sudo).
- **Windows:** MSVC build tools + WebView2 runtime.
- Rust (`rustup`) and Node (for the frontend `beforeBuildCommand`).

Then:

```bash
npm install
npm run tauri build      # or: npm run tauri dev
```

The GUI host has **not** been compiled in the authoring environment (no C linker / no webkit). Only the data core above is verified here; the host is code, pending a build on a machine with the prerequisites.
