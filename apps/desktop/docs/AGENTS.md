# BroPS Agent Working Instructions

- **Purpose:** The working contract for any human or AI contributor to BroPS.
- **Scope:** How to work in this repository. Product truth lives in the canonical docs below.
- **Owner:** Gev.
- **Related:** [README.md](../README.md), [PRINCIPLES.md](PRINCIPLES.md), [AI_RUNTIME.md](architecture/AI_RUNTIME.md), [DECISIONS.md](DECISIONS.md).
- **Last updated:** 2026-07-22.

Before substantive work, read in this order:

1. `README.md`
2. `PROJECT_CONTEXT.md`
3. `PRINCIPLES.md`
4. `TERMINOLOGY.md`
5. `ARCHITECTURE.md`
6. `AI_RUNTIME.md`
7. `DESIGN_SYSTEM.md`
8. `product/NAVIGATION.md` and the rest of `product/`
9. `DECISIONS.md`
10. `ROADMAP.md`
11. `SUCCESS_CRITERIA.md`

## Working laws

- Never report completion without direct evidence.
- Do not treat chat memory as canonical truth when repository documents exist.
- Preserve documentation meaning parity across languages; the product runtime is trilingual (HY/EN/RU).
- Record accepted architecture or product changes in canonical documentation via a decision in `DECISIONS.md`.
- Keep one source of truth per topic — extend or reference a canonical doc rather than creating a competing one.
- Do not implement infrastructure before the product and UX model are ready.
- Use branches and pull requests for substantive changes; destructive or security-sensitive work requires explicit owner approval.

## Current focus

> **These are BroPS-desktop-internal working instructions.** The desktop app is fully built (real Tauri/SQLite backend; see [CHANGELOG.md](../CHANGELOG.md)); since the monorepo merge into `menqstudio/OS`, active work is the **OS-level security-remediation track**. For the exact current branch / PR / blockers / next action, read the **root** [`NEXT_CHAT.md`](../../../NEXT_CHAT.md) → `CLAUDE.md` → `PROJECT_STATE.md` → `TASKS.md` (the OS-root canon governs; this file is for desktop product/UX conventions).

Historical: Foundation v1 is **Locked** (D-010); the Phase 1 UX architecture under `product/` was delivered and the app was built out through its internal phases.
