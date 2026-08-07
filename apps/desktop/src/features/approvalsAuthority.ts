// ── Approvals · what actually backs an approval state ────────────────────────
//
// An approval is the mechanism by which the owner authorises something, so the
// worst defect this surface can ship is showing a row as GRANTED when nothing
// established that it was. This module is the single place that decides what the
// page is allowed to claim, kept free of React so it can be tested directly.
//
// THE AUTHORITY DEFINITION (the only one that counts) lives in Rust, in
// `src-tauri/core/src/repo.rs :: approvals::approved_for`. A grant is honoured by
// the backend ONLY when the row satisfies, all together:
//
//     status = 'approved'
//     AND decided_at            IS NOT NULL
//     AND confirmed_at          IS NOT NULL
//     AND confirmation_method   = 'native'
//     AND confirmation_digest   IS NOT NULL
//     AND nonce                 IS NULL          (the one-time nonce was consumed)
//
// Those markers are written together in exactly one place — `approve_confirmed`,
// reached only through the `confirm_approval` command, which drives a native OS
// dialog from Rust that the webview cannot forge. The reject-only `decide` path
// can never produce them.
//
// The renderer can SEE four of those six markers: `status`, `decidedAt`,
// `confirmedAt`/`confirmedBy` and `confirmationMethod`. `confirmation_digest` and
// `nonce` are `#[serde(skip_serializing)]` enforcement tokens and never cross the
// IPC boundary (domain.rs) — so the page can never fully re-verify a grant, only
// corroborate it. That asymmetry is stated on screen rather than papered over.
//
// Consequences encoded below:
//   • `status === 'approved'` ALONE is not a grant. A row that says approved but
//     carries no native-confirmation provenance is `unconfirmed`, and the page
//     must show it as such — never with the green tone, the live mark or the
//     APPROVED seal.
//   • 'granted' and 'confirmed' are NOT synonyms for approved. No backend writer
//     produces either string; treating them as green meant any row carrying that
//     free text would have painted itself authorised.
//   • 'consumed' is a real backend status (`consume_for`) and used to fall through
//     to the pending arm, so an already-spent approval read as "Awaiting decision".

import type { Approval } from '../domain/entities';

/** The grant markers this renderer can actually observe, named as the UI names them. */
export type GrantMarker = 'decidedAt' | 'confirmedAt' | 'confirmedBy' | 'nativeConfirmation';

/** The enforcement tokens the backend deliberately withholds from the renderer, so the
 *  page can corroborate a grant but never fully re-verify one. Stated, not hidden. */
export const WITHHELD_MARKERS = ['confirmation_digest', 'nonce'] as const;

export type ApprovalState =
  /** Awaiting a human decision — the only actionable state. */
  | 'pending'
  /** Owner-authorised: every observable native-confirmation marker is present. */
  | 'granted'
  /** Says `approved`, but the native-confirmation provenance is absent or wrong. */
  | 'unconfirmed'
  /** Rejected through the fail-safe reject path. */
  | 'denied'
  /** Routed to A3 review. Not a verdict: authorises nothing. */
  | 'escalated'
  /** A grant that has already been spent against its gating tuple. */
  | 'consumed'
  /** Timed out without a decision; authorises nothing. */
  | 'expired'
  /** Under engine review. Not a verdict. */
  | 'reviewing'
  /** A status string this build does not know. Rendered verbatim, toneless. */
  | 'unknown';

export interface Classification {
  state: ApprovalState;
  /** The status string exactly as the backend sent it. */
  raw: string;
  /** For `unconfirmed`, the observable grant markers this record does NOT carry. */
  missing: GrantMarker[];
  /** TRUE only when the page established the row as an owner-authorised grant.
   *  The `granted` tone, the live mark and the APPROVED seal hang off this and
   *  nothing else. */
  authorized: boolean;
  /** The backend accepts grant/deny/escalate on pending rows only. */
  actionable: boolean;
}

const nonEmpty = (v: unknown): v is string => typeof v === 'string' && v.trim() !== '';

/**
 * Which observable grant markers are absent. An empty array means every marker the
 * renderer can see corroborates a native-confirmed grant — it does NOT mean the page
 * verified the withheld digest/nonce, which only the backend can do.
 */
export function missingGrantMarkers(a: Approval): GrantMarker[] {
  const missing: GrantMarker[] = [];
  if (!nonEmpty(a.decidedAt)) missing.push('decidedAt');
  if (!nonEmpty(a.confirmedAt)) missing.push('confirmedAt');
  if (!nonEmpty(a.confirmedBy)) missing.push('confirmedBy');
  if (a.confirmationMethod !== 'native') missing.push('nativeConfirmation');
  return missing;
}

/** Classify one real approval record. Never guesses: an unrecognised status stays `unknown`. */
export function classifyApproval(a: Approval): Classification {
  const raw = typeof a.status === 'string' ? a.status : '';
  const s = raw.trim().toLowerCase();
  const none: GrantMarker[] = [];

  if (s === 'approved') {
    const missing = missingGrantMarkers(a);
    return missing.length === 0
      ? { state: 'granted', raw, missing: none, authorized: true, actionable: false }
      : { state: 'unconfirmed', raw, missing, authorized: false, actionable: false };
  }
  if (s === 'pending') return { state: 'pending', raw, missing: none, authorized: false, actionable: true };
  if (s === 'rejected' || s === 'denied') return { state: 'denied', raw, missing: none, authorized: false, actionable: false };
  if (s === 'escalated') return { state: 'escalated', raw, missing: none, authorized: false, actionable: false };
  if (s === 'consumed') return { state: 'consumed', raw, missing: none, authorized: false, actionable: false };
  if (s === 'expired') return { state: 'expired', raw, missing: none, authorized: false, actionable: false };
  if (s === 'reviewing') return { state: 'reviewing', raw, missing: none, authorized: false, actionable: false };
  return { state: 'unknown', raw, missing: none, authorized: false, actionable: false };
}

