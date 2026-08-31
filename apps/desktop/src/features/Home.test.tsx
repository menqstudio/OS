import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// Mock the Tauri IPC boundary. The Home dashboard mirrors real reads — the active
// task queue (list_tasks_by_status) and the pending-approval count (list_approvals)
// — and never fabricates a task or an approval.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Home } from './Home';
import { activitySummary } from './Home.strings';

const TASK = {
  id: 't-1',
  projectId: null,
  title: 'Ship the release notes',
  description: '',
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
    if (cmd === 'list_tasks_by_status') return Promise.resolve([TASK]);
    if (cmd === 'list_approvals') return Promise.resolve([]);
    return Promise.resolve(null);
  });
  return render(<AppProvider><ToastProvider><Home /></ToastProvider></AppProvider>);
}

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Home — mirrors the real dashboard reads', () => {
  it('renders the real active task from list_tasks_by_status', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Ship the release notes').length).toBeGreaterThan(0));
    expect(called('list_tasks_by_status')).toBe(true);
    expect(called('list_approvals')).toBe(true);
  });
});

// T-057. `repo::seed` writes 56 FABRICATED rows straight into `audit_events` so
// this very sparkline has "a real heartbeat". The surface those rows exist to
// animate is therefore the surface being lied to, and marking the row in the
// database is only half a fix — the mark has to arrive here, which is the same
// defect `ActivityEvent.actorType` already carries a paragraph about.
describe('activitySummary — seeded events are named, not hidden', () => {
  it('says how many of the plotted events are fabricated', () => {
    const en = activitySummary('en', 200, 24, 19, 56);
    expect(en).toContain('200 recent events');
    expect(en).toContain('56');
    expect(en.toLowerCase()).toContain('seeded');
  });

  it('says it in every language the app offers', () => {
    expect(activitySummary('hy', 200, 24, 19, 56)).toContain('56');
    expect(activitySummary('ru', 200, 24, 19, 56)).toContain('56');
  });

  it('is unchanged on a real install, where nothing is seeded', () => {
    const plain = activitySummary('en', 200, 24, 19, 0);
    expect(plain).toBe(activitySummary('en', 200, 24, 19));
    expect(plain.toLowerCase()).not.toContain('seeded');
  });
});
