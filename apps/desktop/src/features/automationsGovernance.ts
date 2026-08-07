// Phase 8 — the AUTOMATION RUN CONTRACT (renderer half).
//
// WHY THIS EXISTS. The scheduler is real: `src-tauri/src/lib.rs` ticks once a minute and
// `repo::automations::run_due` fires every enabled automation whose interval trigger is due.
// What it does NOT do is record under what authority a fire acted. The whole durable record of
// a run is `automation_runs(id, automation_id, ran_at, outcome, detail)` — no actor, no role,
// no scope, no risk, no receipt. So a fired automation left the same trace whether the owner
// pressed "Run now" or an unattended timer fired it at 04:00, and a refused run left no trace
// at all. That is the missing half of Phase 8: the run happens, the governance of it does not.
//
// WHAT THIS MODULE IS. The pure, testable contract layer the page runs BEFORE it invokes
// `run_automation`, and the honest reader that turns the run log into a history that says what
// is actually known. It answers, for one automation:
//
//   who      — `actor` (owner of this session · the local scheduler · not recorded)
//   role     — `roleId`, the authority the actor acts under
//   scope    — the exact IPC command plus the store rows the action may write
//   risk     — `risk` + the real `riskFactors` it was derived from
//   evidence — what the run must produce, and whether this page can actually observe it
//
// WHAT IT DELIBERATELY DOES NOT DO. It never marks anything verified. No automation path in
// this build produces a signed engine receipt: `run_automation` is a local SQLite write, not a
// governed turn (`services/governedTurn.ts`), so there is no lease and nothing to verify. The
// strongest honest claim about a run started here is "a contract was enforced before it, in
// this session" — `Provenance.contracted_this_session`. Everything read back from the store
// carries `authority_not_recorded`, because that is the literal truth about those rows.
//
// FAIL-CLOSED. Every unknown is a refusal, never an allowance: an unknown command is treated as
// denied, an unparseable action is refused, an unknown run outcome is never counted as executed.
// The roadmap's Phase-8 rule — "an automation that would need ungoverned execution is refused at
// authoring time" — is implemented here as `assessAction`, used by BOTH the authoring form and
// the run path, so a rule that cannot run governed cannot be created and cannot be fired.

import type { Automation, AutomationRun } from '../domain/entities';

// ─────────────────────────────────────────────────────────────────────────────
// 1 · Capability policy — mirrored, not invented
// ─────────────────────────────────────────────────────────────────────────────

/** T-010 tiers: R read-only · L1 local reversible · L2 local destructive · A approval authority
 *  · X execution/spend. Same vocabulary as `src-tauri/command-policy.json`. */
export type CommandTier = 'R' | 'L1' | 'L2' | 'A' | 'X';
export type CommandGrant = 'allow' | 'deny';
export interface CommandPolicyEntry { tier: CommandTier; grant: CommandGrant }

/**
 * A mirror of the AUTHORITATIVE `src-tauri/command-policy.json` for the commands this page can
 * reach, plus the neighbouring hard-deletes it must never assume anything about.
 *
 * `Automations.governance.test.ts` reads the real JSON and fails if any entry here drifts from
 * it, so this table cannot quietly become a second, wrong source of truth.
 *
 * ⚠ `delete_automation` is `X` / **allow** — the automation store's delete is a GRANTED command
 * and the page must keep offering it. The `L2` hard-deletes below (conversation, knowledge,
 * library item, research item, memory, event) are **deny** with `protection: none`. These are
 * different decisions about different commands: do not generalise in either direction. Listing
 * both here is what makes the distinction asserted rather than a comment nobody checks.
 */
