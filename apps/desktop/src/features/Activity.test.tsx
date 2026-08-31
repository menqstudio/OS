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
