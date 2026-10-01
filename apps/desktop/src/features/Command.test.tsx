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
import { ToastProvider, Toaster } from '../components/toast';
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

  // The operating system and the transport borrow the refusal vocabulary for things that are
  // plainly broken. Each of these matched the old single regex and was announced as "the engine
  // refused this step. Nothing ran."
  it.each([
    'Connection refused (os error 111)',
    'Permission denied (os error 13)',
    'governed sidecar crashed: exit 1',
  ])('a breakdown that borrows refusal words is a FAILURE: %s', async (message) => {
    const alert = await dispatchFailingWith(message);
    expect(alert.className).not.toContain('cmd-outcome--blocked');
    expect(alert.textContent).toContain(message);
  });

  it('the one refusal the desktop itself issues is recognised as one', async () => {
    // `stream_run_step` sends exactly this when the step's approval was rejected.
    const alert = await dispatchFailingWith('approval was rejected for this step');
    expect(alert.className).toContain('cmd-outcome--blocked');
  });

  it('the refusal copy does not name a refuser or claim nothing ran', async () => {
    // The page classifies by wording; it does not know WHO refused or whether a model ran first.
    const alert = await dispatchFailingWith('permission denied: lease not granted for path /etc');
    expect(alert.textContent).not.toMatch(/engine refused|governed wall|Nothing ran/i);
  });

  it('an unrecognised error falls through to FAILED, not to blocked', async () => {
    // The fail-open direction would be calling an unknown error a governed refusal — that
    // claims the system is fine when nothing established it.
    const alert = await dispatchFailingWith('E_SOMETHING_NEW');
    expect(alert.className).not.toContain('cmd-outcome--blocked');
  });

  it('the dispatch trace is a log, not an unnamed live region', async () => {
    // §D: "trace `role=log aria-live`". It had the live region and not the role, so a screen
    // reader was told the content changed without being told what kind of thing it was reading.
    setup();
    fireEvent.click(await screen.findByRole('button', { name: /Draft the quarterly report/ }));
    await screen.findByText('Gather the source figures');
    const trace = await screen.findByRole('log');
    expect(trace).toHaveAttribute('aria-live', 'polite');
    expect(trace).toHaveAccessibleName();
  });

  it('the outcome is announced, not queued behind the output stream', async () => {
    // role=alert, because a dispatch the owner just pressed and that did NOT happen is the
    // definition of something a screen-reader user must be told immediately. The surrounding
    // aria-live="polite" region would hold it until the stream went quiet.
    const alert = await dispatchFailingWith('permission denied');
    expect(alert).toHaveAttribute('role', 'alert');
  });
});

// Advance, add-step, set-status and quick-create each ended `.catch(() => reload())`: the backend's
// reason was discarded and a refused or failed action looked like a click that did nothing.
describe('Command — a rejected write says why', () => {
  function failing(cmd: string, message: string) {
    invokeMock.mockImplementation((c: string) => {
      if (c === 'list_runs') return Promise.resolve([RUN]);
      if (c === 'list_run_steps') return Promise.resolve([STEP]);
      if (c === cmd) return Promise.reject(new Error(message));
      return Promise.resolve(null);
    });
    return render(<AppProvider><ToastProvider><Toaster /><Command /></ToastProvider></AppProvider>);
  }

  it('a failed advance surfaces the backend reason', async () => {
    failing('advance_run', 'run r-1 has no runnable step');
    fireEvent.click(await screen.findByRole('button', { name: /Draft the quarterly report/ }));
    await screen.findByText('Gather the source figures');
    fireEvent.click(screen.getByRole('button', { name: 'Advance' }));
    expect(await screen.findByText('run r-1 has no runnable step')).toBeInTheDocument();
  });

  it('a failed quick-create surfaces the backend reason', async () => {
    failing('create_run', 'database is locked');
    await screen.findByRole('button', { name: /Draft the quarterly report/ });
    const dock = document.querySelector('.dock-input') as HTMLInputElement;
    fireEvent.change(dock, { target: { value: 'ship it' } });
    fireEvent.submit(dock.closest('form') as HTMLFormElement);
    expect(await screen.findByText('database is locked')).toBeInTheDocument();
  });
});
