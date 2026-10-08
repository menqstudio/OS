import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (cmd: string, args?: unknown) => invokeMock(cmd, args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Calendar } from './Calendar';

/**
 * Phase 8: *"Run history with receipt ids in `calendar`."*
 *
 * The calendar read only `list_events`, so scheduled operations were visible and **what actually
 * ran was not**. The history is here now — and so is the fact the box's own wording assumes and
 * this build does not have.
 *
 * **There is no receipt id.** `automationsGovernance.ts` already establishes why in its evidence
 * model: `run_automation` is a local SQLite write, not a governed dispatch, so its
 * `engine_receipt` item is `observed: false` and nothing in the automation path can flip it.
 *
 * These tests pin the honest shape: the runs appear, and the absence is **stated once**, not
 * rendered as a blank column that would read as "pending" or filled with a run id that would read
 * as a receipt.
 */
const AUTOMATIONS = [
  { id: 'au-1', name: 'Nightly backup', trigger: 'cron', action: 'backup', enabled: true,
    createdAt: '1700000000000', updatedAt: '1700000000000' },
];

const RUNS = [
  { id: 'run-2', automationId: 'au-1', ranAt: '1700000200000', outcome: 'ok', detail: '' },
  { id: 'run-1', automationId: 'au-1', ranAt: '1700000100000', outcome: 'failed', detail: 'disk' },
];

function mount(over: { runs?: unknown[]; automations?: unknown[] } = {}) {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_events') return Promise.resolve([]);
    if (cmd === 'list_automations') return Promise.resolve(over.automations ?? AUTOMATIONS);
    if (cmd === 'list_automation_runs') return Promise.resolve(over.runs ?? RUNS);
    return Promise.resolve([]);
  });
  return render(<AppProvider><ToastProvider><Calendar /></ToastProvider></AppProvider>);
}

const history = () => screen.getByLabelText(/run history|պատմություն|история/i);

/** Wait for the RUNS to land, not just the section. The history renders as soon as the
 *  automations read resolves; the per-automation run reads land after it, so asserting on the
 *  section's appearance would be asserting that the reads had not finished yet. */
async function historyWithRuns(n: number) {
  await waitFor(() => expect(within(history()).getAllByRole('listitem')).toHaveLength(n));
  return history();
}

beforeEach(() => invokeMock.mockReset());

