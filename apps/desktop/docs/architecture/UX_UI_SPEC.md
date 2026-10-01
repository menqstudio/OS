# BroPS UX/UI Specification

## Global states
Every workspace MUST define the canonical states in [product/STATES.md](../product/STATES.md). (This line listed seven of its own — loading, empty, ready, error, offline, permission-denied, destructive-confirmation — where `ready` is what STATES.md calls `populated`.)

## Core shell
- Left navigation: the 23 items listed in [product/NAVIGATION.md](../product/NAVIGATION.md). (This line listed 14.)
- Header: workspace title, global search, notifications, language switcher (HY/EN/RU), theme switcher (Dark/Light), profile.
- Right context drawer: selected entity context, linked tasks, files, decisions and activity.

## Workspace component contract
Each page MUST expose: primary action, filters, sort, view switcher where relevant, state feedback, keyboard focus order, responsive collapse rules and audit-visible actions.

## Responsive rules

> **Not reconciled:** three breakpoint tables exist and disagree — [INFORMATION_ARCHITECTURE.md §3](../product/INFORMATION_ARCHITECTURE.md) (1440 / 1200 / 1024 / 768), [UX_UI_SPEC.md](UX_UI_SPEC.md) (1280 / 900 / 640) and [DETAILED_UX_UI_SPEC.md](../product/DETAILED_UX_UI_SPEC.md) (900 and 800) — and the stylesheet follows none of them: its `@media` queries use literal widths (560, 1080, 720, 820, 1040, 900, 860 and others), not tokens. Which table is the target has not been decided.

- >=1280px: full navigation + optional right drawer.
- 900-1279px: compact navigation; right drawer overlays.
- 640-899px: icon rail; dense tables become cards.
- <640px: stacked layout; secondary panels become sheets.

## Page-level requirements
Home: command composer, priorities, active runs, approvals, recent work.
Command: intent input, execution plan, tool status, approval gate, result timeline.
Chat/Group Chat: room list, thread, participants/agents, attachments, execution references.
Projects: list/board, project health, linked tasks/files/decisions.
Tasks: list/board/calendar views, dependency and priority indicators.
Agents: cards, capabilities, availability, provider/model, permissions and run history.
Knowledge/Memory: search, filters, source/provenance, confidence and retention controls.
Files: local file browser, preview, tags, links, import/export.
Calendar: month/week/agenda, task and automation overlays.
Automations: trigger, conditions, actions, approval policy, run logs.
Analytics: KPIs, costs, latency, success/error rates, agent and workspace breakdowns.
Settings: profile, languages, themes, providers, storage, security, backup and accessibility.

## Motion and accessibility
Transitions 160-240ms; data visualization 600-900ms; KPI count-up ~800ms. Respect reduced motion. WCAG-oriented contrast, visible focus, full keyboard navigation and screen-reader labels are required.
