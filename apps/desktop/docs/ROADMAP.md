# BroPS Roadmap

- **Purpose:** Track phased future work from foundation to deployment.
- **Scope:** Future work only. Shipped changes are in [CHANGELOG.md](../CHANGELOG.md); acceptance is in [SUCCESS_CRITERIA.md](SUCCESS_CRITERIA.md).
- **Owner:** Gev.
- **Related:** [SUCCESS_CRITERIA.md](SUCCESS_CRITERIA.md), [ARCHITECTURE.md](architecture/ARCHITECTURE.md), [DESIGN_SYSTEM.md](architecture/DESIGN_SYSTEM.md), [DECISIONS.md](DECISIONS.md).
- **Last updated:** 2026-07-19.

## Phase 0 — Foundation

Status: Locked (2026-07-19) — see decision D-010

- Product identity and vision
- Canonical laws and decision log
- Navigation model
- Group Chat specification
- Agent model
- Product architecture
- Design-system direction
- Documentation canonicalized to one source of truth per topic

Exit condition: foundation reviewed and marked Locked.

## Phase 1 — UX architecture

Status: Delivered (2026-07-19) — every MVP capability has a defined user flow in `product/` (IA, chat, project/task, decision/approval, agent, remaining-workspace flows, and canonical states).

- Full information architecture
- User journeys
- Screen inventory
- Group Chat flows
- Project workspace flows
- Task, decision, approval, and agent flows
- Empty, loading, error, offline, and permission states

Exit condition: every MVP capability has a defined user flow. ✓

## Phase 2 — Interactive product prototype

Status: Delivered (2026-07-19) — the clickable shell shipped, then the mock layer was removed once the real backend landed (Phase 3). App shell, all primary screens, HY/EN/RU, Dark/Light.

- Application shell
- Home and Command
- Direct Chat and Group Chat
- Projects and Tasks
- Agents
- Knowledge, Memory, and Decisions
- Approvals, Activity, and Notifications
- Responsive behavior and motion

Exit condition: complete clickable prototype with no dead-end primary flows.

## Phase 3 — Application foundation

Status: Delivered (2026-07-19) — the desktop app runs on a real backend; the mock layer is gone. Schema at **v13**, `cargo test -p brops-core` GREEN (**68 tests**), CI green. *(Schema/test counts have since grown with the OS-monorepo security-remediation waves — see the root [`NEXT_CHAT.md`](../../../NEXT_CHAT.md).)*

- React + TypeScript frontend ✓ (Phase 2)
- **SQLite data core** ✓ — `src-tauri/core` schema (13 migrations), typed repositories, 68 tests
- **Tauri desktop shell** ✓ — GUI binary builds and runs; typed IPC boundary (`src/services/desktop.ts`), no mock layer
- Token-based design system ✓ · Trilingual (HY/EN/RU) runtime switching ✓
- Concrete persisted schema ✓ — `docs/architecture/DATA_MODEL.md` + `docs/architecture/DATABASE_SCHEMA.md`
- CI ✓ (GitHub Actions: frontend + data-core + desktop-build)
- Remaining: secure store, backup/restore, Windows CI runner

## Phase 4 — Core runtime

Status: Largely delivered (2026-07-19) — see the Phases 4–20 entry in [CHANGELOG.md](../CHANGELOG.md).

- Real chat and room persistence ✓ (streaming Chat/Group Chat, delete/rename)
- Project/task/decision/approval data model ✓ (incl. task dependencies, approval gating that actually blocks execution)
- Agent orchestration contracts ✓ (live AI via local `claude` CLI; runs execute step-by-step)
- File and knowledge indexing ✓ (Files view/edit; global FTS5 search + palette deep-links)
- Activity and evidence system ✓ (audit trail, run results persisted)
- Security and permission enforcement — partial (approvals + audit; filesystem confinement still open)

## Phase 5 — Integrations

- GitHub
- Gmail
- Google Calendar
- Google Drive
- Local filesystem
- Additional communication channels

## Phase 6 — Debian AI server

- Deployment architecture
- Database and object storage
- Model gateway and optional local models
- Queue and background workers
- Monitoring, backups, recovery, and secure remote access

---

# Ճանապարհային քարտեզ

Սկզբում lock ենք անում product foundation-ը և UX-ը, հետո ստեղծում ենք ամբողջական interactive prototype, դրանից հետո միայն production app-ը (React + TypeScript + Tauri, trilingual HY/EN/RU) և վերջում Debian AI server-ը։ `DATA_MODEL.md` և `IMPLEMENTATION.md` canonical ֆայլերը ստեղծվում են Phase 3-ում, երբ սկսվում է իրական կոդը։
