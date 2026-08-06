import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// Mock the Tauri IPC boundary. Tasks mirrors the real list_tasks store and mutates
// only through the real set_task_status command — nothing is fabricated.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Tasks } from './Tasks';

const TASK = {
  id: 't-1',
  projectId: null,
  title: 'Draft the specification',
  description: 'first cut of the spec',
  status: 'active',
  priority: 'high',
  assignedAgentId: null,
  dueAt: null,
  position: 1,
  createdAt: '1700000000000',
  updatedAt: '1700000000000',
  completedAt: null,
};

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_tasks') return Promise.resolve([TASK]);
    if (cmd === 'list_projects') return Promise.resolve([]);
    if (cmd === 'list_task_dependencies') return Promise.resolve([]);
    if (cmd === 'set_task_status') return Promise.resolve({ ...TASK, status: 'done' });
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Tasks />
      </ToastProvider>
    </AppProvider>,
  );
}

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Tasks — mirrors the real task store', () => {
  it('renders the real task from list_tasks', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Draft the specification').length).toBeGreaterThan(0));
    expect(called('list_tasks')).toBe(true);
  });
});
