import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

// Mock the Tauri IPC boundary. Projects mirrors the real list_projects store and
// mutates only through the real set_project_status command — nothing is fabricated.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider, Toaster } from '../components/toast';
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

// `setProjectStatus(...).then(onSaved).catch(onSaved)`: a rejection was discarded and the select
// simply snapped back on the reload.
describe('Projects — a refused status change says why', () => {
  it('surfaces the backend reason', async () => {
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'list_projects') return Promise.resolve([PROJECT]);
      if (cmd === 'list_tasks_by_project') return Promise.resolve([]);
      if (cmd === 'set_project_status') return Promise.reject(new Error('project p-1 has open tasks'));
      return Promise.resolve(null);
    });
    render(<AppProvider><ToastProvider><Toaster /><Projects /></ToastProvider></AppProvider>);
    await waitFor(() => expect(screen.getAllByText('Website revamp').length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByText('Website revamp')[0]);

    const select = await waitFor(() => {
      const el = document.querySelector('.pd-statusrow select') as HTMLSelectElement | null;
      expect(el).not.toBeNull();
      return el as HTMLSelectElement;
    });
    fireEvent.change(select, { target: { value: 'completed' } });
    expect(await screen.findByText('Status not changed: project p-1 has open tasks')).toBeInTheDocument();
  });
});

// Project statuses had their own five strings, drifted from `domain/statusLabels.ts`, which the
// same page already used for task statuses: the Armenian for `completed` was `Թողարկված`
// ("released") for a project and `Ավարտված` for a task, side by side.
describe('Projects — one status vocabulary on the page', () => {
  it('labels a project status with the shared table, in Armenian too', async () => {
    localStorage.setItem('brops.lang', JSON.stringify('hy'));
    try {
      invokeMock.mockImplementation((cmd: string) => {
        if (cmd === 'list_projects') return Promise.resolve([{ ...PROJECT, status: 'completed' }]);
        if (cmd === 'list_tasks_by_project') return Promise.resolve([]);
        return Promise.resolve(null);
      });
      render(<AppProvider><ToastProvider><Projects /></ToastProvider></AppProvider>);
      await waitFor(() => expect(screen.getAllByText('Website revamp').length).toBeGreaterThan(0));
      expect(screen.getAllByText('Ավարտված').length).toBeGreaterThan(0);
      expect(screen.queryByText('Թողարկված')).not.toBeInTheDocument();
      expect(document.body.textContent).not.toMatch(/թողարկված/i);
    } finally {
      localStorage.removeItem('brops.lang');
    }
  });

  it('the page catalog carries no status labels of its own', async () => {
    const { STR } = await import('./Projects.strings');
    expect(Object.keys(STR).filter((k) => k.startsWith('st_'))).toEqual([]);
  });
});
