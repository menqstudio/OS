-- Migration 0007: give run steps a produced result.
-- Executing a step asks the AI provider to produce the concrete output for that
-- step; the streamed text is stored here and the step is marked done.

ALTER TABLE run_steps ADD COLUMN result TEXT NOT NULL DEFAULT '';
