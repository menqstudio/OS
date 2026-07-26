-- Wave 3b: signed manifest snapshot + governed receipt forensic evidence.
CREATE TABLE IF NOT EXISTS manifest_current (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    payload_bytes BLOB NOT NULL,
    root_sig TEXT NOT NULL,
    root_key_id TEXT NOT NULL,
    manifest_epoch INTEGER NOT NULL CHECK (manifest_epoch >= 0),
    manifest_hash TEXT NOT NULL CHECK (length(manifest_hash) = 64 AND manifest_hash NOT GLOB '*[^0-9a-f]*'),
    accepted_at INTEGER NOT NULL CHECK (accepted_at >= 0)
);

CREATE TABLE IF NOT EXISTS manifest_floor (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    highest_epoch INTEGER NOT NULL CHECK (highest_epoch >= 0),
    manifest_hash TEXT NOT NULL CHECK (length(manifest_hash) = 64 AND manifest_hash NOT GLOB '*[^0-9a-f]*')
);

ALTER TABLE receipt_verification_attempts ADD COLUMN attestation_evidence_jcs BLOB;
ALTER TABLE receipt_verification_attempts ADD COLUMN attestation_signature BLOB;
ALTER TABLE receipt_verification_attempts ADD COLUMN supervisor_attestation_key_id TEXT;
ALTER TABLE receipt_verification_attempts ADD COLUMN run_id TEXT;
ALTER TABLE receipt_verification_attempts ADD COLUMN execution_attempt_id TEXT;
ALTER TABLE receipt_verification_attempts ADD COLUMN lease_id TEXT;
ALTER TABLE receipt_verification_attempts ADD COLUMN challenge_accepted_at_ms INTEGER;
ALTER TABLE receipt_verification_attempts ADD COLUMN record_handle TEXT;
ALTER TABLE receipt_verification_attempts ADD COLUMN lease_handle TEXT;
ALTER TABLE receipt_verification_attempts ADD COLUMN execution_receipt_handle TEXT;
ALTER TABLE receipt_verification_attempts ADD COLUMN output_sha256 TEXT;
ALTER TABLE receipt_verification_attempts ADD COLUMN output_bytes INTEGER;
ALTER TABLE receipt_verification_attempts ADD COLUMN evidence_final_event_hash TEXT;
ALTER TABLE receipt_verification_attempts ADD COLUMN evidence_event_count INTEGER;
ALTER TABLE receipt_verification_attempts ADD COLUMN evidence_last_sequence INTEGER;
ALTER TABLE receipt_verification_attempts ADD COLUMN evidence_head_sequence INTEGER;

CREATE INDEX IF NOT EXISTS idx_receipt_attempts_run_attempt
    ON receipt_verification_attempts(run_id, execution_attempt_id);
