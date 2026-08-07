// Phase-9 (Integrations) — the honest state model for one external connector.
//
// WHAT AN INTEGRATION IS IN THIS PRODUCT
// --------------------------------------
// A row in the desktop's `integrations` table is a *declaration*: "this product knows
// about a channel called <name> served by <provider>". It is deliberately NOT a
// credential and NOT an open connection. The Phase-9 security gate (MASTER_EXECUTION_
// ROADMAP.md §Phase 9) says the desktop stores **no external secret**: the secret and
// the actual external call boundary live with the engine/operator sidecar. The record
// carries seven columns — id, name, provider, status, auth_ref, created_at, updated_at
// (src-tauri/core/src/domain.rs; `auth_ref` added by schema 0022) — and still no column
// that can hold a credential: `auth_ref` is a `scheme:locator` REFERENCE to a secret the
// engine or the operator holds, never the secret itself, and naming one proves nothing
// about it.
//
// WHY THIS MODULE EXISTS
// ----------------------
// `status` is the ONLY mutable field, and the Rust store is explicit about what writing
// it means: "Set a connector's local status. This records the desired state; it does not
// itself reach any external service." (repo.rs::integrations::set_status). So a row
// reading `status = 'connected'` proves that somebody pressed a button on this desktop —
// nothing more. Painting that as "Connected", with a green live pulse, is the product
// claiming a working external link it has never once tested. That is the exact class of
// defect liveIndicators.guard.test.ts was written for, one level up: the indicator IS
// bound to real read state, but the real read state does not mean what the label says.
//
// So the page renders FOUR independent facts instead of one, and each is allowed to say
// "I don't know":
//
//   1. declaration  — the row exists (always true for anything we render)
//   2. enablement   — what the LOCAL record says the owner asked for      (real, local)
//   3. credential   — whether the record even references an engine-held secret (never
//                     "provisioned": a reference is not proof the secret exists)
//   4. reachability — whether anything has ever actually been contacted    (see
//                     integrationsProbe.ts — today: nothing can be, and it says so)
//
// The composite verdict is fail-closed: `connected_verified` requires a real probe that
// really answered. Every other combination degrades to a state whose label admits what
// is missing. No code path can produce `connected_verified` from local data alone.

import type { Integration } from '../domain/entities';

/** The statuses the Rust store accepts (domain.rs `INTEGRATION_STATUSES`). Anything
 *  else arriving over IPC is unrecognized and must fail closed, never be read as on. */
export const RECORD_STATUSES = ['disconnected', 'connected', 'error'] as const;
export type RecordStatus = (typeof RECORD_STATUSES)[number];

// ── 2. Enablement — what the local record says ───────────────────────────────────────

/**
 * The owner's recorded intent, read from the local row. NEVER evidence of a working
 * link: `enabled` means "this desktop wrote 'connected' into its own SQLite row".
 */
export type Enablement = 'enabled' | 'not_enabled' | 'faulted' | 'unknown';

export function enablementOf(status: string): Enablement {
  if (status === 'connected') return 'enabled';
  if (status === 'disconnected') return 'not_enabled';
  if (status === 'error') return 'faulted';
  // Fail closed. An unrecognized status is not "probably fine" — it is a record this
  // build does not understand, and it must never be rendered as enabled.
  return 'unknown';
}

// ── 3. Credential custody ────────────────────────────────────────────────────────────

/**
 * Where the connector's secret lives, as far as the desktop can tell — which is: not
 * here. `referenced` means the record names an engine/operator-held secret; it is still
 * NOT proof that the secret exists or is valid, only that a handoff target is named.
 * There is deliberately no `provisioned` value: the desktop cannot prove that, ever.
 */
export type CredentialCustody = 'referenced' | 'no_reference';

/**
 * Today the backend record has no auth-reference column, so this returns `no_reference`
 * for every connector. It reads the field rather than hard-coding the answer so that the
 * day the Rust `Integration` grows `auth_ref`, this lights up without a UI rewrite — and
 * so the honest "no reference" statement is a *finding*, not a constant.
 */
export function credentialCustodyOf(record: Integration): CredentialCustody {
  const ref = (record as Integration & { authRef?: unknown }).authRef;
  return typeof ref === 'string' && ref.trim() !== '' ? 'referenced' : 'no_reference';
}

// ── 4. Reachability ──────────────────────────────────────────────────────────────────

/**
 * Whether anything was actually contacted, and by whom.
 *
 *  - `untested`      no probe has been attempted (the state every connector starts in)
 *  - `reachable`     a probe RAN and the backend explicitly answered `reachable: true`
 *  - `unreachable`   a probe RAN and the backend explicitly answered `reachable: false`
 *  - `indeterminate` a probe was attempted and produced no usable answer — this says
 *                    nothing about the service, only that we failed to learn anything
 *  - `unsupported`   this build cannot probe at all (no such command / capability-denied)
 *
 * `unsupported` and `indeterminate` are kept apart from `unreachable` on purpose: "we
 * could not ask" is a statement about us, "it did not answer" is a statement about them,
 * and collapsing the two would let a missing feature read as a broken service.
 */
