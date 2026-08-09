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

-- ---------------------------------------------------------------------------
-- 6. Per-artifact staging upload session (rev-30 §2.4 + §4.10(a)(b)(c)).
--
-- One row per (challenge_handle, artifact): the durable cursor of a chunked
-- upload. The rules that make an upload MEAN something live here rather than in
-- the Python that drives them, for the same reason the acceptance lifecycle does:
-- a writer that bypasses the handlers entirely still cannot fabricate a finished
-- upload.
--
--   * a session is BORN `UPLOADING` at cursor zero with no published handle, so
--     nothing can declare an `ARTIFACT_READY` session having uploaded nothing;
--   * the cursor may only advance by EXACTLY one seq and EXACTLY the length of
--     the chunk row just recorded, so `byte_count` is provably the sum of the
--     recorded `chunk_len`s and `next_seq` is provably their count -- there is no
--     way to write a cursor that outruns the bytes actually on disk;
--   * a chunk row may only be inserted AT the current cursor, so the sequence is
--     gapless by construction, and it can never be UPDATEd afterwards, so an
--     already-counted chunk cannot be retroactively re-described.
--
-- `session_dir` holds the IMMUTABLE `<seq>.chunk` files; the DB records only the
-- cursor plus each chunk's `(sha256, len)`. There is deliberately NO
-- `running_sha256` column (§2.4, P0-1): a finalized SHA-256 digest is not a
-- resumable internal hash state, so the final digest is recomputed from byte zero
-- over the immutable chunk files and no incremental state is trusted across a
-- restart.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS governed_turn_staging_session (
    staging_session_id TEXT PRIMARY KEY NOT NULL,
    challenge_handle   TEXT NOT NULL,
    artifact           TEXT NOT NULL CHECK (artifact IN (
        'system','history','generation_config')),
    declared_len       INTEGER NOT NULL CHECK (
        declared_len >= 0 AND declared_len <= 8388608),
    declared_sha256    TEXT NOT NULL,
    next_seq           INTEGER NOT NULL CHECK (next_seq >= 0 AND next_seq <= 46),
    byte_count         INTEGER NOT NULL CHECK (
        byte_count >= 0 AND byte_count <= declared_len),
    session_dir        TEXT NOT NULL,
    state              TEXT NOT NULL CHECK (state IN (
        'UPLOADING','ARTIFACT_READY','SESSION_CORRUPT')),
    published_handle   TEXT,
    UNIQUE (challenge_handle, artifact),

    -- The session's turn is its parent row, in the DB and not merely by convention:
    -- an orphan session -- one naming a challenge the supervisor never opened, or one
    -- outliving the sweep of its turn -- can neither be created nor left behind.
    -- `policy_bundle` has no place in the `artifact` CHECK above because §2.4 gives
    -- policy to the supervisor itself; the untrusted sidecar can never upload it.
    FOREIGN KEY (challenge_handle)
        REFERENCES governed_turn_staging (challenge_handle) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_governed_turn_staging_session_challenge
    ON governed_turn_staging_session (challenge_handle);

-- Per-chunk digest of the IMMUTABLE `<seq>.chunk` file -- the source of truth for
-- resume/idempotency (§2.4). `chunk_len >= 1` is load-bearing: the §4.10(b)
-- deterministic length is `min(184320, declared_len - byte_count)` and a chunk is
-- only ever sent while bytes remain, so a zero-length chunk row is not a small
-- upload, it is a cursor advance that carried nothing.
CREATE TABLE IF NOT EXISTS governed_turn_staging_chunk (
    staging_session_id TEXT NOT NULL,
    seq                INTEGER NOT NULL CHECK (seq >= 0 AND seq <= 45),
    chunk_sha256       TEXT NOT NULL,
    chunk_len          INTEGER NOT NULL CHECK (
        chunk_len >= 1 AND chunk_len <= 184320),
    PRIMARY KEY (staging_session_id, seq),
    FOREIGN KEY (staging_session_id)
        REFERENCES governed_turn_staging_session (staging_session_id) ON DELETE CASCADE
);

-- A session may only ENTER the world empty: `UPLOADING`, cursor 0, zero bytes, no
-- published handle. Without this a writer could INSERT an `ARTIFACT_READY` row
-- carrying a `published_handle` for bytes that were never uploaded -- the same
-- "declare the end state, do nothing" hole the staging row's own insert trigger closes.
CREATE TRIGGER IF NOT EXISTS trg_governed_turn_staging_session_insert_state
BEFORE INSERT ON governed_turn_staging_session
FOR EACH ROW
WHEN NEW.state <> 'UPLOADING'
  OR NEW.next_seq <> 0
  OR NEW.byte_count <> 0
  OR NEW.published_handle IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'staging session must be created empty and UPLOADING');
