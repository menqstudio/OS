# BroPS Foundation v1 — Critical Review & Canonicalization Plan

- **Purpose:** Record the gap review of Foundation v1 and the target canonical structure that Phase 2 executes.
- **Status:** Working review (removed or archived once canonicalization is merged).
- **Owner:** Gev.
- **Reviewed:** 2026-07-19. Baseline: 35 root Markdown documents, Foundation v1 (Draft).

## 1. Verdict

Foundation v1 is strong in intent but organized as a **documentation library**: 35 flat root files, several describing the same topic in different framings. There is no single source of truth per topic, one real contradiction, and no documentation index. This is exactly what the canonicalization mandate targets.

## 2. Contradiction (RED — must resolve)

**Language scope disagrees across canonical docs.**

- Bilingual (HY/EN): `PROJECT_CONTEXT.md` law 6, `PRINCIPLES.md` 11, `AGENTS.md`, `DECISION_RECORDS.md` D-007 ("Armenian and English have equal product status").
- Trilingual (HY/EN/RU): `DESIGN_SYSTEM.md`, `LOCALIZATION_AND_THEMES.md` (Status: Draft canonical, six-combo acceptance gate), and the two most recent commits `f0531ac docs: lock trilingual UI` and `3e9a17b docs: add canonical localization`.

**Resolution (evidence-based):** the newest explicit decision wins. Russian is in scope → **trilingual HY/EN/RU is canonical**. All bilingual references are stale and will be updated to trilingual. Recorded as a new decision (D-009) superseding the bilingual wording of D-007.

## 3. Duplication / overlap map

| Overlapping set | Problem | Action |
|---|---|---|
| `MISSION` · `VISION` · `PROJECT_CONTEXT` · `PRODUCT_SCOPE` | 4 docs, same product framing | merge → `PROJECT_CONTEXT.md` |
| `PRINCIPLES` (14) · `LAWS` (12) | same values, two framings | merge → `PRINCIPLES.md` (principles + enforceable laws L-001..L-012) |
| `DECISIONS` (log) · `DECISION_RECORDS` (format) | split decision truth | merge → `DECISIONS.md` (format + log) |
| `DESIGN_SYSTEM` · `LOCALIZATION_AND_THEMES` | design + i18n split | merge → `DESIGN_SYSTEM.md` ("MenQ Studio Design Standards") |
| `BRO_ORCHESTRATOR` · `MULTI_AGENT_RUNTIME` · `COMMAND_ENGINE` · `DECISION_ENGINE` · `CONTEXT_ENGINE` · `KNOWLEDGE_ENGINE` · `MEMORY_ENGINE` · `EVENT_SYSTEM` · `TOOL_EXECUTION` · `APPROVAL_MODEL` · `AGENTS_SPEC` · `PERSONAS` | 12 docs, one runtime | merge → `AI_RUNTIME.md` (sectioned) |
| `NEXT_CHAT` | session handoff notes | retire → content into README/ROADMAP/CHANGELOG |

## 4. Target canonical structure

**Root — product & governance truth**
- `README.md` — entry point + documentation index + status
- `PROJECT_CONTEXT.md` — identity, mission, vision, scope (in/out), users, constraints
- `PRINCIPLES.md` — principles + enforceable laws (L-001..L-012)
- `TERMINOLOGY.md` — glossary
- `ARCHITECTURE.md` — domains, entities, execution model, state separation
- `AI_RUNTIME.md` — Bro orchestrator, agents, personas, command/decision/context/knowledge/memory engines, events, tool execution, approvals
- `DESIGN_SYSTEM.md` — MenQ Studio Design Standards (visual system + trilingual i18n + dark/light)
- `DECISIONS.md` — decision format + log
- `ROADMAP.md` — phased future work
- `SUCCESS_CRITERIA.md` — MVP definition of done
- `CHANGELOG.md` — foundation history (new)
- `AGENTS.md` — contributor/agent working contract (reading order, working laws)

**`product/` — UX / product-surface specs (expanded in Phase 3)**
- `product/NAVIGATION.md`
- `product/SCREEN_INVENTORY.md`
- `product/WORKSPACES.md`
- `product/GROUP_CHAT.md`
- `product/SEARCH_AND_COMMAND_PALETTE.md`
- `product/USER_FLOWS.md`

Every canonical doc carries a `Purpose / Scope / Owner / Related / Last updated` header, cross-links related docs, and preserves HY/EN (and, where user-facing, HY/EN/RU) meaning parity.

## 5. Deliberately NOT created

Per "only document real architecture": no `DATA_MODEL.md` (no schema designed yet — the entity list stays in ARCHITECTURE; the concrete SQLite model is a Phase 3/4 deliverable) and no `IMPLEMENTATION.md` (no application code yet — `AGENTS.md` is the working contract until Phase 3). Both are tracked as ROADMAP items.

## 6. Net effect

35 flat root docs → 12 root canonical docs + 6 organized `product/` specs (18 total), one source of truth per topic, contradiction resolved, indexed, cross-linked.
