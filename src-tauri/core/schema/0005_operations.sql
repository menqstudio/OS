-- Migration 0005: operational workspaces — runs (Command), events (Calendar),
-- automations, and integrations. All plain SQLite rows; IDs are text (UUID);
-- timestamps are text (see core::now). Analytics and Security are computed at
-- read time over existing tables and need no schema of their own.

CREATE TABLE IF NOT EXISTS runs (
    id         TEXT PRIMARY KEY,
    intent     TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'drafted',
    plan       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'event',
    location   TEXT NOT NULL DEFAULT '',
    starts_at  TEXT NOT NULL,
    ends_at    TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS automations (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    trigger    TEXT NOT NULL DEFAULT '',
    action     TEXT NOT NULL DEFAULT '',
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS integrations (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    provider   TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'disconnected',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(starts_at);
CREATE INDEX IF NOT EXISTS idx_integrations_status ON integrations(status);
