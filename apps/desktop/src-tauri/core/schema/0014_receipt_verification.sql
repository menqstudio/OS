-- T-015 / Wave 3a slice 2: durable receipt-verification storage & atomicity.
--
-- The merged slice-1 core (`brops-core::receipt`) is pure/I-O-free: it parses,
-- verifies the Ed25519 signature, and binds the §3 value subset, but it holds no
-- state. Slice 2 adds the three durable tables the atomic verify->consume->persist
-- transaction (design §4) needs so that a governed reply renders only against a
-- fresh, one-time, never-before-accepted receipt, and every attempt -- ACCEPTED or
-- BLOCKED, and including a receipt that fails BEFORE strict-decode -- leaves a
-- re-verifiable evidence record.
--
-- Invariants enforced HERE, in the schema, as defense-in-depth beneath the Rust
-- transaction (a wiring bug cannot violate them without a constraint error):
--   * a `blocked` attempt NEVER links a `messages` row;
--   * an accepted attempt (`trusted_verified` | `development_untrusted`) ALWAYS
--     links exactly one existing `messages` row (real FK -> no orphan pointer);
--   * a receipt_id can be ACCEPTED at most once (global-uniqueness / replay defense);
--   * a challenge nonce is consumed at most once (the one-time compare-and-consume
--     UPDATE ... WHERE consumed_at IS NULL is the mutual exclusion).

-- Durable one-time desktop challenge (design §3.3, §4). The desktop mints a nonce
-- when it ISSUES a governed request and records it here unspent; the returned
-- receipt must carry this exact nonce, still unconsumed. The atomic transaction
-- consumes it (sets consumed_at) in the same tx that persists the outcome, so a
-- crash can neither persist an accepted message without consuming its nonce nor
-- consume a nonce without persisting the message.
CREATE TABLE IF NOT EXISTS receipt_challenges (
    -- The desktop-generated one-time challenge (opaque high-entropy string). PK, so
    -- issuing the same nonce twice is refused at the DB layer.
    nonce           TEXT PRIMARY KEY,
    -- The conversation the governed turn belongs to; the accepted agent message is
    -- posted here. Scoped + cascades if the conversation is deleted.
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    -- The canonical request-envelope hash (design §2.2) the desktop committed to when
    -- it issued THIS challenge. NOT NULL + lowercase-64-hex. The atomic transaction
    -- loads it and requires it to equal `expected.request.request_sha256()` before it
    -- can accept, so the durable challenge is bound to the exact request envelope (not
    -- merely to the nonce + conversation). Combined with the core `bind()` recompute
    -- (receipt.request_sha256 == expected...), challenge, Expected, and receipt all
    -- agree on the request envelope.
    request_sha256  TEXT NOT NULL
        CHECK (length(request_sha256) = 64 AND request_sha256 NOT GLOB '*[^0-9a-f]*'),
    issued_at       TEXT NOT NULL,
    -- NULL = unspent. Set exactly once by the atomic consume
    -- (UPDATE ... WHERE nonce = ? AND consumed_at IS NULL); 0 rows affected => the
    -- nonce was already spent or unknown => the receipt is a replay => blocked.
    consumed_at     TEXT
);

