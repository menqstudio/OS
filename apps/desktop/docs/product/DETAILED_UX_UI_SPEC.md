# Detailed UX/UI Specification

Status: Implementing

## Global shell

Desktop-first application shell with collapsible navigation, top context bar, central workspace, optional right context drawer, command composer and notification center. All screens support Armenian, English and Russian plus dark and light themes.

## Mandatory states for every screen

The canonical set is the ten states in [STATES.md](STATES.md). This line's own list — loading, empty, ready, filtered-empty, offline, degraded, permission-denied, error, destructive-confirmation and success-feedback — names `ready` for `populated` and `success-feedback` for `success`; `filtered-empty` is a sub-pattern of `empty` there, and `degraded` is defined nowhere in STATES.md. Async actions expose queued, running, awaiting-approval, paused, succeeded, failed and cancelled states.

> **Breakpoints are not reconciled:** three breakpoint tables exist and disagree — [INFORMATION_ARCHITECTURE.md §3](INFORMATION_ARCHITECTURE.md) (1440 / 1200 / 1024 / 768), [UX_UI_SPEC.md](../architecture/UX_UI_SPEC.md) (1280 / 900 / 640) and [DETAILED_UX_UI_SPEC.md](DETAILED_UX_UI_SPEC.md) (900 and 800) — and the stylesheet follows none of them: its `@media` queries use literal widths (560, 1080, 720, 820, 1040, 900, 860 and others), not tokens. Which table is the target has not been decided.

## Workspace contracts

### Home
Components: daily briefing, active projects, urgent tasks, pending approvals, recent runs, agent status, quick command.
Responsive: cards collapse from multi-column to one column; command remains primary.

### Command
Components: command composer, attachments, context chips, plan preview, approval gates, live run timeline, evidence drawer, retry/cancel controls.
States: draft, interpreting, planned, awaiting approval, executing, completed, failed.

### Chat and Group Chat
Components: room list, thread header, participant/agent status, messages, citations, attachments, tool activity, composer.
Responsive: room list becomes a drawer below 900px.

### Projects
Components: project list, overview, goals, tasks, files, decisions, conversations, agents, activity.
States: active, archived, blocked and completed projects.

### Tasks
Components: inbox/list/board views, filters, task detail drawer, dependencies, assignee, due date, evidence and linked run.
Responsive: board becomes grouped vertical lists below 800px.

### Agents
Components: agent gallery, capability filters, status, model/provider, permissions, budget, prompt/version, run history and test panel.

### Knowledge
Components: source list, collections, search, ingestion state, chunk preview, citations, indexing errors and retention controls.

### Memory
Components: proposed memories, accepted memories, source, confidence, scope, retention, edit/supersede/delete controls.

### Files
Components: browser, recent files, project links, preview, checksum, import/export and protected delete.

### Calendar
Components: agenda, week/month, linked tasks, automation triggers and event detail.

### Automations
Components: trigger builder, condition builder, action plan, approval policy, run history, dry-run and enable switch.

### Analytics
Components: workload, completion, run quality, cost, latency, agent performance and audit filters. Charts animate but never conceal exact values.

### Settings
Components: language, theme, profile, providers, secrets, storage, backup, permissions, notifications, accessibility and diagnostics.

## Component rules

All styling uses semantic tokens. Keyboard navigation and visible focus are mandatory. Touch targets are at least 40px. Reduced-motion is respected. No critical state is communicated by color alone. Destructive actions require explicit wording and cannot use ambiguous primary buttons.