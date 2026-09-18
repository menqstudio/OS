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

const EVENT = {
  id: 'a-1',
  eventType: 'task.created',
  actorType: 'system',
  source: null as string | null,
  actorId: null,
  entityType: 'task',
  entityId: 't-1',
  createdAt: '1700000000000',
};

/** `activity` rows for the sparkline. `seeded` of them carry `source: 'seed'`, the mark
 *  `repo::seed` writes; the rest carry `null`, which is what a real audited write produces. */
function events(total: number, seeded: number) {
  return Array.from({ length: total }, (_, i) => ({
    ...EVENT,
    id: `a-${i}`,
    source: i < seeded ? 'seed' : null,
    createdAt: String(1700000000000 + i * 60000),
  }));
}

function setup(activity: ReturnType<typeof events> = []) {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_tasks_by_status') return Promise.resolve([TASK]);
    if (cmd === 'list_approvals') return Promise.resolve([]);
    if (cmd === 'list_activity') return Promise.resolve(activity);
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
// V-4, `docs/VERIFICATION_QUEUE_1.md`. `activitySummary` was tested; the WIRING that feeds it
// was not. Replacing `rows.filter((e) => e.source === 'seed').length` with `0` type-checked and
// left the suite green — measured on 2026-09-01 before these tests existed. A pure function with
// a tested body and an untested caller is a function whose result nobody has seen arrive.
//
// So these render the real `<Home />` over a mocked `list_activity` and read the sentence off the
// screen. They fail on the constant-fold, on the wrong predicate, and on the mark being dropped
// between the IPC boundary and the summary — which is the whole path T-057 was about.
describe('Home — the seeded mark survives the wiring, not just the formatter', () => {
  it('counts the seeded rows it was actually given and says so on screen', async () => {
    setup(events(5, 2));
    await waitFor(() =>
      expect(screen.getByText(/2 of them are seeded demo data/)).toBeTruthy());
  });

  it('says nothing about seeding when every row is real', async () => {
    setup(events(5, 0));
    await waitFor(() => expect(screen.getByText(/5 recent events/)).toBeTruthy());
    expect(screen.queryByText(/seeded demo data/)).toBeNull();
  });

  it('counts the seeded rows rather than all of them', async () => {
    // The arm that separates "wired up" from "wired up correctly": a caller that dropped the
    // predicate and passed `rows.length` would pass the first test and fail this one.
    setup(events(5, 5));
    await waitFor(() =>
      expect(screen.getByText(/5 of them are seeded demo data/)).toBeTruthy());
    setup(events(9, 3));
    await waitFor(() =>
      expect(screen.getByText(/3 of them are seeded demo data/)).toBeTruthy());
  });
});

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
