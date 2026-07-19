-- Migration 0008: approvals actually gate run-step execution.
-- A run step can be flagged as requiring approval; approvals can point back at
-- the entity that requested them, so a step's execution can wait on a decision.

ALTER TABLE run_steps ADD COLUMN requires_approval INTEGER NOT NULL DEFAULT 0;
ALTER TABLE approvals ADD COLUMN entity_type TEXT;
ALTER TABLE approvals ADD COLUMN entity_id TEXT;

CREATE INDEX IF NOT EXISTS idx_approvals_entity ON approvals(entity_id, status);
