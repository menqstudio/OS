# BroPS Changelog

- **Purpose:** Record notable repository changes, most recent first.
- **Scope:** Documentation and, later, released application changes. Future work is in [ROADMAP.md](docs/ROADMAP.md).
- **Owner:** Gev.
- **Last updated:** 2026-07-19.

BroPS was intentionally recreated from zero; prior history is not part of this repository.

## 2026-07-19 — Phase 3 data core (SQLite) + Tauri scaffold

- Added `src-tauri/core` (`brops-core`): SQLite schema, forward-only migrations, and typed project/task/audit repositories. `cargo test -p brops-core` is GREEN (6 tests: migration idempotency, CRUD, foreign-key enforcement, validation, audit).
- Scaffolded the Tauri 2 host (`src-tauri/`): `AppState`, typed `#[tauri::command]` surface, `tauri.conf.json`, capabilities. The GUI binary build needs system webview libraries and is documented in `src-tauri/README.md` (not built in the authoring environment).

## 2026-07-19 — Phase 2 frontend prototype

- Running React + TypeScript + Vite prototype: app shell, command palette, all primary screens with mock data, trilingual HY/EN/RU switching, Dark/Light themes, semantic design tokens. `npm run build` is GREEN.
- Backend (Tauri/Rust/SQLite) deferred to Phase 3, marked as prototype rather than fake-working.

## 2026-07-19 — Reconciled implementation line

- Merged the `brops-v1-foundation-implementation` scaffold and deeper architecture docs (`docs/architecture/*`, `IMPLEMENTATION_EXECUTION_HANDOFF.md`, `MENQ_STUDIO_DESIGN_STANDARD_ADOPTION.md`) onto the canonicalized foundation without reintroducing the old flat docs.

## 2026-07-19 — Phase 1 UX architecture delivered

- Completed the Phase 1 UX flows (`product/`): information architecture, chat, project/task, decision/approval, agent, and remaining-workspace flows, plus canonical states. Roadmap Phase 1 exit condition met.

## 2026-07-19 — Foundation v1 Locked

- Marked Foundation v1 (Roadmap Phase 0) **Locked** after review, canonicalization, and the Phase 1 UX-architecture layer (decision D-010).
- Removed the transient `FOUNDATION_REVIEW.md` working artifact.

## 2026-07-19 — Phase 1 UX architecture

- Added `product/INFORMATION_ARCHITECTURE.md`, `product/CHAT_FLOWS.md`, `product/PROJECT_TASK_FLOWS.md`, `product/DECISION_APPROVAL_FLOWS.md`, and `product/STATES.md`.

## 2026-07-19 — Foundation canonicalized

- Consolidated 35 flat root documents into one source of truth per topic.
- Merged `MISSION` + `VISION` + `PRODUCT_SCOPE` into `PROJECT_CONTEXT.md`.
- Merged `PRINCIPLES` + `LAWS` into `PRINCIPLES.md` (laws keep IDs L-001..L-012).
- Merged `DECISIONS` + `DECISION_RECORDS` into `DECISIONS.md`.
- Merged `DESIGN_SYSTEM` + `LOCALIZATION_AND_THEMES` into `DESIGN_SYSTEM.md` (MenQ Studio Design Standards).
- Merged the orchestrator, multi-agent runtime, personas, the five engines, event system, tool execution, and approval model into `AI_RUNTIME.md`.
- Moved UX/product-surface specs into `product/` (NAVIGATION, SCREEN_INVENTORY, WORKSPACES, GROUP_CHAT, SEARCH_AND_COMMAND_PALETTE, USER_FLOWS).
- Retired `NEXT_CHAT.md`; added `CHANGELOG.md`.
- Added a documentation index and `Purpose/Scope/Owner/Related/Last updated` headers to canonical docs.
- Resolved the language-scope contradiction: the product is trilingual **HY/EN/RU** (decision D-009 supersedes the bilingual wording of D-007).

## Foundation v1 (Draft)

- Established product identity, mission, vision, scope, principles, and laws.
- Defined product architecture, the AI runtime model, navigation, first-class Group Chat, the agent model, and design direction.
- Recorded the initial accepted decisions and the phased roadmap.
