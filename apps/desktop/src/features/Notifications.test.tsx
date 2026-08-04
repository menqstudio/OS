import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// Mock the Tauri IPC boundary. Notifications mirrors the real notification store
// (list_notifications) and can only mark-read through the real command
// (mark_notification_read). It never fabricates a notification, and the governance
// read (read_evidence_chain) is unreachable in the Phase-2 steady state.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Notifications } from './Notifications';

const NOTE = {
  id: 'n-1',
  kind: 'system',
  severity: 'warning',
  title: 'Disk almost full',
  body: 'Free space is under 5%.',
  entityType: null,
  entityId: null,
  readAt: null,
  createdAt: '1700000000000',
};

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_notifications') return Promise.resolve([NOTE]);
    if (cmd === 'read_evidence_chain') return Promise.reject(new Error('broker_unavailable'));
    if (cmd === 'mark_notification_read') return Promise.resolve({ ...NOTE, readAt: '1700000001000' });
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Notifications />
      </ToastProvider>
    </AppProvider>,
  );
}

const calledWith = (cmd: string, pred: (arg: Record<string, unknown>) => boolean) =>
  invokeMock.mock.calls.some((c) => c[0] === cmd && pred((c[1] ?? {}) as Record<string, unknown>));

beforeEach(() => invokeMock.mockReset());

describe('Notifications — mirrors the real store; mark-read is a real command', () => {
  it('renders the real notification from list_notifications', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Disk almost full').length).toBeGreaterThan(0));
  });

  it('dismiss routes through the real mark_notification_read command for that id', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Disk almost full').length).toBeGreaterThan(0));
    // The unread notification exposes a Dismiss control that marks it read via the real command.
    fireEvent.click(screen.getAllByRole('button', { name: 'Dismiss' })[0]);
    await waitFor(() => expect(calledWith('mark_notification_read', (a) => a.id === 'n-1')).toBe(true));
  });
});