/**
 * Is this unknown value the Approval record shape? Used on a command REPLY before the
 * page announces an outcome from it: a reply that is not a readable approval record
 * establishes nothing, so the page says that instead of claiming the verdict it hoped for.
 */
export function isApprovalRecord(v: unknown): v is Approval {
  if (typeof v !== 'object' || v === null) return false;
  const o = v as Record<string, unknown>;
  return typeof o.id === 'string' && typeof o.status === 'string';
}

// ── queue counts ─────────────────────────────────────────────────────────────

/** Every bucket a row can land in. Exhaustive by construction: `total` equals the sum
 *  of the rest, so the stats strip can never show four numbers with a silent remainder. */
export interface QueueCounts {
  total: number;
  pending: number;
  granted: number;
  unconfirmed: number;
  denied: number;
  escalated: number;
  consumed: number;
  /** expired · reviewing · unrecognised — decided nothing, authorises nothing. */
  other: number;
}

const ZERO: QueueCounts = {
  total: 0, pending: 0, granted: 0, unconfirmed: 0,
  denied: 0, escalated: 0, consumed: 0, other: 0,
};

export function countQueue(items: readonly Approval[]): QueueCounts {
  const c: QueueCounts = { ...ZERO, total: items.length };
  for (const a of items) {
    switch (classifyApproval(a).state) {
      case 'pending': c.pending += 1; break;
      case 'granted': c.granted += 1; break;
      case 'unconfirmed': c.unconfirmed += 1; break;
      case 'denied': c.denied += 1; break;
      case 'escalated': c.escalated += 1; break;
      case 'consumed': c.consumed += 1; break;
      default: c.other += 1; break;
    }
  }
  return c;
}

/** The buckets that make up `total`, for the reconciliation invariant. */
export function bucketSum(c: QueueCounts): number {
  return c.pending + c.granted + c.unconfirmed + c.denied + c.escalated + c.consumed + c.other;
}

// ── what this page can actually do ───────────────────────────────────────────

export type ActionKind = 'grant' | 'deny' | 'escalate';

export interface ActionCapability {
  kind: ActionKind;
  /** The real backend command this action sends. */
  command: string;
  /** Granted by the window capability set (`src-tauri/capabilities/default.json`). */
  granted: boolean;
  /** The backend adjudicates it behind a native OS dialog the webview cannot forge. */
  nativeConfirmed: boolean;
  /** It moves privilege TOWARDS the agent (grant) rather than away from it. */
  grantsPrivilege: boolean;
}

/**
 * The three actions this page offers, each pinned to the real command behind it.
 *
 * The deliberate asymmetry: the generic approve verb `decide_approval` is DENIED, while
 * `reject_approval` is GRANTED — privilege can always be taken away, and is only ever
 * given through the one narrow, natively-confirmed path. `confirm_approval` is the only
 * approve path there is, and it is granted precisely because the approval is adjudicated
 * outside the webview. This page must never render a control for `decide_approval`.
 */
export const APPROVAL_ACTIONS: Readonly<Record<ActionKind, ActionCapability>> = {
  grant: {
    kind: 'grant', command: 'confirm_approval',
    granted: true, nativeConfirmed: true, grantsPrivilege: true,
  },
  deny: {
    kind: 'deny', command: 'reject_approval',
    granted: true, nativeConfirmed: false, grantsPrivilege: false,
  },
  escalate: {
    kind: 'escalate', command: 'escalate_approval',
    granted: true, nativeConfirmed: false, grantsPrivilege: false,
  },
};

/** The generic approve verb, DENIED to this window on purpose. Exported so the guard
 *  test can assert no control on this page is ever wired to it. */
export const DENIED_DECIDE_COMMAND = 'decide_approval';

/** Can this row take this action? Only pending rows, and only granted commands. */
export function canAct(kind: ActionKind, c: Classification): boolean {
  return APPROVAL_ACTIONS[kind].granted && c.actionable;
}

// ── outcome of a real command reply ──────────────────────────────────────────

export type OutcomeKind =
  /** The reply is a readable approval record; `state` is what it actually says. */
  | 'recorded'
  /** The command resolved but returned nothing the page can read as an approval. */
  | 'unreadable'
  /** The owner dismissed the native confirmation dialog — no decision was made. */
  | 'cancelled'
  /** The backend refused. `reason` is its own words, verbatim. */
  | 'refused';

export interface Outcome {
  kind: OutcomeKind;
  state?: ApprovalState;
  reason?: string;
}

/**
 * What a resolved command reply established. Deliberately pessimistic: the page
 * announces the state the RECORD carries, never the state the click intended. A
 * `confirm_approval` that comes back without native-confirmation provenance is
 * announced as `unconfirmed`, not as "Granted".
 */
export function readReply(reply: unknown): Outcome {
  if (!isApprovalRecord(reply)) return { kind: 'unreadable' };
  return { kind: 'recorded', state: classifyApproval(reply).state };
}

/**
 * A REJECTED command. `confirm_approval` returns "approval was not confirmed" when the
 * owner dismisses the native dialog — that is a non-decision, not a failure, and must not
 * be shown as an error. Everything else is the backend's refusal, surfaced verbatim.
 */
export function readRejection(error: unknown): Outcome {
  const reason = error instanceof Error ? error.message : String(error);
  if (/was not confirmed|cancell?ed by (the )?user|dialog dismissed/i.test(reason)) {
    return { kind: 'cancelled', reason };
  }
  return { kind: 'refused', reason };
}
