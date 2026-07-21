-- T-011 concurrency fix: a run step is claimed for execution BEFORE the provider
-- call, so one approval can start exactly one provider execution.
--
-- `execution_attempt_id` is a fresh one-time token written when a step is claimed
-- (the `... IS NULL` guard on the claiming UPDATE is the mutual exclusion — a second
-- concurrent claim writes 0 rows and is refused before any provider dispatch). Only
-- the claiming attempt may complete or fail that step, so a stale/duplicate dispatch
-- cannot persist a result. Nullable / backfill-safe: pre-existing rows carry NULL.
ALTER TABLE run_steps ADD COLUMN execution_attempt_id TEXT;
