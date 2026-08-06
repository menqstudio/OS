import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// Mock the Tauri IPC boundary. Research mirrors the real list_research store; it renders only
// what the store returns and never fabricates an entry.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Research } from './Research';

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_research') return Promise.resolve([{ id: 'r-1', title: 'Market analysis', question: 'size?', findings: '', status: 'active', createdAt: '1700000000000', updatedAt: '1700000000000' }]);
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Research />
      </ToastProvider>
    </AppProvider>,
  );
}

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Research — mirrors the real list_research store', () => {
  it('renders the real entry from list_research', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Market analysis').length).toBeGreaterThan(0));
    expect(called('list_research')).toBe(true);
  });
});
