import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// Two honesty defects lived on this page:
//
//   * A "Verifiable memory" pill rendered UNCONDITIONALLY in the header. Nothing
//     verifies a memory row — `list_memory` returns plain local SQLite rows with no
//     signature, receipt or chain behind them — so the badge claimed more than the
//     backend can prove, in every state including a failed read.
//   * `delete_memory` (DENIED in the window capability set) and `set_memory_pinned`
//     both ended in `.catch(() => s.reload())`: the refusal vanished, the row came
//     straight back on the reload, and the user was told nothing.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Memory } from './Memory';

const ENTRY = {
  id: 'm-1',
  scope: 'user',
  kind: 'fact',
  content: 'Rotate the API key monthly',
  pinned: false,
  createdAt: '1700000000000',
  updatedAt: '1700000000000',
};

const DENIAL = 'delete_memory not allowed. Permissions associated with this command: ';

function setup(opts: { listFails?: boolean; deleteRefuses?: boolean; pinRefuses?: boolean } = {}) {
  const store = [ENTRY];
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_memory') {
      return opts.listFails
        ? Promise.reject(new Error('store_unavailable'))
        : Promise.resolve([...store]);
    }
    if (cmd === 'delete_memory') {
      if (opts.deleteRefuses) return Promise.reject(new Error(DENIAL));
      store.length = 0;
      return Promise.resolve(null);
    }
    if (cmd === 'set_memory_pinned') {
      if (opts.pinRefuses) return Promise.reject(new Error('set_memory_pinned not allowed.'));
      return Promise.resolve(null);
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

/** The page's polite live region (what a screen-reader user is told). */
const liveText = () => document.querySelector('.mem-sr-only')?.textContent ?? '';

async function selectTheEntry() {
  await waitFor(() => expect(screen.getAllByText(/Rotate the API key monthly/).length).toBeGreaterThan(0));
  fireEvent.click(screen.getAllByText(/Rotate the API key monthly/)[0]);
  await screen.findByRole('button', { name: 'Delete' });
}

async function confirmDeleteDialog() {
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
  const dialog = await screen.findByRole('dialog');
  const confirm = Array.from(dialog.querySelectorAll('button')).find(
    (b) => b.className.includes('danger'),
  );
  expect(confirm).toBeTruthy();
  fireEvent.click(confirm as HTMLButtonElement);
}

// Rendering a whole feature page under jsdom can exceed the 5s default on a loaded
// machine. The assertions below are about honesty, not speed — give them room so a
// slow environment cannot be mistaken for a regression.
vi.setConfig({ testTimeout: 30000 });

beforeEach(() => invokeMock.mockReset());

describe('Memory — nothing claims the memory is verifiable', () => {
  it('never renders the unbacked "Verifiable memory" pill on a loaded page', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText(/Rotate the API key monthly/).length).toBeGreaterThan(0));

    expect(screen.queryByText('Verifiable memory')).not.toBeInTheDocument();
    expect(screen.queryByText(/verifiable/i)).not.toBeInTheDocument();

    // What is shown instead is a real fact: the outcome of the one `list_memory` read,
    // plus a CURRENT statement of what backs the rows. That line used to read "no
    // verification chain"; every write now appends a local record, so the old sentence
    // became false — and a stale honest label is a dishonest one.
    expect(screen.getByText('Read from the store')).toBeInTheDocument();
    expect(screen.getByText(/each write appends a local record/i)).toBeInTheDocument();
    // It still refuses the stronger claim: content, never the writer.
    expect(screen.getByText(/never who wrote it/i)).toBeInTheDocument();
    // And the sentence that is no longer true is gone.
    expect(screen.queryByText(/no verification chain/i)).not.toBeInTheDocument();
  });

  it('never renders it when the store read FAILED either', async () => {
    setup({ listFails: true });
    await waitFor(() => expect(screen.getByText('Store unavailable')).toBeInTheDocument());
    expect(screen.queryByText(/verifiable/i)).not.toBeInTheDocument();
  });
});

describe('Memory — a REFUSED delete is surfaced, never swallowed', () => {
  it('keeps the entry, shows the refusal with its reason, and says nothing was removed', async () => {
    setup({ deleteRefuses: true });
    await selectTheEntry();
    await confirmDeleteDialog();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Delete refused — nothing was removed');
    expect(alert).toHaveTextContent(/still in the store/i);
    expect(alert).toHaveTextContent(/delete_memory not allowed/);

    // The row is provably still listed.
    expect(screen.getAllByText(/Rotate the API key monthly/).length).toBeGreaterThan(0);
    // And the live region announced the refusal rather than a count as if nothing happened.
    await waitFor(() => expect(liveText()).toMatch(/refused/i));
  });
});

