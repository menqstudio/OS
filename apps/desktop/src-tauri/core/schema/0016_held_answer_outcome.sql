-- Phase 2 (govern the AI surfaces): add the 'development_untrusted_held' ACCEPTED outcome.
--
-- Conversation-less governed surfaces (e.g. Ask Bro) verify a governed reply but HOLD it (stash it under
-- a one-time id for a later, owner-chosen save) instead of posting it to a conversation — so an accepted
-- held turn links NO `messages` row. The 0014 CHECK ties every accepted outcome to a message, so it must be
-- widened. SQLite cannot ALTER a CHECK constraint, so `receipt_verification_attempts` is rebuilt with:
--   * the `outcome` set widened to include 'development_untrusted_held';
--   * the accepted<->message invariant widened so a 'development_untrusted_held' attempt has message_id NULL
--     (like 'blocked'), while 'trusted_verified'/'development_untrusted' still REQUIRE a message.
-- All existing evidence rows are preserved verbatim (same column order). The verify->consume->replay-ledger
-- transaction is unchanged; only the accept persistence of the held path differs.
--
-- FK note: migrations run inside `BEGIN IMMEDIATE` (db.rs), where `PRAGMA foreign_keys` is a no-op, so the
-- standard 12-step rebuild cannot toggle it off. Dropping the old table fires the receipt_ids_seen.attempt_id
-- `ON DELETE SET NULL` action (harmless — that ledger is empty whenever no governed turn has been ACCEPTED,
-- i.e. always under the shipped NoTrustedManifest fail-closed path). The backlinks are then restored from the
-- rebuilt table by receipt_id, so no audit linkage is lost even if accepted rows existed.

CREATE TABLE receipt_verification_attempts_v16 (
    id                    TEXT PRIMARY KEY,
    wire_envelope_jcs_b64 TEXT NOT NULL,
    wire_signature_b64    TEXT NOT NULL,
    receipt_id            TEXT,
    key_id                TEXT,
    envelope_jcs          BLOB,
    signature             BLOB,
    outcome               TEXT NOT NULL
        CHECK (outcome IN ('trusted_verified', 'development_untrusted', 'development_untrusted_held', 'blocked')),
    verification_error    TEXT,
    nonce                 TEXT,
    message_id            TEXT REFERENCES messages(id) ON DELETE RESTRICT,
    verified_at           TEXT NOT NULL,
    -- Accepted<->message invariant (design §4), widened for the held accept:
    --   * 'blocked' and 'development_untrusted_held' link NO message (message_id NULL);
    --   * 'trusted_verified' / 'development_untrusted' ALWAYS link exactly one message.
    CHECK (
        (outcome IN ('blocked', 'development_untrusted_held') AND message_id IS NULL)
        OR (outcome IN ('trusted_verified', 'development_untrusted') AND message_id IS NOT NULL)
    )
);

INSERT INTO receipt_verification_attempts_v16
    (id, wire_envelope_jcs_b64, wire_signature_b64, receipt_id, key_id, envelope_jcs,
     signature, outcome, verification_error, nonce, message_id, verified_at)
    SELECT id, wire_envelope_jcs_b64, wire_signature_b64, receipt_id, key_id, envelope_jcs,
           signature, outcome, verification_error, nonce, message_id, verified_at
    FROM receipt_verification_attempts;

DROP TABLE receipt_verification_attempts;
ALTER TABLE receipt_verification_attempts_v16 RENAME TO receipt_verification_attempts;

CREATE INDEX IF NOT EXISTS idx_receipt_attempts_receipt_id
    ON receipt_verification_attempts (receipt_id);
CREATE INDEX IF NOT EXISTS idx_receipt_attempts_verified_at
    ON receipt_verification_attempts (verified_at);

-- Restore any receipt_ids_seen -> attempt backlinks the implicit drop-delete may have NULLed (a no-op when
-- the ledger is empty, i.e. under the shipped fail-closed path). A receipt_id is accepted at most once, so
-- the match is unambiguous.
UPDATE receipt_ids_seen
SET attempt_id = (
    SELECT a.id FROM receipt_verification_attempts a
    WHERE a.receipt_id = receipt_ids_seen.receipt_id
      AND a.outcome IN ('trusted_verified', 'development_untrusted', 'development_untrusted_held')
    LIMIT 1
)
WHERE attempt_id IS NULL;
