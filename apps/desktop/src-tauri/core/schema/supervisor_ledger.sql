-- ===========================================================================
-- CANONICAL supervisor durable-ledger DDL (Wave 3b-1B, rev-30 §5; F-01 closure)
--
-- THIS FILE IS THE SINGLE NORMATIVE SOURCE for the governed-supervisor's durable
-- state. Two components load it VERBATIM:
--
--   * engine/runtime/governed_supervisor_ledger.py  — the Python supervisor
--     service that OWNS this state (it is the only writer in production);
--   * apps/desktop/src-tauri/core/src/supervisor_ledger.rs — the Rust ledger
--     library, via `include_str!` of the mirrored copy at
--     apps/desktop/src-tauri/core/schema/supervisor_ledger.sql.
--
-- The two copies are byte-compared by the fail-closed CI gate
-- `tools/check_ledger_ddl_parity.py`; a divergence (or a missing copy) is RED.
-- The mirror exists ONLY so each half still builds standalone (CLAUDE.md §4);
-- it is never edited directly — edit THIS file and re-run the gate.
--
-- Why this matters (independent audit 2026-08-06, F-01 P0): the supervisor's
-- `attest-run` used to SIGN caller-supplied facts, so the broker uid could mint a
-- signed receipt for a run that never happened. The enforcement that makes an
-- attestation mean something lives HERE, in the DB, not in either language:
--
--   * the three UNIQUE constraints on `governed_turn_acceptance` ARE the
--     one-lease-per-challenge CAS (a replayed signed challenge cannot mint a
--     second execution attempt);
--   * the `state` CHECK + the BEFORE-UPDATE trigger ARE the closed §5 lifecycle
--     (no illegal jump, no path back out of a terminal state);
--   * `governed_turn_completion`'s PK IS the write-once gate on the run-produced
--     facts (a second, different completion for one attempt is refused);
--   * `governed_evidence_head_floor` IS the anti-rollback / anti-fork floor.
--
-- A fabricated run therefore has no acceptance row, no lease, and no completion —
-- so it has no evidence the supervisor will build, and no attestation.
-- ===========================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- 1. Acceptance ledger — one row per accepted governed turn (§5 step 4).
--
-- Every column is SUPERVISOR-DERIVED: the identity/binding columns are copied
-- out of the signature-verified `brops.governed-turn-challenge.v1` payload, the
-- lease window is stamped from the supervisor's own clock, and `receipt_id` is
-- minted by the supervisor at acceptance. NONE of it is a later caller message.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS governed_turn_acceptance (
    install_id                     TEXT NOT NULL,
    request_nonce                  TEXT NOT NULL,
    challenge_handle               TEXT NOT NULL,
    run_id                         TEXT NOT NULL,
    task_id                        TEXT NOT NULL,
    workspace_id                   TEXT NOT NULL,
    execution_attempt_id           TEXT NOT NULL,
    challenge_accepted_at_ms       INTEGER NOT NULL,
    challenge_registry_handle      TEXT NOT NULL,
    challenge_registry_hash        TEXT NOT NULL,
    challenge_registry_epoch       INTEGER NOT NULL,
    challenge_registry_root_key_id TEXT NOT NULL,
    lease_payload_sha256           TEXT NOT NULL,
    lease_payload_bytes            BLOB NOT NULL,
    lease_handle                   TEXT,

    -- ---- F-01: the request binding, copied from the SIGNED challenge payload --
    -- These are what let `attest-run` rebuild the §4.9 evidence from supervisor
    -- state alone. Because they come from the challenge the supervisor itself
    -- signature-verified, the broker cannot choose them after the fact.
    lease_id                       TEXT NOT NULL,
    lease_issued_at_ms             INTEGER NOT NULL,
    lease_expires_at_ms            INTEGER NOT NULL,
    receipt_id                     TEXT NOT NULL,
    supervisor_id                  TEXT NOT NULL,
    requested_at_ms                INTEGER NOT NULL,
    request_sha256                 TEXT NOT NULL,
    system_handle                  TEXT NOT NULL,
    history_handle                 TEXT NOT NULL,
    generation_config_handle       TEXT NOT NULL,

    state                          TEXT NOT NULL CHECK (state IN (
        'ACCEPTED_PREPARED','LEASE_READY','EXECUTION_STARTING','EXECUTING',
        'COMPLETED','BLOCKED','FAILED','EXPIRED','RECOVERY_REQUIRED')),
    execution_started_marker       TEXT,
    cgroup_id                      TEXT,
    process_group_id               TEXT,
    terminal_record_handle         TEXT,
    failure_reason                 TEXT,
    created_at_ms                  INTEGER NOT NULL,
    updated_at_ms                  INTEGER NOT NULL,
    UNIQUE (install_id, request_nonce),
    UNIQUE (challenge_handle),
    UNIQUE (execution_attempt_id)
);

