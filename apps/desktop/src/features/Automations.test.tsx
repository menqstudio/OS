import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// Mock the Tauri IPC boundary. Automations mirrors the real list_automations store; it renders only
// what the store returns and never fabricates an entry.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Automations } from './Automations';

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_automations') return Promise.resolve([{ id: 'au-1', name: 'Nightly backup', trigger: 'cron', action: 'backup', enabled: true, createdAt: '1700000000000', updatedAt: '1700000000000' }]);
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Automations />
      </ToastProvider>
    </AppProvider>,
  );
}

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Automations — mirrors the real list_automations store', () => {
  it('renders the real entry from list_automations', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Nightly backup').length).toBeGreaterThan(0));
    expect(called('list_automations')).toBe(true);
  });
});
