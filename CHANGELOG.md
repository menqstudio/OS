# BroPS Changelog

- **Purpose:** Record notable repository changes, most recent first.
- **Scope:** Documentation and, later, released application changes. Future work is in [ROADMAP.md](ROADMAP.md).
- **Owner:** Gev.
- **Last updated:** 2026-07-19.

BroPS was intentionally recreated from zero; prior history is not part of this repository.

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
