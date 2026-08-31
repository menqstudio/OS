-- 0025: the produced agent bundle, and the queue that stands between a due
-- trigger and an action.
--
-- Why a queue at all. Before this migration `run_due` DETECTED a due trigger and
-- PERFORMED the action in the same call (repo.rs:2592 -> run -> execute_action),
-- and `lib.rs` discarded the result with `let _ =`. A poisoned mutex, a failed
-- open and a refusal were therefore indistinguishable from a quiet week. A
-- scheduler that cannot say what it did on a tick cannot be audited unattended,
-- and unattended auditability is the whole question a produced artifact raises.
--
-- The tick's authority SHRINKS here rather than growing: for a bundle it may
-- write a `flow_runs` row and a `scheduler_ticks` row and nothing else. It
-- performs no action, reaches no network, holds no credential and calls no
-- model. A separate claim step does the work, using the one-time-claim shape
-- migration 0013 already established for run steps -- reused rather than
-- reinvented, because it is the only concurrency control in this codebase that
-- has survived an audit round.

CREATE TABLE IF NOT EXISTS agent_bundles (
    bundle_digest   TEXT PRIMARY KEY,      -- sha256(manifest.json), lowercase hex; IS the directory name
    bundle_id       TEXT NOT NULL,         -- the AGENT's identity, stable across versions
    bundle_version  INTEGER NOT NULL,
    display_name    TEXT NOT NULL,
    built_at        TEXT NOT NULL,
    state           TEXT NOT NULL,         -- 'built' | 'approved' | 'retired'
    created_at      TEXT NOT NULL
);

-- One row per bundle_id names the digest the scheduler resolves a trigger to.
-- A digest named here with no agent_bundles row is the `no_active_bundle`
-- refusal, not a skip.
CREATE TABLE IF NOT EXISTS agent_bundle_active (
    bundle_id       TEXT PRIMARY KEY,
    bundle_digest   TEXT NOT NULL REFERENCES agent_bundles(bundle_digest) ON DELETE RESTRICT,
    interval_ms     INTEGER NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS flow_runs (
    id               TEXT PRIMARY KEY,
    bundle_id        TEXT NOT NULL,
    bundle_digest    TEXT NOT NULL,
    trigger_kind     TEXT NOT NULL,        -- 'interval' | 'manual'
    invoked_by       TEXT NOT NULL,        -- the runtime entry point; 'run_due' for the tick
    due_at           TEXT NOT NULL,
    state            TEXT NOT NULL,        -- 'queued'|'running'|'done'|'failed'|'refused'
    refusal_reason   TEXT,                 -- closed set, never free text; NULL unless state='refused'
    claim_attempt_id TEXT,
    claim_session_id TEXT,
    claim_started_at TEXT,
    created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_flow_runs_state ON flow_runs(state, bundle_digest);

-- Exists because of `let _ =`. Always written, including on a tick that found
-- nothing: "nothing was due" and "the tick did not run" must not look the same.
CREATE TABLE IF NOT EXISTS scheduler_ticks (
    at        TEXT PRIMARY KEY,
    due_found INTEGER NOT NULL,
    enqueued  INTEGER NOT NULL,
    refused   INTEGER NOT NULL,
    error     TEXT
);

-- A receipt names what a run touched and the regime it ran under.
-- `enforcement_regime` is recorded per run rather than read from the
-- environment at display time: a receipt that cannot distinguish "was blocked"
-- from "would have been blocked" is not evidence.
CREATE TABLE IF NOT EXISTS flow_receipts (
    run_id             TEXT PRIMARY KEY,
    bundle_digest      TEXT NOT NULL,
    enforcement_regime TEXT NOT NULL,
    steps_run          INTEGER NOT NULL,
    touched            TEXT NOT NULL,      -- JSON array of what the run wrote
    outcome            TEXT NOT NULL,      -- 'done' | 'failed' | 'refused'
    written_at         TEXT NOT NULL
);
