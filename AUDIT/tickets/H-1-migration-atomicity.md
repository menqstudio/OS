# H-1 — Migration runner is non-atomic → a mid-migration crash permanently bricks the DB

- **Severity:** High
- **Confidence:** High (verified in source)
- **Type:** Data durability / availability
- **Files:** `src-tauri/core/src/db.rs:42-67`
- **Status:** Proposed patch (read-only audit)

## Problem
`migrate()` runs, per version, `conn.execute_batch(sql)` and then a **separate** `INSERT INTO _migrations`, with **no enclosing transaction** (`execute_batch` does not wrap statements in one).

Two failure windows:
1. Crash / power-loss between the batch and the ledger insert.
2. Crash mid-batch in a multi-statement migration (0008 = 2×`ALTER TABLE` + index; 0010 = ~40 statements).

On next launch `is_applied()` returns false and the whole batch re-runs. `CREATE ... IF NOT EXISTS` is idempotent, but **`ALTER TABLE run_steps ADD COLUMN result ...` (0007) and the three `ALTER TABLE`s in 0008 are not** — re-execution fails with `"duplicate column name"`. Since `open()` calls `migrate()` on every startup, **the app then fails to open forever**. Unrecoverable without manual DB surgery.

## Fix
Wrap each version's DDL + ledger insert in one exclusive transaction (SQLite DDL is transactional):

```rust
for (version, sql) in [ /* ...MIGRATION_0001.. */ ] {
    if !is_applied(conn, version)? {
        conn.execute_batch("BEGIN IMMEDIATE;")?;
        let r = conn.execute_batch(sql).and_then(|_| conn.execute(
            "INSERT INTO _migrations(version, applied_at) VALUES (?1, ?2)",
            rusqlite::params![version, crate::now()]).map(|_| ()));
        match r {
            Ok(_)  => conn.execute_batch("COMMIT;")?,
            Err(e) => { let _ = conn.execute_batch("ROLLBACK;"); return Err(e.into()); }
        }
    }
}
```
`BEGIN IMMEDIATE` also serializes two processes racing the same migration.

## Acceptance criteria
- [ ] Each migration version's DDL and its `_migrations` insert commit atomically (all-or-nothing).
- [ ] Simulated failure: inject an error after `execute_batch(sql)` but before the ledger insert → after restart, `migrate()` succeeds (the failed version is rolled back and re-applied cleanly, no "duplicate column name").
- [ ] Full migrate on a fresh DB still reaches `SCHEMA_VERSION = 10`.
- [ ] Existing migration tests pass; add a test that runs `migrate()` twice and asserts idempotency.