export const COMMAND_POLICY: Readonly<Record<string, CommandPolicyEntry>> = {
  // automations — what this page invokes
  list_automations: { tier: 'R', grant: 'allow' },
  list_automation_runs: { tier: 'R', grant: 'allow' },
  create_automation: { tier: 'X', grant: 'allow' },
  set_automation_enabled: { tier: 'X', grant: 'allow' },
  run_automation: { tier: 'X', grant: 'allow' },
  delete_automation: { tier: 'X', grant: 'allow' },
  // the denied neighbours — recorded so the difference is asserted, never assumed
  delete_conversation: { tier: 'L2', grant: 'deny' },
  delete_knowledge: { tier: 'L2', grant: 'deny' },
  delete_library_item: { tier: 'L2', grant: 'deny' },
  delete_research_item: { tier: 'L2', grant: 'deny' },
  delete_memory: { tier: 'L2', grant: 'deny' },
  delete_event: { tier: 'L2', grant: 'deny' },
};

/** Look a command up FAIL-CLOSED: anything not in the mirror is treated as execution-tier and
 *  denied, so an unknown or renamed command can never be presented as permitted. */
export function commandPolicy(
  command: string,
  policy: Readonly<Record<string, CommandPolicyEntry>> = COMMAND_POLICY,
): CommandPolicyEntry {
  return policy[command] ?? { tier: 'X', grant: 'deny' };
}

// ─────────────────────────────────────────────────────────────────────────────
// 2 · The action vocabulary (mirrors `repo::automations::execute_action`)
// ─────────────────────────────────────────────────────────────────────────────

/** The store rows a local action may create. Nothing else is reachable from an automation. */
export type ActionEffect = 'notification' | 'task' | 'knowledge_note';

export const LOCAL_VERBS = ['notify', 'task', 'note'] as const;
export type LocalVerb = (typeof LOCAL_VERBS)[number];

const EFFECT_OF: Record<LocalVerb, ActionEffect> = {
  notify: 'notification',
  task: 'task',
  note: 'knowledge_note',
};

/**
 * Verbs that would have to reach the model / engine / network. None of them exists in the
 * backend's executor, so today they merely record a `failed` run — but the refusal must be
 * stated for what it is (there is no governed dispatch path for an automation in this build)
 * rather than left looking like a typo. If a governed automation dispatch is ever added, these
 * are the verbs that must acquire a lease, and this list is where that decision is recorded.
 */
export const MODEL_REACHING_VERBS = [
  'ask', 'ai', 'agent', 'chat', 'model', 'prompt', 'reply', 'research',
  'run', 'dispatch', 'summarize', 'summarise', 'http', 'fetch', 'post', 'webhook',
] as const;

/** The closed set of reasons this contract can refuse. No free-text refusals. */
export type RefusalReason =
  | 'action_empty'
  | 'action_malformed'
  | 'action_argument_missing'
  | 'action_verb_unknown'
  | 'action_reaches_model'
  | 'automation_disabled'
  | 'command_denied'
  | 'risk_above_local_ceiling';

export type ActionParse =
  | { ok: true; verb: LocalVerb; argument: string; effect: ActionEffect }
  | { ok: false; reason: RefusalReason; offending: string };

/**
 * Parse an automation action the way the backend executor does (`verb: argument`, verbs
 * `notify` | `task` | `note`) and classify everything else as a typed refusal. A model-reaching
 * verb is called out separately from an unknown one because they need different answers: one is
 * a typo, the other is a governance gap.
 */
export function parseAction(action: string): ActionParse {
  const trimmed = action.trim();
  if (!trimmed) return { ok: false, reason: 'action_empty', offending: '' };
  const idx = trimmed.indexOf(':');
  if (idx === -1) return { ok: false, reason: 'action_malformed', offending: trimmed };
  const verb = trimmed.slice(0, idx).trim().toLowerCase();
  const argument = trimmed.slice(idx + 1).trim();
  if (!verb) return { ok: false, reason: 'action_malformed', offending: trimmed };
  if ((MODEL_REACHING_VERBS as readonly string[]).includes(verb)) {
    return { ok: false, reason: 'action_reaches_model', offending: verb };
  }
  if (!(LOCAL_VERBS as readonly string[]).includes(verb)) {
    return { ok: false, reason: 'action_verb_unknown', offending: verb };
  }
  // Argument emptiness is checked AFTER the verb so the reason names the real problem.
  if (!argument) return { ok: false, reason: 'action_argument_missing', offending: verb };
  const v = verb as LocalVerb;
  return { ok: true, verb: v, argument, effect: EFFECT_OF[v] };
}

