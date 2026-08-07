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
    expect(screen.getByText(/no verification chain/i)).toBeInTheDocument();
    expect(screen.getByText(/counted from the store/i)).toBeInTheDocument();
  });

  it('claims nothing at all when the store read FAILED', async () => {
    setup({ listFails: true });
    await waitFor(() => expect(screen.getByText('Store unavailable')).toBeInTheDocument());
    expect(screen.queryByText(/verifiable/i)).not.toBeInTheDocument();
    // The metric strip (and its provenance note) is hidden on an error — a failed read
    // must not leave a standing claim about rows nobody could load.
    expect(screen.queryByText(/no verification chain/i)).not.toBeInTheDocument();
  });
});
