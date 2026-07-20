# L-3 — Data integrity / correctness (6 items)

- **Severity:** Low ×6
- **Confidence:** High
- **Type:** Correctness, schema integrity
- **Status:** Proposed patches (read-only audit)
- **Shared-file note:** most touch `repo.rs` / `schema/` — coordinate with M-2/M-3/M-5/M-6.

## L-3a — `add_step` position race + no `UNIQUE(run_id, position)`
**Files:** `src-tauri/core/src/repo.rs:881-896`, `schema/0006_run_steps.sql`.
**Problem:** `MAX(position)+1` is computed outside a transaction and the schema has no uniqueness → concurrent adds duplicate positions → nondeterministic `ORDER BY position`.
**Fix:** `CREATE UNIQUE INDEX IF NOT EXISTS idx_run_steps_run_pos ON run_steps(run_id, position);` (new migration) + inline the insert (`INSERT ... SELECT ?, ?, COALESCE(MAX(position),0)+1, ... FROM run_steps WHERE run_id = ?`) or wrap in `BEGIN IMMEDIATE`.
**Accept:** [ ] two concurrent `add_step` calls can't produce duplicate positions.

## L-3b — `seed()` non-transactional; partial seed locks in forever
**Files:** `src-tauri/core/src/repo.rs:1410-1428`.
**Problem:** guard is `SELECT COUNT(*) FROM projects ... > 0 → return`, then ~60 inserts run with no transaction. A crash after the first insert makes every future launch skip the rest — app runs with agents but no conversations/runs, unrepairable.
**Fix:** wrap the whole body in `conn.unchecked_transaction()` with the COUNT guard inside it (`BEGIN IMMEDIATE`).
**Accept:** [ ] a failure mid-seed rolls back entirely; the guard stays accurate.

## L-3c — TOCTOU in `task_deps::add` → concurrent adds create a cycle
**Files:** `src-tauri/core/src/repo.rs:200-216`.
**Problem:** the recursive reachability check and the `INSERT OR IGNORE` are separate statements; concurrent `add(A,B)`/`add(B,A)` both pass the pre-insert check → create the A→B→A cycle the function promises to refuse.
**Fix:** do check + insert (+ audit) in one `unchecked_transaction()` (ideally `BEGIN IMMEDIATE`).
**Accept:** [ ] concurrent dependency adds cannot create a cycle.

## L-3d — No CHECK constraints on enum-like columns
**Files:** `src-tauri/core/schema/0001_initial.sql:29-30,42-43` (+ 0003:8,17; 0004:17-18; 0005:9,40; 0006:11).
**Problem:** `status`, `priority`, `kind`, `role` are free TEXT; validity is Rust-only. Any other write path (triggers, a future command, `set_step_result`'s hardcoded `'done'`) can store values outside the valid set → rows silently vanish from status-filtered queries.
**Fix:** add `CHECK (status IN (...))` (new migration, recreate or define on new tables) at least on `run_steps.status`, `runs.status`, `approvals.status`.
**Accept:** [ ] invalid enum values are rejected at the DB layer for the gated tables.

## L-3e — Swallowed errors: WAL pragma & `current_version`
**Files:** `src-tauri/core/src/db.rs:37`, `69-74`.
**Problem:** `let _ = conn.pragma_update(None,"journal_mode","WAL");` discards failure; `current_version` does `.unwrap_or(None)` → any error (I/O, corruption, locked) becomes version 0, so a corrupt DB reads as "needs migration".
**Fix:** log/inspect WAL result; propagate `current_version` errors (`query_row(...)?`), handling "table missing" explicitly for a legitimate pre-migration DB.
**Accept:** [ ] a query error in `current_version` surfaces as an error, not `0`.

## L-3f — `task_deps::remove` silent success + no audit
**Files:** `src-tauri/core/src/repo.rs:221-227`.
**Problem:** deletes without recording anything and returns `Ok(())` even on 0 rows changed; removing a blocker edge is a sensitive graph mutation yet leaves no audit trace.
**Fix:** `changed == 0 → CoreError::NotFound`; add `audit::record(conn, "task.dependency_removed", ...)` (in the same transaction per M-5).
**Accept:** [ ] removing a nonexistent edge errors; a successful removal writes an audit event.
