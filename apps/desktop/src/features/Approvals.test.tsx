import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';

// Mock the Tauri IPC boundary with a call-tracking spy so the tests can assert
// BOTH what the page renders AND — the cardinal invariant — which engine commands
// it does (and does NOT) send. Approvals is a mirror-never-decide surface: it may
// only *request* a verdict the engine adjudicates, and escalate has no engine
// command in this build, so its path must send nothing and say so honestly.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (cmd: string, args?: unknown) => invokeMock(cmd, args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Approvals } from './Approvals';

// One real, actionable pending approval (the shape the desktop `list_approvals`
// command returns) — deliberately the high-risk external-email action.
const PENDING = {
  id: 'ap-1',
  actionType: 'Send external email',
  target: 'vendor@example.com',
  level: 'A3',
  riskLevel: 'high',
  status: 'pending',
  requestedBy: 'A3',
  decisionNote: null,
  entityType: null,
  entityId: null,
  requestedAt: '1700000000000',
  decidedAt: null,
};

function setup(approvals: unknown[] = [PENDING]) {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_approvals') return Promise.resolve(approvals);
    // The engine approval-QUEUE read is the honest Phase-2 steady state: unreachable.
    if (cmd === 'read_engine_approval_queue') return Promise.reject(new Error('broker_unavailable'));
    if (cmd === 'confirm_approval') return Promise.resolve(null);
    if (cmd === 'reject_approval') return Promise.resolve(null);
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Approvals />
      </ToastProvider>
    </AppProvider>,
  );
}

beforeEach(() => invokeMock.mockReset());

describe('Approvals — mirror-never-decide honesty invariants', () => {
  it('renders the real pending approval seated from the engine queue', async () => {
    setup();
    // The seated gate + queue row both show the real target/action from list_approvals.
    await waitFor(() => expect(screen.getAllByText('vendor@example.com').length).toBeGreaterThan(0));
    expect(screen.getAllByText('Send external email').length).toBeGreaterThan(0);
  });

  it('ESCALATE never sends an engine command — it reports honestly and decides nothing', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('vendor@example.com').length).toBeGreaterThan(0));

    // Open the escalate confirm from the authorization bar (accessible name = aria-label).
    fireEvent.click(screen.getByRole('button', { name: 'Escalate for higher review' }));

    // The dialog states, honestly, that escalation is not wired — confirming sends nothing.
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/not wired to the engine/i)).toBeInTheDocument();

    // Confirm the escalate.
    fireEvent.click(within(dialog).getByRole('button', { name: 'Escalate' }));

    // The cardinal invariant: NO decide command was ever sent to the engine.
    await waitFor(() => {
      expect(invokeMock).not.toHaveBeenCalledWith('confirm_approval', expect.anything());
      expect(invokeMock).not.toHaveBeenCalledWith('reject_approval', expect.anything());
    });
    // …and the verdict is announced honestly as unavailable, never as a fake success.
    expect(screen.getByText(/Escalation unavailable for/i)).toBeInTheDocument();
  });

  it('DENY routes through the real fail-safe reject command', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('vendor@example.com').length).toBeGreaterThan(0));

    // Open the deny confirm from the authorization bar.
    fireEvent.click(screen.getByRole('button', { name: 'Deny — reject this action' }));
    const dialog = await screen.findByRole('dialog');
    // Commit the deny (confirm button = shared action.reject label).
    fireEvent.click(within(dialog).getByRole('button', { name: 'Reject' }));

    // The real fail-safe engine reject command is sent for this exact approval id.
    await waitFor(() =>
      expect(invokeMock).toHaveBeenCalledWith('reject_approval', expect.objectContaining({ id: 'ap-1' })),
    );
  });
});
