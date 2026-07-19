# BroPS

**BroPS — Bro's Personal Space** is MenQ Studio's command-first AI Operating System.

BroPS is not a generic dashboard. It is the daily operating environment where Gev works with Bro and a coordinated team of specialist AI agents across conversations, projects, tasks, knowledge, memory, decisions, approvals, files, automations, and integrations.

## Product principle

**Gev → Bro → BroPS → specialist agents → controlled execution → evidence**

Bro is the primary interface and coordinator. Specialist agents work inside explicit project, permission, approval, and evidence boundaries.

## Status — working desktop app (Phases 0–20)

- Foundation v1: **Locked** (2026-07-19) — see decision D-010.
- **Real backend, no mock layer.** React 19 + TypeScript + Vite frontend over a typed IPC boundary to a Tauri 2 + Rust host with SQLite (`rusqlite`, bundled). `cargo test -p brops-core` is GREEN (**28 tests**), schema **v10**, CI green.
- **Live AI** through the local `claude` CLI — Gev's own Claude Code subscription, free, no API key — with token-by-token streaming; Anthropic API key and Ollama are optional fallbacks.
- **Shipped surfaces (all backed by real commands + SQLite):**
  - Streaming **Chat / Group Chat** — agent picker, `@mention`, delete/rename, live Markdown.
  - **Command** runs that actually execute step-by-step via the AI, with **approval gating** (a gated step can't run until approved; rejection is terminal).
  - **Projects** (detail, edit, status change, Overview/Tasks tabs), **Tasks** kanban board (drag between statuses) with **dependencies / blockers** (self-edge + cycle guarded).
  - **Files** browser with text **view + edit** (2 MB / binary guarded), **Calendar** month view, **Analytics** charts.
  - **Global full-text search (FTS5)** + command palette with **deep-links** — opens the specific project / task / knowledge note / conversation, not just its screen.
  - Honest **offline / permission** states, plus Knowledge, Memory, Approvals, Decisions, Activity, Notifications, Integrations, Automations, Security, Settings.
- **Purpose:** a prettier, handier UI over what Gev already does in VS Code + Claude Code — not a from-scratch reimplementation.

## Run

```bash
# Frontend only (browser preview — shows honest offline state, no backend)
npm install
npm run dev          # http://localhost:1420

# Full desktop app (real Rust + SQLite backend + live AI)
npm run tauri dev    # dev build with the webview
# …or a release binary:
cargo build --release --manifest-path src-tauri/Cargo.toml
./src-tauri/target/release/brops

# Verify
npm run build                                                   # tsc --noEmit + vite
cargo test -p brops-core --manifest-path src-tauri/Cargo.toml   # 28 tests
```

AI uses the local `claude` binary by default. If it isn't on the app's `PATH`, set `BROPS_CLAUDE_BIN`; other knobs: `BROPS_AI_PROVIDER` (`claude` | `anthropic` | `ollama`), `ANTHROPIC_API_KEY`, `BROPS_CLAUDE_MODEL`. The SQLite database lives at `~/.local/share/studio.menq.brops/brops.db`.

## Documentation index

**Product & governance**
- [PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) — identity, mission, vision, scope, users, constraints
- [PRINCIPLES.md](docs/PRINCIPLES.md) — principles and enforceable laws (L-001..L-012)
- [TERMINOLOGY.md](docs/TERMINOLOGY.md) — glossary
- [DECISIONS.md](docs/DECISIONS.md) — decision format and log
- [ROADMAP.md](docs/ROADMAP.md) — phased future work
- [SUCCESS_CRITERIA.md](docs/SUCCESS_CRITERIA.md) — MVP definition of done
- [CHANGELOG.md](CHANGELOG.md) — repository history
- [AGENTS.md](docs/AGENTS.md) — contributor working contract

**System**
- [ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) — domains, entities, execution model
- [AI_RUNTIME.md](docs/architecture/AI_RUNTIME.md) — orchestrator, agents, engines, events, tools, approvals
- [DESIGN_SYSTEM.md](docs/architecture/DESIGN_SYSTEM.md) — MenQ Studio Design Standards (visual system, trilingual i18n, themes)

**Implementation contracts**
- [src-tauri/README.md](src-tauri/README.md) — desktop host + tested SQLite data core
- [IMPLEMENTATION_EXECUTION_HANDOFF.md](docs/IMPLEMENTATION_EXECUTION_HANDOFF.md) — full build contract (React/Tauri/Rust/SQLite)
- [MENQ_STUDIO_DESIGN_STANDARD_ADOPTION.md](docs/architecture/MENQ_STUDIO_DESIGN_STANDARD_ADOPTION.md) — design-token adoption rules
- [docs/architecture/DATA_MODEL.md](docs/architecture/DATA_MODEL.md) — entities, enums, state rules
- [docs/architecture/DATABASE_SCHEMA.md](docs/architecture/DATABASE_SCHEMA.md) — SQLite schema contract
- [docs/architecture/AI_RUNTIME_CONTRACTS.md](docs/architecture/AI_RUNTIME_CONTRACTS.md) — provider/model/prompt/run contracts
- [docs/architecture/DESKTOP_ARCHITECTURE.md](docs/architecture/DESKTOP_ARCHITECTURE.md) — Tauri desktop boundaries
- [docs/architecture/NOTIFICATIONS_AND_PERMISSIONS.md](docs/architecture/NOTIFICATIONS_AND_PERMISSIONS.md) — RBAC and notifications

**Product surfaces ([product/](docs/product/))**
- [product/NAVIGATION.md](docs/product/NAVIGATION.md) — navigation model
- [product/INFORMATION_ARCHITECTURE.md](docs/product/INFORMATION_ARCHITECTURE.md) — desktop IA, app shell, routing, keyboard
- [product/SCREEN_INVENTORY.md](docs/product/SCREEN_INVENTORY.md) — screens and global surfaces
- [product/WORKSPACES.md](docs/product/WORKSPACES.md) — per-workspace specifications
- [product/GROUP_CHAT.md](docs/product/GROUP_CHAT.md) — first-class Group Chat
- [product/SEARCH_AND_COMMAND_PALETTE.md](docs/product/SEARCH_AND_COMMAND_PALETTE.md) — search and command palette
- [product/STATES.md](docs/product/STATES.md) — canonical UI state patterns

**Product surfaces — UX flows (Phase 1)**
- [product/USER_FLOWS.md](docs/product/USER_FLOWS.md) — core user flows (overview)
- [product/CHAT_FLOWS.md](docs/product/CHAT_FLOWS.md) — Direct Chat and Group Chat flows
- [product/PROJECT_TASK_FLOWS.md](docs/product/PROJECT_TASK_FLOWS.md) — project and task flows
- [product/DECISION_APPROVAL_FLOWS.md](docs/product/DECISION_APPROVAL_FLOWS.md) — decision, approval, and agent-run flows
- [product/AGENT_FLOWS.md](docs/product/AGENT_FLOWS.md) — agent profile, team, permission, and execution flows
- [product/WORKSPACE_FLOWS.md](docs/product/WORKSPACE_FLOWS.md) — remaining intelligence/operations/system workspace flows

## Language and themes

BroPS is trilingual at runtime — Armenian (hy), English (en), Russian (ru) — with first-class Dark and Light themes. See [DESIGN_SYSTEM.md](docs/architecture/DESIGN_SYSTEM.md).

## Contribution flow

Read [AGENTS.md](docs/AGENTS.md) first. Work on a branch, keep one source of truth per topic, record accepted changes as decisions in [DECISIONS.md](docs/DECISIONS.md), and never claim completion without evidence. Destructive or security-sensitive changes require explicit owner approval.

---

# BroPS — Հայերեն

**BroPS — Bro's Personal Space**-ը MenQ Studio-ի command-first AI Operating System-ն է։

BroPS-ը սովորական dashboard չէ։ Այն Gev-ի ամենօրյա աշխատանքային միջավայրն է, որտեղ նա աշխատում է Bro-ի և մասնագիտացված AI agent-ների թիմի հետ՝ chat-երի, project-ների, task-երի, knowledge-ի, memory-ի, decision-ների, approval-ների, file-երի, automation-ների և integration-ների միջոցով։

## Հիմնական սկզբունք

**Gev → Bro → BroPS → մասնագիտացված agent-ներ → վերահսկվող կատարում → ապացույց**

Bro-ն հիմնական interface-ն ու coordinator-ն է։ Մասնագիտացված agent-ները աշխատում են project-ի, permission-ի, approval-ի և evidence-ի հստակ սահմաններում։ Փաստաթղթերի ամբողջական ցանկը՝ վերևի Documentation index-ում։ Product-ը runtime-ում եռալեզու է՝ հայերեն, անգլերեն, ռուսերեն։
