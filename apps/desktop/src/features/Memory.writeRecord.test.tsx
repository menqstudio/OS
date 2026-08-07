import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// ---------------------------------------------------------------------------
// The Memory page now reads the LOCAL WRITE RECORD for every row it lists
// (`memory_write_record_state`, read-only).
//
// What the record proves: the row has not been edited behind the app's back since it was
// written — every write appends a content hash inside the write's own transaction, into a
// chain the database keeps append-only. What it does NOT prove: anything about the
// writer. Nothing is signed. So this suite pins the four backend states, and the two
// distinctions that make them worth rendering at all:
//
//   * `content_diverged` must be VISIBLY different from `recorded`, not a subtle shade —
//     it is the one state that says a row was edited out of band.
//   * "could not read the record" must be distinguishable from "there is no record".
//     Collapsing them is how a real fault reads as an innocent, empty system.
// ---------------------------------------------------------------------------

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Memory } from './Memory';

const entry = (id: string, content: string) => ({
  id, scope: 'user', kind: 'fact', content, pinned: false,
  createdAt: '1700000000000', updatedAt: '1700000000000',
});

const record = (over: Record<string, unknown> = {}) => ({
  id: 'wr-1',
  seq: 3,
  subjectKind: 'memory_entry',
  subjectId: 'm-ok',
  operation: 'created',
  contentSha256: 'a'.repeat(64),
  prevRecordSha256: '0'.repeat(64),
  recordSha256: 'b'.repeat(64),
  recordedAt: '1700000000000',
  ...over,
});

const READ_FAULT = 'ipc error: the record store did not answer';

const ENTRIES = [
  entry('m-ok', 'Rotate the API key monthly'),
  entry('m-diverged', 'Deploy window is Friday'),
  entry('m-unrecorded', 'Written before the record existed'),
  entry('m-fault', 'The record read fails for this one'),
  entry('m-deleted', 'Present under a deleted id'),
  entry('m-garbage', 'The backend answers in a shape we cannot read'),
];

/** Every state the backend can return, plus the two ways a read can fail. */
const STATES: Record<string, unknown> = {
  'm-ok': { state: 'recorded', record: record() },
  'm-diverged': {
    state: 'content_diverged',
    record: record({ subjectId: 'm-diverged' }),
    actual_content_sha256: 'c'.repeat(64),
  },
  'm-unrecorded': { state: 'unrecorded' },
  'm-deleted': { state: 'deleted_but_present', record: record({ subjectId: 'm-deleted', operation: 'deleted' }) },
  // Not a state at all — a reply this build cannot interpret. Must fail CLOSED.
  'm-garbage': { state: 'something_new_from_the_future' },
};