// ─────────────────────────────────────────────────────────────────────────────
// 3 · Trigger — is this automation actually scheduled?
// ─────────────────────────────────────────────────────────────────────────────

export type TriggerKind = 'interval' | 'manual' | 'unrecognised';
export interface TriggerParse {
  kind: TriggerKind;
  /** Non-null only for `interval`. */
  intervalMs: number | null;
  raw: string;
}

/**
 * Port of `repo::automations::parse_interval_ms` — `every: <N>{m|h|d}`, N > 0. Kept equivalent
 * (lowercase, `every:` prefix, trailing unit character, trimmed numeric head) because the whole
 * point is to tell the truth about what the SCHEDULER will do; a looser parser here would claim
 * fires that never happen.
 */
export function parseIntervalMs(trigger: string): number | null {
  const lowered = trigger.trim().toLowerCase();
  if (!lowered.startsWith('every:')) return null;
  const rest = lowered.slice('every:'.length).trim();
  if (rest.length < 2) return null;
  const num = rest.slice(0, -1).trim();
  const unit = rest.slice(-1);
  if (!/^\d+$/.test(num)) return null;
  const n = Number(num);
  if (!Number.isSafeInteger(n) || n <= 0) return null;
  if (unit === 'm') return n * 60_000;
  if (unit === 'h') return n * 3_600_000;
  if (unit === 'd') return n * 86_400_000;
  return null;
}

/** Classify a trigger: scheduled, deliberately manual, or a string the scheduler ignores. The
 *  third case matters — an automation with trigger `cron` looks armed and never fires. */
export function parseTrigger(trigger: string): TriggerParse {
  const raw = trigger.trim();
  const intervalMs = parseIntervalMs(raw);
  if (intervalMs !== null) return { kind: 'interval', intervalMs, raw };
  if (raw === '' || raw.toLowerCase() === 'manual') return { kind: 'manual', intervalMs: null, raw };
  return { kind: 'unrecognised', intervalMs: null, raw };
}

// ─────────────────────────────────────────────────────────────────────────────
// 4 · The contract
// ─────────────────────────────────────────────────────────────────────────────

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';

const RISK_ORDER: RiskLevel[] = ['low', 'medium', 'high', 'critical'];

/** The highest risk an UNLEASED, local automation run may carry. Anything above this has no
 *  governed path in this build and is refused rather than run. */
export const LOCAL_RISK_CEILING: RiskLevel = 'medium';

export function riskExceeds(risk: RiskLevel, ceiling: RiskLevel): boolean {
  return RISK_ORDER.indexOf(risk) > RISK_ORDER.indexOf(ceiling);
}

/** Why the risk is what it is — closed ids so the UI can localise them and tests can assert
 *  them. Every factor is a checkable fact about this build, not a vibe. */
export type RiskFactor =
  | 'local_effect_only'      // writes one local SQLite row; no model, no network, no spend
  | 'not_removable_in_app'   // the created row has no granted delete command
  | 'unattended_schedule'    // an interval trigger fires it with no human present
  | 'reaches_model';         // would leave the local store — needs a lease this page cannot get

/** Who a run acts as. `unrecorded` is the honest value for every row read back from the store. */
export type RunActor = 'owner' | 'scheduler' | 'unrecorded';
export type RoleId = 'desktop-owner' | 'local-scheduler' | 'none';

/** One thing a governed run is supposed to leave behind, and whether THIS page can see it. */
export interface EvidenceItem {
  id: 'run_row' | 'audit_event' | 'engine_receipt';
  /** True only when this page genuinely holds/observes the artefact. */
  observed: boolean;
}

