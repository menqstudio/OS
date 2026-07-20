-- Migration 0006: run_steps — the ordered plan a run executes through.
-- A run advances step by step (a controlled state machine); the app does not
-- execute anything on the host — it models the execution lifecycle only.

CREATE TABLE IF NOT EXISTS run_steps (
    id         TEXT PRIMARY KEY,
    run_id     TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    position   INTEGER NOT NULL DEFAULT 0,
    title      TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_run_steps_run ON run_steps(run_id, position);
