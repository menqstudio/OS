import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// Mock the Tauri IPC boundary: the decision ledger loads locally, but the engine
// evidence-chain read REJECTS (transport failure) — exactly the Phase-2 steady state.
// The desktop wrapper maps that to a typed `unreachable`, and the page must render the
// honest blocked/unreachable evidence state, never fabricated evidence.
vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn((cmd: string) => {
    if (cmd === 'list_decisions') {
      return Promise.resolve([
        { id: 'd-1', title: 'Ship the mirror', status: 'accepted', owner: 'gev', rationale: 'because', createdAt: '1000', updatedAt: '1000' },
      ]);
    }
    if (cmd === 'read_evidence_chain') {
      return Promise.reject(new Error('broker_unavailable'));
    }
    return Promise.resolve(null);
  }),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { Decisions } from './Decisions';

describe('Decisions — engine evidence chain renders blocked when the read-IPC is unreachable', () => {
  it('opens evidence and shows the honest unreachable state, not fabricated evidence', async () => {
    render(
      <AppProvider>
        <Decisions />
      </AppProvider>,
    );

    // The local decision table was read; the decision appears (row + chamber title).
    await waitFor(() => expect(screen.getAllByText('Ship the mirror').length).toBeGreaterThan(0));

    // Open the evidence viewer — triggers the real READ-ONLY engine chain read.
    fireEvent.click(screen.getByText('Open evidence'));

    // The engine read was unreachable → the page renders the honest blocked state.
    await waitFor(() =>
      expect(screen.getByText('Evidence chain unreachable')).toBeInTheDocument(),
    );
    // The honest engine reason is surfaced; no fabricated evidence is shown.
    expect(screen.getByText(/broker_unavailable/)).toBeInTheDocument();
  });
});

// The list on this page is `list_decisions`: `repo::decisions::list` on the desktop's SQLite. The
// page called it "ENGINE LEDGER" and "Read-only mirror", and its failure "could not be read from
// the engine". The engine's decision ledger is a different read, shown only by the bridge panel.
describe('Decisions — the local decision table is not called the engine ledger', () => {
  it('names the source as the local table in the header and the chamber', async () => {
    const { container } = render(
      <AppProvider>
        <Decisions />
      </AppProvider>,
    );
    await waitFor(() => expect(screen.getAllByText('Ship the mirror').length).toBeGreaterThan(0));

    expect(screen.getByText('Read-only · local table')).toBeInTheDocument();
    expect(screen.getByText('DELIBERATION · LOCAL DECISION TABLE')).toBeInTheDocument();
    // Scoped to the page's own header and chamber heading: the bridge panel below legitimately
    // names the engine's decision ledger, because that is what it reads.
    const head = container.querySelector('.pageHead') as HTMLElement;
    const chamberHead = container.querySelector('#chamber .ch-head') as HTMLElement;
    for (const el of [head, chamberHead]) {
      expect(el.textContent).not.toMatch(/engine ledger/i);
      expect(el.textContent).not.toMatch(/mirror\b/i);
    }
    // The disabled Reweigh control no longer attributes a decision to the engine.
    expect(screen.getByText('↻ Reweigh').closest('button')?.getAttribute('title'))
      .not.toMatch(/adjudicated by the engine/i);
  });
});