export interface RunContract {
  automationId: string;
  automationName: string;
  actor: RunActor;
  roleId: RoleId;
  /** The IPC command the run goes through. */
  command: 'run_automation';
  tier: CommandTier;
  grant: CommandGrant;
  /** Machine-readable scope strings: the automation itself + every store the action may write. */
  scope: string[];
  effect: ActionEffect | null;
  risk: RiskLevel;
  riskFactors: RiskFactor[];
  evidence: EvidenceItem[];
  /** True when an interval trigger means the scheduler fires this with nobody watching. */
  unattended: boolean;
  trigger: TriggerParse;
}

export interface ContractAssessment {
  /** The contract the run WOULD carry — built even when refused, so the page can show the shape
   *  it failed to satisfy instead of an opaque "no". */
  contract: RunContract;
  /** `null` means allowed. Anything else means the page must not invoke. */
  refusal: RefusalReason | null;
  /** The offending fragment (verb / raw action / risk) behind a refusal, for honest copy. */
  offending: string;
}

/** The store each effect writes, and whether the app can undo it. Both come from the real
 *  command surface: there is no `delete_task` or `delete_notification` command at all, and
 *  `delete_knowledge` exists but is DENIED — so nothing an automation creates is removable from
 *  the app. That is a genuine risk factor, not a decoration. */
const EFFECT_SCOPE: Record<ActionEffect, { scope: string; removable: boolean }> = {
  notification: { scope: 'notifications:create', removable: false },
  task: { scope: 'tasks:create', removable: false },
  knowledge_note: { scope: 'knowledge:create', removable: false },
};

/** The role an actor acts under. `unrecorded` gets `none`: we refuse to name a role we did not
 *  observe, which is the entire complaint about the stored rows. */
function roleOf(actor: RunActor): RoleId {
  if (actor === 'owner') return 'desktop-owner';
  if (actor === 'scheduler') return 'local-scheduler';
  return 'none';
}

/**
 * Assess ONE prospective run of `automation` by `actor`, returning the contract it would carry
 * and any refusal. This is the single gate: the page must call it before `run_automation` and
 * must not invoke when `refusal !== null`.
 */
export function assessRun(
  automation: Automation,
  actor: 'owner' | 'scheduler',
  policy: Readonly<Record<string, CommandPolicyEntry>> = COMMAND_POLICY,
): ContractAssessment {
  const parsed = parseAction(automation.action);
  const trigger = parseTrigger(automation.trigger);
  const unattended = trigger.kind === 'interval';
  const { tier, grant } = commandPolicy('run_automation', policy);

  const factors: RiskFactor[] = [];
  const scope = [`automation:${automation.id}`];

  if (parsed.ok) {
    const e = EFFECT_SCOPE[parsed.effect];
    scope.push(e.scope);
    factors.push('local_effect_only');
    if (!e.removable) factors.push('not_removable_in_app');
    if (unattended) factors.push('unattended_schedule');
  } else if (parsed.reason === 'action_reaches_model') {
    factors.push('reaches_model');
  }

  // Risk: a local write the owner asked for is low; the same write firing unattended is medium
  // (nobody is present to see it happen); anything that would leave the local store is high and
  // therefore above the ceiling an unleased path may carry.
  const risk: RiskLevel = factors.includes('reaches_model')
    ? 'high'
    : unattended && parsed.ok
      ? 'medium'
      : 'low';

  const contract: RunContract = {
    automationId: automation.id,
    automationName: automation.name,
    actor,
    roleId: roleOf(actor),
    command: 'run_automation',
    tier,
    grant,
    scope,
    effect: parsed.ok ? parsed.effect : null,
    risk,
    riskFactors: factors,
    evidence: [
      // `observed` becomes true only once the call really returns the row (see `bindReceipt`).
      { id: 'run_row', observed: false },
      // The backend writes `audit::record("automation.ran", …)` in the same transaction, but
      // this page never reads the audit table, so it must not claim to have seen it.
      { id: 'audit_event', observed: false },
      // Never true in this build. No automation path produces a signed receipt.
      { id: 'engine_receipt', observed: false },
    ],
    unattended,
    trigger,
  };

  // Refusal order: policy first (a denied command is refused whatever the action says), then the
  // action vocabulary, then the risk ceiling, then liveness. Keeping `automation_disabled` last
  // means a broken rule reports the broken rule, not merely that it happens to be switched off.
  if (grant !== 'allow') {
    return { contract, refusal: 'command_denied', offending: 'run_automation' };
  }
  if (!parsed.ok) {
    return { contract, refusal: parsed.reason, offending: parsed.offending };
  }
  if (riskExceeds(risk, LOCAL_RISK_CEILING)) {
    return { contract, refusal: 'risk_above_local_ceiling', offending: risk };
  }
  if (!automation.enabled) {
    return { contract, refusal: 'automation_disabled', offending: automation.name };
  }
  return { contract, refusal: null, offending: '' };
}