-- Every verification attempt's re-verifiable evidence (design §4). Both accepted
-- outcomes AND blocked attempts are recorded here; only accepted outcomes also
-- produce a `messages` row (linked via message_id).
--
-- The `wire_*` columns hold the EXACT bytes as they arrived on the wire so a
-- receipt that fails BEFORE strict-decode (bad-base64, oversized, invalid-JSON)
-- still leaves forensic evidence -- those failures are part of the protocol. The
-- Rust layer caps each `wire_*` value at the protocol size limit before insert, so
-- this evidence table cannot be turned into a storage-DoS vector. The `envelope_jcs`
-- / `signature` BLOBs hold the DECODED canonical bytes and are populated only once
-- decode succeeds (NULL otherwise).
CREATE TABLE IF NOT EXISTS receipt_verification_attempts (
    id                    TEXT PRIMARY KEY,
    -- Raw wire strings as received (capped at the protocol limit by the Rust layer).
    -- Always present -- the evidence of what actually arrived.
    wire_envelope_jcs_b64 TEXT NOT NULL,
    wire_signature_b64    TEXT NOT NULL,
    -- The receipt envelope's receipt_id. NULL when decode/parse failed before it
    -- could be read.
    receipt_id            TEXT,
    -- The signing key id from the envelope. NULL for pre-parse blocked attempts.
    key_id                TEXT,
    -- The EXACT canonical envelope bytes as DECODED (never a re-serialization), so an
    -- accepted record stays cryptographically re-verifiable. NULL when decode failed.
    envelope_jcs          BLOB,
    -- The 64-byte Ed25519 signature (decoded). NULL when absent/undecodable.
    signature             BLOB,
    -- Tri-state outcome (design §4/§6). trusted_verified is modeled here for Wave 3b
    -- but is UNREACHABLE in Wave 3a (production trust_class resolves to Blocked).
    outcome               TEXT NOT NULL
        CHECK (outcome IN ('trusted_verified', 'development_untrusted', 'blocked')),
    -- Machine/human reason a blocked attempt failed; NULL for accepted outcomes.
    verification_error    TEXT,
    -- The challenge this attempt targeted. NULL when the attempt referenced no valid
    -- challenge. No FK: evidence must survive a challenge-row cascade delete.
    nonce                 TEXT,
    -- The accepted agent message; NULL for blocked. Real FK -> an accepted attempt
    -- can never point to a non-existent message at INSERT time. ON DELETE SET NULL
    -- (NOT CASCADE): deleting a message/conversation must NOT erase the accepted
    -- forensic evidence (audit round: CASCADE would delete the attempt with its
    -- message). The attempt row and its exact envelope+signature+outcome are RETAINED;
    -- only this convenience link nulls. receipt_ids_seen is untouched, so deleting a
    -- message never re-opens replay of its receipt.
    message_id            TEXT REFERENCES messages(id) ON DELETE SET NULL,
    verified_at           TEXT NOT NULL,
    -- Security-critical invariant, enforced at the DB layer: a `blocked` attempt
    -- NEVER links a message (so blocked content can never render). We deliberately do
    -- NOT add an `accepted => message_id NOT NULL` CHECK: message_id is ON DELETE SET
    -- NULL, so after a message deletion an accepted row legitimately carries a NULL
    -- link while retaining its evidence, and SQLite re-checks CHECKs on that SET-NULL
    -- cascade. The accepted<->message link is instead guaranteed at INSERT by the FK
    -- + the message->attempt->ledger insert order (and a test). This weaker CHECK is
    -- cascade-safe: SET-NULL on an accepted row keeps `outcome != 'blocked'` true.
    CHECK (outcome != 'blocked' OR message_id IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_receipt_attempts_receipt_id
    ON receipt_verification_attempts (receipt_id);
CREATE INDEX IF NOT EXISTS idx_receipt_attempts_verified_at
    ON receipt_verification_attempts (verified_at);

-- Durable global-uniqueness ledger for ACCEPTED receipt_ids (design §3.8). A
-- receipt_id is recorded here only when a receipt is ACCEPTED, so replaying an
-- accepted receipt is refused (its id is already present), while a blocked
-- duplicate still gets its evidence row in receipt_verification_attempts without
-- poisoning a future legitimate id. The PRIMARY KEY is the hard DB guarantee that
-- no receipt_id is accepted twice, even under a race the tx did not serialize.
CREATE TABLE IF NOT EXISTS receipt_ids_seen (
    receipt_id    TEXT PRIMARY KEY,
    first_seen_at TEXT NOT NULL,
    -- The accepting attempt (audit trail back to the evidence row). SET NULL on the
    -- attempt's deletion so the receipt_id stays recorded (replay defense) even after
    -- its message/attempt is deleted.
    attempt_id    TEXT REFERENCES receipt_verification_attempts(id) ON DELETE SET NULL
);
