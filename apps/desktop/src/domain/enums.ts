// Canonical BroPS enums — reconciled from docs/architecture/DATA_MODEL.md and
// IMPLEMENTATION_EXECUTION_HANDOFF.md. This is the single machine vocabulary
// the prototype uses; UX statuses in product/ map onto these.

export type TaskStatus = 'inbox' | 'planned' | 'active' | 'blocked' | 'review' | 'done' | 'cancelled';
export type ProjectStatus = 'planned' | 'active' | 'blocked' | 'completed' | 'archived';
export type AgentStatus = 'offline' | 'idle' | 'observing' | 'thinking' | 'working' | 'blocked' | 'review' | 'failed' | 'completed';
export type RunStatus = 'drafted' | 'queued' | 'planning' | 'awaiting_approval' | 'running' | 'paused' | 'succeeded' | 'failed' | 'cancelled';
export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'expired' | 'cancelled';
export type ApprovalLevel = 'A0' | 'A1' | 'A2' | 'A3';
export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';
export type Priority = 'low' | 'normal' | 'high' | 'critical';
export type Severity = 'info' | 'success' | 'warning' | 'error' | 'critical';
export type Lang = 'hy' | 'en' | 'ru';
export type Theme = 'dark' | 'light';

// Value lists for form controls — mirror the allowed sets in src-tauri/core.
export const TASK_STATUSES: TaskStatus[] = ['inbox', 'planned', 'active', 'blocked', 'review', 'done', 'cancelled'];
export const PRIORITIES: Priority[] = ['low', 'normal', 'high', 'critical'];
export const PROJECT_STATUSES: ProjectStatus[] = ['planned', 'active', 'blocked', 'completed', 'archived'];
/**
 * Decision statuses, and the family each one puts a decision in — ninth audit `I-11`.
 *
 * `Decision.status` is `string` on the entity and `TEXT` with no CHECK in `0002_decisions.sql`,
 * because the value is READ from a ledger this app does not own: narrowing the entity type would
 * claim a contract with the engine that nobody has written, and `Decisions.tsx` classifies with
 * deliberately tolerant substring rules for exactly that reason. What was missing is the other
 * half — a declared vocabulary for the statuses this repository DOES know a source for, so a
 * fixture cannot invent one. `status: 'accepted'` in the browser spec was such an invention: it
 * matches neither of the page's two families and therefore renders through the fallback, which
 * means the fixture would have produced an identical screenshot for the word `zzz`.
 *
 * The family attached to each word is not a new rule — it is what `statusMeta` already computes,
 * and `decisions status vocabulary` asserts the two agree, so this map cannot drift away from the
 * page it describes.
 */
export const DECISION_STATUS_FAMILY = {
  proposed: 'waiting',    // the ONLY value the desktop store itself writes (repo.rs decisions::create)
  open: 'waiting',
  review: 'waiting',
  accepted: 'settled',
  superseded: 'settled',
  rejected: 'blocked',
  blocked: 'blocked',
} as const;
export type DecisionStatus = keyof typeof DECISION_STATUS_FAMILY;
export type DecisionStatusFamily = (typeof DECISION_STATUS_FAMILY)[DecisionStatus];
export const DECISION_STATUSES = Object.keys(DECISION_STATUS_FAMILY) as DecisionStatus[];

export type MemoryKind = 'fact' | 'preference' | 'note' | 'reference';
export const MEMORY_KINDS: MemoryKind[] = ['fact', 'preference', 'note', 'reference'];
export const RUN_STATUSES: RunStatus[] = ['drafted', 'queued', 'planning', 'awaiting_approval', 'running', 'paused', 'succeeded', 'failed', 'cancelled'];
export const INTEGRATION_STATUSES = ['disconnected', 'connected', 'error'] as const;
export const STEP_STATUSES = ['pending', 'active', 'done', 'failed', 'skipped'] as const;

// Maps a status-like value to a visual tone used by Badge/StatusPill.
export type Tone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'info';

export const statusTone: Record<string, Tone> = {
  // tasks / projects / runs
  inbox: 'neutral', planned: 'neutral', active: 'accent', running: 'accent',
  blocked: 'danger', review: 'warning', done: 'success', completed: 'success',
  succeeded: 'success', cancelled: 'neutral', archived: 'neutral',
  drafted: 'neutral', queued: 'neutral', planning: 'accent', paused: 'warning',
  awaiting_approval: 'warning', failed: 'danger',
  // agents
  offline: 'neutral', idle: 'neutral', observing: 'info', thinking: 'accent',
  working: 'accent',
  // approvals
  pending: 'warning', approved: 'success', rejected: 'danger', expired: 'neutral',
  // integrations (error tone already defined under severity)
  disconnected: 'neutral', connected: 'success',
  // risk / priority / severity
  low: 'neutral', normal: 'neutral', medium: 'warning', high: 'warning',
  critical: 'danger', info: 'info', success: 'success', warning: 'warning', error: 'danger',
};
