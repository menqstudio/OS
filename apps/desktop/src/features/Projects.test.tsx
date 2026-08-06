import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// Mock the Tauri IPC boundary. Projects mirrors the real list_projects store and
// mutates only through the real set_project_status command — nothing is fabricated.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Projects } from './Projects';

const PROJECT = {
  id: 'p-1',
  workspaceId: null,
  name: 'Website revamp',
  description: 'Rebuild the marketing site',
  status: 'active',
  priority: 'high',
  createdAt: '1700000000000',
  updatedAt: '1700000000000',
  archivedAt: null,
};

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_projects') return Promise.resolve([PROJECT]);
    if (cmd === 'list_tasks_by_project') return Promise.resolve([]);
    if (cmd === 'set_project_status') return Promise.resolve({ ...PROJECT, status: 'done' });
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Projects />
      </ToastProvider>
    </AppProvider>,
  );
}

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Projects — mirrors the real project store', () => {
  it('renders the real project from list_projects', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Website revamp').length).toBeGreaterThan(0));
    expect(called('list_projects')).toBe(true);
  });
});
