-- Migration 0004: knowledge notes + memory entries.
-- Knowledge = searchable, attributable notes. Memory = inspectable persistent
-- entries with a scope and kind. Both are plain SQLite rows; IDs are text (UUID).

CREATE TABLE IF NOT EXISTS knowledge_notes (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL DEFAULT '',
    source     TEXT NOT NULL DEFAULT '',
    tags       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_entries (
    id         TEXT PRIMARY KEY,
    scope      TEXT NOT NULL DEFAULT 'global',
    kind       TEXT NOT NULL DEFAULT 'note',
    content    TEXT NOT NULL DEFAULT '',
    pinned     INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_knowledge_updated ON knowledge_notes(updated_at);
CREATE INDEX IF NOT EXISTS idx_memory_scope ON memory_entries(scope, updated_at);