function setup() {
  invokeMock.mockImplementation((cmd: string, args?: Record<string, unknown>) => {
    if (cmd === 'list_memory') return Promise.resolve(ENTRIES.map((e) => ({ ...e })));
    if (cmd === 'memory_write_record_state') {
      const id = String(args?.id ?? '');
      if (id === 'm-fault') return Promise.reject(new Error(READ_FAULT));
      return Promise.resolve(STATES[id] ?? null);
    }
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Memory />
      </ToastProvider>
    </AppProvider>,
  );
}

/** The badges the page rendered, keyed by the state they claim. */
const badges = (kind: string) =>
  Array.from(document.querySelectorAll<HTMLElement>(`.wrec-badge[data-wrec="${kind}"]`));

/** Open one memory in the recall rail (the first match is the row button itself). */
async function select(content: string) {
  const hits = await screen.findAllByText(content);
  fireEvent.click(hits[0]);
  await screen.findByRole('button', { name: 'Delete' });
}

beforeEach(() => invokeMock.mockReset());

describe('Memory — every row states its real write-record state', () => {
  it('renders one badge per row, each carrying the backend’s own answer', async () => {
    setup();
    await waitFor(() => expect(badges('recorded').length).toBe(1));

    expect(badges('recorded')[0]).toHaveTextContent('Recorded');
    expect(badges('diverged')[0]).toHaveTextContent('Content diverged');
    expect(badges('unrecorded')[0]).toHaveTextContent('No record');
    expect(badges('deletedPresent')[0]).toHaveTextContent('Deleted, yet present');
    // Two rows could not be read: one rejected, one answered in an unknown shape.
    await waitFor(() => expect(badges('unreadable').length).toBe(2));
    expect(badges('unreadable')[0]).toHaveTextContent('Record unreadable');
  });

  it('reads the real read-only command once per listed row', async () => {
    setup();
    await waitFor(() => expect(badges('recorded').length).toBe(1));
    const ids = invokeMock.mock.calls
      .filter((c) => c[0] === 'memory_write_record_state')
      .map((c) => (c[1] as { id: string }).id);
    expect(new Set(ids)).toEqual(new Set(ENTRIES.map((e) => e.id)));
  });
});

describe('Memory — a diverged row is not a shade of a recorded one', () => {
  it('gives divergence its own tone, its own word and its own glyph', async () => {
    setup();
    await waitFor(() => expect(badges('diverged').length).toBe(1));

    const ok = badges('recorded')[0];
    const bad = badges('diverged')[0];
    expect(bad.className).not.toBe(ok.className);
    expect(bad.className).toContain('wrec-badge--diverged');
    expect(ok.className).toContain('wrec-badge--recorded');
    // The word itself differs — the state is never carried by colour alone.
    expect(bad.textContent).not.toEqual(ok.textContent);
    expect(bad.querySelector('.wrec-glyph')?.textContent)
      .not.toEqual(ok.querySelector('.wrec-glyph')?.textContent);
  });

  it('states what actually happened, with the recorded and the current hash', async () => {
    setup();
    await select('Deploy window is Friday');

    const panel = document.querySelector('.wrec-panel[data-wrec="diverged"]');
    expect(panel).toBeTruthy();
    expect(panel).toHaveTextContent(/no longer matches its record/i);
    expect(panel).toHaveTextContent(/changed outside the app/i);
    // Both digests are shown, so the claim is checkable rather than decorative.
    expect(panel).toHaveTextContent('aaaaaaaaaaaaaaaa…');
    expect(panel).toHaveTextContent('cccccccccccccccc…');
  });

  it('summarises the standing condition for the whole page', async () => {
    setup();
    await waitFor(() => expect(badges('diverged').length).toBe(1));
    const notice = document.querySelector('.wrec-notice');
    expect(notice).toHaveTextContent(/1 row no longer matches its record/i);
    expect(notice).toHaveTextContent(/present under an id whose latest record says it was deleted/i);
  });
});

describe('Memory — "no record" is an honest absence, not a failure', () => {
  it('renders it neutrally, in neither the fault nor the divergence tone', async () => {
    setup();
    await waitFor(() => expect(badges('unrecorded').length).toBe(1));

    const none = badges('unrecorded')[0];
    expect(none.className).toContain('wrec-badge--unrecorded');
    expect(none.className).not.toContain('wrec-badge--unreadable');
    expect(none.className).not.toContain('wrec-badge--diverged');
    expect(none.textContent).not.toMatch(/unreadable|diverged|fail|error/i);
  });

  it('explains that nothing was back-filled, because that would be an invention', async () => {
    setup();
    await select('Written before the record existed');

    const panel = document.querySelector('.wrec-panel[data-wrec="unrecorded"]');
    expect(panel).toBeTruthy();
    expect(panel).toHaveTextContent(/written before the record existed/i);
    expect(panel).toHaveTextContent(/nothing was back-filled/i);
    // An absence carries no record fields to show.
    expect(panel?.querySelector('.wrec-fields')).toBeNull();
  });
});

describe('Memory — a failed read is a fault, never an empty ledger', () => {
  it('separates "could not read the record" from "there is no record"', async () => {
    setup();
    await waitFor(() => expect(badges('unreadable').length).toBe(2));

    const fault = badges('unreadable')[0];
    const none = badges('unrecorded')[0];
    expect(fault.className).not.toBe(none.className);
    expect(fault.textContent).not.toEqual(none.textContent);
    // The page-level notice keeps them apart in words too.
    const notice = document.querySelector('.wrec-notice');
    expect(notice).toHaveTextContent(/2 records could not be read/i);
    expect(notice).toHaveTextContent(/read fault, not missing records/i);
  });

  it('surfaces the backend’s own reason for the row that rejected', async () => {
    setup();
    await select('The record read fails for this one');

    const panel = document.querySelector('.wrec-panel[data-wrec="unreadable"]');
    expect(panel).toHaveTextContent(/this row’s state is unknown/i);
    expect(panel).toHaveTextContent(/not a row without a record/i);
    expect(panel).toHaveTextContent(READ_FAULT);
  });

  it('fails CLOSED on a reply it cannot interpret — never "no record"', async () => {
    setup();
    await select('The backend answers in a shape we cannot read');

    const panel = document.querySelector('.wrec-panel[data-wrec="unreadable"]');
    expect(panel).toBeTruthy();
    expect(panel).toHaveTextContent(/shape this page cannot read/i);
    expect(document.querySelector('.wrec-panel[data-wrec="unrecorded"]')).toBeNull();
  });
});
