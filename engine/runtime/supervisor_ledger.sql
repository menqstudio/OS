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

-- ---------------------------------------------------------------------------
-- 5. PRE-ACCEPT input staging (rev-30 §2.4 + §4.10(a0)).
--
-- This table is the supervisor's record that a signed challenge was OPENED --
-- admitted to upload its three declared inputs -- and NOTHING more. It is
-- deliberately NOT the acceptance ledger above, and the difference is the whole
-- point of the §2.4 "no staging<->acceptance deadlock" rule:
--
--   * it carries NO `execution_attempt_id` and NO lease. Opening a turn grants no
--     execution right; the right is minted later, once, by the acceptance CAS.
--     A caller that supplies an `execution_attempt_id` at open (the P1-5 defect --
--     the requester minting what the supervisor must mint) has nowhere to put it:
--     the wire shape rejects the field and this table has no column for it.
--   * it is gated by the VERIFIED signed challenge, not by an acceptance row --
--     which, at open time, does not and must not yet exist.
--
-- `challenge_expires_at_ms` is copied from the *signature-verified* §4.1 payload,
-- so the row's own lifetime is bounded by the challenge that authorized it. The
-- §2.4 live-count rule reads it: a row past its expiry occupies ZERO staging quota
-- whether or not the sweep has reached it, which is what stops an expired or
-- replayed challenge from pinning a `MAX_CONCURRENT_GOVERNED_TURNS` slot (P1-3).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS governed_turn_staging (
    install_id               TEXT NOT NULL,
    request_nonce            TEXT NOT NULL,
    challenge_handle         TEXT NOT NULL,   -- 64hex = SHA256(exact signed document bytes)
    run_id                   TEXT NOT NULL,
    task_id                  TEXT NOT NULL,
    workspace_id             TEXT NOT NULL,

    -- The three digests the VERIFIED challenge committed to. §4.10(a) refuses any
    -- staging-open whose `declared_sha256` is not one of these, so the bytes that
    -- may be uploaded are fixed by the signature before the first chunk arrives.
    system_sha256            TEXT NOT NULL,
    history_sha256           TEXT NOT NULL,
    generation_config_sha256 TEXT NOT NULL,

    -- Set by §4.10(c) as each artifact publishes; all three set => INPUTS_READY.
    system_handle            TEXT,
    history_handle           TEXT,
    generation_config_handle TEXT,

    state                    TEXT NOT NULL CHECK (state IN (
        'VERIFYING','UPLOADING','INPUTS_READY')),
    challenge_expires_at_ms  INTEGER NOT NULL,
    created_at_ms            INTEGER NOT NULL,
    updated_at_ms            INTEGER NOT NULL,
    UNIQUE (install_id, request_nonce),
    UNIQUE (challenge_handle)
);

-- The §2.4 live-count predicate (`install_id` + not-yet-expired) is read on EVERY
-- open to enforce MAX_CONCURRENT_GOVERNED_TURNS, so it gets an index rather than a
-- table scan a hostile caller could lengthen.
CREATE INDEX IF NOT EXISTS idx_governed_turn_staging_live
    ON governed_turn_staging (install_id, challenge_expires_at_ms);

-- A row may only ENTER the world as VERIFYING. §4.10(a0) is the only creator, and it
-- creates `absent -> VERIFYING -> UPLOADING` inside one transaction; every later state
-- must therefore be REACHED through the transitions below rather than declared at
-- INSERT. Without this, a writer could conjure an `INPUTS_READY` row -- the exact state
-- §4.10(d) treats as "all three inputs published and re-hashed against the challenge" --
-- having published nothing at all.
CREATE TRIGGER IF NOT EXISTS trg_governed_turn_staging_insert_state
BEFORE INSERT ON governed_turn_staging
FOR EACH ROW
WHEN NEW.state <> 'VERIFYING'
BEGIN
    SELECT RAISE(ABORT, 'staging row must be created VERIFYING');
END;

-- CHECK cannot see OLD.state, so the §2.4 ordering VERIFYING -> UPLOADING -> INPUTS_READY
-- is enforced by a BEFORE-UPDATE trigger, exactly as the acceptance lifecycle above. A
-- same-state write (recording a published `*_handle`) is allowed; every cross-state edge
-- must be one of the two legal ones; nothing may move backwards, and nothing may skip
-- UPLOADING to reach INPUTS_READY.
CREATE TRIGGER IF NOT EXISTS trg_governed_turn_staging_transition
BEFORE UPDATE OF state ON governed_turn_staging
FOR EACH ROW
WHEN NOT (
    OLD.state = NEW.state
    OR (OLD.state = 'VERIFYING'  AND NEW.state = 'UPLOADING')
    OR (OLD.state = 'UPLOADING'  AND NEW.state = 'INPUTS_READY')
)
BEGIN
    SELECT RAISE(ABORT, 'illegal staging state transition');
END;

-- The staging row's identity is the challenge it was opened for. Rebinding an existing
-- row to a DIFFERENT challenge would let a second signed document inherit the first
-- one's admitted slot and its already-published inputs, so the immutable columns are
-- immutable in the DB and not merely by convention (§4.10(a0) `retry_conflict` is the
-- wire verdict; this is the floor underneath it).
CREATE TRIGGER IF NOT EXISTS trg_governed_turn_staging_immutable_binding
BEFORE UPDATE ON governed_turn_staging
FOR EACH ROW
WHEN OLD.install_id <> NEW.install_id
  OR OLD.request_nonce <> NEW.request_nonce
  OR OLD.challenge_handle <> NEW.challenge_handle
  OR OLD.run_id <> NEW.run_id
  OR OLD.task_id <> NEW.task_id
  OR OLD.workspace_id <> NEW.workspace_id
  OR OLD.system_sha256 <> NEW.system_sha256
  OR OLD.history_sha256 <> NEW.history_sha256
  OR OLD.generation_config_sha256 <> NEW.generation_config_sha256
  OR OLD.challenge_expires_at_ms <> NEW.challenge_expires_at_ms
BEGIN
    SELECT RAISE(ABORT, 'staging row binding is immutable');
END;
