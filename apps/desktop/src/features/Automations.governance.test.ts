/// <reference types="vite/client" />
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

/** Vitest runs with `apps/desktop` as its root, so repo files are resolved from there. Reading
 *  the REAL files (rather than importing a copy) is the point: this suite exists to catch the
 *  renderer's mirror drifting away from the authoritative policy. */
const fromDesktopRoot = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8');

import {
  COMMAND_POLICY, LOCAL_RISK_CEILING, assessAction, assessRun, bindReceipt, buildLedger,
  classifyRun, commandPolicy, isAllowed, isContractEnforced, isEngineVerified, parseAction,
  parseIntervalMs, parseTrigger, riskExceeds, summarise,
  type RunContract, type SessionRefusal,
} from './automationsGovernance';
import type { Automation, AutomationRun } from '../domain/entities';

// ─────────────────────────────────────────────────────────────────────────────
// Fixtures
// ─────────────────────────────────────────────────────────────────────────────

const automation = (over: Partial<Automation> = {}): Automation => ({
  id: 'au-1',
  name: 'Morning digest',
  trigger: 'manual',
  action: 'notify: good morning',
  enabled: true,
  createdAt: '1700000000000',
  updatedAt: '1700000000000',
  ...over,
});

const run = (over: Partial<AutomationRun> = {}): AutomationRun => ({
  id: 'r-1',
  automationId: 'au-1',
  ranAt: '1700000000000',
  outcome: 'ok',
  detail: 'notified: good morning',
  ...over,
});

// ─────────────────────────────────────────────────────────────────────────────
// 1 · The capability mirror must equal the authoritative policy
// ─────────────────────────────────────────────────────────────────────────────

interface PolicyFile {
  commands: Record<string, { tier: string; grant: string; protection?: string }>;
}

const authoritative: PolicyFile = JSON.parse(fromDesktopRoot('src-tauri/command-policy.json'));

