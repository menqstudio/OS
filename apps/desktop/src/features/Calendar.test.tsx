import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// Mock the Tauri IPC boundary. Calendar mirrors the real list_events store; it renders only
// what the store returns and never fabricates an entry.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Calendar } from './Calendar';

function setup() {
  // The calendar defaults to today's day-agenda, so the event must fall on today
  // to be seated in the visible view.
  const today = String(Date.now());
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_events') return Promise.resolve([{ id: 'e-1', title: 'Team standup', kind: 'meeting', location: 'room', startsAt: today, endsAt: null, createdAt: today, updatedAt: today }]);
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Calendar />
      </ToastProvider>
    </AppProvider>,
  );
}

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Calendar — mirrors the real list_events store', () => {
  it('renders the real entry from list_events', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Team standup').length).toBeGreaterThan(0));
    expect(called('list_events')).toBe(true);
  });
});
