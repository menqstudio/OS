- **Purpose:** Specify global search and the keyboard-first command palette surface.
- **Scope:** Search coverage, result fields, filters, palette actions, and safety rules. Trilingual product surface (HY/EN/RU).
- **Owner:** Gev.
- **Related:** [NAVIGATION.md](NAVIGATION.md), [SCREEN_INVENTORY.md](SCREEN_INVENTORY.md), [WORKSPACES.md](WORKSPACES.md), [GROUP_CHAT.md](GROUP_CHAT.md), [USER_FLOWS.md](USER_FLOWS.md), [../ARCHITECTURE.md](../ARCHITECTURE.md), [../DESIGN_SYSTEM.md](../DESIGN_SYSTEM.md).
- **Last updated:** 2026-07-19.

# Search and Command Palette / Որոնում և հրամանների պալիտրա

Status: Draft canonical

## Global Search / Համընդհանուր որոնում

Search MUST cover projects, tasks, chats, group rooms, agents, files, decisions, knowledge, memory, automations, approvals, and activity.

Որոնումը ՊԵՏՔ Է ընդգրկի նախագծերը, առաջադրանքները, զրույցները, խմբային սենյակները, ագենտները, ֆայլերը, որոշումները, գիտելիքը, հիշողությունը, ավտոմատացումները, հաստատումները և գործունեությունը։

Each result MUST show type, title, context, owner or source, updated time, and permission status.

## Filters / Ֆիլտրեր

- Object type
- Project
- Owner
- Agent
- Date range
- Status
- Source
- Tag
- Permission scope

## Command Palette / Հրամանների պալիտրա

Keyboard-first global surface, opened with Ctrl/Cmd+K.

Supported actions:

- Navigate to any workspace
- Create project, task, room, decision, automation, or note
- Ask Bro
- Run safe command
- Open approval queue
- Switch language or theme
- Search recent objects
- Open agent or project context

## Safety Rules / Անվտանգության կանոններ

The palette may initiate a protected action but MUST NOT bypass the approval model.

Պալիտրան կարող է սկսել պաշտպանված գործողություն, բայց ՉՊԵՏՔ Է շրջանցի հաստատման մոդելը։
