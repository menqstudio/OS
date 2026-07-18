# BroPS

**BroPS — Bro's Personal Space** is MenQ Studio's command-first AI Operating System.

BroPS is not a generic dashboard. It is the daily operating environment where Gev works with Bro and a coordinated team of specialist AI agents across conversations, projects, tasks, knowledge, memory, decisions, approvals, files, automations, and integrations.

## Product principle

**Gev → Bro → BroPS → specialist agents → controlled execution → evidence**

Bro is the primary interface and coordinator. Specialist agents work inside explicit project, permission, approval, and evidence boundaries.

## Foundation status

- Foundation v1: **Locked** (2026-07-19) — see decision D-010
- Phase 2 interactive prototype: **frontend running** (React + TypeScript + Vite, mock data)
- Phase 3 data core: **SQLite schema + migrations + repositories tested** (`cargo test -p brops-core`, 6 tests GREEN)
- Tauri desktop host: scaffolded (`src-tauri/`); GUI binary build needs system webview libs — see [src-tauri/README.md](src-tauri/README.md)

## Run the prototype

```bash
npm install
npm run dev        # http://localhost:1420
npm run build      # typecheck + production build
```

The prototype is the frontend app shell: left navigation, top bar, command palette (⌘/Ctrl-K), all primary screens with mock data, trilingual runtime switching (HY/EN/RU), and Dark/Light themes. It uses in-memory mock data — no backend is connected yet. Features that need the desktop backend are visibly marked as prototype rather than shown as working.

## Documentation index

**Product & governance**
- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — identity, mission, vision, scope, users, constraints
- [PRINCIPLES.md](PRINCIPLES.md) — principles and enforceable laws (L-001..L-012)
- [TERMINOLOGY.md](TERMINOLOGY.md) — glossary
- [DECISIONS.md](DECISIONS.md) — decision format and log
- [ROADMAP.md](ROADMAP.md) — phased future work
- [SUCCESS_CRITERIA.md](SUCCESS_CRITERIA.md) — MVP definition of done
- [CHANGELOG.md](CHANGELOG.md) — repository history
- [AGENTS.md](AGENTS.md) — contributor working contract

**System**
- [ARCHITECTURE.md](ARCHITECTURE.md) — domains, entities, execution model
- [AI_RUNTIME.md](AI_RUNTIME.md) — orchestrator, agents, engines, events, tools, approvals
- [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) — MenQ Studio Design Standards (visual system, trilingual i18n, themes)

**Implementation contracts**
- [src-tauri/README.md](src-tauri/README.md) — desktop host + tested SQLite data core
- [IMPLEMENTATION_EXECUTION_HANDOFF.md](IMPLEMENTATION_EXECUTION_HANDOFF.md) — full build contract (React/Tauri/Rust/SQLite)
- [MENQ_STUDIO_DESIGN_STANDARD_ADOPTION.md](MENQ_STUDIO_DESIGN_STANDARD_ADOPTION.md) — design-token adoption rules
- [docs/architecture/DATA_MODEL.md](docs/architecture/DATA_MODEL.md) — entities, enums, state rules
- [docs/architecture/DATABASE_SCHEMA.md](docs/architecture/DATABASE_SCHEMA.md) — SQLite schema contract
- [docs/architecture/AI_RUNTIME_CONTRACTS.md](docs/architecture/AI_RUNTIME_CONTRACTS.md) — provider/model/prompt/run contracts
- [docs/architecture/DESKTOP_ARCHITECTURE.md](docs/architecture/DESKTOP_ARCHITECTURE.md) — Tauri desktop boundaries
- [docs/architecture/NOTIFICATIONS_AND_PERMISSIONS.md](docs/architecture/NOTIFICATIONS_AND_PERMISSIONS.md) — RBAC and notifications

**Product surfaces ([product/](product/))**
- [product/NAVIGATION.md](product/NAVIGATION.md) — navigation model
- [product/INFORMATION_ARCHITECTURE.md](product/INFORMATION_ARCHITECTURE.md) — desktop IA, app shell, routing, keyboard
- [product/SCREEN_INVENTORY.md](product/SCREEN_INVENTORY.md) — screens and global surfaces
- [product/WORKSPACES.md](product/WORKSPACES.md) — per-workspace specifications
- [product/GROUP_CHAT.md](product/GROUP_CHAT.md) — first-class Group Chat
- [product/SEARCH_AND_COMMAND_PALETTE.md](product/SEARCH_AND_COMMAND_PALETTE.md) — search and command palette
- [product/STATES.md](product/STATES.md) — canonical UI state patterns

**Product surfaces — UX flows (Phase 1)**
- [product/USER_FLOWS.md](product/USER_FLOWS.md) — core user flows (overview)
- [product/CHAT_FLOWS.md](product/CHAT_FLOWS.md) — Direct Chat and Group Chat flows
- [product/PROJECT_TASK_FLOWS.md](product/PROJECT_TASK_FLOWS.md) — project and task flows
- [product/DECISION_APPROVAL_FLOWS.md](product/DECISION_APPROVAL_FLOWS.md) — decision, approval, and agent-run flows
- [product/AGENT_FLOWS.md](product/AGENT_FLOWS.md) — agent profile, team, permission, and execution flows
- [product/WORKSPACE_FLOWS.md](product/WORKSPACE_FLOWS.md) — remaining intelligence/operations/system workspace flows

## Language and themes

BroPS is trilingual at runtime — Armenian (hy), English (en), Russian (ru) — with first-class Dark and Light themes. See [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md).

## Contribution flow

Read [AGENTS.md](AGENTS.md) first. Work on a branch, keep one source of truth per topic, record accepted changes as decisions in [DECISIONS.md](DECISIONS.md), and never claim completion without evidence. Destructive or security-sensitive changes require explicit owner approval.

---

# BroPS — Հայերեն

**BroPS — Bro's Personal Space**-ը MenQ Studio-ի command-first AI Operating System-ն է։

BroPS-ը սովորական dashboard չէ։ Այն Gev-ի ամենօրյա աշխատանքային միջավայրն է, որտեղ նա աշխատում է Bro-ի և մասնագիտացված AI agent-ների թիմի հետ՝ chat-երի, project-ների, task-երի, knowledge-ի, memory-ի, decision-ների, approval-ների, file-երի, automation-ների և integration-ների միջոցով։

## Հիմնական սկզբունք

**Gev → Bro → BroPS → մասնագիտացված agent-ներ → վերահսկվող կատարում → ապացույց**

Bro-ն հիմնական interface-ն ու coordinator-ն է։ Մասնագիտացված agent-ները աշխատում են project-ի, permission-ի, approval-ի և evidence-ի հստակ սահմաններում։ Փաստաթղթերի ամբողջական ցանկը՝ վերևի Documentation index-ում։ Product-ը runtime-ում եռալեզու է՝ հայերեն, անգլերեն, ռուսերեն։
