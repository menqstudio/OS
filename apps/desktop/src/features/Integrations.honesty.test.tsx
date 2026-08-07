import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/**
 * The Integrations page renders one claim that matters: is this channel connected?
 *
 * The backend cannot answer that. `set_integration_status` writes a local row and its own
 * doc comment says so — "records the desired state; it does not itself reach any external
 * service" — and the window capability set grants exactly two integration commands, so
 * nothing on this desktop can contact a connector at all. A page that prints "Connected"
 * off that row is asserting a working external link it has never once tested.
 *
 * These tests pin the honest behaviour end to end: enabled is never rendered as connected,
 * a check that could not run never upgrades anything, and only a real affirmative answer
 * earns the verified word.
 */
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Integrations } from './Integrations';

const CONNECTED_ROW = {
  id: 'in-1', name: 'GitHub', provider: 'github', status: 'connected',
  createdAt: '1700000000000', updatedAt: '1700000000000',
};

/** Verbatim Tauri capability-wall refusal — what an ungranted command really returns. */
const PROBE_DENIAL = 'probe_integration not allowed. Permissions associated with this command: ';
const DECLARE_DENIAL = 'create_integration not allowed. Permissions associated with this command: ';

function setup(probe?: () => Promise<unknown>) {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_integrations') return Promise.resolve([CONNECTED_ROW]);
    if (cmd === 'probe_integration') {
      return probe ? probe() : Promise.reject(new Error(PROBE_DENIAL));
    }
    if (cmd === 'create_integration') return Promise.reject(new Error(DECLARE_DENIAL));
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Integrations />
      </ToastProvider>
    </AppProvider>,
  );
}

/** Open the connector's detail pane by activating its catalog row. */
async function openConnector(user: ReturnType<typeof userEvent.setup>) {
  const row = await screen.findByRole('button', { name: /GitHub, github/ });
  await user.click(row);
}

beforeEach(() => invokeMock.mockReset());

describe('a locally enabled connector is never rendered as connected', () => {
  it('labels a status="connected" row "Enabled · unverified"', async () => {
    setup();
    const row = await screen.findByRole('button', { name: /GitHub, github/ });
    // The accessible name carries BOTH the verdict and the reachability fact, so a
    // screen-reader user hears "unverified" exactly where the pill says it.
    expect(row).toHaveAccessibleName(/Enabled · unverified/);
    expect(row).toHaveAccessibleName(/Never tested/);
    expect(row).not.toHaveAccessibleName(/^GitHub, github, Connected/);
  });

  it('counts it as enabled but reports zero verified in the header', async () => {
    setup();
    await screen.findByRole('button', { name: /GitHub, github/ });
    expect(screen.getByText('0 verified')).toBeInTheDocument();
    expect(screen.getByText('1 enabled')).toBeInTheDocument();
  });

  it('says in the detail pane that nothing external has been contacted', async () => {
    const user = userEvent.setup();
    setup();
    await openConnector(user);
    expect(screen.getByText(/Nothing external has been contacted/)).toBeInTheDocument();
    expect(screen.getByText(/Not configured here — none referenced/)).toBeInTheDocument();
  });

  it('never probes on mount — a check only runs when the owner asks', async () => {
    setup();
    await screen.findByRole('button', { name: /GitHub, github/ });
    expect(invokeMock.mock.calls.some((c) => c[0] === 'probe_integration')).toBe(false);
  });
});

describe('a reachability check that cannot run upgrades nothing', () => {
  it('reports the capability wall as a missing feature here, not a dead service', async () => {
    const user = userEvent.setup();
    setup();
    await openConnector(user);
    await user.click(screen.getByRole('button', { name: /Test reachability/ }));

    await waitFor(() =>
      expect(screen.getAllByText(/Cannot be tested from this build/).length).toBeGreaterThan(0));
    // The verbatim refusal is shown, so the owner can see exactly what is missing.
    expect(screen.getByText(/probe_integration not allowed/)).toBeInTheDocument();
    // And the honest banner appears only AFTER a real attempt proved it.
    expect(screen.getByText(/Reachability testing is not wired in this build/)).toBeInTheDocument();
    // Critically: still not connected, and still zero verified.
    expect(screen.getByText('0 verified')).toBeInTheDocument();
    expect(screen.queryByText('Connected · verified')).not.toBeInTheDocument();
  });

  it('does not claim the connector is unreachable when we simply could not ask', async () => {
    const user = userEvent.setup();
    setup();
    await openConnector(user);
    await user.click(screen.getByRole('button', { name: /Test reachability/ }));
    await waitFor(() =>
      expect(screen.getAllByText(/Cannot be tested from this build/).length).toBeGreaterThan(0));
    expect(screen.queryByText('Did not answer')).not.toBeInTheDocument();
  });

  it('treats a malformed affirmative reply as no answer at all', async () => {
    const user = userEvent.setup();
    // The classic over-claim: a truthy-but-not-true field.
    setup(() => Promise.resolve({ reachable: 'true' }));
    await openConnector(user);
    await user.click(screen.getByRole('button', { name: /Test reachability/ }));
    await waitFor(() =>
      expect(screen.getAllByText(/No answer obtained/).length).toBeGreaterThan(0));
    expect(screen.getByText('0 verified')).toBeInTheDocument();
    expect(screen.queryByText('Connected · verified')).not.toBeInTheDocument();
  });
});

