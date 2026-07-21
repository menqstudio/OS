-- T-011: durable approval provenance + native-confirmation record.
--
-- Replaces the process-memory-only self-approval origin (lost on restart) with a
-- persisted principal, and binds a decision to the exact request it was raised for
-- (request_digest) with a one-time nonce (replay-safety). The confirmation columns
-- record the renderer-independent native confirmation that a privileged *approve*
-- now requires. All nullable/backfill-safe: pre-existing rows simply carry NULLs.
--
-- Enforcement note: these are the durable inputs to the decision flow implemented
-- in the repo/commands layer; the column presence alone changes nothing.

-- Stable enforcement identity of the requester (e.g. "webview:main"). The
-- self-approval check compares THIS, so it survives an app restart.
ALTER TABLE approvals ADD COLUMN origin_principal TEXT;

-- Per-process/session forensic id (audit only, never an enforcement authority —
-- an ephemeral id alone is not restart-safe).
ALTER TABLE approvals ADD COLUMN origin_session_id TEXT;

-- SHA-256 of the canonical JSON request envelope; recomputed from current state at
-- decision time and compared, so a mutated request cannot be approved by replay.
ALTER TABLE approvals ADD COLUMN request_digest TEXT;

-- One-time token consumed on decision; a second decision with a spent nonce fails.
ALTER TABLE approvals ADD COLUMN nonce TEXT;

-- When the renderer-independent native confirmation completed (NULL until then).
ALTER TABLE approvals ADD COLUMN confirmed_at TEXT;

-- Server-derived confirmer identity.
ALTER TABLE approvals ADD COLUMN confirmed_by TEXT;

-- How the approve was confirmed: currently "native".
ALTER TABLE approvals ADD COLUMN confirmation_method TEXT;

-- Digest of the exact envelope shown in the native dialog, so the confirmed request
-- provably equals the recorded one.
ALTER TABLE approvals ADD COLUMN confirmation_digest TEXT;