/** True only for an assessment with no refusal. */
export function isAllowed(assessment: ContractAssessment): boolean {
  return assessment.refusal === null;
}

/**
 * Authoring-time gate (roadmap Phase 8: "an automation that would need ungoverned execution is
 * refused at authoring time"). Same vocabulary as the run gate, so a rule that could never run
 * governed cannot be created in the first place.
 */
export function assessAction(action: string): { ok: boolean; reason: RefusalReason | null; offending: string } {
  const parsed = parseAction(action);
  if (parsed.ok) return { ok: true, reason: null, offending: '' };
  return { ok: false, reason: parsed.reason, offending: parsed.offending };
}

/** Mark the run-row evidence as observed once the backend actually handed the row back. This is
 *  the ONLY way an evidence item becomes `observed`, and it never touches `engine_receipt`. A
 *  row for a different automation is ignored rather than bound. */
export function bindReceipt(contract: RunContract, run: AutomationRun): RunContract {
  if (run.automationId !== contract.automationId) return contract;
  return {
    ...contract,
    evidence: contract.evidence.map((e) => (e.id === 'run_row' ? { ...e, observed: true } : e)),
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// 5 · The history — what actually happened, and what is merely not known
// ─────────────────────────────────────────────────────────────────────────────

export type LedgerKind = 'executed' | 'refused' | 'failed';

/** How much is known about a history row's authority. There is deliberately NO "verified"
 *  value: nothing in the automation path produces a signed receipt. */
export type Provenance =
  /** This session built and enforced a contract before the call, and holds the returned row. */
  | 'contracted_this_session'
  /** A store row from before/outside this session: the table records no actor, role or scope. */
  | 'authority_not_recorded'
  /** The contract refused it here; the call was never made, and nothing was written. */
  | 'refused_preflight'
  /** The backend refused it (capability, disabled automation, or its own vocabulary check). */
  | 'refused_by_store';

export interface LedgerEntry {
  key: string;
  kind: LedgerKind;
  provenance: Provenance;
  /** Epoch-ms as string, matching `AutomationRun.ranAt`. */
  at: string;
  detail: string;
  reason: RefusalReason | null;
  /** Present only when this session actually built one. */
  contract: RunContract | null;
  /** False for session-only rows: the store has no table for refusals, so they vanish on reload. */
  persisted: boolean;
  runId: string | null;
}

/** A refusal this session observed. Never persisted — the backend has nowhere to put it. */
export interface SessionRefusal {
  key: string;
  at: string;
  reason: RefusalReason | null;
  detail: string;
  contract: RunContract;
  /** `preflight` = the contract refused and no call was made; `store` = the call was made and
   *  the backend refused it. */
  origin: 'preflight' | 'store';
}

/**
 * The backend's own action-vocabulary refusals, recorded as `failed` runs by
 * `repo::automations::execute_action`. Matching the real strings lets a REFUSED store row read
 * as refused rather than as an ordinary failure. Anything unmatched stays `failed` — fail-closed
 * in the honest direction (never upgraded to `executed`).
 */
const STORE_REFUSALS: Array<{ re: RegExp; reason: RefusalReason }> = [
  { re: /^unrecognized action \(expected/i, reason: 'action_malformed' },
  { re: /^unknown action verb '/i, reason: 'action_verb_unknown' },
  { re: /^action '.*' has no argument$/i, reason: 'action_argument_missing' },
];

export interface RunClassification {
  kind: LedgerKind;
  reason: RefusalReason | null;
}

/** Classify one stored run row from its REAL outcome + detail. Only the literal outcome `ok`
 *  counts as executed; any unknown outcome string is treated as a failure. */
export function classifyRun(run: AutomationRun): RunClassification {
  if (run.outcome === 'ok') return { kind: 'executed', reason: null };
  for (const { re, reason } of STORE_REFUSALS) {
    if (re.test(run.detail.trim())) return { kind: 'refused', reason };
  }
  return { kind: 'failed', reason: null };
}

function numericAt(at: string): number {
  const n = Number(at);
  return Number.isFinite(n) ? n : 0;
}

/**
 * Merge the durable run log with this session's refusals into ONE truthful history.
 *
 *  - a store row bound to a session contract (we made that exact call) → `contracted_this_session`
 *  - any other store row                                              → `authority_not_recorded`
 *  - a refusal from this session                                      → not persisted, with a reason
 *
 * Newest first. Nothing is invented and nothing is hidden: a run whose authority is unknown says
 * so instead of borrowing the current session's contract.
 */
export function buildLedger(
  runs: AutomationRun[],
  refusals: SessionRefusal[],
  receipts: Readonly<Record<string, RunContract>> = {},
): LedgerEntry[] {
  const fromStore: LedgerEntry[] = runs.map((run) => {
    const { kind, reason } = classifyRun(run);
    const bound = receipts[run.id] ?? null;
    return {
      key: `run:${run.id}`,
      kind,
      provenance: kind === 'refused'
        ? 'refused_by_store'
        : bound
          ? 'contracted_this_session'
          : 'authority_not_recorded',
      at: run.ranAt,
      detail: run.detail,
      reason,
      contract: bound,
      persisted: true,
      runId: run.id,
    };
  });

  const fromSession: LedgerEntry[] = refusals.map((r) => ({
    key: r.key,
    kind: 'refused',
    provenance: r.origin === 'preflight' ? 'refused_preflight' : 'refused_by_store',
    at: r.at,
    detail: r.detail,
    reason: r.reason,
    contract: r.contract,
    persisted: false,
    runId: null,
  }));

  return [...fromStore, ...fromSession].sort((a, b) => numericAt(b.at) - numericAt(a.at));
}

/** Counts a page can show without lying: executed / refused / failed, plus how many runs this
 *  session can actually attribute and how many the store left anonymous. */
export interface LedgerSummary {
  total: number;
  executed: number;
  refused: number;
  failed: number;
  attributed: number;
  unattributed: number;
}

export function summarise(entries: LedgerEntry[]): LedgerSummary {
  const s: LedgerSummary = {
    total: entries.length, executed: 0, refused: 0, failed: 0, attributed: 0, unattributed: 0,
  };
  for (const e of entries) {
    if (e.kind === 'executed') s.executed += 1;
    else if (e.kind === 'refused') s.refused += 1;
    else s.failed += 1;
    if (e.provenance === 'contracted_this_session') s.attributed += 1;
    if (e.provenance === 'authority_not_recorded') s.unattributed += 1;
  }
  return s;
}

/**
 * The single honesty predicate the UI asks before painting anything that reads as governed.
 * True ONLY for a run this session contracted and whose row it holds — and even then the UI must
 * say "contract enforced here", never "verified", because `engine_receipt` is never observed.
 */
export function isContractEnforced(entry: LedgerEntry): boolean {
  return entry.provenance === 'contracted_this_session'
    && entry.contract !== null
    && entry.contract.evidence.some((e) => e.id === 'run_row' && e.observed);
}

/** Always false in this build, and the one place that would have to change if a governed
 *  automation dispatch ever lands. Keeping it as a function (rather than a scattered `false`)
 *  means the claim has exactly one owner. */
export function isEngineVerified(entry: LedgerEntry): boolean {
  return entry.contract !== null
    && entry.contract.evidence.some((e) => e.id === 'engine_receipt' && e.observed);
}
