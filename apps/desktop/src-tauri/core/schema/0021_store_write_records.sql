-- Phase 5 (Memory & Knowledge): a durable, append-only LOCAL WRITE RECORD for every
-- memory-entry and knowledge-note write.
--
-- WHY: until now a memory or knowledge write was an ordinary local row with nothing
-- vouching for it — no evidence that the row is the one that was written, and nothing
-- that would notice a later out-of-band edit. This migration adds the durable half of
-- the record; `core/src/local_write_record.rs` owns the transaction that appends it in
-- the SAME transaction as the write itself (create / update / delete), exactly as
-- `receipt_store.rs` records an evidence attempt inside the verify transaction.
--
-- WHAT A RECORD PROVES (and nothing more):
--   * the exact content bytes the store held at write time, as a SHA-256 over a
--     canonical (RFC-8785-shaped, sorted-key, compact) envelope of the subject's fields;
--   * that the row on screen still hashes to its own latest record (or that it has
--     DIVERGED — an out-of-band edit is detectable, not silently absorbed);
--   * that the ledger itself is unbroken: every record carries the previous record's
--     hash, the sequence is contiguous from 1, and the table is append-only at the DB
--     layer (UPDATE and DELETE both RAISE).
--
-- WHAT IT DOES **NOT** PROVE — read this before naming anything on screen:
--   * NOTHING is signed. There is no key, no manifest, no external authority. A record
--     is produced by the same local process that performs the write, so an attacker who
--     already owns that process can append a consistent chain of their own.
--   * It is therefore NOT a governed receipt and NOT "verified". The production trust
--     vocabulary (`trusted_verified`, `development_untrusted`, `demonstration_verified`)
--     belongs to `receipt_verification_attempts` and MUST NOT be reused for these rows.
--     The honest words are "recorded" / "local write record" / "content diverged".
--
-- NO BACKFILL, EVER: rows written before this migration get NO record. Manufacturing a
-- record for a write nobody witnessed would be a forged receipt. Their honest state is
-- `Unrecorded`, and the API reports exactly that.
--
-- NO FOREIGN KEY to `memory_entries` / `knowledge_notes` is declared ON PURPOSE: a
-- `deleted` record must survive the row it describes, otherwise the one write that most
-- needs evidence would erase its own evidence.

CREATE TABLE IF NOT EXISTS store_write_records (
    -- Chain position. Explicit (never AUTOINCREMENT-assigned) because the position is an
    -- input to `record_sha256`; the INSERT trigger below requires it to be exactly
    -- MAX(seq)+1, and the PRIMARY KEY makes a raced duplicate fail the whole write.
    seq                INTEGER PRIMARY KEY,
    id                 TEXT NOT NULL UNIQUE,
    protocol           TEXT NOT NULL
                       CHECK (protocol = 'brops.local-write-record.v1'),
    subject_kind       TEXT NOT NULL
                       CHECK (subject_kind IN ('memory_entry', 'knowledge_note')),
    subject_id         TEXT NOT NULL,
    operation          TEXT NOT NULL
                       CHECK (operation IN ('created', 'updated', 'deleted')),
    -- SHA-256 (lowercase hex) of the canonical envelope of the subject's fields.
    content_sha256     TEXT NOT NULL
                       CHECK (length(content_sha256) = 64),
    -- The previous record's `record_sha256`; the genesis record carries 64 zeros.
    prev_record_sha256 TEXT NOT NULL
                       CHECK (length(prev_record_sha256) = 64),
    record_sha256      TEXT NOT NULL UNIQUE
                       CHECK (length(record_sha256) = 64),
    recorded_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_store_write_records_subject
    ON store_write_records (subject_kind, subject_id, seq);

-- Append-only at the DB layer, not merely by convention: rewriting or dropping a record
-- is the exact tamper the chain exists to detect, so SQLite refuses it outright. (The
-- Rust API never issues either statement; these triggers bind anything else that opens
-- the database file too.)
CREATE TRIGGER IF NOT EXISTS trg_store_write_records_no_update
BEFORE UPDATE ON store_write_records
BEGIN
    SELECT RAISE(ABORT, 'store_write_records is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_store_write_records_no_delete
BEFORE DELETE ON store_write_records
BEGIN
    SELECT RAISE(ABORT, 'store_write_records is append-only: DELETE is forbidden');
END;

-- Every appended record must extend the CURRENT head: its `seq` is MAX(seq)+1 and its
-- `prev_record_sha256` is the head's `record_sha256` (or the genesis 64 zeros on an empty
-- ledger). A fork, a gap, or a re-pointed link is rejected by the database itself, so the
-- linkage cannot drift even if a future caller forgets to compute it.
CREATE TRIGGER IF NOT EXISTS trg_store_write_records_extends_head
BEFORE INSERT ON store_write_records
FOR EACH ROW
WHEN NEW.seq <> (SELECT COALESCE(MAX(seq), 0) + 1 FROM store_write_records)
  OR NEW.prev_record_sha256 <> COALESCE(
        (SELECT record_sha256 FROM store_write_records ORDER BY seq DESC LIMIT 1),
        '0000000000000000000000000000000000000000000000000000000000000000')
BEGIN
    SELECT RAISE(ABORT, 'store_write_records: an appended record must extend the current chain head');
END;