describe('Memory — a REFUSED pin change is surfaced, never swallowed', () => {
  it('states that the pin state did not change', async () => {
    setup({ pinRefuses: true });
    await selectTheEntry();
    fireEvent.click(screen.getByRole('button', { name: 'Pin' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Pin change refused — nothing was changed');
    expect(alert).toHaveTextContent(/set_memory_pinned not allowed/);
    await waitFor(() => expect(liveText()).toMatch(/refused/i));
  });
});

describe('Memory — an ACCEPTED delete reports the real outcome', () => {
  it('removes the entry and raises no refusal alert', async () => {
    setup();
    await selectTheEntry();
    await confirmDeleteDialog();

    await waitFor(() => expect(screen.queryByText(/Rotate the API key monthly/)).not.toBeInTheDocument());
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// The equivalent of `Knowledge.honesty.test.tsx`'s vocabulary guard, for Memory —
// now that this page renders the LOCAL WRITE RECORD.
//
// The record is real: every memory write appends it in the same transaction as the row,
// hashing the content into a DB-enforced append-only chain. It is also UNSIGNED — no
// key, no manifest, no authority, no containment — and it attests CONTENT, never the
// writer. So the page may say "recorded" and it may say "content diverged", but it may
// never borrow the production trust vocabulary or a badge a reader would file next to a
// governed turn's.
// ---------------------------------------------------------------------------

const RECORD = {
  id: 'wr-1',
  seq: 1,
  subjectKind: 'memory_entry',
  subjectId: 'm-1',
  operation: 'created',
  contentSha256: 'a'.repeat(64),
  prevRecordSha256: '0'.repeat(64),
  recordSha256: 'b'.repeat(64),
  recordedAt: '1700000000000',
};

/** Every rendered word — direct text nodes plus tooltips — with `<style>` excluded so
 *  the assertion is about what a reader sees, not about CSS comments. */
function renderedText(): string {
  const parts: string[] = [];
  for (const el of Array.from(document.body.querySelectorAll('*'))) {
    if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') continue;
    for (const n of Array.from(el.childNodes)) {
      if (n.nodeType === 3) parts.push(n.textContent ?? '');
    }
    const title = el.getAttribute('title');
    if (title) parts.push(title);
  }
  return parts.join(' ');
}

/** The vocabulary this page may never use — it belongs to the signed governed-receipt
 *  path, and nothing on this page has custody of anything. */
const FORBIDDEN = [
  /verifiable/i,
  /verified/i,
  /trusted[ _-]?verified/i,
  /trusted/i,
  /signed/i,
  /governed receipt/i,
  /receipt/i,
  /custody/i,
  /tamper[ -]?proof/i,
];

function setupWithRecord(state: unknown) {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_memory') return Promise.resolve([{ ...ENTRY }]);
    if (cmd === 'memory_write_record_state') return Promise.resolve(state);
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

describe('Memory — the write record never borrows the receipt vocabulary', () => {
  it('says "recorded" and nothing stronger for a row that matches its record', async () => {
    setupWithRecord({ state: 'recorded', record: RECORD });
    await waitFor(() => expect(screen.getAllByText('Recorded').length).toBeGreaterThan(0));
    // The full statement lives in the recall rail, so open the row it describes.
    await selectTheEntry();

    const text = renderedText();
    for (const forbidden of FORBIDDEN) {
      expect(text, `rendered text must not contain ${forbidden}`).not.toMatch(forbidden);
    }
    // The ceiling is stated on the surface itself, not just in a comment.
    expect(screen.getAllByText(/nothing outside this machine vouches for it/i).length)
      .toBeGreaterThan(0);
  });

  it('stays inside the vocabulary on the loudest state too', async () => {
    setupWithRecord({
      state: 'content_diverged',
      record: RECORD,
      actual_content_sha256: 'c'.repeat(64),
    });
    await waitFor(() => expect(screen.getAllByText('Content diverged').length).toBeGreaterThan(0));

    const text = renderedText();
    for (const forbidden of FORBIDDEN) {
      expect(text, `rendered text must not contain ${forbidden}`).not.toMatch(forbidden);
    }
  });
});
