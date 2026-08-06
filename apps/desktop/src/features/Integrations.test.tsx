import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// Mock the Tauri IPC boundary. Integrations mirrors the real list_integrations store; it renders only
// what the store returns and never fabricates an entry.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Integrations } from './Integrations';

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_integrations') return Promise.resolve([{ id: 'in-1', name: 'GitHub', provider: 'github', status: 'connected', createdAt: '1700000000000', updatedAt: '1700000000000' }]);
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

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Integrations — mirrors the real list_integrations store', () => {
  it('renders the real entry from list_integrations', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('GitHub').length).toBeGreaterThan(0));
    expect(called('list_integrations')).toBe(true);
  });
});
