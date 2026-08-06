import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// Mock the Tauri IPC boundary. Memory mirrors the real list_memory store; it renders only
// what the store returns and never fabricates an entry.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Memory } from './Memory';

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_memory') return Promise.resolve([{ id: 'm-1', scope: 'user', kind: 'fact', content: 'Rotate the API key monthly', pinned: false, createdAt: '1700000000000', updatedAt: '1700000000000' }]);
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Memory />
      </ToastProvider>
    </AppProvider>,
  );
}

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Memory — mirrors the real list_memory store', () => {
  it('renders the real entry from list_memory', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Rotate the API key monthly').length).toBeGreaterThan(0));
    expect(called('list_memory')).toBe(true);
  });
});