END;

-- The closed §2.4 session lifecycle. `ARTIFACT_READY` and `SESSION_CORRUPT` are both
-- terminal, so neither appears as an OLD.state with a different NEW.state: a corrupt
-- session can never be resurrected into a usable one (§2.4 "operator-swept only"), and
-- a published artifact can never be walked back into an uploading one.
CREATE TRIGGER IF NOT EXISTS trg_governed_turn_staging_session_transition
BEFORE UPDATE OF state ON governed_turn_staging_session
FOR EACH ROW
WHEN NOT (
    OLD.state = NEW.state
    OR (OLD.state = 'UPLOADING' AND NEW.state IN ('ARTIFACT_READY','SESSION_CORRUPT'))
)
BEGIN
    SELECT RAISE(ABORT, 'illegal staging session state transition');
END;

-- THE CURSOR RULE. `next_seq`/`byte_count` may only move forward by exactly one seq
-- and exactly the length of the chunk row recorded at the cursor being left. Anything
-- else -- a jump, a rewind, a byte count that does not match the bytes on disk, an
-- advance with no chunk row at all (the sub-select is NULL, and `IS` makes that a
-- refusal rather than an unknown) -- aborts. This is what makes `byte_count` provably
-- SUM(chunk_len) and `next_seq` provably COUNT(chunk rows): a cursor cannot outrun the
-- immutable files it claims to summarize.
CREATE TRIGGER IF NOT EXISTS trg_governed_turn_staging_session_cursor
BEFORE UPDATE OF next_seq, byte_count ON governed_turn_staging_session
FOR EACH ROW
WHEN NOT (
    NEW.next_seq = OLD.next_seq + 1
    AND NEW.byte_count IS (OLD.byte_count + (
        SELECT chunk_len FROM governed_turn_staging_chunk
         WHERE staging_session_id = OLD.staging_session_id AND seq = OLD.next_seq))
)
BEGIN
    SELECT RAISE(ABORT, 'staging cursor must advance by exactly one recorded chunk');
END;

-- The session's identity and its declared contract are fixed at open, and the handle
-- it publishes is write-once. Rebinding any of them would let a second declared digest,
-- a second artifact, or a second published handle inherit a session's already-accepted
-- chunks (§4.10(a) `retry_conflict` is the wire verdict; this is the floor under it).
CREATE TRIGGER IF NOT EXISTS trg_governed_turn_staging_session_immutable
BEFORE UPDATE ON governed_turn_staging_session
FOR EACH ROW
WHEN OLD.staging_session_id <> NEW.staging_session_id
  OR OLD.challenge_handle <> NEW.challenge_handle
  OR OLD.artifact <> NEW.artifact
  OR OLD.declared_len <> NEW.declared_len
  OR OLD.declared_sha256 <> NEW.declared_sha256
  OR OLD.session_dir <> NEW.session_dir
  OR (OLD.published_handle IS NOT NULL
      AND NEW.published_handle IS NOT OLD.published_handle)
