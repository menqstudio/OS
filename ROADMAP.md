# BroPS Roadmap

- **Purpose:** Track phased future work from foundation to deployment.
- **Scope:** Future work only. Shipped changes are in [CHANGELOG.md](CHANGELOG.md); acceptance is in [SUCCESS_CRITERIA.md](SUCCESS_CRITERIA.md).
- **Owner:** Gev.
- **Related:** [SUCCESS_CRITERIA.md](SUCCESS_CRITERIA.md), [ARCHITECTURE.md](ARCHITECTURE.md), [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md), [DECISIONS.md](DECISIONS.md).
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

Status: Frontend prototype running (React + TypeScript + Vite; app shell, all primary screens, mock data, HY/EN/RU, Dark/Light). Backend deferred to Phase 3.

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

- React + TypeScript frontend
- Tauri desktop shell
- Token-based design system
- Trilingual (HY/EN/RU) runtime switching
- Local application state and persistence
- **`DATA_MODEL.md`** — concrete persisted schema (tables, keys, indexes, migrations)
- **`IMPLEMENTATION.md`** — coding standards and the single implementation contract
- Test and CI baseline

## Phase 4 — Core runtime

- Real chat and room persistence
- Project/task/decision/approval data model
- Agent orchestration contracts
- File and knowledge indexing
- Activity and evidence system
- Security and permission enforcement

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
