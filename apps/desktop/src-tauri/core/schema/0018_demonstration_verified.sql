-- Honest live DEMONSTRATION-verified badge (additive; does NOT touch the trust-critical records).
--
-- A message may carry a "demonstration_verified" badge when its reply was produced INSIDE the in-process
-- governed chain (challenge -> lease -> attest -> sign -> verify_and_accept) and verified under the
-- compiled-in DEMONSTRATION anchor (tcb::DEMO_*) — NEVER the production offline root, and the executor is not
-- session-0-contained. It is therefore demonstration custody, never production `trusted_verified`.
--
-- This is a SEPARATE, additive table on purpose: it deliberately does NOT touch
-- `receipt_verification_attempts`, whose CHECK-constrained rows back the PRODUCTION development_untrusted /
-- trusted_verified badges (rebuilding that table is a trust-critical migration we do not entangle here). A row
-- is written ONLY by the desktop AFTER the in-process chain returns trusted_verified for that exact message,
-- so the badge is backed by a real verification, not a settable flag. The message-receipt projection derives
-- 'demonstration_verified' from this table as a fallback (a real production receipt always takes precedence).
CREATE TABLE IF NOT EXISTS demonstration_verified_messages (
    message_id   TEXT PRIMARY KEY
                 REFERENCES messages(id) ON DELETE CASCADE,
    recorded_at  TEXT NOT NULL
);