-- A `receipt_id` is the §7.1(d) global-unique replay key, so one attempt must
-- never share it with another (independent audit F-02 notes a deployment-static
-- receipt_id defeats that key outright; the supervisor now mints it per turn).
CREATE UNIQUE INDEX IF NOT EXISTS idx_governed_turn_acceptance_receipt
    ON governed_turn_acceptance (receipt_id);

-- CHECK cannot see OLD.state, so the transition matrix is enforced by a BEFORE-UPDATE trigger.
-- It fires whenever `state` is in the SET list; a same-state write (updating other columns) is
-- allowed, every cross-state edge must be one of the §5 legal edges, and NO edge may leave a
-- terminal state (terminals never appear as an OLD.state with a different NEW.state below).
CREATE TRIGGER IF NOT EXISTS trg_governed_turn_acceptance_transition
BEFORE UPDATE OF state ON governed_turn_acceptance
FOR EACH ROW
WHEN NOT (
    OLD.state = NEW.state
    OR (OLD.state = 'ACCEPTED_PREPARED'  AND NEW.state IN ('LEASE_READY','BLOCKED'))
    OR (OLD.state = 'LEASE_READY'         AND NEW.state IN ('EXECUTION_STARTING','EXPIRED','BLOCKED'))
    OR (OLD.state = 'EXECUTION_STARTING'  AND NEW.state IN ('EXECUTING','RECOVERY_REQUIRED'))
    OR (OLD.state = 'EXECUTING'           AND NEW.state IN ('COMPLETED','FAILED','RECOVERY_REQUIRED'))
)
BEGIN
    SELECT RAISE(ABORT, 'illegal acceptance state transition');
END;

-- ---------------------------------------------------------------------------
-- 2. Completion facts — the WRITE-ONCE record of what the run actually produced
--    (F-01). These are the ONLY §4.9 evidence values the supervisor cannot know
--    on its own, so they are reported once, bound to an attempt that already
--    passed accept-open + the launch gate + a confirmed start.
--
--    The PRIMARY KEY is the write-once gate: a second `complete-run` for the same
--    attempt is either byte-identical (an idempotent crash-retry) or REFUSED. The
--    broker therefore gets exactly one shot at the facts, and only for a run the
--    supervisor durably authorized.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS governed_turn_completion (
    execution_attempt_id        TEXT PRIMARY KEY NOT NULL,
    output_handle               TEXT NOT NULL,
    containment_evidence_handle TEXT NOT NULL,
    record_handle               TEXT NOT NULL,
    lease_handle                TEXT NOT NULL,
    execution_receipt_handle    TEXT NOT NULL,
    completed_at_ms             INTEGER NOT NULL,
    evidence_final_event_hash   TEXT NOT NULL,
    evidence_event_count        INTEGER NOT NULL CHECK (evidence_event_count >= 1),
    evidence_last_sequence      INTEGER NOT NULL CHECK (evidence_last_sequence >= 1),
    evidence_head_sequence      INTEGER NOT NULL CHECK (evidence_head_sequence >= 1),
    facts_sha256                TEXT NOT NULL,
    created_at_ms               INTEGER NOT NULL,
    FOREIGN KEY (execution_attempt_id)
        REFERENCES governed_turn_acceptance (execution_attempt_id)
);

-- ---------------------------------------------------------------------------
-- 3. Outbox — the durable terminal record staged for the atomic publish.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS governed_turn_outbox (
    execution_attempt_id   TEXT PRIMARY KEY NOT NULL,
    run_id                 TEXT NOT NULL,
    terminal_state         TEXT NOT NULL CHECK (terminal_state IN (
        'COMPLETED','BLOCKED','FAILED','EXPIRED','RECOVERY_REQUIRED')),
    terminal_record_handle TEXT,
    record_filename        TEXT NOT NULL,
    payload_sha256         TEXT NOT NULL,
    payload_bytes          BLOB NOT NULL,
    published              INTEGER NOT NULL DEFAULT 0 CHECK (published IN (0,1)),
    created_at_ms          INTEGER NOT NULL,
    published_at_ms        INTEGER,
    FOREIGN KEY (execution_attempt_id)
        REFERENCES governed_turn_acceptance (execution_attempt_id)
);

-- ---------------------------------------------------------------------------
-- 4. Evidence-head anti-rollback / anti-fork floor (§5 step 11 / §7 P1-7).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS governed_evidence_head_floor (
    install_id            TEXT NOT NULL,
    task_id               TEXT NOT NULL,
    highest_head_sequence INTEGER NOT NULL CHECK (highest_head_sequence >= 1),
    event_count           INTEGER NOT NULL CHECK (event_count >= 1),
    last_sequence         INTEGER NOT NULL CHECK (last_sequence >= 1),
    final_event_hash      TEXT NOT NULL,
    updated_at_ms         INTEGER NOT NULL,
    PRIMARY KEY (install_id, task_id)
);