describe('only a real affirmative answer earns the verified word', () => {
  it('promotes to "Connected · verified" when the backend really says reachable', async () => {
    const user = userEvent.setup();
    setup(() => Promise.resolve({ reachable: true, detail: 'HTTP 200' }));
    await openConnector(user);
    await user.click(screen.getByRole('button', { name: /Test reachability/ }));
    await waitFor(() => expect(screen.getByText('1 verified')).toBeInTheDocument());
    expect(screen.getAllByText('Connected · verified').length).toBeGreaterThan(0);
    expect(screen.getByText('HTTP 200')).toBeInTheDocument();
  });

  it('reports a real negative as "Did not answer", kept apart from a failed check', async () => {
    const user = userEvent.setup();
    setup(() => Promise.resolve({ reachable: false, detail: 'connection refused' }));
    await openConnector(user);
    await user.click(screen.getByRole('button', { name: /Test reachability/ }));
    await waitFor(() =>
      expect(screen.getAllByText('Did not answer').length).toBeGreaterThan(0));
    expect(screen.getByText('0 verified')).toBeInTheDocument();
    expect(screen.getByText('connection refused')).toBeInTheDocument();
  });

  it('drops a stale verified result the moment the record is rewritten', async () => {
    const user = userEvent.setup();
    setup(() => Promise.resolve({ reachable: true }));
    await openConnector(user);
    await user.click(screen.getByRole('button', { name: /Test reachability/ }));
    await waitFor(() => expect(screen.getByText('1 verified')).toBeInTheDocument());

    // The owner disables and re-enables: the row is rewritten, so the earlier check no
    // longer describes it. A "verified" badge carried across that write would be a lie.
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'list_integrations') {
        return Promise.resolve([{ ...CONNECTED_ROW, updatedAt: '1800000000000' }]);
      }
      if (cmd === 'set_integration_status') return Promise.resolve(CONNECTED_ROW);
      return Promise.resolve(null);
    });
    await user.click(screen.getByRole('button', { name: 'Disable' }));

    await waitFor(() => expect(screen.getByText('0 verified')).toBeInTheDocument());
    expect(screen.queryByText('Connected · verified')).not.toBeInTheDocument();
  });
});

describe('enabling records intent and says exactly that', () => {
  it('announces "enabled locally — not yet verified", never "connected"', async () => {
    const user = userEvent.setup();
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'list_integrations') {
        return Promise.resolve([{ ...CONNECTED_ROW, status: 'disconnected' }]);
      }
      if (cmd === 'set_integration_status') return Promise.resolve(CONNECTED_ROW);
      return Promise.resolve(null);
    });
    render(
      <AppProvider><ToastProvider><Integrations /></ToastProvider></AppProvider>,
    );
    await openConnector(user);
    await user.click(screen.getByRole('button', { name: 'Enable' }));
    await waitFor(() =>
      expect(screen.getByText(/GitHub enabled locally — not yet verified/)).toBeInTheDocument());
  });
});

describe('declaring a connector', () => {
  it('offers no credential field and reports the exact missing command', async () => {
    const user = userEvent.setup();
    setup();
    await screen.findByRole('button', { name: /GitHub, github/ });
    await user.click(screen.getByRole('button', { name: /Declare a connector…/ }));

    const form = screen.getByRole('form', { name: 'Declare a connector' });
    // A declaration is a name and a provider. There is nowhere to type a secret.
    expect(form.querySelectorAll('input')).toHaveLength(2);
    expect(form.querySelector('input[type="password"]')).toBeNull();

    await user.type(screen.getByPlaceholderText('GitHub'), 'Slack');
    await user.type(screen.getByPlaceholderText('github'), 'slack');
    await user.click(screen.getByRole('button', { name: 'Declare' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/This build cannot declare connectors/);
    expect(alert).toHaveTextContent(/create_integration not allowed/);
  });
});
