import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';

/**
 * Phase 8 — a fired automation must be GOVERNED, and its history must be honest.
 *
 * Before this, a fire recorded `automation_runs(id, time, outcome, detail)` and nothing about
 * authority: an owner-pressed run and an unattended 04:00 scheduler fire were indistinguishable,
 * a refused run left no trace at all, and an action that would reach the model was allowed to be
 * authored and merely failed at fire time.
 *
 * What must hold now:
 *   1. an action with no governed path is refused at AUTHORING time — `create_automation` is
 *      never invoked;
 *   2. the same rule seals the conduit and refuses at RUN time — `run_automation` is never
 *      invoked, and the reason is readable;
 *   3. an allowed run states the contract it runs under (authority, role, command + tier, scope,
 *      risk, evidence);
 *   4. the history distinguishes a run this session contracted from a stored run whose authority
 *      the table never recorded, and shows refusals with their origin;
 *   5. nothing is ever shown as engine-verified — no automation run produces a receipt.
 */
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Automations } from './Automations';

const AUTOMATION = {
  id: 'au-1',
  name: 'Morning digest',
  trigger: 'manual',
  action: 'notify: good morning',
  enabled: true,
  createdAt: '1700000000000',
  updatedAt: '1700000000000',
};

/** A run already in the store when the page opens — nobody knows who fired it. */
const OLD_RUN = {
  id: 'r-old',
  automationId: 'au-1',
  ranAt: '1700000000000',
  outcome: 'ok',
  detail: 'notified: yesterday',
};

interface Options {
  action?: string;
  enabled?: boolean;
  runs?: Array<typeof OLD_RUN>;
  /** How `run_automation` answers. */
  onRun?: 'ok' | 'refuse';
  /** How `create_automation` answers. */
  onCreate?: 'ok' | 'refuse';
}

function setup(opts: Options = {}) {
  const automation = { ...AUTOMATION, action: opts.action ?? AUTOMATION.action, enabled: opts.enabled ?? true };
  const store = [...(opts.runs ?? [])];
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_automations') return Promise.resolve([automation]);
    if (cmd === 'list_automation_runs') return Promise.resolve([...store].reverse());
    if (cmd === 'run_automation') {
      if (opts.onRun === 'refuse') {
        return Promise.reject(new Error('run_automation not allowed. Permissions associated with this command: '));
      }
      const fresh = {
        id: 'r-new', automationId: 'au-1', ranAt: '1700000009000', outcome: 'ok', detail: 'notified: good morning',
      };
      store.push(fresh);
      return Promise.resolve(fresh);
    }
    if (cmd === 'create_automation') {
      if (opts.onCreate === 'refuse') return Promise.reject(new Error('create_automation denied'));
      return Promise.resolve(automation);
    }
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Automations />
      </ToastProvider>
    </AppProvider>,
  );
}

const called = (cmd: string) => invokeMock.mock.calls.filter((c) => c[0] === cmd).length;
const liveText = () => document.querySelector('.au-sr')?.textContent ?? '';
const history = () => document.querySelectorAll('.au-runs .au-run');

async function loaded() {
  await waitFor(() => expect(screen.getAllByText('Morning digest').length).toBeGreaterThan(0));
}

vi.setConfig({ testTimeout: 30000 });
beforeEach(() => invokeMock.mockReset());

// ─────────────────────────────────────────────────────────────────────────────