export type ReachabilityState =
  | 'untested'
  | 'reachable'
  | 'unreachable'
  | 'indeterminate'
  | 'unsupported';

export interface Reachability {
  state: ReachabilityState;
  /** The honest machine reason, verbatim, for every state except `untested`. */
  reason?: string;
  /** ISO timestamp of the attempt. Absent for `untested` — nothing happened. */
  checkedAt?: string;
}

/** The starting state of every connector: nothing has been contacted. */
export const UNTESTED: Reachability = { state: 'untested' };

/** True only for a probe that really ran and really got an answer, either way. */
export function isAnswered(r: Reachability): boolean {
  return r.state === 'reachable' || r.state === 'unreachable';
}

// ── Composite verdict ────────────────────────────────────────────────────────────────

/**
 * What the product is allowed to claim about this connector.
 *
 *  - `connected_verified`  enabled AND a real probe really answered `reachable`
 *  - `enabled_unverified`  enabled locally, but nothing has been contacted (or the probe
 *                          could not answer) — the honest state of every connector today
 *  - `unreachable`         enabled locally, and a real probe says the channel did NOT answer
 *  - `faulted`             the store recorded a fault for this connector
 *  - `not_enabled`         the owner has not enabled it
 *  - `unknown`             the record's status is not one this build understands
 */
export type Verdict =
  | 'connected_verified'
  | 'enabled_unverified'
  | 'unreachable'
  | 'faulted'
  | 'not_enabled'
  | 'unknown';

/**
 * Fail-closed composition. A recorded fault or an unrecognized status outranks any probe
 * result (the worse state wins), and `connected_verified` is reachable by exactly one
 * path: locally enabled AND a probe that genuinely answered `reachable`.
 */
export function verdictOf(enablement: Enablement, reach: Reachability): Verdict {
  if (enablement === 'faulted') return 'faulted';
  if (enablement === 'unknown') return 'unknown';
  if (enablement === 'not_enabled') return 'not_enabled';
  if (reach.state === 'reachable') return 'connected_verified';
  if (reach.state === 'unreachable') return 'unreachable';
  return 'enabled_unverified';
}

/** The single predicate the UI may use to paint a "genuinely connected" affordance. */
export function isGenuinelyConnected(v: Verdict): boolean {
  return v === 'connected_verified';
}

/** Everything the page knows about one connector, derived — never fabricated. */
export interface ConnectorState {
  record: Integration;
  enablement: Enablement;
  credential: CredentialCustody;
  reachability: Reachability;
  verdict: Verdict;
}

export function connectorStateOf(record: Integration, reachability: Reachability): ConnectorState {
  const enablement = enablementOf(record.status);
  return {
    record,
    enablement,
    credential: credentialCustodyOf(record),
    reachability,
    verdict: verdictOf(enablement, reachability),
  };
}

// ── Page-level telemetry ─────────────────────────────────────────────────────────────

export interface Summary {
  total: number;
  /** Locally enabled — the owner's recorded intent, not a proven link. */
  enabled: number;
  notEnabled: number;
  faulted: number;
  unknownStatus: number;
  /** Enabled AND probe-verified. The ONLY count that may drive a live affordance. */
  verifiedConnected: number;
  /** Enabled but never actually contacted (or the probe could not answer). */
  enabledUnverified: number;
  /** Enabled and a real probe said the channel did not answer. */
  unreachable: number;
  /** No probe has run at all — across every connector, whatever its enablement. */
  untested: number;
  /** Drives the page's live indicator. False whenever nothing is proven. */
  anyVerifiedConnected: boolean;
}

export function summarize(states: readonly ConnectorState[]): Summary {
  const count = (p: (s: ConnectorState) => boolean) => states.filter(p).length;
  const verifiedConnected = count((s) => isGenuinelyConnected(s.verdict));
  return {
    total: states.length,
    enabled: count((s) => s.enablement === 'enabled'),
    notEnabled: count((s) => s.enablement === 'not_enabled'),
    faulted: count((s) => s.enablement === 'faulted'),
    unknownStatus: count((s) => s.enablement === 'unknown'),
    verifiedConnected,
    enabledUnverified: count((s) => s.verdict === 'enabled_unverified'),
    unreachable: count((s) => s.verdict === 'unreachable'),
    untested: count((s) => s.reachability.state === 'untested'),
    anyVerifiedConnected: verifiedConnected > 0,
  };
}
