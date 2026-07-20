-- Migration 0011: database-level integrity for the gated state machines.
--
-- SQLite cannot `ALTER TABLE ... ADD CHECK`, so instead of rebuilding the
-- tables the enum-like status columns are guarded with BEFORE INSERT /
-- BEFORE UPDATE triggers that abort on values outside the valid set. The
-- allowed values mirror the canonical lists in core/src/domain.rs
-- (RUN_STATUSES, STEP_STATUSES, and APPROVAL_DECISIONS plus 'pending').
-- Any write path — Rust, a future command, or a hand-written trigger — is
-- now rejected at the DB layer instead of silently vanishing from
-- status-filtered queries.

-- runs.status
CREATE TRIGGER IF NOT EXISTS trg_runs_status_ins BEFORE INSERT ON runs
WHEN NEW.status NOT IN ('drafted', 'queued', 'planning', 'awaiting_approval',
                        'running', 'paused', 'succeeded', 'failed', 'cancelled')
BEGIN
    SELECT RAISE(ABORT, 'invalid runs.status');
END;

CREATE TRIGGER IF NOT EXISTS trg_runs_status_upd BEFORE UPDATE OF status ON runs
WHEN NEW.status NOT IN ('drafted', 'queued', 'planning', 'awaiting_approval',
                        'running', 'paused', 'succeeded', 'failed', 'cancelled')
BEGIN
    SELECT RAISE(ABORT, 'invalid runs.status');
END;

-- run_steps.status
CREATE TRIGGER IF NOT EXISTS trg_run_steps_status_ins BEFORE INSERT ON run_steps
WHEN NEW.status NOT IN ('pending', 'active', 'done', 'failed', 'skipped')
BEGIN
    SELECT RAISE(ABORT, 'invalid run_steps.status');
END;

CREATE TRIGGER IF NOT EXISTS trg_run_steps_status_upd BEFORE UPDATE OF status ON run_steps
WHEN NEW.status NOT IN ('pending', 'active', 'done', 'failed', 'skipped')
BEGIN
    SELECT RAISE(ABORT, 'invalid run_steps.status');
END;

-- approvals.status ('consumed' marks a spent grant: set when a gated step
-- completes and its approval is used up — see repo::approvals::consume_for).
CREATE TRIGGER IF NOT EXISTS trg_approvals_status_ins BEFORE INSERT ON approvals
WHEN NEW.status NOT IN ('pending', 'approved', 'rejected', 'consumed')
BEGIN
    SELECT RAISE(ABORT, 'invalid approvals.status');
END;

CREATE TRIGGER IF NOT EXISTS trg_approvals_status_upd BEFORE UPDATE OF status ON approvals
WHEN NEW.status NOT IN ('pending', 'approved', 'rejected', 'consumed')
BEGIN
    SELECT RAISE(ABORT, 'invalid approvals.status');
END;

-- approvals.entity_id is loose text (no FK), so deleting a run step would
-- otherwise strand its approvals — and a stale grant against a reused id must
-- never unlock anything. Clean them up with the step.
CREATE TRIGGER IF NOT EXISTS trg_run_steps_delete_approvals AFTER DELETE ON run_steps
BEGIN
    DELETE FROM approvals WHERE entity_type = 'run_step' AND entity_id = OLD.id;
END;

-- run_steps ordering relies on position being unique per run, but nothing
-- enforced it. Renumber each run's steps 1..N deterministically (current
-- position, then id, matching the existing ORDER BY position semantics) so
-- any historical duplicates are resolved before uniqueness is locked in.
UPDATE run_steps SET position = (
    SELECT COUNT(*)
    FROM run_steps AS s
    WHERE s.run_id = run_steps.run_id
      AND (s.position < run_steps.position
           OR (s.position = run_steps.position AND s.id < run_steps.id))
) + 1;

CREATE UNIQUE INDEX IF NOT EXISTS idx_run_steps_run_pos ON run_steps(run_id, position);
