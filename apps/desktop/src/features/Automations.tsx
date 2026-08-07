import {
  useEffect, useMemo, useRef, useState,
  type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type ReactNode,
} from 'react';
import { useApp } from '../app/store';
import { Modal, FormRow, Input, Button, ConfirmDialog } from '../components/ui';
import { desktop, hasBackend } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { Mark } from '../components/Ambient';
import { riskLabel } from '../domain/statusLabels';
import type { Lang } from '../domain/enums';
import type { Automation } from '../domain/entities';
import { STR } from './Automations.strings';
import {
  assessAction, assessRun, bindReceipt, buildLedger, isContractEnforced, isEngineVerified,
  parseTrigger, summarise,
  type EvidenceItem, type LedgerEntry, type RefusalReason,
  type RiskFactor, type RunContract, type SessionRefusal, type TriggerParse,
} from './automationsGovernance';

// ── `automations` ⇶ Ավտոմատներ — the WORKFLOW ENERGY MANIFOLD, dressed as the AI-OS
// mockup (views/automations.js). Every automation is a horizontal energy conduit:
// intake valve (trigger) ▸ governed gates ▸ outlet (action). Selecting a conduit
// re-forges the SCHEMATIC below. The panel chrome — `.mani .surface .soft .lg .hud`
// (brackets/ticks/eyebrow) + the `.manifold`/`.lane`/`.schem`/`.arow` grammar — is
// the shared aios.css, rooted under `.v-automations`.
//
// REAL DATA. Every conduit is a REAL row from `list_automations` (services/desktop →
// domain Automation). Create/delete/enable flows are unchanged. No pipeline is
// invented.
//
// HONEST STATE. The real `Automation` entity carries only { name, trigger, action,
// enabled, createdAt, updatedAt } — no throughput, success rate, gate ledger or owner.
// So the mockup's `flowing`/`throttled`/`completed` runtime states and its per-conduit
// rate/sparkline are NEVER fabricated: a conduit is `idle` (armed, enabled), `off`
// (disabled), or `blocked` — a live wall/guard denial, or a rule the run contract
// permanently refuses (see `sealReason`). Throughput reads stay "—": the run log is real
// but records no rate, and the page says so instead of computing one.
//
// LIVE FIELD, NOT A RATE. The manifold's signature motion — flowing packets along a
// conduit, the schematic's traveling pulse — is driven purely by whether a conduit
// is ARMED & enabled (the `au-live` class), never by a fabricated run rate. It reads
// as "this conduit is energised and ready", the honest counterpart of `enabled`;
// disabled and sealed conduits are still. Readouts stay "—" throughout. The
// SCHEDULER SWEEP likewise walks only armed intake valves. Reduced motion stills all.
//
// GOVERNED RUN (Phase 8). A fire now carries a CONTRACT, and the history says what is
// actually known about each one. `automationsGovernance.ts` holds the whole rule set; this
// page is its surface:
//
//   · Authoring refuses a rule whose action has no governed path (the roadmap's Phase-8 rule),
//     so an ungoverned automation cannot be created at all — `create_automation` is not called.
//   · "Run now" is gated by `assessRun` BEFORE the invoke. A refusal never reaches the backend,
//     and it is recorded with its reason instead of vanishing.
//   · The selected conduit shows the contract it runs under: authority, role, command + tier,
//     scope, risk (with the facts the level came from) and the evidence a run must produce.
//   · The history merges the real `automation_runs` log with this session's refusals, and
//     labels each row with what is genuinely known: a run this session contracted, a stored run
//     whose authority the table never recorded, or a refusal (and by whom).
//
// WHAT IS NEVER CLAIMED. No automation path produces a signed engine receipt in this build, so
// nothing here is ever shown as verified — the strongest label is "contract enforced here".
// The scheduler fires unattended runs inside the Rust backend, which this page cannot gate;
// those rows say "authority not recorded", because that is exactly what the store knows.

// The three states honestly derivable from the entity + a live denial.
type RuntimeState = 'idle' | 'off' | 'blocked';

// ── enum → string-table maps. Every governance value the module produces is a closed id,
//    so the copy for it is looked up, never composed. TypeScript checks exhaustiveness. ──
const REFUSAL_STR: Record<RefusalReason, keyof typeof STR> = {
  action_empty: 'refuseActionEmpty',
  action_malformed: 'refuseActionMalformed',
  action_argument_missing: 'refuseActionArgumentMissing',
  action_verb_unknown: 'refuseActionVerbUnknown',
  action_reaches_model: 'refuseActionReachesModel',
  automation_disabled: 'refuseAutomationDisabled',
  command_denied: 'refuseCommandDenied',
  risk_above_local_ceiling: 'refuseRiskAboveCeiling',
};

const REFUSAL_FIX: Record<RefusalReason, keyof typeof STR> = {
  action_empty: 'fixVocabulary',
  action_malformed: 'fixVocabulary',
  action_argument_missing: 'fixVocabulary',
  action_verb_unknown: 'fixVocabulary',
  action_reaches_model: 'fixNoGovernedPath',
  automation_disabled: 'fixEnable',
  command_denied: 'guardFix',
  risk_above_local_ceiling: 'fixNoGovernedPath',
};

const FACTOR_STR: Record<RiskFactor, keyof typeof STR> = {
  local_effect_only: 'factorLocalEffectOnly',
  not_removable_in_app: 'factorNotRemovable',
  unattended_schedule: 'factorUnattended',
  reaches_model: 'factorReachesModel',
};

const EVIDENCE_STR: Record<EvidenceItem['id'], keyof typeof STR> = {
  run_row: 'evRunRow',
  audit_event: 'evAuditEvent',
  engine_receipt: 'evEngineReceipt',
};

const ACTOR_STR: Record<RunContract['actor'], keyof typeof STR> = {
  owner: 'actorOwner',
  scheduler: 'actorScheduler',
  unrecorded: 'actorUnrecorded',
};

const ROLE_STR: Record<RunContract['roleId'], keyof typeof STR> = {
  'desktop-owner': 'roleDesktopOwner',
  'local-scheduler': 'roleLocalScheduler',
  none: 'roleNone',
};

const KIND_STR: Record<LedgerEntry['kind'], keyof typeof STR> = {
  executed: 'kindExecuted',
  refused: 'kindRefused',
  failed: 'kindFailed',
};

const PROVENANCE_STR: Record<LedgerEntry['provenance'], keyof typeof STR> = {
  contracted_this_session: 'provContracted',
  authority_not_recorded: 'provUnrecorded',
  refused_preflight: 'provRefusedPreflight',
  refused_by_store: 'provRefusedStore',
};

// state → shared aios state class (drives the `--st`/`--st-rgb` colour token used by
// the lane, valve, pipe, diagram rail, index dot and readout).
const STATE_CLASS: Record<RuntimeState, string> = { idle: 'idle', off: 'idle', blocked: 'blocked' };
// state → foundation `.st-*` tone (drives the `.ln-state` readout colour).
const STATE_TONE: Record<RuntimeState, string> = { idle: 'st-idle', off: 'st-idle', blocked: 'st-blocked' };
// state → GLYPH power-mark (mockup rule: idle default; alert on blocked; never green).
const STATE_MARK: Record<RuntimeState, string> = { idle: 'idle', off: 'idle', blocked: 'alert' };

