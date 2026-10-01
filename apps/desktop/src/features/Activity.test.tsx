import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Activity } from './Activity';

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_activity') return Promise.resolve([{ id: 'ev-1', eventType: 'task.created', actorType: 'user', actorId: 'local-operator', entityType: 'task', entityId: 't-1', createdAt: '1700000000000' }]);
    return Promise.resolve(null);
  });
  return render(<AppProvider><ToastProvider><Activity /></ToastProvider></AppProvider>);
}

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Activity — mirrors the real list_activity store', () => {
  it('mounts and wires the real list_activity read without fabricating', async () => {
    setup();
    await waitFor(() => expect(called('list_activity')).toBe(true));
  });
});

// `repo::seed` writes demo rows straight into `audit_events` and marks each `source: 'seed'`.
// This page's header says "Every beat is a REAL system event" and it never read the mark, so
// the demo rows were plotted, counted, rated and tallied as system events.
describe('Activity — a seeded row is not a beat', () => {
  const real = (id: string, at: string) => ({
    id, eventType: 'task.created', actorType: 'user', source: null,
    actorId: 'local-operator', entityType: 'task', entityId: 't-1', createdAt: at,
  });
  const seeded = (id: string, at: string) => ({
    id, eventType: 'demo.heartbeat', actorType: 'system', source: 'seed',
    actorId: null, entityType: 'project', entityId: 'p-1', createdAt: at,
  });
  function mount(rows: unknown[]) {
    invokeMock.mockImplementation((cmd: string) =>
      Promise.resolve(cmd === 'list_activity' ? rows : null));
    return render(<AppProvider><ToastProvider><Activity /></ToastProvider></AppProvider>);
  }

  it('plots and tallies only the real rows, and says how many seeded ones it held out', async () => {
    mount([
      real('ev-1', '1700000000000'),
      seeded('s-1', '1700000100000'), seeded('s-2', '1700000200000'), seeded('s-3', '1700000300000'),
    ]);
    await waitFor(() => expect(screen.getByText(/3 seeded demo rows are not plotted or counted/)).toBeInTheDocument());
    // The seeded event type reaches no instrument: not the tallies, not the timeline.
    expect(screen.queryByText('demo.heartbeat')).not.toBeInTheDocument();
    expect(screen.getAllByText('task.created').length).toBeGreaterThan(0);
    // "plotted N / total" counts real rows only.
    expect(document.querySelector('.vitals')?.textContent).toContain('/1');
    expect(document.querySelector('.vitals')?.textContent).not.toContain('/4');
  });

  it('a store holding ONLY seeded rows reads as no activity, not as a heartbeat', async () => {
    mount([seeded('s-1', '1700000100000'), seeded('s-2', '1700000200000')]);
    await waitFor(() => expect(screen.getByText('No activity yet')).toBeInTheDocument());
    expect(screen.getByText(/2 seeded demo rows are not plotted or counted/)).toBeInTheDocument();
  });

  it('says nothing about seeding when no row is seeded', async () => {
    mount([real('ev-1', '1700000000000')]);
    await waitFor(() => expect(screen.getAllByText('task.created').length).toBeGreaterThan(0));
    expect(screen.queryByText(/seeded demo row/)).not.toBeInTheDocument();
  });
});

// `list_activity` only locks the local database and queries it. A refusal of it was shown as
// "did not clear the governance wall. No live data crosses until it is approved" — a wall and an
// approval that do not exist for this read.
describe('Activity — a refused local read is not a governance wall', () => {
  it('names a refused read and its reason, and promises no approval', async () => {
    invokeMock.mockImplementation((cmd: string) =>
      cmd === 'list_activity'
        ? Promise.reject(new Error('list_activity not allowed. Permissions associated with this command: '))
        : Promise.resolve(null));
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
    try {
      render(<AppProvider><ToastProvider><Activity /></ToastProvider></AppProvider>);
      await waitFor(() => expect(screen.getByText('Activity read refused')).toBeInTheDocument());
      expect(screen.getByText(/list_activity not allowed/)).toBeInTheDocument();
      expect(screen.queryByText(/governance wall/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/until it is approved/i)).not.toBeInTheDocument();
    } finally {
      delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
    }
  });
});
