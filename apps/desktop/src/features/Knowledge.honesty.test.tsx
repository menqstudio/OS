import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// The Memory page once shipped an unconditional "Verifiable memory" pill with nothing
// behind it. Knowledge is the same kind of surface — plain local SQLite rows returned by
// `list_knowledge` / `search_knowledge` — so it must never grow the same defect.
//
// The backend now appends an unsigned, append-only LOCAL write record for every knowledge
// write (core/src/local_write_record.rs, migration 0021). That record is real, but it is
// (a) unsigned, so it is not "verified", and (b) not readable from this page yet — no
// command is registered for it. These tests lock BOTH halves: the page claims no
// verification, and it states its real provenance instead of staying silent about it.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Knowledge } from './Knowledge';

const NOTE = {
  id: 'k-1',
  title: 'Forward-only migrations',
  body: 'Never edit a past migration.',
  source: 'docs/ARCHITECTURE.md',
  tags: 'sqlite,schema',
  createdAt: '1700000000000',
  updatedAt: '1700000000000',
};

function setup(opts: { listFails?: boolean } = {}) {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_knowledge' || cmd === 'search_knowledge') {
      return opts.listFails
        ? Promise.reject(new Error('store_unavailable'))
        : Promise.resolve([{ ...NOTE }]);
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

// Rendering a whole feature page under jsdom can exceed the 5s default on a loaded
// machine; these assertions are about honesty, not speed.
vi.setConfig({ testTimeout: 30000 });

beforeEach(() => invokeMock.mockReset());

describe('Knowledge — nothing claims a knowledge note is verified', () => {
  it('renders no verification/receipt claim on a loaded page', async () => {
    setup();
    await waitFor(() =>
      expect(screen.getAllByText(/Forward-only migrations/).length).toBeGreaterThan(0),
    );

    // The production trust vocabulary must not appear on a page of plain local rows.
    for (const forbidden of [/verifiable/i, /trusted[ _-]?verified/i, /\bsigned\b/i, /governed receipt/i]) {
      expect(screen.queryByText(forbidden)).not.toBeInTheDocument();
    }
    // A stray "Verified" badge would be the exact regression this guards.
    expect(screen.queryByText(/^\s*Verified/i)).not.toBeInTheDocument();
  });

  it('states its real provenance rather than staying silent about it', async () => {
    setup();
    await waitFor(() =>
      expect(screen.getAllByText(/Forward-only migrations/).length).toBeGreaterThan(0),
    );
    // Same honest sentence the Memory page carries: real counts, and what backs them.
    // It used to read "no verification chain"; every knowledge write now appends a local
    // record, so that sentence became false and the line was updated rather than left to
    // rot — a stale honest label is a dishonest one.
    expect(screen.getByText(/each write appends a local record/i)).toBeInTheDocument();
    expect(screen.getByText(/never who wrote it/i)).toBeInTheDocument();
    expect(screen.getByText(/counted from the store/i)).toBeInTheDocument();
    expect(screen.queryByText(/no verification chain/i)).not.toBeInTheDocument();
  });

  it('claims nothing at all when the store read FAILED', async () => {
    setup({ listFails: true });
    await waitFor(() => expect(screen.getByText('Store unavailable')).toBeInTheDocument());
    expect(screen.queryByText(/verifiable/i)).not.toBeInTheDocument();
    // The metric strip (and its provenance note) is hidden on an error — a failed read
    // must not leave a standing claim about rows nobody could load.
    expect(screen.queryByText(/each write appends a local record/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/no verification chain/i)).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// The same guard, now that the page renders the LOCAL WRITE RECORD per article.
//
// The record is real (appended in the same transaction as the note, chained, DB-enforced
// append-only) and it is UNSIGNED: no key, no manifest, no authority, no containment. It
// attests CONTENT, never the writer. "Recorded" and "content diverged" are inside what it
// proves; the production trust vocabulary never is.
// ---------------------------------------------------------------------------

const RECORD = {
  id: 'wr-1',
  seq: 4,
  subjectKind: 'knowledge_note',
  subjectId: 'k-1',
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
    if (cmd === 'list_knowledge' || cmd === 'search_knowledge') return Promise.resolve([{ ...NOTE }]);
    if (cmd === 'knowledge_write_record_state') return Promise.resolve(state);
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

describe('Knowledge — the write record never borrows the receipt vocabulary', () => {
  it('says "recorded" and nothing stronger for a note that matches its record', async () => {
    setupWithRecord({ state: 'recorded', record: RECORD });
    await waitFor(() => expect(screen.getAllByText('Recorded').length).toBeGreaterThan(0));

    const text = renderedText();
    for (const forbidden of FORBIDDEN) {
      expect(text, `rendered text must not contain ${forbidden}`).not.toMatch(forbidden);
    }
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
