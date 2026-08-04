import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// Mock the Tauri IPC boundary. The Agents roster is a pure mirror of the real
// list_agents command — only the facts an agent carries (displayName, role, status,
// model, slug, id) are shown; nothing about an agent is fabricated.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Agents } from './Agents';

const AGENT = {
  id: 'a-1',
  slug: 'scout',
  displayName: 'Scout',
  role: 'researcher',
  status: 'active',
  model: null,
  createdAt: '1700000000000',
  updatedAt: '1700000000000',
};

function setup(agents: unknown[] = [AGENT]) {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_agents') return Promise.resolve(agents);
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Agents />
      </ToastProvider>
    </AppProvider>,
  );
}

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Agents — mirrors the real roster from list_agents', () => {
  it('renders the real agent by its display name', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Scout').length).toBeGreaterThan(0));
    expect(called('list_agents')).toBe(true);
  });
});
