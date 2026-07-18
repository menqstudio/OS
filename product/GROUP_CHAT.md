- **Purpose:** Define Group Chat as a first-class operating workspace for humans and agents.
- **Scope:** Room types, capabilities, Bro's room modes, message lifecycle, layout, and safety law. Trilingual product surface (HY/EN/RU).
- **Owner:** Gev.
- **Related:** [NAVIGATION.md](NAVIGATION.md), [SCREEN_INVENTORY.md](SCREEN_INVENTORY.md), [WORKSPACES.md](WORKSPACES.md), [SEARCH_AND_COMMAND_PALETTE.md](SEARCH_AND_COMMAND_PALETTE.md), [USER_FLOWS.md](USER_FLOWS.md), [../ARCHITECTURE.md](../ARCHITECTURE.md), [../DESIGN_SYSTEM.md](../DESIGN_SYSTEM.md).
- **Last updated:** 2026-07-19.

# Group Chat Specification

## Role

Group Chat is a first-class operating workspace, not a messaging add-on. It is where Gev, Bro, and specialist agents reason together, create work, make decisions, request approvals, and preserve shared context.

## Room types

- Direct: Gev + Bro
- Ad hoc group: temporary multi-agent conversation
- Team room: persistent functional room
- Project room: automatically linked to one project
- Review room: scoped architecture, design, security, or release review

## Required capabilities

- Agent mentions such as `@Forge` and `@Mason`
- Message replies and threads
- Files and linked knowledge
- Create task from message
- Create decision from message
- Request approval from message
- Pin messages, files, tasks, and decisions
- Room goal and operating instructions
- Room members and role permissions
- Room-scoped memory
- Automatic summaries
- Search and filters
- Agent live status
- Read receipts and execution states
- Full activity and audit history

## Bro's room modes

- Moderator: coordinates speakers and prevents duplication
- Router: assigns a question to the best agent
- Synthesizer: combines agent outputs into one recommendation
- Recorder: captures decisions, tasks, and unresolved questions
- Guardian: blocks unauthorized or risky actions

## Response controls

Each agent can be configured to:
- respond only when mentioned
- respond when its domain is relevant
- observe silently
- propose work without executing
- execute only within pre-approved scope

## Message lifecycle

Draft → Sent → Routed → Acknowledged → Working → Result posted → Evidence attached → Accepted or Reopened

## Core room layout

- Left: rooms and conversations
- Center: messages and threads
- Right: room context, members, files, tasks, decisions, approvals, and activity
- Composer: message, mention, file, command, task, decision, and approval actions

## Safety law

A chat message never silently grants unlimited authority. Execution authority comes only from explicit project permissions, agent scope, approval policy, and the specific request.

---

# Group Chat — Հայերեն

Group Chat-ը սովորական messenger չէ։ Այն Gev-ի, Bro-ի և agent-ների համատեղ աշխատանքային սենյակն է, որտեղ քննարկումը վերածվում է task-ի, decision-ի, approval-ի և evidence-ով ավարտված աշխատանքի։

Bro-ն կարող է լինել moderator, router, synthesizer, recorder և guardian։ Ոչ մի chat հաղորդագրություն ինքնուրույն անսահման permission չի տալիս։
