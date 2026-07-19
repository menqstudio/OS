-- Migration 0003: conversations + messages (Chat / Group Chat backend).
-- A conversation is either a 1:1 'direct' thread with Bro or a 'group' room
-- shared by humans and agents. Messages belong to exactly one conversation and
-- cascade-delete with it. IDs are text (UUID); timestamps are text (see core::now).

CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL DEFAULT 'direct',
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL DEFAULT 'user',
    author          TEXT NOT NULL,
    body            TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversations_kind ON conversations(kind, updated_at);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);
