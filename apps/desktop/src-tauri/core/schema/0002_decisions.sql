-- Migration 0002: decisions log.

CREATE TABLE IF NOT EXISTS decisions (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'proposed',
    owner      TEXT NOT NULL,
    rationale  TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status, updated_at);
