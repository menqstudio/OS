# Database Schema Contract

BroPS uses SQLite in WAL mode with foreign keys enabled. Migrations are ordered, immutable SQL files.

## Tables

users, workspaces, projects, tasks, task_dependencies, agents, conversations, conversation_members, messages, commands, runs, run_steps, tool_calls, approvals, decisions, memories, knowledge_items, file_records, notifications, automations, audit_events, settings.

## Required indexes

- tasks(project_id, status, updated_at)
- messages(conversation_id, created_at)
- runs(command_id, created_at)
- approvals(status, created_at)
- notifications(read_at, created_at)
- audit_events(entity_type, entity_id, created_at)
- knowledge_items(content_hash)

## Integrity

Foreign keys are required. JSON columns store versioned envelopes. Secret values are never stored in SQLite; only secret references are stored. Full-text search uses FTS5 shadow tables for messages, knowledge and decisions. Backups are transactionally consistent snapshots and include schema version metadata.

## Migration policy

Migrations MUST be forward-only. Destructive migrations require an export, backup verification and explicit owner approval. Application startup MUST refuse to open a database newer than the supported schema version.