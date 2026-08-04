-- Phase 8 (Automation) execution: an append-only log of automation runs. Running an automation
-- performs its action LOCALLY (no AI provider — an AI-touching action would have to route through the
-- governed, fail-closed chain) and records the outcome here so the user can see what fired and when.
-- Cascades with its automation so deleting an automation cleans up its run history.
CREATE TABLE IF NOT EXISTS automation_runs (
    id            TEXT PRIMARY KEY,
    automation_id TEXT NOT NULL REFERENCES automations(id) ON DELETE CASCADE,
    ran_at        TEXT NOT NULL,
    outcome       TEXT NOT NULL,          -- 'ok' | 'failed'
    detail        TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_automation_runs ON automation_runs(automation_id, ran_at);