/** A wall denial or a tripped guard — distinguished from a plain backend/load
 *  failure so the UI can render the spec's `blocked` state (reason + fix). */
function isDenial(message: string): boolean {
  return /denied|not permitted|permission|guard|blocked|wall|ungoverned|lease|receipt/i.test(message);
}

function reduced(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

// Typed carrier for CSS custom properties (the packet stagger `--d`). One cast,
// centralised, so the inline styles stay type-clean.
const cssVars = (v: Record<string, string>): CSSProperties => v as unknown as CSSProperties;

type Localise = (k: keyof typeof STR) => string;

/** The interval in the trigger's own vocabulary (`every: 5m`), rebuilt from the parsed
 *  milliseconds so the readout can never disagree with what the scheduler will do. */
function intervalText(intervalMs: number): string {
  if (intervalMs % 86_400_000 === 0) return `${intervalMs / 86_400_000}d`;
  if (intervalMs % 3_600_000 === 0) return `${intervalMs / 3_600_000}h`;
  return `${intervalMs / 60_000}m`;
}

/** What the SCHEDULER will really do with this trigger. `unrecognised` is the one that used to
 *  be invisible: a rule with trigger `cron` reads as armed and is never fired by anything. */
function describeTrigger(trigger: string, L: Localise): { parsed: TriggerParse; text: string } {
  const parsed = parseTrigger(trigger);
  if (parsed.kind === 'interval' && parsed.intervalMs !== null) {
    return { parsed, text: `${L('everyLabel')} ${intervalText(parsed.intervalMs)} — ${L('triggerScheduled')}` };
  }
  return { parsed, text: parsed.kind === 'manual' ? L('triggerManualOnly') : L('triggerUnrecognised') };
}

/** One labelled row of the contract panel. */
function Fact({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="au-fact">
      <span className="au-fk">{k}</span>
      <span>{children}</span>
    </div>
  );
}

/**
 * The contract a run of this automation carries: who, under which role, through which command at
 * which tier, over what scope, at what risk (and from which facts), and what evidence it owes.
 * Rendered for the selected conduit and previewed while a rule is being written, so the shape is
 * the same thing in both places.
 */
function ContractPanel(
  { contract, lang, L, compact }:
  { contract: RunContract; lang: Lang; L: Localise; compact?: boolean },
) {
  const trigger = describeTrigger(contract.trigger.raw, L);
  return (
    <div className="au-contract" role="group" aria-label={L('runContract')}>
      <span className="micro au-ct-h">{L('runContract')}</span>
      <div className="au-facts">
        <Fact k={L('contractAuthority')}>{L(ACTOR_STR[contract.actor])}</Fact>
        <Fact k={L('contractRole')}><code className="mono">{L(ROLE_STR[contract.roleId])}</code></Fact>
        <Fact k={L('contractCommand')}>
          <code className="mono">{contract.command}</code>
          <span className="au-ct-tags">
            <span className={`tier tier-${contract.tier}`}>{L('tierLabel')} {contract.tier}</span>
            <span className={`pill ${contract.grant === 'allow' ? 'info' : 'warn'}`}>
              {L(contract.grant === 'allow' ? 'grantAllow' : 'grantDeny')}
            </span>
          </span>
        </Fact>
        <Fact k={L('contractScope')}>
          <ul className="au-list">
            {contract.scope.map((sc) => <li key={sc}><code className="mono">{sc}</code></li>)}
          </ul>
        </Fact>
        <Fact k={L('contractRisk')}>
          <b>{riskLabel(contract.risk, lang)}</b>
          <ul className="au-list">
            {contract.riskFactors.map((f) => <li key={f}>{L(FACTOR_STR[f])}</li>)}
          </ul>
        </Fact>
        <Fact k={L('contractEvidence')}>
          {/* An item is only ever `held` when this page genuinely has it. `engine_receipt` is
              never produced in this build, and says so instead of reading as merely missing. */}
          <ul className="au-list au-ev">
            {contract.evidence.map((e) => (
              <li key={e.id} className={e.observed ? 'is-held' : 'is-open'}>
                {L(EVIDENCE_STR[e.id])} — <i className="micro">
                  {e.id === 'engine_receipt' ? L('evNever') : e.observed ? L('evObserved') : L('evNotObserved')}
                </i>
              </li>
            ))}
          </ul>
        </Fact>
        {!compact && <Fact k={L('contractSchedule')}>{trigger.text}</Fact>}
      </div>
      {!compact && <p className="au-note muted">{L('contractNote')}</p>}
    </div>
  );
}

// ── the authoring form — the Phase-8 authoring-time gate lives here ───────────
function NewRuleForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { t, lang } = useApp();
  const L = (k: keyof typeof STR) => STR[k][lang] ?? STR[k].en;
  const [name, setName] = useState('');
  const [trigger, setTrigger] = useState('');
  const [action, setAction] = useState('');
  const [error, setError] = useState<string | null>(null);
  // OUR refusal, kept apart from the backend `error` because the call is never made.
  const [refused, setRefused] = useState<RefusalReason | null>(null);
  const [busy, setBusy] = useState(false);

  // The contract this rule WOULD run under, previewed live from what is typed. Built through the
  // same `assessRun` the run path uses, over a draft automation, so the preview cannot drift
  // from the gate that will actually judge it.
  const draft: Automation = {
    id: 'draft', name: name.trim(), trigger: trigger.trim(), action: action.trim(),
    enabled: true, createdAt: '', updatedAt: '',
  };
  const assessment = assessRun(draft, 'owner');
  const triggerRead = describeTrigger(trigger, L);

  const submit = () => {
    if (!name.trim() || busy) return;
    // FAIL-CLOSED GATE (roadmap Phase 8: refuse an ungoverned automation at AUTHORING time).
    // An action with no governed path never becomes a stored automation — `create_automation`
    // is not invoked at all, and the reason is shown instead of a rule that can only ever fail.
    const gate = assessAction(action);
    if (!gate.ok) {
      setRefused(gate.reason);
      setError(null);
      return;
    }
    setRefused(null);
    setBusy(true);
    setError(null);
    desktop
      .createAutomation({ name: name.trim(), trigger: trigger.trim(), action: action.trim() })
      .then(() => {
        onCreated();
        onClose();
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
        setBusy(false);
      });
  };

  return (
    <Modal title={t('automations.newRule')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      {/* Governance guarantee (honest): local actions run directly; any action reaching
          the model/engine routes through the governed, fail-closed chain (see `govern`). */}
      <div className="au-gov" role="note">
        <span aria-hidden="true">🛡</span>
        <span>{L('govern')}</span>
      </div>
      <FormRow label={t('field.name')}>
        <Input value={name} autoFocus onChange={(e) => setName(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.trigger')}>
        <Input value={trigger} onChange={(e) => setTrigger(e.target.value)} placeholder={L('triggerHint')} />
      </FormRow>
      {trigger.trim() !== '' && (
        <p className={`au-note micro${triggerRead.parsed.kind === 'unrecognised' ? ' au-warn' : ' muted'}`}>
          {triggerRead.text}
        </p>
      )}
      <FormRow label={t('field.action')}>
        <Input value={action} onChange={(e) => setAction(e.target.value)} placeholder={L('actionHint')} />
      </FormRow>
      {/* The refusal, if the owner already pressed Create. Assertive: it is the answer to an
          action they took, and it means nothing was written. */}
      {refused && (
        <div className="au-blocked" role="alert">
          <div className="au-blocked-title"><span aria-hidden="true">⛔</span>{L('authoringRefused')}</div>
          <div className="au-blocked-reason">{L(REFUSAL_STR[refused])}</div>
          <div className="au-blocked-fix">{L(REFUSAL_FIX[refused])}</div>
        </div>
      )}
      {/* The contract preview — shown once the action parses, so the owner sees the authority,
          scope, risk and evidence the rule will carry BEFORE it exists. */}
      {assessment.refusal === null && (
        <div className="au-preview">
          <span className="micro">{L('contractPreview')}</span>
          <ContractPanel contract={assessment.contract} lang={lang} L={L} compact />
        </div>
      )}
      <div className="form-actions">
        <Button type="button" variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button type="button" variant="primary" disabled={busy} onClick={submit}>{t('action.create')}</Button>
      </div>
    </Modal>
  );
}

export function Automations() {
  const { t, lang } = useApp();
  const L = (k: keyof typeof STR) => STR[k][lang] ?? STR[k].en;

  const [creating, setCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [stateFilter, setStateFilter] = useState<'all' | RuntimeState>('all');
  // A wall/guard denial captured from an enable/disable attempt; drives the
  // per-automation `blocked` runtime state and the inline reason + fix. `reason` is set only
  // when OUR contract refused (no call was made), which gets a different title and fix.
  const [actionError, setActionError] =
    useState<{ id: string; message: string; reason?: RefusalReason } | null>(null);
  const [announce, setAnnounce] = useState('');

  // ── the governed-run session record ────────────────────────────────────────────────
  // `receipts` binds a returned run row to the contract this session enforced before the call —
  // the ONLY basis on which a history row may be attributed to anyone. `refusals` holds the runs
  // that were refused; the store has no table for them, so they live here and say so.
  const [receipts, setReceipts] = useState<Record<string, RunContract>>({});
  const [refusals, setRefusals] = useState<SessionRefusal[]>([]);

  const manifoldRef = useRef<HTMLDivElement | null>(null);
  const laneRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const heroRef = useRef<HTMLElement | null>(null);

  const s = useAsync(() => desktop.listAutomations(), []);
  const items = useMemo(() => s.data ?? [], [s.data]);
  // The selected conduit's real run history (Phase 8). Refetches when the selection changes and is
  // reloaded after a "Run now"; empty for a never-run automation.
  const runs = useAsync(
    () => (selectedId ? desktop.listAutomationRuns(selectedId) : Promise.resolve([])),
    [selectedId],
  );

  const stateLabel = (st: RuntimeState): string => ({
    idle: L('armedState'),
    off: L('offState'),
    blocked: L('sealedState'),
  }[st]);

  /**
   * A contract refusal that is about the RULE itself — not merely that it is switched off. Such
   * a conduit is SEALED: no fire of it can ever take effect, whether from this page or from the
   * scheduler, so the page says so up front instead of only when the owner presses Run.
   * `automation_disabled` is excluded because "off" is already its own honest state.
   */
  const sealReason = (a: Automation): RefusalReason | null => {
    const { refusal } = assessRun(a, 'owner');
    return refusal !== null && refusal !== 'automation_disabled' ? refusal : null;
  };

  // Honest state derivation — never fabricates a run it cannot observe.
  const runtimeState = (a: Automation): RuntimeState => {
    if (actionError && actionError.id === a.id
      && (actionError.reason !== undefined || isDenial(actionError.message))) return 'blocked';
    if (sealReason(a) !== null) return 'blocked';
    return a.enabled ? 'idle' : 'off';
  };

  const fmtDate = (iso: string): string => {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    try {
      return d.toLocaleDateString(lang === 'hy' ? 'hy-AM' : 'en-US', {
        year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
      });
    } catch {
      return d.toISOString().slice(0, 16).replace('T', ' ');
    }
  };

  // Live census over the REAL rows (all honestly countable).
  const counts = useMemo(() => {
    const c = { idle: 0, off: 0, blocked: 0 };
    for (const a of items) c[runtimeState(a)] += 1;
    return c;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, actionError]);

  const filtered = useMemo(
    () => (stateFilter === 'all' ? items : items.filter((a) => runtimeState(a) === stateFilter)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [items, stateFilter, actionError],
  );

  const selected = items.find((a) => a.id === selectedId)
    ?? filtered[0] ?? items[0] ?? null;

  // The selected conduit's governed history: the durable run log merged with this session's
  // refusals for THIS automation, each row carrying only the authority that is genuinely known.
  const ledger = useMemo(
    () => buildLedger(
      runs.data ?? [],
      refusals.filter((r) => r.contract.automationId === selected?.id),
      receipts,
    ),
    [runs.data, refusals, receipts, selected?.id],
  );
  const ledgerSummary = useMemo(() => summarise(ledger), [ledger]);

  // Does the SCHEDULER actually fire anything here? True only when a real row carries an
  // interval trigger — the unattended path this page cannot gate.
  const hasScheduled = useMemo(
    () => items.some((a) => a.enabled && parseTrigger(a.trigger).kind === 'interval'),
    [items],
  );

  // Default-select the first conduit once data arrives (mockup init select(DEFAULT)).
  useEffect(() => {
    if (selectedId === null && items.length > 0) setSelectedId(items[0].id);
  }, [items, selectedId]);

  const select = (a: Automation, focusLane = false) => {
    setSelectedId(a.id);
    setAnnounce(`${a.name} — ${stateLabel(runtimeState(a))}`);
    if (focusLane) {
      requestAnimationFrame(() => laneRefs.current[a.id]?.focus());
    }
  };

  const toggle = (a: Automation) => {
    const next = !a.enabled;
    desktop
      .setAutomationEnabled(a.id, next)
      .then(() => {
        setActionError(null);
        setAnnounce(`${a.name}: ${next ? t('automations.enabled') : stateLabel('off')}`);
        s.reload();
      })
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e);
        setActionError({ id: a.id, message });
        setAnnounce(isDenial(message) ? `${a.name}: ${stateLabel('blocked')}` : message);
        s.reload();
      });
  };

  // Not optimistic: the conduit leaves the selection only once the backend confirms.
  // A refusal keeps it selected and reports the reason through the same denial channel
  // every other refused action already uses, instead of a silent reload.
  const remove = (id: string) => {
    setPendingDelete(null);
    setActionError(null);
    desktop.deleteAutomation(id)
      .then(() => {
        if (selectedId === id) setSelectedId(null);
        s.reload();
      })
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e);
        setActionError({ id, message });
        setAnnounce(isDenial(message) ? `${stateLabel('blocked')}: ${message}` : message);
        s.reload();
      });
  };

  /** Record a refusal so it survives in the history instead of vanishing. Never persisted —
   *  `automation_runs` only has room for runs that executed. */
  const recordRefusal = (
    contract: RunContract, reason: RefusalReason | null, origin: 'preflight' | 'store', detail: string,
  ) => {
    const at = Date.now();
    setRefusals((prev) => [
      ...prev,
      { key: `refusal:${contract.automationId}:${at}:${prev.length}`, at: String(at), reason, detail, contract, origin },
    ]);
  };

  /**
   * Run an automation NOW, GOVERNED.
   *
   * The contract is assessed FIRST. A refusal ends here: `run_automation` is never invoked, so
   * nothing is written, and the reason + fix are shown and recorded. Only an allowed contract
   * reaches the backend, and the row it returns is bound to that contract — which is the only
   * thing that lets the history say, truthfully, under whose authority that run happened.
   */
  const runNow = (a: Automation) => {
    const assessment = assessRun(a, 'owner');
    if (assessment.refusal !== null) {
      const reason = assessment.refusal;
      const message = L(REFUSAL_STR[reason]);
      recordRefusal(assessment.contract, reason, 'preflight', message);
      setActionError({ id: a.id, message, reason });
      setAnnounce(`${a.name}: ${L('refusalTitle')} — ${message}`);
      return;
    }
    desktop
      .runAutomation(a.id)
      .then((r) => {
        setActionError(null);
        // The returned row is the run-row evidence. Binding it here is the ONLY way an entry
        // becomes attributable; nothing else in the page can set it.
        setReceipts((prev) => ({ ...prev, [r.id]: bindReceipt(assessment.contract, r) }));
        setAnnounce(`${a.name}: ${r.outcome === 'ok' ? '✓' : '⚠'} ${r.detail}`);
        s.reload();
        runs.reload();
      })
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e);
        // The backend refused a run our contract allowed: recorded as a refusal BY THE STORE, so
        // the two kinds of "no" stay distinguishable in the history.
        recordRefusal(assessment.contract, null, 'store', message);
        setActionError({ id: a.id, message });
        setAnnounce(isDenial(message) ? `${a.name}: ${stateLabel('blocked')}` : message);
      });
  };

  // ── Manifold keyboard model (listbox): arrows move selection (follows focus),
  //    Home/End jump, Enter re-announces the selected conduit's schematic. ──────
  const onManifoldKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (filtered.length === 0) return;
    const idx = Math.max(0, filtered.findIndex((a) => a.id === selected?.id));
    const go = (i: number) => {
      const a = filtered[i];
      if (a) select(a, true);
    };
    if (e.key === 'ArrowDown') { e.preventDefault(); go(Math.min(filtered.length - 1, idx + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); go(Math.max(0, idx - 1)); }
    else if (e.key === 'Home') { e.preventDefault(); go(0); }
    else if (e.key === 'End') { e.preventDefault(); go(filtered.length - 1); }
    else if (e.key === 'Enter' && selected) {
      e.preventDefault();
      setAnnounce(`${selected.name} — ${stateLabel(runtimeState(selected))}`);
    }
  };

  // ── The one live instrument: the SCHEDULER SWEEP — Bro walking the intake
  //    valves in turn. It only ever touches ARMED (enabled) conduits (`.au-live`),
  //    since a disabled or sealed intake is not being polled — a purely visual
  //    attention marker over REAL conduits (it asserts no schedule data). Skipped
  //    entirely when motion is reduced. ─────────────────────────────────────────
  useEffect(() => {
    if (reduced() || filtered.length === 0) return;
    const root = manifoldRef.current;
    if (!root) return;
    let i = 0;
    let active: Element | null = null;
    const tick = () => {
      if (active) { active.classList.remove('checking'); active = null; }
      const valves = root.querySelectorAll('.lane.au-live .ln-valve');
      if (!valves.length) return;
      const v = valves[i % valves.length];
      i += 1;
      v.classList.add('checking');
      active = v;
    };
    const timer = window.setInterval(tick, 1700);
    return () => {
      window.clearInterval(timer);
      if (active) active.classList.remove('checking');
    };
  }, [filtered.length, stateFilter]);

  // Page shortcut: `n` opens the authoring form (suppressed while typing / modal).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (creating || pendingDelete) return;
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el?.isContentEditable) return;
      if (e.key === 'n' || e.key === 'N') { e.preventDefault(); setCreating(true); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [creating, pendingDelete]);

  const governLine = L('govern');
  const telemetryPending = L('telemetry');

  // ── Index legend / filter states present in the honest vocabulary ────────────
  const FILTERS: Array<'all' | RuntimeState> = ['all', 'idle', 'off', 'blocked'];
  const filterLabel = (f: 'all' | RuntimeState): string =>
    (f === 'all' ? L('allFilter') : stateLabel(f));

  const header = (
    <header className="pageHead">
      <div>
        <span className="eyebrow">{L('workflowManifold')}</span>
        <h1>{t('nav.automations')}</h1>
        <p className="sub">{t('automations.subtitle')}</p>
      </div>
      <div className="right">
        {items.length > 0 && (
          <span className="pill info" id="auSched">{L('schedSweep')}</span>
        )}
        {/* Earned, not decorative: shown only when a real enabled row has an interval trigger,
            i.e. when the backend scheduler genuinely fires runs this page cannot contract. */}
        {hasScheduled && (
          <span className="pill warn" title={L('contractNote')}>{L('schedulerUngoverned')}</span>
        )}
        <Button variant="primary" onClick={() => setCreating(true)} title={L('newN')}>
          {t('action.new')}
        </Button>
      </div>
    </header>
  );

  // ── the blocked (wall/guard denial) panel ────────────────────────────────────
  const renderBlocked = (reason: string, fix: string) => (
    <div className="au-blocked" role="alert">
      <div className="au-blocked-title">
        <span aria-hidden="true">⛔</span>
        {L('blockedByWall')}
      </div>
      <div className="au-blocked-reason">{reason}</div>
      <div className="au-blocked-fix">{fix}</div>
    </div>
  );

  // ── one conduit lane (a listbox option) ──────────────────────────────────────
  const renderLane = (a: Automation) => {
    const st = runtimeState(a);
    const isSel = a.id === selected?.id;
    const off = st === 'off';
    const guardCls = st === 'blocked' ? 'is-sealed' : 'is-pending';
    return (
      <button
        key={a.id}
        type="button"
        role="option"
        id={`au-lane-${a.id}`}
        ref={(el) => { laneRefs.current[a.id] = el; }}
        aria-selected={isSel}
        tabIndex={isSel ? 0 : -1}
        className={`lane ${STATE_CLASS[st]}${st === 'idle' ? ' au-live' : ''}${isSel ? ' sel' : ''}${off ? ' au-off' : ''}`}
        aria-label={`${a.name}, ${a.trigger || L('anyEvent')}, ${stateLabel(st)}`}
        onClick={() => select(a)}
        onFocus={() => { if (!isSel) select(a); }}
      >
        <span className="ln-valve" aria-hidden="true"><span className="lv-core" /></span>
        <span className="ln-lead">
          <b className="ln-name">{a.name}</b>
          <span className="ln-trig micro">{a.trigger || '—'}</span>
        </span>
        <span className="ln-pipe">
          {/* energy packets — three staggered layers. They read as the conduit's
              live standing field (armed & energised), NOT a run rate: CSS reveals
              them only on `.au-live` lanes and stills them under reduced motion. */}
          <span className="ln-flow" style={cssVars({ '--d': '0s' })} aria-hidden="true" />
          <span className="ln-flow" style={cssVars({ '--d': '-.9s' })} aria-hidden="true" />
          <span className="ln-flow" style={cssVars({ '--d': '-1.8s' })} aria-hidden="true" />
          <span className={`ln-stage ${guardCls}`} style={{ left: '40%' }} aria-hidden="true">
            {st === 'blocked' ? '✕' : ''}
          </span>
          <span className="ln-stage is-pending" style={{ left: '70%' }} aria-hidden="true" />
          <span className="ln-out" aria-hidden="true" />
        </span>
        <span className="ln-read">
          <b className="mono">—</b>
          <i className="micro">{L('runsPerHr')}</i>
        </span>
        <span className={`ln-state ${STATE_TONE[st]}`}><i />{stateLabel(st)}</span>
      </button>
    );
  };

  // ── the re-forgeable schematic of the selected conduit ───────────────────────
  const renderSchematic = () => {
    if (!selected) {
      return (
        <div className="schem" role="region" aria-label={L('schematic')}>
          <div className="au-pick">
            <Mark state="idle" size={44} />
            <div className="au-empty-title">{L('selectConduit')}</div>
            <p className="muted">{L('chooseConduit')}</p>
          </div>
        </div>
      );
    }
    const a = selected;
    const st = runtimeState(a);
    const sealed = st === 'blocked';
    const err = actionError && actionError.id === a.id ? actionError : null;
    const denial = err ? err.message : null;
    // The contract this conduit runs under, and the standing refusal (if any) that seals it.
    const assessment = assessRun(a, 'owner');
    const seal = sealReason(a);

    return (
      <div className="schem" role="region" aria-label={`${L('schematic')} — ${a.name}`}>
        <div className="sc-head">
          <Mark state={STATE_MARK[st]} size={46} />
          <div className="sc-id">
            <span className={`eyebrow ${STATE_TONE[st]}`}>{stateLabel(st)}</span>
            <h2>{a.name}</h2>
            <code className="sc-slug mono">#{a.id.slice(0, 8)}</code>
          </div>
          <span className={`ln-state sc-state ${STATE_TONE[st]}`}><i />{stateLabel(st)}</span>
        </div>

        <div className="sc-actions">
          {/* Disabled for a sealed conduit as well as an off one — but `runNow` re-assesses the
              contract itself, so the guarantee does not rest on the button being disabled. */}
          <Button
            variant="ghost"
            onClick={() => runNow(a)}
            disabled={!a.enabled || seal !== null}
            title={L('runNowTitle')}
          >
            {L('runNow')}
          </Button>
          <Button variant="ghost" onClick={() => toggle(a)}>
            {t(a.enabled ? 'automations.disable' : 'automations.enable')}
          </Button>
          {/* `delete_automation` is a GRANTED command (tier X) — unlike the hard-deletes on the
              neighbouring pages, which the window capability set denies. It stays offered here. */}
          <Button variant="ghost" onClick={() => setPendingDelete(a.id)}>{t('action.delete')}</Button>
        </div>

        {/* governance guarantee, surfaced on the selected conduit */}
        <p className="sc-desc">{governLine}</p>

        {/* Three distinct "no"s, never blurred into one: OUR contract refused (nothing was
            called), the backend denied, or an ordinary failure. */}
        {err?.reason !== undefined && renderBlocked(
          `${L('refusalTitle')}: ${err.message}`,
          L(REFUSAL_FIX[err.reason]),
        )}
        {err?.reason === undefined && denial && isDenial(denial) && renderBlocked(
          denial,
          L('guardFix'),
        )}
        {err?.reason === undefined && denial && !isDenial(denial) && <div className="form-error">{denial}</div>}
        {/* A standing seal is shown even before anything is pressed: this rule cannot run. */}
        {err === null && seal !== null && renderBlocked(
          `${L('refusalTitle')}: ${L(REFUSAL_STR[seal])}`,
          L(REFUSAL_FIX[seal]),
        )}

        <div className="sc-grid">
          {/* the diagram — trigger ▸ governed guard ▸ action ▸ outlet. No run data,
              so no node is ever marked done/now. The traveling pulse runs only while
              the conduit is armed/energised (`.au-live`) — a live-field marker, not an
              observed run; a sealed (blocked) or off conduit stays still. */}
          <div className={`sc-diagram ${STATE_CLASS[st]}${st === 'idle' ? ' au-live' : ''}`}>
            <div className="sc-track">
              <span className="sc-rail" aria-hidden="true" />
              <span className="sc-pulse" aria-hidden="true" />
              <span className="sc-node sc-src">
                <span className="sc-g" aria-hidden="true">⌁</span>
                <span className="sc-nl"><b>{L('trigger')}</b><i className="micro">{a.trigger || '—'}</i></span>
              </span>
              <span className={`sc-node ${sealed ? 'is-sealed' : 'is-armed'}`}>
                <span className="sc-g" aria-hidden="true">{sealed ? '⊘' : '◇'}</span>
                <span className="sc-nl"><b>{L('governed')}</b><i className="micro">{L('guard')}</i></span>
              </span>
              <span className="sc-node is-armed">
                <span className="sc-g" aria-hidden="true">▸</span>
                <span className="sc-nl"><b>{a.action || '—'}</b><i className="micro">{L('action')}</i></span>
              </span>
              <span className="sc-node is-pending">
                <span className="sc-g" aria-hidden="true">⬢</span>
                <span className="sc-nl"><b>{L('outlet')}</b><i className="micro">{L('dispatch')}</i></span>
              </span>
            </div>
            <div className="sc-legend">
              <span className="micro">{L('triggerLabel')} <b>{a.trigger || '—'}</b></span>
              <span className="micro sc-next">{L('actionLabel')} <b>{a.action || '—'}</b></span>
            </div>
          </div>

          {/* side rail — REAL entity facts (state, created, updated) + honest
              omission of the run telemetry the entity does not carry. */}
          <div className="sc-side">
            <div className="au-facts">
              <div className="au-fact">
                <span className="au-fk">{L('stateFact')}</span>
                <span className={`ln-state ${STATE_TONE[st]}`}><i />{stateLabel(st)}</span>
              </div>
              <div className="au-fact">
                <span className="au-fk">{L('createdFact')}</span>
                <span className="mono">{fmtDate(a.createdAt)}</span>
              </div>
              <div className="au-fact">
                <span className="au-fk">{L('updatedFact')}</span>
                <span className="mono">{fmtDate(a.updatedAt)}</span>
              </div>
              <div className="au-fact">
                <span className="au-fk">{L('ownerFact')}</span>
                {/* The entity carries no owner column, and inventing one would be the exact
                    defect this page is fixing. The CONTRACT below names the authority a run
                    acts under, which is a different and knowable thing. */}
                <span>{L('actorUnrecorded')}</span>
              </div>
            </div>

            {/* The run contract — who, which role, which command at which tier, what scope,
                what risk and from which facts, and what evidence a run owes. */}
            <div className="au-block">
              <ContractPanel contract={assessment.contract} lang={lang} L={L} />
            </div>

            <div className="au-block">
              <span className="micro">{L('governedTelemetry')}</span>
              <p className="au-note muted">{telemetryPending}</p>
            </div>
          </div>
        </div>

        <div className="sc-foot">
          <span className="micro sc-foot-h">{L('recentFires')}</span>
          {/* THE GOVERNED HISTORY. The real `automation_runs` log merged with the refusals this
              session recorded, newest first. Every row states what is genuinely known about it:
              a run this session contracted, a stored run whose authority the table never
              recorded, or a refusal — and, for a refusal, whether it was refused here (nothing
              was written) or by the store. Nothing is shown as verified: no automation run
              produces a signed receipt in this build (`isEngineVerified` is never true). */}
          {ledger.length > 0 ? (
            <>
              <ul className="au-runs" role="list">
                {ledger.slice(0, 8).map((e) => (
                  <li key={e.key} className={`au-run au-k-${e.kind}${e.persisted ? '' : ' au-volatile'}`}>
                    <span className={`pill ${e.kind === 'executed' ? 'mint' : 'warn'}`}>
                      {e.kind === 'executed' ? '✓' : e.kind === 'refused' ? '⊘' : '⚠'} {L(KIND_STR[e.kind])}
                    </span>
                    <span className="au-run-detail">{e.detail}</span>
                    <span
                      className={`micro au-run-prov${isContractEnforced(e) ? ' is-bound' : ''}`}
                      title={isEngineVerified(e) ? undefined : L('contractNote')}
                    >
                      {L(PROVENANCE_STR[e.provenance])}
                    </span>
                    {!e.persisted && <span className="micro au-run-vol">{L('notPersisted')}</span>}
                    <span className="micro mono au-run-time">{fmtDate(e.at)}</span>
                  </li>
                ))}
              </ul>
              <p className="au-note muted">
                {L('historyLegend')} — <b className="mono">{ledgerSummary.attributed}</b> {L('ledgerAttributed')}
                {' · '}<b className="mono">{ledgerSummary.unattributed}</b> {L('ledgerUnattributed')}
              </p>
            </>
          ) : (
            <p className="au-note muted">{L('noRuns')}</p>
          )}
        </div>
      </div>
    );
  };

  // ── one quiet index row (data tier) ──────────────────────────────────────────
  const renderRow = (a: Automation, i: number) => {
    const st = runtimeState(a);
    const isSel = a.id === selected?.id;
    const off = st === 'off';
    return (
      <button
        key={a.id}
        type="button"
        className={`arow surface soft ${STATE_CLASS[st]}${isSel ? ' on' : ''}${off ? ' au-off' : ''}`}
        aria-pressed={isSel}
        aria-label={`${a.name}, ${stateLabel(st)}`}
        onClick={() => {
          select(a);
          heroRef.current?.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'start' });
        }}
      >
        <span className="ar-ix">
          <span className="ar-dot" aria-hidden="true" />
          <b className="mono">{String(i + 1).padStart(2, '0')}</b>
        </span>
        <span className="ar-main">
          <b className="ar-ti">{a.name}</b>
          <code className="ar-slug mono">#{a.id.slice(0, 8)}</code>
        </span>
        <span className="ar-trig micro">{a.trigger || '—'}</span>
        <span className="ar-num"><b className="mono">—</b><span className="micro">{L('runs')}</span></span>
        <span className="ar-num"><b className="mono">—</b><span className="micro">{L('success')}</span></span>
        <span className={`ln-state ${STATE_TONE[st]}`}><i />{stateLabel(st)}</span>
      </button>
    );
  };

  // ── body: loading · error(link/denial) · empty · main manifold ───────────────
  let body: ReactNode;
  if (s.loading && s.data === null) {
    body = (
      <section className="mani surface soft lg hud" aria-busy="true" aria-label={L('manifold')}>
        <span className="bracket tl" /><span className="bracket tr" />
        <span className="bracket bl" /><span className="bracket br" />
        <div className="muted" aria-live="polite">{L('chargingManifold')}</div>
        <div className="au-skel" aria-hidden="true"><i /><i /><i /><i /></div>
      </section>
    );
  } else if (s.error && !hasBackend()) {
    body = (
      <section className="mani surface soft lg hud au-empty" role="status">
        <span className="au-empty-glyph" aria-hidden="true">◍</span>
        <div className="au-empty-title">{t('state.offline')}</div>
        <p className="muted">{t('state.offlineHint')}</p>
      </section>
    );
  } else if (s.error && isDenial(s.error)) {
    body = (
      <section className="mani surface soft lg hud" role="alert" aria-label={L('manifold')}>
        <span className="bracket tl" /><span className="bracket tr" />
        {renderBlocked(
          `${t('state.permissionDenied')}: ${s.error}`,
          L('storeDenied'),
        )}
      </section>
    );
  } else if (s.error) {
    body = (
      <section className="mani surface soft lg hud" role="alert" aria-label={L('manifold')}>
        <span className="eyebrow st-blocked">{L('manifoldEyebrow')}</span>
        <p className="muted" style={{ margin: '10px 0 14px', maxWidth: '60ch' }}>{s.error}</p>
        <button type="button" className="au-btn" onClick={s.reload}>{L('retry')}</button>
      </section>
    );
  } else if (items.length === 0) {
    body = (
      <section className="mani surface soft lg hud au-empty" role="status">
        <span className="au-empty-glyph" aria-hidden="true">⇶</span>
        <div className="au-empty-title">{L('noConduits')}</div>
        <p className="muted">{L('forgeFirst')}</p>
        <button type="button" className="au-btn" onClick={() => setCreating(true)}>
          {L('forgeConduit')}
        </button>
      </section>
    );
  } else {
    body = (
      <>
        {/* ── HERO · the energy manifold ─────────────────────────────────────── */}
        <section className="mani surface soft lg hud reveal" ref={heroRef}>
          <span className="bracket tl" /><span className="bracket tr" />
          <span className="bracket bl" /><span className="bracket br" />
          <span className="ticks" aria-hidden="true">
            {Array.from({ length: 9 }).map((_, i) => <i key={i} />)}
          </span>

          <div className="mani-head">
            <div className="mh-title">
              <span className="eyebrow">{L('energyManifold')}</span>
              <span className="mh-sub micro">
                {L('triggerGatesOutlet')} · {items.length} {L('conduits')}
              </span>
            </div>
            <div className="mh-gauge">
              <div className="mh-press">
                <b className="mono">{counts.idle}</b>
                <span className="micro">{L('armedConduits')}</span>
              </div>
            </div>
          </div>

          <div
            className="manifold"
            id="manifold"
            ref={manifoldRef}
            role="listbox"
            aria-label={L('automationManifold')}
            onKeyDown={onManifoldKey}
          >
            {filtered.length > 0
              ? filtered.map(renderLane)
              : <p className="muted" style={{ padding: 'var(--s4)' }}>{L('noConduitInState')}</p>}
          </div>

          <div className="mani-foot">
            <div className="mn-legend">
              {(['idle', 'off', 'blocked'] as RuntimeState[]).map((st) => (
                <span key={st} className={`mn-leg ${STATE_TONE[st]}`}><i />{stateLabel(st)}</span>
              ))}
            </div>
            <span className="micro">{L('valveGate')}</span>
          </div>

          {/* The travelling `live` pulse is the manifold's energised signature — it is
              earned only when at least one conduit is genuinely ARMED. With every lane
              off or blocked it is a still divider, not a running feed. */}
          <div className={`wire${counts.idle > 0 ? ' live' : ''}`} />

          {renderSchematic()}
        </section>

        {/* ── AUTOMATION INDEX (quiet data tier) ─────────────────────────────── */}
        <div className="sec-head" style={{ marginTop: 26 }}>
          <h2>{L('automationIndex')}</h2>
          <div className="afilter" role="group" aria-label={L('filterByState')}>
            {FILTERS.map((f) => (
              <button
                key={f}
                type="button"
                className={`chip${stateFilter === f ? ' on' : ''}`}
                aria-pressed={stateFilter === f}
                onClick={() => setStateFilter(f)}
              >
                {filterLabel(f)}
              </button>
            ))}
            <span className="af-count micro">
              <b className="mono">{filtered.length}</b>/{items.length}
            </span>
          </div>
        </div>
        <div className="arows">
          {filtered.map(renderRow)}
        </div>

        {/* ── manifold census (honest — every count is real) ──────────────────── */}
        <section className="surface soft astats-wrap rise">
          <div className="astats">
            <div className="astat"><b>{items.length}</b><span className="micro">{L('conduitsManifold')}</span></div>
            <div className="astat as-info"><b>{counts.idle}</b><span className="micro">{L('armed')}</span></div>
            <div className="astat"><b>{counts.off}</b><span className="micro">{L('off')}</span></div>
            <div className="astat au-danger"><b>{counts.blocked}</b><span className="micro">{L('sealed')}</span></div>
          </div>
          <div className="wire" />
        </section>

        <div className="au-kbd" aria-hidden="true">
          <span><kbd>n</kbd> {L('kbdNew')}</span>
          <span><kbd>↑</kbd><kbd>↓</kbd> {L('navigate')}</span>
          <span><kbd>↵</kbd> {L('open')}</span>
        </div>
      </>
    );
  }

  return (
    <div className="v-automations">
      <style>{CSS}</style>
      {header}

      {/* polite live region — announces selection + enable/disable/blocked outcomes */}
      <span className="au-sr" role="status" aria-live="polite">{announce}</span>

      {creating && <NewRuleForm onClose={() => setCreating(false)} onCreated={() => s.reload()} />}
      {pendingDelete && (
        <ConfirmDialog
          title={t('confirm.deleteTitle')}
          message={t('confirm.deleteBody')}
          confirmLabel={t('action.delete')}
          cancelLabel={t('action.cancel')}
          onConfirm={() => remove(pendingDelete)}
          onCancel={() => setPendingDelete(null)}
        />
      )}

      {body}
    </div>
  );
}

