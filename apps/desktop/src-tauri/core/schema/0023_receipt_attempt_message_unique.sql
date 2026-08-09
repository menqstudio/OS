-- One accepted attempt per message — enforced, not assumed.
--
-- `MESSAGE_RECEIPT_PROJECTION` (repo.rs) paints the chat trust badge from the outcome of a
-- message's accepted verification attempt. It read that outcome with `LIMIT 1` and no `ORDER BY`,
-- and nothing in the schema said a message could only have one: 0014/0016 give `message_id` no
-- UNIQUE constraint and no index at all. Two accepted attempts on one message therefore made the
-- badge whichever row SQLite happened to hand back first — a green "trusted_verified" badge could
-- be decided by a query plan.
--
-- The invariant the code already relies on is real: `receipt_store::verify_and_record_receipt`
-- CREATES the message inside the same transaction as the attempt that names it (receipt_store.rs
-- ~:437-467), so a message is named by exactly one accepted attempt. This states that in the
-- schema so it stops being a property of one call site.
--
-- Partial (`WHERE message_id IS NOT NULL`) because the widened 0016 invariant deliberately leaves
-- `message_id` NULL for every 'blocked' and 'development_untrusted_held' row, and those are many.
-- SQLite treats NULLs as distinct in a UNIQUE index anyway; the predicate makes the intent explicit
-- and keeps the index small.
--
-- The index doubles as the missing lookup index: the projection's correlated subquery ran a full
-- scan of the attempts table for every message in a conversation page.
CREATE UNIQUE INDEX IF NOT EXISTS idx_receipt_attempts_message_unique
    ON receipt_verification_attempts (message_id)
    WHERE message_id IS NOT NULL;