describe('an ungoverned automation cannot be authored', () => {
  it('refuses a model-reaching action at authoring time and never calls create_automation', async () => {
    setup();
    await loaded();

    fireEvent.click(screen.getByRole('button', { name: 'New' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Summarise inbox' } });
    fireEvent.change(within(dialog).getByLabelText('Action'), { target: { value: 'ask: summarise my inbox' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create' }));

    const alert = await within(dialog).findByRole('alert');
    expect(alert).toHaveTextContent('This rule cannot be created');
    expect(alert).toHaveTextContent(/would reach the model\/engine/i);
    // The whole point: nothing was written.
    expect(called('create_automation')).toBe(0);
    // The dialog stays open so the owner can fix the action.
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('accepts a local action and previews the contract it would run under', async () => {
    setup();
    await loaded();

    fireEvent.click(screen.getByRole('button', { name: 'New' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Daily note' } });
    fireEvent.change(within(dialog).getByLabelText('Trigger'), { target: { value: 'every: 1d' } });
    fireEvent.change(within(dialog).getByLabelText('Action'), { target: { value: 'note: daily log' } });

    // The preview names the authority and the store the action would write — before it exists.
    const preview = dialog.querySelector('.au-contract') as HTMLElement;
    expect(preview).toBeTruthy();
    expect(preview).toHaveTextContent('knowledge:create');
    expect(preview).toHaveTextContent('tier X');

    fireEvent.click(within(dialog).getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(called('create_automation')).toBe(1));
  });

  it('says when a trigger is one the scheduler will never fire', async () => {
    setup();
    await loaded();
    fireEvent.click(screen.getByRole('button', { name: 'New' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Trigger'), { target: { value: 'cron' } });
    expect(dialog).toHaveTextContent(/not a recognised trigger/i);
  });
});

describe('a run that cannot be governed is refused before the backend is touched', () => {
  it('seals the conduit, explains why, and never invokes run_automation', async () => {
    setup({ action: 'ask: summarise my inbox' });
    await loaded();

    // The standing refusal is on screen without anyone pressing anything.
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Refused by the run contract');
    expect(alert).toHaveTextContent(/would reach the model\/engine/i);
    expect(alert).toHaveTextContent(/Ask Bro directly in chat/i);

    // The conduit reads as sealed rather than armed.
    expect(screen.getAllByText('Sealed').length).toBeGreaterThan(0);

    // And the run button cannot be used to reach the backend.
    const runNow = screen.getByRole('button', { name: 'Run now' });
    expect(runNow).toBeDisabled();
    fireEvent.click(runNow);
    expect(called('run_automation')).toBe(0);
  });

  it('an unrecognised verb is refused too, and named as a typo rather than a governance gap', async () => {
    setup({ action: 'backup' });
    await loaded();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/not `verb: argument`/);
    expect(called('run_automation')).toBe(0);
  });
});

describe('an allowed run carries a contract, and the history says what is known', () => {
  it('shows the contract: authority, role, command + tier, scope, risk and evidence', async () => {
    setup({ runs: [OLD_RUN] });
    await loaded();

    const contract = document.querySelector('.sc-side .au-contract') as HTMLElement;
    expect(contract).toBeTruthy();
    expect(contract).toHaveTextContent('You — this session');
    expect(contract).toHaveTextContent('desktop-owner');
    expect(contract).toHaveTextContent('run_automation');
    expect(contract).toHaveTextContent('tier X');
    expect(contract).toHaveTextContent('automation:au-1');
    expect(contract).toHaveTextContent('notifications:create');
    expect(contract).toHaveTextContent('Low');
    // Evidence is stated with whether it is actually held — and the receipt never is.
    expect(contract).toHaveTextContent(/run row \(automation_runs\)/);
    expect(contract).toHaveTextContent(/audit event \(automation\.ran\).*not observed here/s);
    expect(contract).toHaveTextContent(/signed engine receipt.*never produced in this build/s);
  });

  it('attributes only the run it contracted, and leaves the pre-existing one unattributed', async () => {
    setup({ runs: [OLD_RUN] });
    await loaded();

    // Before: one stored run, authority unknown.
    await waitFor(() => expect(history().length).toBe(1));
    expect(history()[0]).toHaveTextContent('authority not recorded');

    fireEvent.click(screen.getByRole('button', { name: 'Run now' }));
    await waitFor(() => expect(called('run_automation')).toBe(1));
    await waitFor(() => expect(history().length).toBe(2));

    // The new run is the only one this session can vouch for.
    const rows = Array.from(history()).map((r) => r.textContent ?? '');
    const contracted = rows.filter((r) => r.includes('contract enforced here'));
    const unattributed = rows.filter((r) => r.includes('authority not recorded'));
    expect(contracted).toHaveLength(1);
    expect(contracted[0]).toContain('notified: good morning');
    expect(unattributed).toHaveLength(1);
    expect(unattributed[0]).toContain('notified: yesterday');

    // Nothing anywhere claims the run was verified.
    expect(document.querySelector('.au-runs')?.textContent ?? '').not.toMatch(/verified/i);
  });

  it('records a backend refusal as a refusal — never as a run, and flagged as unpersisted', async () => {
    setup({ runs: [OLD_RUN], onRun: 'refuse' });
    await loaded();
    await waitFor(() => expect(history().length).toBe(1));

    fireEvent.click(screen.getByRole('button', { name: 'Run now' }));
    await waitFor(() => expect(history().length).toBe(2));

    const refused = Array.from(history()).find((r) => (r.textContent ?? '').includes('refused'));
    expect(refused).toBeTruthy();
    expect(refused).toHaveTextContent('refused by the store');
    expect(refused).toHaveTextContent(/run_automation not allowed/);
    expect(refused).toHaveTextContent(/this session only/i);
    // The refused attempt did not become an executed run.
    expect(Array.from(history()).filter((r) => (r.textContent ?? '').includes('ran'))).toHaveLength(1);
    expect(liveText()).not.toMatch(/✓/);
  });

  it('reads the store’s own vocabulary refusal as refused, not merely failed', async () => {
    setup({
      runs: [{
        id: 'r-bad',
        automationId: 'au-1',
        ranAt: '1700000005000',
        outcome: 'failed',
        detail: "unknown action verb 'backup' (supported: notify, task, note)",
      }],
    });
    await loaded();
    await waitFor(() => expect(history().length).toBe(1));
    expect(history()[0]).toHaveTextContent('refused');
    expect(history()[0]).toHaveTextContent('refused by the store');
  });
});

describe('the unattended path is disclosed rather than implied', () => {
  it('does not flag it when nothing is actually scheduled (the flag is earned, not decorative)', async () => {
    setup({ action: 'notify: tick' });   // trigger is `manual`
    await loaded();
    expect(screen.queryByText('Unattended fires carry no contract')).not.toBeInTheDocument();
    // …and the contract for a manual conduit does not claim an unattended risk factor.
    const contract = document.querySelector('.sc-side .au-contract') as HTMLElement;
    expect(contract).not.toHaveTextContent(/nobody present/i);
    expect(contract).toHaveTextContent(/manual only — the scheduler never fires it/i);
  });

  it('flags the unattended path when a real row carries an interval trigger', async () => {
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'list_automations') {
        return Promise.resolve([{ ...AUTOMATION, trigger: 'every: 5m' }]);
      }
      if (cmd === 'list_automation_runs') return Promise.resolve([]);
      return Promise.resolve(null);
    });
    render(
      <AppProvider>
        <ToastProvider>
          <Automations />
        </ToastProvider>
      </AppProvider>,
    );
    await loaded();
    expect(await screen.findByText('Unattended fires carry no contract')).toBeInTheDocument();
    // And the contract for that conduit says the risk is raised because nobody is present.
    const contract = document.querySelector('.sc-side .au-contract') as HTMLElement;
    expect(contract).toHaveTextContent(/interval trigger fires it with nobody present/i);
  });
});
