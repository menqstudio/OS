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

// §D `blocked`: "dispatch denied by wall → reason".
//
// A governed REFUSAL and a network failure used to render identically: one warn pill with the
// raw string, announced to nobody. They are opposite events — a refusal is the wall doing its
// job and nothing ran, a failure is something broken — and showing them the same way teaches
// the owner to read the wall as a bug.
async function dispatchFailingWith(message: string) {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_runs') return Promise.resolve([RUN]);
    if (cmd === 'list_run_steps') return Promise.resolve([STEP]);
    if (cmd === 'stream_run_step') return Promise.reject(new Error(message));
    return Promise.resolve(null);
  });
  render(<AppProvider><ToastProvider><Command /></ToastProvider></AppProvider>);
  fireEvent.click(await screen.findByRole('button', { name: /Draft the quarterly report/ }));
  await screen.findByText('Gather the source figures');
  fireEvent.click(screen.getByRole('button', { name: 'Execute step' }));
  return await screen.findByRole('alert');
}

describe('Command — a refusal at the wall is not a failure', () => {
  it('renders a governed refusal as a refusal, with the engine reason verbatim', async () => {
    const alert = await dispatchFailingWith('permission denied: lease not granted for path /etc');
    expect(alert.className).toContain('cmd-outcome--blocked');
    // The engine's own words, never paraphrased — the reason IS the finding.
    expect(alert.textContent).toContain('lease not granted for path /etc');
  });

  it('renders a real failure as a failure, not as a governed refusal', async () => {
    const alert = await dispatchFailingWith('connection reset by peer');
    expect(alert.className).not.toContain('cmd-outcome--blocked');
    expect(alert.textContent).toContain('connection reset by peer');
  });

  it('an unrecognised error falls through to FAILED, not to blocked', async () => {
    // The fail-open direction would be calling an unknown error a governed refusal — that
    // claims the system is fine when nothing established it.
    const alert = await dispatchFailingWith('E_SOMETHING_NEW');
    expect(alert.className).not.toContain('cmd-outcome--blocked');
  });

  it('the outcome is announced, not queued behind the output stream', async () => {
    // role=alert, because a dispatch the owner just pressed and that did NOT happen is the
    // definition of something a screen-reader user must be told immediately. The surrounding
    // aria-live="polite" region would hold it until the stream went quiet.
    const alert = await dispatchFailingWith('permission denied');
    expect(alert).toHaveAttribute('role', 'alert');
  });
});