BEGIN
    SELECT RAISE(ABORT, 'staging session binding is immutable');
END;

-- A chunk may only be recorded AT the cursor, so the recorded sequence is gapless by
-- construction: there is no INSERT that skips a seq and none that back-fills one. A
-- session that does not exist yields NULL from the sub-select, and `IS NOT` turns that
-- into a refusal rather than an unknown that lets the row through.
CREATE TRIGGER IF NOT EXISTS trg_governed_turn_staging_chunk_gapless
BEFORE INSERT ON governed_turn_staging_chunk
FOR EACH ROW
WHEN NEW.seq IS NOT (
    SELECT next_seq FROM governed_turn_staging_session
     WHERE staging_session_id = NEW.staging_session_id)
BEGIN
    SELECT RAISE(ABORT, 'staging chunk must be recorded at the current cursor');
END;

-- A recorded chunk is IMMUTABLE. The PRIMARY KEY already refuses a second INSERT at a
-- seq; this refuses the other way in -- re-describing an already-counted chunk with a
-- different digest or length, which would silently break the `byte_count == SUM(chunk_len)`
-- guarantee the cursor rule establishes. (DELETE is deliberately still permitted: the
-- §2.4 operator sweep removes a whole session, and the FK cascade takes its chunks.)
CREATE TRIGGER IF NOT EXISTS trg_governed_turn_staging_chunk_immutable
BEFORE UPDATE ON governed_turn_staging_chunk
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'recorded staging chunks are immutable');
END;

-- ---------------------------------------------------------------------------
-- 6b. What a published input handle is allowed to be (§4.10(c)).
--
-- The staging row's three `*_handle` columns are filled by §4.10(c) as each artifact
-- publishes. A handle is SHA256 of the exact stored bytes, and the challenge already
-- COMMITTED to that digest -- so a published handle that is not the committed digest
-- means the supervisor published bytes the signature never authorized. §4.10(c)
-- refuses that on the wire as `handle_not_challenge`; this refuses to RECORD it at all,
-- and it is also write-once, so a second artifact cannot displace a published one.
-- ---------------------------------------------------------------------------
CREATE TRIGGER IF NOT EXISTS trg_governed_turn_staging_handle_binding
BEFORE UPDATE ON governed_turn_staging
FOR EACH ROW
WHEN (NEW.system_handle IS NOT NULL
      AND NEW.system_handle <> NEW.system_sha256)
  OR (NEW.history_handle IS NOT NULL
      AND NEW.history_handle <> NEW.history_sha256)
  OR (NEW.generation_config_handle IS NOT NULL
      AND NEW.generation_config_handle <> NEW.generation_config_sha256)
  OR (OLD.system_handle IS NOT NULL
      AND NEW.system_handle IS NOT OLD.system_handle)
  OR (OLD.history_handle IS NOT NULL
      AND NEW.history_handle IS NOT OLD.history_handle)
  OR (OLD.generation_config_handle IS NOT NULL
      AND NEW.generation_config_handle IS NOT OLD.generation_config_handle)
BEGIN
    SELECT RAISE(ABORT, 'published input handle must be the challenge-committed digest');
END;

-- `INPUTS_READY` is the state §4.10(d) reads as "every declared input exists in the
-- store and re-hashes to the challenge's committed digest". Combined with the handle
-- trigger above, this makes that reading TRUE of the row rather than a claim about it:
-- the state cannot be reached until all three handles are set, and no handle can be set
-- unless it equals the digest the signed challenge committed to.
CREATE TRIGGER IF NOT EXISTS trg_governed_turn_staging_inputs_ready
BEFORE UPDATE OF state ON governed_turn_staging
FOR EACH ROW
WHEN NEW.state = 'INPUTS_READY'
  AND (NEW.system_handle IS NULL
       OR NEW.history_handle IS NULL
       OR NEW.generation_config_handle IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'INPUTS_READY requires all three published input handles');
END;
