import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// Mock the Tauri IPC boundary. Library mirrors the real list_library store; it renders only
// what the store returns and never fabricates an entry.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Library } from './Library';

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_library') return Promise.resolve([{ id: 'l-1', title: 'Design tokens', kind: 'doc', body: '', tags: 'ui', createdAt: '1700000000000', updatedAt: '1700000000000' }]);
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Library />
      </ToastProvider>
    </AppProvider>,
  );
}

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Library — mirrors the real list_library store', () => {
  it('renders the real entry from list_library', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Design tokens').length).toBeGreaterThan(0));
    expect(called('list_library')).toBe(true);
  });
});
