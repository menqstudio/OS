# Database Schema Contract

BroPS uses SQLite in WAL mode with foreign keys enabled. Migrations are ordered, immutable SQL files.

## Tables

The migrations under `src-tauri/core/schema/` are the schema; this list is read off them (`grep -ohE "CREATE TABLE (IF NOT EXISTS )?[a-z_0-9]+" src-tauri/core/schema/*.sql`):

agent_bundle_active, agent_bundles, agents, approvals, audit_events, automation_runs, automations, conversation_participants, conversations, credential_bindings, decisions, demonstration_verified_messages, events, flow_receipts, flow_runs, governed_evidence_head_floor, governed_output_streams, governed_turn_acceptance, governed_turn_completion, governed_turn_outbox, governed_turn_staging, governed_turn_staging_chunk, governed_turn_staging_session, integrations, knowledge_notes, library_items, memory_entries, messages, notifications, projects, receipt_challenges, receipt_ids_seen, receipt_verification_attempts, receipt_verification_attempts_v16, research_items, run_steps, runs, scheduler_ticks, settings, store_write_records, task_dependencies, tasks, workspaces — plus the FTS5 table `search_index` and the `_migrations` ledger.

*(This section listed `users`, `commands`, `tool_calls`, `memories`, `file_records`, `knowledge_items` and `conversation_members`. None of them was ever created; the names that were are `memory_entries`, `knowledge_notes` and `conversation_participants`.)*

## Indexes

Read off the same files:

- tasks(project_id, status, updated_at)
- messages(conversation_id, created_at)
- runs(status, updated_at)
- run_steps(run_id, position)
- approvals(status, requested_at) and approvals(entity_id, status)
- notifications(read_at, created_at)
- audit_events(entity_type, entity_id, created_at)
- projects(workspace_id, status), conversations(kind, updated_at), decisions(status, updated_at), memory_entries(scope, updated_at), knowledge_notes(updated_at), library_items(updated_at), research_items(updated_at), events(starts_at), integrations(status), automation_runs(automation_id, ran_at), flow_runs(state, bundle_digest), task_dependencies(task_id), task_dependencies(depends_on_id)

*(The contract asked for `runs(command_id, created_at)`, `approvals(status, created_at)` and `knowledge_items(content_hash)`. No `command_id` or `content_hash` column exists.)*

## Integrity

Foreign keys are required. JSON columns store versioned envelopes. Secret values are never stored in SQLite; only secret references are stored. Full-text search is one standalone FTS5 table, `search_index` (migration `0010`), kept in step by triggers. Backups are transactionally consistent snapshots and include schema version metadata.

## Migration policy

Migrations MUST be forward-only. Destructive migrations require an export, backup verification and explicit owner approval. Application startup MUST refuse to open a database newer than the supported schema version. **Not implemented:** `db::migrate` (`src-tauri/core/src/db.rs`) skips the versions already applied and applies the missing ones, and never compares the database's highest applied version with `SCHEMA_VERSION` — that constant is read by nothing outside tests. An older binary opening a newer database is therefore not refused today.