import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// ---------------------------------------------------------------------------
// The Knowledge page now reads the LOCAL WRITE RECORD for every article it lists
// (`knowledge_write_record_state`, read-only) — the same backend, the same reader and
// the same vocabulary the Memory page uses, so the two surfaces cannot drift apart.
//
// A record proves the note has not been edited behind the app's back since it was
// written. It is unsigned and says nothing about the writer, so the page renders
// "recorded" / "content diverged" / "deleted, yet present" / "no record" — and keeps a
// FAILED read visibly separate from an absent record.
// ---------------------------------------------------------------------------

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Knowledge } from './Knowledge';

const note = (id: string, title: string) => ({
  id, title, body: `body of ${title}`, source: '', tags: '',
  createdAt: '1700000000000', updatedAt: '1700000000000',
});

const record = (over: Record<string, unknown> = {}) => ({
  id: 'wr-1',
  seq: 7,
  subjectKind: 'knowledge_note',
  subjectId: 'k-ok',
  operation: 'created',
  contentSha256: 'a'.repeat(64),
  prevRecordSha256: '0'.repeat(64),
  recordSha256: 'b'.repeat(64),
  recordedAt: '1700000000000',
  ...over,
});

const READ_FAULT = 'ipc error: the record store did not answer';

const NOTES = [
  note('k-ok', 'Forward-only migrations'),
  note('k-diverged', 'Edited outside the app'),
  note('k-unrecorded', 'Written before the record existed'),
  note('k-fault', 'The record read fails here'),
];

const STATES: Record<string, unknown> = {
  'k-ok': { state: 'recorded', record: record() },
  'k-diverged': {
    state: 'content_diverged',
    record: record({ subjectId: 'k-diverged' }),
    actual_content_sha256: 'c'.repeat(64),
  },
  'k-unrecorded': { state: 'unrecorded' },
};

function setup() {
  invokeMock.mockImplementation((cmd: string, args?: Record<string, unknown>) => {
    if (cmd === 'list_knowledge' || cmd === 'search_knowledge') {
      return Promise.resolve(NOTES.map((n) => ({ ...n })));
    }
    if (cmd === 'knowledge_write_record_state') {
      const id = String(args?.id ?? '');
      if (id === 'k-fault') return Promise.reject(new Error(READ_FAULT));
      return Promise.resolve(STATES[id] ?? null);
    }
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Knowledge />
      </ToastProvider>
    </AppProvider>,
  );
}

const badges = (kind: string) =>
  Array.from(document.querySelectorAll<HTMLElement>(`.wrec-badge[data-wrec="${kind}"]`));

/** Open one article in the reading rail. */
async function select(title: string) {
  const hits = await screen.findAllByText(title);
  fireEvent.click(hits[0]);
  await waitFor(() =>
    expect(document.querySelector('.kb-article')?.textContent).toContain(title),
  );
}

beforeEach(() => invokeMock.mockReset());

describe('Knowledge — every article states its real write-record state', () => {
  it('renders one badge per row, each carrying the backend’s own answer', async () => {
    setup();
    // The first article is selected by default, so `recorded` appears on its row AND in
    // the reading rail's panel.
    await waitFor(() => expect(badges('recorded').length).toBeGreaterThan(0));

    expect(badges('recorded')[0]).toHaveTextContent('Recorded');
    expect(badges('diverged')[0]).toHaveTextContent('Content diverged');
    expect(badges('unrecorded')[0]).toHaveTextContent('No record');
    await waitFor(() => expect(badges('unreadable').length).toBe(1));
    expect(badges('unreadable')[0]).toHaveTextContent('Record unreadable');
  });

  it('reads the real read-only command once per listed article', async () => {
    setup();
    await waitFor(() => expect(badges('recorded').length).toBeGreaterThan(0));
    const ids = invokeMock.mock.calls
      .filter((c) => c[0] === 'knowledge_write_record_state')
      .map((c) => (c[1] as { id: string }).id);
    expect(new Set(ids)).toEqual(new Set(NOTES.map((n) => n.id)));
  });
});

describe('Knowledge — a diverged note is not a shade of a recorded one', () => {
  it('gives divergence its own tone, its own word and its own glyph', async () => {
    setup();
    await waitFor(() => expect(badges('diverged').length).toBeGreaterThan(0));

    const ok = badges('recorded')[0];
    const bad = badges('diverged')[0];
    expect(bad.className).not.toBe(ok.className);
    expect(bad.className).toContain('wrec-badge--diverged');
    expect(bad.textContent).not.toEqual(ok.textContent);
    expect(bad.querySelector('.wrec-glyph')?.textContent)
      .not.toEqual(ok.querySelector('.wrec-glyph')?.textContent);
  });

  it('states what happened, with the recorded and the current hash', async () => {
    setup();
    await select('Edited outside the app');

    const panel = document.querySelector('.wrec-panel[data-wrec="diverged"]');
    expect(panel).toBeTruthy();
    expect(panel).toHaveTextContent(/no longer matches its record/i);
    expect(panel).toHaveTextContent(/changed outside the app/i);
    expect(panel).toHaveTextContent('aaaaaaaaaaaaaaaa…');
    expect(panel).toHaveTextContent('cccccccccccccccc…');
  });

  it('summarises the standing condition for the whole page', async () => {
    setup();
    await waitFor(() => expect(badges('diverged').length).toBeGreaterThan(0));
    const notice = document.querySelector('.wrec-notice');
    expect(notice).toHaveTextContent(/1 row no longer matches its record/i);
  });
});

describe('Knowledge — absence and fault are never the same statement', () => {
  it('renders "no record" neutrally, in neither the fault nor the divergence tone', async () => {
    setup();
    await waitFor(() => expect(badges('unrecorded').length).toBe(1));

    const none = badges('unrecorded')[0];
    expect(none.className).toContain('wrec-badge--unrecorded');
    expect(none.className).not.toContain('wrec-badge--unreadable');
    expect(none.className).not.toContain('wrec-badge--diverged');
    expect(none.textContent).not.toMatch(/unreadable|diverged|fail|error/i);
  });

  it('explains that nothing was back-filled', async () => {
    setup();
    await select('Written before the record existed');

    const panel = document.querySelector('.wrec-panel[data-wrec="unrecorded"]');
    expect(panel).toHaveTextContent(/nothing was back-filled/i);
    expect(panel?.querySelector('.wrec-fields')).toBeNull();
  });

  it('reports a failed read as a fault, with the backend’s own reason', async () => {
    setup();
    await select('The record read fails here');

    const panel = document.querySelector('.wrec-panel[data-wrec="unreadable"]');
    expect(panel).toHaveTextContent(/this row’s state is unknown/i);
    expect(panel).toHaveTextContent(/not a row without a record/i);
    expect(panel).toHaveTextContent(READ_FAULT);

    const notice = document.querySelector('.wrec-notice');
    expect(notice).toHaveTextContent(/1 record could not be read/i);
    expect(notice).toHaveTextContent(/read fault, not a missing record/i);
  });
});
