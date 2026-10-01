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

// `markNotificationRead(id).then(reload).catch(reload)`: a rejection was discarded, the row came
// back unread, and nothing was said — the pattern Memory and Library were fixed for.
describe('Notifications — a refused mark-as-read is said, not swallowed', () => {
  it('shows the store\'s reason and keeps the signal listed', async () => {
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'list_notifications') return Promise.resolve([NOTE]);
      if (cmd === 'read_evidence_chain') return Promise.reject(new Error('broker_unavailable'));
      if (cmd === 'mark_notification_read') {
        return Promise.reject(new Error('mark_notification_read not allowed.'));
      }
      return Promise.resolve(null);
    });
    render(<AppProvider><ToastProvider><Notifications /></ToastProvider></AppProvider>);
    await waitFor(() => expect(screen.getAllByText('Disk almost full').length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByRole('button', { name: 'Dismiss' })[0]);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Not marked as read');
    expect(alert).toHaveTextContent('mark_notification_read not allowed.');
    expect(screen.getAllByText('Disk almost full').length).toBeGreaterThan(0);
  });
});

// The feed's key handler sits on the container. Enter on a row's own Open/Dismiss button was
// prevented there and toggled the SELECTED row instead; `x` on a button marked the selected row
// read.
describe('Notifications — a key pressed on a row\'s own button belongs to that button', () => {
  it('Enter and x on the Dismiss button are not taken over by the feed', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Disk almost full').length).toBeGreaterThan(0));
    const dismiss = screen.getAllByRole('button', { name: 'Dismiss' })[0];
    dismiss.focus();

    // true = no handler called preventDefault, so the button's own activation is intact.
    expect(fireEvent.keyDown(dismiss, { key: 'Enter' })).toBe(true);
    // The feed did not expand the selected row…
    expect(document.querySelector('.nsig-body')).toBeNull();
    expect(fireEvent.keyDown(dismiss, { key: 'x' })).toBe(true);
    // …and `x` did not mark anything read behind the button's back.
    expect(calledWith('mark_notification_read', () => true)).toBe(false);
  });

  it('Enter on the row itself still opens it', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Disk almost full').length).toBeGreaterThan(0));
    const row = screen.getByRole('article');
    row.focus();
    expect(fireEvent.keyDown(row, { key: 'Enter' })).toBe(false);
    await waitFor(() => expect(document.querySelector('.nsig-body')).not.toBeNull());
  });
});
