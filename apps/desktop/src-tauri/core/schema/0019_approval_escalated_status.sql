-- Escalation (repo::approvals::escalate) routes a pending approval to higher review
-- (tier A3) without deciding it — neither granted nor denied, authorizing no execution.
-- 'escalated' is therefore a legitimate approvals.status, but the status guards added in
-- 0011 only permit pending/approved/rejected/consumed, so any escalate is aborted with
-- 'invalid approvals.status'. SQLite has no ALTER TRIGGER, so drop and recreate both the
-- INSERT and UPDATE status guards with 'escalated' added to the allowed set. This only
-- WIDENS what is allowed; every previously-valid status stays valid.
DROP TRIGGER IF EXISTS trg_approvals_status_ins;
DROP TRIGGER IF EXISTS trg_approvals_status_upd;

CREATE TRIGGER trg_approvals_status_ins BEFORE INSERT ON approvals
WHEN NEW.status NOT IN ('pending', 'approved', 'rejected', 'consumed', 'escalated')
BEGIN
    SELECT RAISE(ABORT, 'invalid approvals.status');
END;

CREATE TRIGGER trg_approvals_status_upd BEFORE UPDATE OF status ON approvals
WHEN NEW.status NOT IN ('pending', 'approved', 'rejected', 'consumed', 'escalated')
BEGIN
    SELECT RAISE(ABORT, 'invalid approvals.status');
END;