describe('the capability mirror is a mirror, not a second opinion', () => {
  it('every mirrored command matches src-tauri/command-policy.json exactly', () => {
    const drift: string[] = [];
    for (const [command, mirrored] of Object.entries(COMMAND_POLICY)) {
      const real = authoritative.commands[command];
      if (!real) {
        drift.push(`${command}: not in command-policy.json at all`);
        continue;
      }
      if (real.tier !== mirrored.tier || real.grant !== mirrored.grant) {
        drift.push(
          `${command}: mirror says ${mirrored.tier}/${mirrored.grant}, policy says ${real.tier}/${real.grant}`,
        );
      }
    }
    expect(drift, 'Update the mirror to match the authoritative policy — never the other way round').toEqual([]);
  });

  // The rule this page is most likely to get wrong in either direction.
  it('delete_automation is GRANTED at tier X — it is not one of the denied hard-deletes', () => {
    expect(authoritative.commands.delete_automation).toMatchObject({ tier: 'X', grant: 'allow' });
    expect(commandPolicy('delete_automation')).toEqual({ tier: 'X', grant: 'allow' });
  });

  it('the neighbouring hard-deletes stay DENIED — the automation grant is never generalised to them', () => {
    for (const command of [
      'delete_conversation', 'delete_knowledge', 'delete_library_item',
      'delete_research_item', 'delete_memory', 'delete_event',
    ]) {
      expect(authoritative.commands[command], `${command} in command-policy.json`)
        .toMatchObject({ tier: 'L2', grant: 'deny' });
      expect(commandPolicy(command).grant, `${command} in the mirror`).toBe('deny');
    }
  });

  it('an unknown command is treated as execution-tier and DENIED (fail-closed)', () => {
    expect(commandPolicy('some_command_that_does_not_exist')).toEqual({ tier: 'X', grant: 'deny' });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 2 · The action vocabulary
// ─────────────────────────────────────────────────────────────────────────────

describe('parseAction — the same vocabulary the backend executor implements', () => {
  it('accepts the three local verbs and names the store each one writes', () => {
    expect(parseAction('notify: hello')).toMatchObject({ ok: true, verb: 'notify', effect: 'notification', argument: 'hello' });
    expect(parseAction('task: ship it')).toMatchObject({ ok: true, verb: 'task', effect: 'task' });
    expect(parseAction('NOTE: read me')).toMatchObject({ ok: true, verb: 'note', effect: 'knowledge_note' });
  });

  it('refuses an action with no verb/argument shape', () => {
    expect(parseAction('')).toMatchObject({ ok: false, reason: 'action_empty' });
    expect(parseAction('backup')).toMatchObject({ ok: false, reason: 'action_malformed' });
    expect(parseAction(': orphan')).toMatchObject({ ok: false, reason: 'action_malformed' });
    expect(parseAction('notify:   ')).toMatchObject({ ok: false, reason: 'action_argument_missing' });
  });

  it('distinguishes an unknown verb from one that would reach the model', () => {
    expect(parseAction('archive: everything')).toMatchObject({ ok: false, reason: 'action_verb_unknown' });
    expect(parseAction('ask: summarise my inbox')).toMatchObject({ ok: false, reason: 'action_reaches_model', offending: 'ask' });
    expect(parseAction('agent: research this')).toMatchObject({ ok: false, reason: 'action_reaches_model' });
    expect(parseAction('http: https://example.com')).toMatchObject({ ok: false, reason: 'action_reaches_model' });
  });
});

describe('parseIntervalMs — the truth about what the scheduler will fire', () => {
  it('accepts exactly the shapes the Rust parser accepts', () => {
    expect(parseIntervalMs('every: 5m')).toBe(300_000);
    expect(parseIntervalMs('EVERY:1h')).toBe(3_600_000);
    expect(parseIntervalMs('every: 2d')).toBe(172_800_000);
  });

  it('rejects everything else, so no fire is claimed that never happens', () => {
    for (const t of ['manual', '', 'cron', 'every: 0m', 'every: -5m', 'every: 5x', 'every: m', 'daily', 'every: 1.5h']) {
      expect(parseIntervalMs(t), t).toBeNull();
    }
  });

  it('classifies a trigger as interval / manual / unrecognised', () => {
    expect(parseTrigger('every: 10m')).toMatchObject({ kind: 'interval', intervalMs: 600_000 });
    expect(parseTrigger('manual')).toMatchObject({ kind: 'manual' });
    expect(parseTrigger('')).toMatchObject({ kind: 'manual' });
    // The quiet one: this looks like a schedule and is fired by nothing.
    expect(parseTrigger('cron')).toMatchObject({ kind: 'unrecognised' });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 3 · The contract
// ─────────────────────────────────────────────────────────────────────────────

describe('assessRun — every run carries who / role / scope / risk / evidence', () => {
  it('builds the full contract for an allowed owner-initiated run', () => {
    const a = assessRun(automation(), 'owner');
    expect(isAllowed(a)).toBe(true);
    expect(a.contract).toMatchObject({
      actor: 'owner',
      roleId: 'desktop-owner',
      command: 'run_automation',
      tier: 'X',
      grant: 'allow',
      effect: 'notification',
      risk: 'low',
      unattended: false,
    });
    expect(a.contract.scope).toEqual(['automation:au-1', 'notifications:create']);
    expect(a.contract.riskFactors).toContain('local_effect_only');
    expect(a.contract.evidence.map((e) => e.id)).toEqual(['run_row', 'audit_event', 'engine_receipt']);
  });

  it('an unattended (interval) fire is the scheduler’s, at a higher risk, and says why', () => {
    const a = assessRun(automation({ trigger: 'every: 15m' }), 'scheduler');
    expect(a.contract).toMatchObject({ actor: 'scheduler', roleId: 'local-scheduler', risk: 'medium', unattended: true });
    expect(a.contract.riskFactors).toContain('unattended_schedule');
    expect(riskExceeds(a.contract.risk, LOCAL_RISK_CEILING)).toBe(false);
    expect(isAllowed(a)).toBe(true);
  });

  it('refuses a model-reaching action instead of running it ungoverned', () => {
    const a = assessRun(automation({ action: 'ask: summarise my inbox' }), 'owner');
    expect(a.refusal).toBe('action_reaches_model');
    // The contract is still built, so the page can show the shape that was not satisfiable.
    expect(a.contract.risk).toBe('high');
    expect(a.contract.riskFactors).toContain('reaches_model');
    expect(riskExceeds(a.contract.risk, LOCAL_RISK_CEILING)).toBe(true);
  });

  it('refuses a disabled automation, and reports a broken rule ahead of merely being off', () => {
    expect(assessRun(automation({ enabled: false }), 'owner').refusal).toBe('automation_disabled');
    // Off AND unrunnable: the rule problem is the one worth reporting.
    expect(assessRun(automation({ enabled: false, action: 'backup' }), 'owner').refusal).toBe('action_malformed');
  });

  it('refuses when the capability policy denies the command, whatever the action says', () => {
    const denied = { run_automation: { tier: 'X', grant: 'deny' } } as const;
    const a = assessRun(automation(), 'owner', denied);
    expect(a.refusal).toBe('command_denied');
    expect(a.contract.grant).toBe('deny');
  });

  it('authoring uses the same gate as running', () => {
    expect(assessAction('notify: hi')).toMatchObject({ ok: true });
    expect(assessAction('ask: anything')).toMatchObject({ ok: false, reason: 'action_reaches_model' });
    expect(assessAction('backup')).toMatchObject({ ok: false, reason: 'action_malformed' });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 4 · The history
// ─────────────────────────────────────────────────────────────────────────────

describe('classifyRun — a stored row is read, never flattered', () => {
  it('only the literal outcome `ok` counts as executed', () => {
    expect(classifyRun(run())).toEqual({ kind: 'executed', reason: null });
    expect(classifyRun(run({ outcome: 'OK' })).kind).toBe('failed');
    expect(classifyRun(run({ outcome: 'whatever' })).kind).toBe('failed');
  });

  it('reads the backend’s own vocabulary refusals as refusals, with the reason', () => {
    expect(classifyRun(run({ outcome: 'failed', detail: "unknown action verb 'backup' (supported: notify, task, note)" })))
      .toEqual({ kind: 'refused', reason: 'action_verb_unknown' });
    expect(classifyRun(run({ outcome: 'failed', detail: 'unrecognized action (expected `verb: argument`): backup' })))
      .toEqual({ kind: 'refused', reason: 'action_malformed' });
    expect(classifyRun(run({ outcome: 'failed', detail: "action 'notify' has no argument" })))
      .toEqual({ kind: 'refused', reason: 'action_argument_missing' });
  });

  it('an ordinary failure stays a failure', () => {
    expect(classifyRun(run({ outcome: 'failed', detail: 'database is locked' })))
      .toEqual({ kind: 'failed', reason: null });
  });
});

describe('buildLedger — the history says only what is known', () => {
  const contract = (): RunContract => assessRun(automation(), 'owner').contract;

  it('a stored run with no session binding is UNATTRIBUTED', () => {
    const [entry] = buildLedger([run()], [], {});
    expect(entry).toMatchObject({ kind: 'executed', provenance: 'authority_not_recorded', persisted: true });
    expect(entry.contract).toBeNull();
    expect(isContractEnforced(entry)).toBe(false);
  });

  it('a stored run bound to this session’s contract is attributed — and only then', () => {
    const bound = bindReceipt(contract(), run());
    const [entry] = buildLedger([run()], [], { 'r-1': bound });
    expect(entry.provenance).toBe('contracted_this_session');
    expect(isContractEnforced(entry)).toBe(true);
    // A contract whose row was never returned does not count as enforced.
    const [unbound] = buildLedger([run()], [], { 'r-1': contract() });
    expect(isContractEnforced(unbound)).toBe(false);
  });

  it('bindReceipt refuses a row belonging to another automation', () => {
    const c = contract();
    const foreign = bindReceipt(c, run({ automationId: 'au-2' }));
    expect(foreign.evidence.find((e) => e.id === 'run_row')?.observed).toBe(false);
  });

  it('a refusal from this session appears in the history, unpersisted, with its reason', () => {
    const refusal: SessionRefusal = {
      key: 'refusal:au-1:1700000000500:0',
      at: '1700000000500',
      reason: 'action_reaches_model',
      detail: 'would reach the model',
      contract: contract(),
      origin: 'preflight',
    };
    const entries = buildLedger([run()], [refusal], {});
    expect(entries.map((e) => e.provenance)).toEqual(['refused_preflight', 'authority_not_recorded']); // newest first
    expect(entries[0]).toMatchObject({ kind: 'refused', persisted: false, reason: 'action_reaches_model' });
  });

  it('a refusal by the store is distinguishable from one refused before the call', () => {
    const base = { key: 'k', at: '1700000000600', reason: null, detail: 'denied', contract: contract() };
    expect(buildLedger([], [{ ...base, origin: 'store' }], {})[0].provenance).toBe('refused_by_store');
    expect(buildLedger([], [{ ...base, origin: 'preflight' }], {})[0].provenance).toBe('refused_preflight');
  });

  it('summarises without inflating: refusals are never counted as runs', () => {
    const refusal: SessionRefusal = {
      key: 'k', at: '1700000000700', reason: 'action_verb_unknown', detail: 'no', contract: contract(), origin: 'preflight',
    };
    const s = summarise(buildLedger(
      [run(), run({ id: 'r-2', outcome: 'failed', detail: 'database is locked' })],
      [refusal],
      {},
    ));
    expect(s).toMatchObject({ total: 3, executed: 1, failed: 1, refused: 1, attributed: 0, unattributed: 2 });
  });
});

describe('nothing is ever presented as engine-verified', () => {
  it('no ledger entry this module can build is engine-verified', () => {
    const c = assessRun(automation(), 'owner').contract;
    const entries = [
      ...buildLedger([run(), run({ id: 'r-2', outcome: 'failed', detail: 'boom' })], [], { 'r-1': bindReceipt(c, run()) }),
      ...buildLedger([], [{ key: 'k', at: '1', reason: null, detail: 'd', contract: c, origin: 'store' }], {}),
    ];
    expect(entries.length).toBeGreaterThan(0);
    for (const e of entries) expect(isEngineVerified(e)).toBe(false);
  });

  it('binding the returned row never marks the engine receipt observed', () => {
    const bound = bindReceipt(assessRun(automation(), 'owner').contract, run());
    expect(bound.evidence.find((e) => e.id === 'engine_receipt')?.observed).toBe(false);
    expect(bound.evidence.find((e) => e.id === 'audit_event')?.observed).toBe(false);
    expect(bound.evidence.find((e) => e.id === 'run_row')?.observed).toBe(true);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 5 · Source guard — the gate cannot be removed from the run path
// ─────────────────────────────────────────────────────────────────────────────

const pageSource = fromDesktopRoot('src/features/Automations.tsx');

describe('the run path cannot lose its pre-flight gate', () => {
  it('every runAutomation call site is preceded by an assessRun refusal check that returns', () => {
    const sites = [...pageSource.matchAll(/desktop\s*\n?\s*\.runAutomation\(/g)];
    expect(sites.length, 'expected exactly one run_automation call site on this page').toBe(1);
    const before = pageSource.slice(0, sites[0].index);
    const gate = before.lastIndexOf('assessRun(');
    expect(gate, 'assessRun must be called before runAutomation').toBeGreaterThan(-1);
    const between = before.slice(gate);
    expect(between, 'the refusal must end the handler before the invoke').toMatch(/refusal !== null[\s\S]*return;/);
  });

  it('the page never invokes a denied hard-delete', () => {
    for (const denied of [
      'delete_conversation', 'delete_knowledge', 'delete_library_item',
      'delete_research_item', 'delete_memory', 'delete_event',
    ]) {
      // The names may appear in the governance mirror, but never as a call from this page.
      expect(pageSource).not.toContain(`desktop.${denied}`);
    }
  });
});
