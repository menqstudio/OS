//! Connection setup and forward-only migrations.

use crate::domain::CoreResult;
use rusqlite::Connection;

const MIGRATION_0001: &str = include_str!("../schema/0001_initial.sql");
const MIGRATION_0002: &str = include_str!("../schema/0002_decisions.sql");
const MIGRATION_0003: &str = include_str!("../schema/0003_conversations.sql");
const MIGRATION_0004: &str = include_str!("../schema/0004_knowledge_memory.sql");
const MIGRATION_0005: &str = include_str!("../schema/0005_operations.sql");
const MIGRATION_0006: &str = include_str!("../schema/0006_run_steps.sql");
const MIGRATION_0007: &str = include_str!("../schema/0007_run_step_result.sql");
const MIGRATION_0008: &str = include_str!("../schema/0008_approval_gating.sql");
const MIGRATION_0009: &str = include_str!("../schema/0009_task_dependencies.sql");
pub const SCHEMA_VERSION: i64 = 9;

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
    // WAL is a no-op for :memory: but valid for files.
    let _ = conn.pragma_update(None, "journal_mode", "WAL");
    Ok(())
}

/// Forward-only, idempotent migration runner.
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
    ] {
        if !is_applied(conn, version)? {
            conn.execute_batch(sql)?;
            conn.execute(
                "INSERT INTO _migrations(version, applied_at) VALUES (?1, ?2)",
                rusqlite::params![version, crate::now()],
            )?;
        }
    }
    Ok(())
}

pub fn current_version(conn: &Connection) -> CoreResult<i64> {
    let v: Option<i64> = conn
        .query_row("SELECT MAX(version) FROM _migrations", [], |r| r.get(0))
        .unwrap_or(None);
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
