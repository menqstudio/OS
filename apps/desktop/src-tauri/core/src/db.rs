//! Connection setup and forward-only migrations.

use crate::domain::CoreResult;
use rusqlite::Connection;
use std::time::Duration;

const MIGRATION_0001: &str = include_str!("../schema/0001_initial.sql");
const MIGRATION_0002: &str = include_str!("../schema/0002_decisions.sql");
const MIGRATION_0003: &str = include_str!("../schema/0003_conversations.sql");
const MIGRATION_0004: &str = include_str!("../schema/0004_knowledge_memory.sql");
const MIGRATION_0005: &str = include_str!("../schema/0005_operations.sql");
const MIGRATION_0006: &str = include_str!("../schema/0006_run_steps.sql");
const MIGRATION_0007: &str = include_str!("../schema/0007_run_step_result.sql");
const MIGRATION_0008: &str = include_str!("../schema/0008_approval_gating.sql");
const MIGRATION_0009: &str = include_str!("../schema/0009_task_dependencies.sql");
const MIGRATION_0010: &str = include_str!("../schema/0010_search_fts.sql");
const MIGRATION_0011: &str = include_str!("../schema/0011_constraints.sql");
const MIGRATION_0012: &str = include_str!("../schema/0012_approval_provenance.sql");
pub const SCHEMA_VERSION: i64 = 12;

/// Open a database file with foreign keys and WAL enabled, and migrate it.
pub fn open(path: &str) -> CoreResult<Connection> {
    let conn = Connection::open(path)?;
    configure(&conn)?;
    migrate(&conn)?;
    Ok(conn)
}

/// Open an in-memory database (used by tests), migrated.
pub fn open_in_memory() -> CoreResult<Connection> {
    let conn = Connection::open_in_memory()?;
    configure(&conn)?;
    migrate(&conn)?;
    Ok(conn)
}

fn configure(conn: &Connection) -> CoreResult<()> {
    conn.pragma_update(None, "foreign_keys", "ON")?;
    // WAL allows one writer at a time; without a busy handler a second
    // connection surfaces an instant SQLITE_BUSY mid-operation instead of
    // waiting its turn.
    conn.busy_timeout(Duration::from_secs(5))?;
    // `PRAGMA journal_mode = WAL` reports the mode actually in effect: files
    // report "wal", in-memory databases legitimately stay on "memory".
    // Anything else means WAL was refused — SQLite keeps working on a
    // rollback journal, so continue, but say so instead of swallowing it.
    let mode: String = conn.pragma_update_and_check(None, "journal_mode", "WAL", |row| row.get(0))?;
    if !mode.eq_ignore_ascii_case("wal") && !mode.eq_ignore_ascii_case("memory") {
        eprintln!("db: journal_mode=WAL not applied (database reports '{mode}')");
    }
    Ok(())
}

/// Forward-only, idempotent migration runner.
///
/// Each version's DDL and its `_migrations` ledger row commit in a single
/// exclusive transaction, so a crash mid-migration rolls the whole version
/// back and it re-applies cleanly on the next launch — non-idempotent
/// statements (the `ALTER TABLE`s in 0007/0008) never re-run against a
/// half-migrated database. `BEGIN IMMEDIATE` also serializes two processes
/// racing the same migration.
pub fn migrate(conn: &Connection) -> CoreResult<()> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS _migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);",
    )?;
    for (version, sql) in [
        (1, MIGRATION_0001),
        (2, MIGRATION_0002),
        (3, MIGRATION_0003),
        (4, MIGRATION_0004),
        (5, MIGRATION_0005),
        (6, MIGRATION_0006),
        (7, MIGRATION_0007),
        (8, MIGRATION_0008),
        (9, MIGRATION_0009),
        (10, MIGRATION_0010),
        (11, MIGRATION_0011),
        (12, MIGRATION_0012),
    ] {
        if is_applied(conn, version)? {
            continue;
        }
        conn.execute_batch("BEGIN IMMEDIATE;")?;
        match apply_version(conn, version, sql) {
            Ok(()) => conn.execute_batch("COMMIT;")?,
            Err(e) => {
                let _ = conn.execute_batch("ROLLBACK;");
                return Err(e);
            }
        }
    }
    Ok(())
}

/// Runs inside the caller's open transaction: re-checks the ledger (another
/// process may have applied this version while we waited for the write lock),
/// then applies the DDL and records the version — all-or-nothing.
fn apply_version(conn: &Connection, version: i64, sql: &str) -> CoreResult<()> {
    if is_applied(conn, version)? {
        return Ok(());
    }
    conn.execute_batch(sql)?;
    conn.execute(
        "INSERT INTO _migrations(version, applied_at) VALUES (?1, ?2)",
        rusqlite::params![version, crate::now()],
    )?;
    Ok(())
}

/// Highest applied migration version. A database that predates the
/// `_migrations` ledger (i.e. has never been migrated) reports 0; any real
/// query error — I/O, corruption, locked — propagates instead of being
/// mistaken for "needs migration".
pub fn current_version(conn: &Connection) -> CoreResult<i64> {
    let ledger_exists: bool = conn.query_row(
        "SELECT EXISTS (SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = '_migrations')",
        [],
        |r| r.get(0),
    )?;
    if !ledger_exists {
        return Ok(0);
    }
    let v: Option<i64> = conn.query_row("SELECT MAX(version) FROM _migrations", [], |r| r.get(0))?;
    Ok(v.unwrap_or(0))
}

fn is_applied(conn: &Connection, version: i64) -> CoreResult<bool> {
    let count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM _migrations WHERE version = ?1",
        [version],
        |r| r.get(0),
    )?;
    Ok(count > 0)
}
