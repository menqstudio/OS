-- Migration 0015: library items + research items.
-- Library = saved components / prompts / patterns (a reusable catalog). Research =
-- recorded research items (a question and its findings). Both are plain SQLite
-- rows; IDs are text (UUID), mirroring the 0004 knowledge/memory conventions.

CREATE TABLE IF NOT EXISTS library_items (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'component',
    body       TEXT NOT NULL DEFAULT '',
    tags       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_items (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    question   TEXT NOT NULL DEFAULT '',
    findings   TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_library_updated ON library_items(updated_at);
CREATE INDEX IF NOT EXISTS idx_research_updated ON research_items(updated_at);
