# BroPS Data Model

Status: Implementing

## Core entities

- User: owner identity, preferences, locale, theme.
- Workspace: bounded operating surface.
- Project: goal, state, participants, files, decisions and tasks.
- Task: actionable work item with owner, status, priority, due date and dependencies.
- Agent: specialist identity, capabilities, policy, model and runtime state.
- Conversation: direct or group thread containing messages and execution references.
- Message: immutable authored content with attachments and provenance.
- Command: normalized user intent submitted to Bro.
- Run: execution instance for a command or automation.
- Step: atomic run unit with input, output, status and evidence.
- ToolCall: requested external or local action.
- Approval: owner decision required before a protected action.
- Decision: durable accepted choice with rationale and consequences.
- Memory: reviewed personal or operational fact with source and retention class.
- KnowledgeItem: indexed document, note, URL or artifact.
- FileRecord: local file metadata, checksum and associations.
- Notification: user-facing event with read and action state.
- Automation: trigger, conditions, action plan and safety policy.
- AuditEvent: append-only record of material state changes.

## Relationships

A Project has many Tasks, Conversations, Decisions, Files and Runs. A Task may depend on other Tasks and may be assigned to a User or Agent. A Command creates zero or more Runs. A Run has ordered Steps and ToolCalls. Protected ToolCalls require an Approval. KnowledgeItems and Memories may be linked to Projects, Tasks, Conversations and Decisions. Every material mutation produces an AuditEvent.

## State rules

- IDs are UUIDv7 strings.
- Timestamps are UTC ISO-8601.
- User-authored records are never silently overwritten.
- Message, Decision and AuditEvent records are append-only; corrections create superseding records.
- Deletion defaults to soft delete and tombstones.
- Every external result stores provider, model/tool, request correlation and evidence references.
- Local database is authoritative for device state; sync is an optional later capability.

## Canonical enums

TaskStatus: inbox, planned, active, blocked, review, done, cancelled.
RunStatus: queued, planning, awaiting_approval, running, paused, succeeded, failed, cancelled.
ApprovalStatus: pending, approved, rejected, expired, revoked.
AgentStatus: offline, idle, thinking, working, blocked, error.
RiskLevel: low, medium, high, critical.

---

# Տվյալների մոդել

BroPS-ի հիմնական օբյեկտներն են օգտատերը, workspace-ը, նախագիծը, առաջադրանքը, գործակալը, զրույցը, հրամանը, run-ը, քայլը, tool call-ը, approval-ը, որոշումը, հիշողությունը, գիտելիքը, ֆայլը, notification-ը, automation-ը և audit event-ը։ Բոլոր կարևոր փոփոխությունները ապացուցելի են, append-only պատմություն ունեն և չեն վերագրվում լուռ կերպով։