// Page-scoped extras (prefixed `au-`) for the parts the shared aios.css does not
// cover: the sr-live region, the `off` (disabled) dim, focus rings, the schematic
// side facts + honest telemetry note, the census danger tone, the empty/error/skeleton
// branches and the keyboard hint. The manifold/schematic/index grammar itself
// (mani/manifold/lane/ln-*/schem/sc-*/arow/astats/pill/eyebrow/bracket/ticks) is the
// shared stylesheet. `.au-gov` is unscoped because the authoring modal portals out of
// `.v-automations`. Colours resolve through tokens; motion honours reduced-motion.
const CSS = `
.v-automations .au-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}

.v-automations .lane.au-off,.v-automations .arow.au-off{opacity:.5}
.v-automations .lane.au-off:hover,.v-automations .arow.au-off:hover{opacity:.74}
.v-automations .lane:focus-visible,.v-automations .arow:focus-visible,
.v-automations .afilter .chip:focus-visible,.v-automations .au-btn:focus-visible{outline:2px solid var(--cyan-soft);outline-offset:2px}

.v-automations .sc-actions{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 2px}

.v-automations .sc-side .au-facts{display:grid;gap:12px}
.v-automations .au-fact{display:flex;flex-direction:column;gap:3px;min-width:0}
.v-automations .au-fk{font-family:var(--f-mono);font-size:8.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-muted)}
.v-automations .au-fact>span:not(.au-fk){font-size:12px;color:var(--ink);word-break:break-word}
.v-automations .au-block{margin-top:14px}
.v-automations .au-block .micro{display:block;margin-bottom:6px}
.v-automations .au-note{font-size:12px;line-height:1.55;margin:0;max-width:52ch}
.v-automations .au-runs{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
.v-automations .au-run{display:flex;align-items:center;gap:10px;font-size:12px;flex-wrap:wrap}
.v-automations .au-run-detail{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.v-automations .au-run-time{flex:0 0 auto;color:var(--ink-muted)}

/* history provenance — what is genuinely known about a row's authority. .is-bound is the
   ONLY affordance that reads as governed, and it is set from isContractEnforced(), never
   from a literal. Nothing here ever reads as verified: no receipt exists to verify. */
.v-automations .au-run-prov{flex:0 0 auto;color:var(--ink-muted);border:1px solid rgb(var(--line-rgb)/.9);
  border-radius:var(--r-pill);padding:1px 8px}
.v-automations .au-run-prov.is-bound{color:var(--cyan);border-color:rgb(var(--cyan-rgb)/.4);background:rgb(var(--cyan-rgb)/.08)}
.v-automations .au-run-vol{flex:0 0 auto;color:var(--ink-muted);font-style:italic}
.v-automations .au-run.au-volatile{opacity:.86}
.v-automations .au-run.au-k-refused .au-run-detail{color:var(--ink-muted)}

/* The run contract panel. Unscoped on purpose — like .au-gov it also renders inside the
   authoring modal, which portals out of .v-automations, so the fact/blocked grammar it uses
   is repeated here rather than inherited from the page-scoped rules above. */
.au-contract{display:block}
.au-contract .au-facts{display:grid;gap:12px}
.au-contract .au-fact{display:flex;flex-direction:column;gap:3px;min-width:0}
.au-contract .au-fk{font-family:var(--f-mono);font-size:8.5px;font-weight:700;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink-muted)}
.au-contract .au-fact>span:not(.au-fk){font-size:12px;color:var(--ink);word-break:break-word}
.au-contract .au-note{font-size:12px;line-height:1.55;margin:10px 0 0;max-width:52ch;color:var(--ink-muted)}
.au-blocked{border:1px solid rgb(var(--danger-rgb)/.4);background:rgb(var(--danger-rgb)/.09);
  border-radius:12px;padding:var(--s4);margin:4px 0 12px}
.au-blocked-title{font-weight:700;color:var(--danger);display:flex;align-items:center;gap:8px}
.au-blocked-reason{margin-top:6px;word-break:break-word}
.au-blocked-fix{margin-top:8px;font-size:13px;color:var(--ink-muted);max-width:60ch}
.au-contract .au-ct-h{display:block;margin-bottom:8px;font-weight:700}
.au-contract .au-ct-tags{display:inline-flex;gap:6px;align-items:center;margin-left:8px;flex-wrap:wrap}
.au-contract .au-list{list-style:none;margin:3px 0 0;padding:0;display:flex;flex-direction:column;gap:3px;
  font-size:11.5px;color:var(--ink-muted);line-height:1.45}
.au-contract .au-ev li.is-held{color:var(--ink)}
.au-preview{margin:12px 0 4px;border-top:1px solid rgb(var(--line-rgb)/.9);padding-top:10px}
.au-preview>.micro{display:block;margin-bottom:8px;color:var(--ink-muted)}
.au-warn{color:var(--warn,var(--danger))}

.v-automations .astat.au-danger b{color:var(--danger)}

/* blocked (wall/guard denial) panel */
.v-automations .au-blocked{border:1px solid rgb(var(--danger-rgb)/.4);background:rgb(var(--danger-rgb)/.09);
  border-radius:12px;padding:var(--s4);margin:4px 0 12px}
.v-automations .au-blocked-title{font-weight:700;color:var(--danger);display:flex;align-items:center;gap:8px}
.v-automations .au-blocked-reason{margin-top:6px;word-break:break-word}
.v-automations .au-blocked-fix{margin-top:8px;font-size:13px;color:var(--ink-muted);max-width:60ch}

/* state branches: empty · error · skeleton */
.v-automations .au-empty,.v-automations .au-pick{text-align:center;padding:var(--s7) var(--s5);display:grid;gap:8px;place-items:center}
.v-automations .au-empty-glyph{font-size:34px;color:var(--cyan-soft)}
.v-automations .au-empty-title{font-family:var(--f-display);font-weight:700;font-size:17px}
.v-automations .au-empty .muted,.v-automations .au-pick .muted{max-width:40ch;font-size:13px;line-height:1.5}
.v-automations .au-btn{font:inherit;font-size:13px;font-weight:600;height:32px;padding:0 16px;cursor:pointer;margin-top:4px;
  color:var(--cyan);border:1px solid rgb(var(--cyan-rgb)/.4);background:rgb(var(--cyan-rgb)/.08);border-radius:var(--r-pill)}
.v-automations .au-btn:hover{background:rgb(var(--cyan-rgb)/.14)}
.v-automations .au-skel{display:grid;gap:10px;margin-top:14px}
.v-automations .au-skel i{height:44px;border-radius:12px;
  background:linear-gradient(90deg,transparent,rgb(var(--cyan-rgb)/.14) 40%,rgb(var(--line-rgb)/.9) 50%,rgb(var(--cyan-rgb)/.14) 60%,transparent);
  background-size:200% 100%;animation:au-shimmer 1.4s linear infinite}
@keyframes au-shimmer{from{background-position:200% 0}to{background-position:-200% 0}}

/* keyboard hint strip */
.v-automations .au-kbd{display:flex;flex-wrap:wrap;gap:16px;margin-top:16px;font-family:var(--f-mono);font-size:var(--t-micro);color:var(--ink-muted)}
.v-automations .au-kbd span{display:inline-flex;align-items:center;gap:5px}
.v-automations .au-kbd kbd{font:inherit;font-size:11px;background:rgb(var(--raised-rgb)/.7);
  border:1px solid rgb(var(--line-rgb)/.9);border-bottom-width:2px;border-radius:5px;padding:1px 6px}

/* authoring-form governance note (portalled modal — unscoped) */
.au-gov{display:flex;gap:8px;align-items:flex-start;font-size:12px;color:var(--ink-muted);
  background:rgb(var(--cyan-rgb)/.06);border:1px solid rgb(var(--cyan-rgb)/.18);
  border-radius:12px;padding:9px 11px;margin-bottom:14px}

/* ── energised (armed) conduit — the live standing field ──────────────────────
   The real entity has no throughput, so packets/pulse must never assert a rate.
   They render only for an ARMED, enabled conduit (.au-live, never off/blocked)
   as the manifold's live-energy signature; readouts stay "—". These selectors
   out-specify the shared aios.css that hides .ln-flow unless a lane is .flowing
   (.lane:not(.flowing):not(.throttled) .ln-flow{display:none}). */
.v-automations .manifold .lane.au-live:not(.au-off) .ln-flow{display:block;animation:au-flow 3s linear infinite;animation-delay:var(--d,0s)}
.v-automations .manifold .lane.au-live:not(.au-off) .ln-flow::before{opacity:.9}
.v-automations .lane.au-live .ln-pipe::before{opacity:1}
.v-automations .lane.au-live .ln-pipe{border-color:rgb(var(--st-rgb)/.34);
  box-shadow:inset 0 0 12px rgb(var(--st-rgb)/.12),inset 0 1px 3px rgb(var(--bg-rgb)/.55)}
.v-automations .lane.au-live .lv-core{opacity:1;animation:pulse 2.6s ease-in-out infinite}
.v-automations .lane.au-live .ln-out{border-color:rgb(var(--st-rgb)/.7);
  background:rgb(var(--st-rgb)/.18);box-shadow:0 0 9px rgb(var(--st-rgb)/.5)}

/* schematic traveling pulse — armed/energised selected conduit only */
.v-automations .sc-diagram.au-live .sc-pulse::before{opacity:.9}
.v-automations .sc-diagram.au-live .sc-pulse{animation:au-flow 3.2s linear infinite}
.v-automations .sc-diagram.au-live .sc-rail{background:linear-gradient(90deg,rgb(var(--st-rgb)/.45),rgb(var(--st-rgb)/.16))}

@media (prefers-reduced-motion:reduce){
  .v-automations .au-skel i{animation:none}
  /* shared css already forces .ln-flow/.sc-pulse/.lv-core animation:none — here
     we just park a single static packet mid-conduit so the field stays legible. */
  .v-automations .manifold .lane.au-live .ln-flow:first-child{transform:translateX(50%)}
  .v-automations .manifold .lane.au-live .ln-flow:not(:first-child){display:none}
  .v-automations .sc-diagram.au-live .sc-pulse{transform:translateX(50%)}
}
`;
