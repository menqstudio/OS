import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// Mock the Tauri IPC boundary. Command is a REAL-only surface: the run ledger
// (list_runs), a run's step chain (list_run_steps) and streamed execution are the
// only sources of what it shows — the mockup's fabricated instruments (agent mesh,
// confidence %, sparkline) are omitted, never faked. These smoke tests lock the
// read path: the ledger renders real runs, and selecting one loads its real steps.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (cmd: string, args?: unknown) => invokeMock(cmd, args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Command } from './Command';

const RUN = {
  id: 'r-1',
  intent: 'Draft the quarterly report',
  status: 'active',
  plan: '',
  createdAt: '1700000000000',
  updatedAt: '1700000000000',
};

const STEP = {
  id: 's-1',
  runId: 'r-1',
  position: 1,
  title: 'Gather the source figures',
  detail: 'pull the ledger totals',
  status: 'active',
  result: '',
  requiresApproval: false,
  createdAt: '1700000000000',
  updatedAt: '1700000000000',
};

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_runs') return Promise.resolve([RUN]);
    if (cmd === 'list_run_steps') return Promise.resolve([STEP]);
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Command />
      </ToastProvider>
    </AppProvider>,
  );
}

beforeEach(() => invokeMock.mockReset());

describe('Command — real run ledger + step chain (never fabricated)', () => {
  it('renders the real run ledger from list_runs', async () => {
    setup();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Draft the quarterly report/ })).toBeInTheDocument(),
    );
  });

  it('selecting a run loads and shows its REAL step chain from list_run_steps', async () => {
    setup();
    const pick = await screen.findByRole('button', { name: /Draft the quarterly report/ });
    fireEvent.click(pick);
    // The console mounts for the selected run and reads its real steps.
    await waitFor(() => expect(screen.getByText('Gather the source figures')).toBeInTheDocument());
    // The step chain read went to the real command for this exact run id.
    expect(invokeMock).toHaveBeenCalledWith('list_run_steps', expect.objectContaining({ runId: 'r-1' }));
  });
});
