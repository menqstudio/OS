- **Purpose:** Define the user-facing sidebar and navigation projection of the BroPS system.
- **Scope:** Primary navigation groups, Home, Chat, project workspace, and task views. Trilingual product surface (HY/EN/RU).
- **Owner:** Gev.
- **Related:** [INFORMATION_ARCHITECTURE.md](INFORMATION_ARCHITECTURE.md), [SCREEN_INVENTORY.md](SCREEN_INVENTORY.md), [WORKSPACES.md](WORKSPACES.md), [GROUP_CHAT.md](GROUP_CHAT.md), [SEARCH_AND_COMMAND_PALETTE.md](SEARCH_AND_COMMAND_PALETTE.md), [USER_FLOWS.md](USER_FLOWS.md), [STATES.md](STATES.md), [../ARCHITECTURE.md](../ARCHITECTURE.md), [../DESIGN_SYSTEM.md](../DESIGN_SYSTEM.md).
- **Last updated:** 2026-07-19.

# BroPS Navigation

## Primary sidebar

### Core
- Home
- Chat
- Projects
- Tasks
- Agents

### Intelligence
- Knowledge
- Memory
- Decisions
- Research
- Library

### Operations
- Calendar
- Automations
- Approvals
- Activity
- Notifications

### System
- Files
- Integrations
- Analytics
- Security
- Settings

## Navigation law

The sidebar is not the product architecture. It is a user-facing projection of the system. Items may be pinned, collapsed, reordered, or hidden without changing the underlying domain model.

## Home

Home is the operational overview: priorities, active agents, approvals, blockers, upcoming events, system health, and a direct Bro command input.

## Chat

Chat contains:
- Direct Chat: Gev + Bro
- Group Chat: Gev + multiple agents
- Team Rooms: persistent collaboration spaces
- Project Rooms: chat bound to one project
- Threads, mentions, files, decisions, tasks, summaries, and approvals

## Project workspace

Every project contains:
- Overview
- Group Chat
- Tasks
- Files
- Knowledge
- Decisions
- Agents
- Timeline
- Activity
- Settings

## Task views

- Inbox
- Today
- Assigned to me
- Assigned to agents
- Waiting approval
- Blocked
- Recurring
- Completed

---

# Նավիգացիա

Sidebar-ը բաժանվում է չորս հիմնական խմբի՝ Core, Intelligence, Operations և System։ Chat-ը Home-ից հետո երկրորդ հիմնական բաժինն է։ Յուրաքանչյուր project ունի իր Group Chat-ը, task-երը, file-երը, knowledge-ը, decision-ները, agent-ները և activity timeline-ը։