describe('Calendar — run history, and the receipt this build cannot produce', () => {
  it('shows what actually ran, newest first', async () => {
    mount();
    await historyWithRuns(2);
    const items = within(history()).getAllByRole('listitem');
    // Newest first: a history that reads oldest-first buries the thing the owner came for.
    expect(items[0].textContent).toContain('ok');
    expect(items[1].textContent).toContain('failed');
    expect(items[0].textContent).toContain('Nightly backup');
  });

  it('states that no engine receipt exists — once, not as an empty column', async () => {
    mount();
    await historyWithRuns(2);
    expect(history().textContent).toMatch(/no engine receipt|անդորրագիր|квитанц/i);
  });

  it('never labels a run id as a receipt', async () => {
    // The failure this guards: printing `run-2` under a "receipt" heading. A run id looks
    // exactly like a receipt id to a reader, and the whole point of the note above is that
    // there is not one.
    mount();
    await historyWithRuns(2);
    const text = history().textContent ?? '';
    // The word may appear ONLY in the note that says there is none — never on a run row. This
    // used to slice the text from the index where /receipt/ matched and assert the slice
    // matched /receipt/: a tautology inside an `if`, which no rendering could fail.
    for (const row of within(history()).getAllByRole('listitem')) {
      expect(row.textContent ?? '').not.toMatch(/receipt|անդորրագիր|квитанц/i);
    }
    const note = history().querySelector('.cal-run-note');
    expect(note?.textContent ?? '').toMatch(/No engine receipt exists/);
    // Exactly one mention, and it is the note's.
    expect(text.match(/receipt/gi)).toHaveLength(1);
    expect(text).not.toContain('run-2');
    expect(text).not.toContain('run-1');
  });

  it('never says "No automation has run yet" before the runs have been read', async () => {
    // The first runs read is made against an EMPTY automation list (the automations are still
    // loading), and `useAsync` keeps that answer until the next read lands. For one committed
    // frame after the automations arrived, the section printed the empty-history sentence over
    // an automation whose runs nobody had asked for yet.
    //
    // One frame is gone before any query can look, so the DOM is WATCHED instead: every node
    // ever added is recorded, including one removed again in the next commit.
    const everAdded: string[] = [];
    const observer = new MutationObserver((records) => {
      for (const r of records) {
        r.addedNodes.forEach((n) => everAdded.push(n.textContent ?? ''));
        if (r.type === 'characterData') everAdded.push(r.target.textContent ?? '');
      }
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    try {
      mount();
      await historyWithRuns(2);
      await new Promise((r) => setTimeout(r, 0));
    } finally {
      observer.disconnect();
    }
    expect(everAdded.length).toBeGreaterThan(0);
    expect(everAdded.some((t) => /No automation has run yet/.test(t))).toBe(false);
  });

  it('an automation that has never run says so instead of showing an empty list', async () => {
    mount({ runs: [] });
    await waitFor(() => expect(history()).toBeInTheDocument());
    expect(within(history()).queryAllByRole('listitem')).toHaveLength(0);
    expect(history().textContent).toMatch(/no automation has run|դեռ չի ա|не запускалась/i);
  });

  it('a failing runs read does not take the calendar down with it', async () => {
    // The history is an addition to a page that worked without it; a rejected read must degrade
    // to no history, not to a blank calendar.
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'list_events') return Promise.resolve([]);
      if (cmd === 'list_automations') return Promise.resolve(AUTOMATIONS);
      if (cmd === 'list_automation_runs') return Promise.reject(new Error('boom'));
      return Promise.resolve([]);
    });
    render(<AppProvider><ToastProvider><Calendar /></ToastProvider></AppProvider>);
    await waitFor(() => expect(within(history()).getByRole('alert')).toBeInTheDocument());
    expect(within(history()).queryAllByRole('listitem')).toHaveLength(0);
    // …and "no history" is not "nothing ran". The failed read used to print the empty-history
    // sentence, which is a claim about the world made from a read that did not answer.
    expect(history().textContent).not.toMatch(/No automation has run yet/);
    expect(within(history()).getByRole('alert')).toHaveTextContent(/could not be read in full/);
    expect(within(history()).getByRole('alert')).toHaveTextContent('boom');
  });

  it('a failing automations read is not "nothing ran" either', async () => {
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'list_events') return Promise.resolve([]);
      if (cmd === 'list_automations') return Promise.reject(new Error('database is locked'));
      return Promise.resolve([]);
    });
    render(<AppProvider><ToastProvider><Calendar /></ToastProvider></AppProvider>);
    await waitFor(() => expect(within(history()).getByRole('alert')).toHaveTextContent('database is locked'));
    expect(history().textContent).not.toMatch(/No automation has run yet/);
  });

  it('the section is named by a real heading in every language', async () => {
    // The Armenian heading began with a Latin "S" and matched nothing this file looks for, so
    // the `պատմություն` branch of the locator above was dead.
    const { STR } = await import('./Calendar.strings');
    for (const lang of ['en', 'hy', 'ru'] as const) {
      expect(STR.runHistory[lang]).toMatch(/run history|պատմություն|история/i);
    }
    expect(STR.runHistory.hy).not.toMatch(/[A-Za-z]/);
  });

  it('delete stays parked: disabled, with its reason, and wired to nothing', async () => {
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'list_events') {
        const today = new Date();
        today.setHours(12, 0, 0, 0);
        return Promise.resolve([{
          id: 'ev-1', title: 'Standup', kind: 'meeting', location: '',
          startsAt: today.toISOString(), endsAt: null, createdAt: '1700000000000', updatedAt: '1700000000000',
        }]);
      }
      return Promise.resolve([]);
    });
    render(<AppProvider><ToastProvider><Calendar /></ToastProvider></AppProvider>);
    const del = await screen.findByRole('button', { name: 'Delete' });
    expect(del).toBeDisabled();
    expect(del).toHaveAttribute('title', expect.stringMatching(/disabled for safety/));
    expect(invokeMock.mock.calls.some((c) => c[0] === 'delete_event')).toBe(false);
  });
});

// Run times were `new Date(Number(run.ranAt)).toLocaleString()`: the shared parser was bypassed, so
// a time it reads and `Number()` does not printed "Invalid Date", and the machine's locale was
// used instead of the page's.
describe('Calendar — run times go through the shared parser', () => {
  it('a time the shared parser reads is not printed as "Invalid Date"', async () => {
    mount({ runs: [{ id: 'run-9', automationId: 'au-1', ranAt: '2026-08-07T14:44:11.166Z', outcome: 'ok', detail: '' }] });
    await historyWithRuns(1);
    expect(document.querySelector('.cal-run-when')!.textContent).not.toMatch(/Invalid Date/);
    expect(document.querySelector('.cal-run-when')!.textContent).toMatch(/2026/);
  });

  it('a time nothing can read is a dash, not "Invalid Date"', async () => {
    mount({ runs: [{ id: 'run-9', automationId: 'au-1', ranAt: 'not a time', outcome: 'ok', detail: '' }] });
    await historyWithRuns(1);
    expect(document.querySelector('.cal-run-when')!.textContent).toBe('—');
  });
});
