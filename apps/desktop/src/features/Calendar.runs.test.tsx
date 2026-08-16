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
    const receiptIdx = text.search(/receipt/i);
    if (receiptIdx >= 0) {
      // The word may appear only in the note that says there is none.
      expect(text.slice(receiptIdx, receiptIdx + 40)).toMatch(/receipt/i);
    }
    expect(text).not.toContain('run-2');
    expect(text).not.toContain('run-1');
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
    await waitFor(() => expect(history()).toBeInTheDocument());
    expect(within(history()).queryAllByRole('listitem')).toHaveLength(0);
  });
});
