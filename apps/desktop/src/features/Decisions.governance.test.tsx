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

    // Ledger mirrored (local read); the decision appears (row + chamber title).
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
