-- Migration 0012: give a chat message its governed-turn receipt verdict.
--
-- A governed AI turn runs behind the engine wall and returns a VERIFIED signed
-- receipt; the desktop stores only the resulting product tag alongside the turn
-- ('verified' when the receipt verified, 'blocked' on a fail-closed verdict).
-- Ungoverned turns carry no tag (NULL) — no verified receipt, no badge.
--
-- SQLite cannot `ALTER TABLE ... ADD CHECK`, so — as with 0011 — the value
-- domain is closed with BEFORE INSERT / BEFORE UPDATE triggers that abort on
-- anything other than 'verified' | 'blocked' | NULL. The tag is derived
-- server-side from interpret_bridge_result (ai.rs); it is never client-supplied.

ALTER TABLE messages ADD COLUMN receipt TEXT;

CREATE TRIGGER IF NOT EXISTS trg_messages_receipt_ins BEFORE INSERT ON messages
WHEN NEW.receipt IS NOT NULL AND NEW.receipt NOT IN ('verified', 'blocked')
BEGIN
    SELECT RAISE(ABORT, 'invalid messages.receipt');
END;

CREATE TRIGGER IF NOT EXISTS trg_messages_receipt_upd BEFORE UPDATE OF receipt ON messages
WHEN NEW.receipt IS NOT NULL AND NEW.receipt NOT IN ('verified', 'blocked')
BEGIN
    SELECT RAISE(ABORT, 'invalid messages.receipt');
END;
