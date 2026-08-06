import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// The chat context rail's RECALL (Phase 5) is a real retrieval: it queries search_all
// with the latest user turn and surfaces cross-store memory/knowledge in the rail. This
// is governance-free (reads local stores), so it works while the trust gate is fail-closed.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Conversations } from './Conversations';

const CONV = {
  id: 'c-1', kind: 'direct', title: 'Planning session', messageCount: 1,
  lastMessageAt: '1700000000000', createdAt: '1700000000000', updatedAt: '1700000000000',
};
const USER_MSG = {
  id: 'm-1', conversationId: 'c-1', role: 'user', author: 'Gev',
  body: 'rotate the api key monthly', createdAt: '1700000000000', receipt: null,
};
const MEM_HIT = {
  kind: 'memory', id: 'mem-1', title: 'API key rotation', subtitle: 'user · fact', route: 'memory',
};

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_conversations') return Promise.resolve([CONV]);
    if (cmd === 'list_messages') return Promise.resolve([USER_MSG]);
    if (cmd === 'search_all') return Promise.resolve([MEM_HIT]);
    if (cmd === 'ai_status') return Promise.resolve({ provider: 'claude-cli', model: 'm', ready: true, detail: 'ok', governed: false });
    if (cmd === 'list_agents') return Promise.resolve([]);
    if (cmd === 'list_conversation_participants') return Promise.resolve([]);
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Conversations kind="direct" />
      </ToastProvider>
    </AppProvider>,
  );
}

const calledWith = (cmd: string, pred: (a: Record<string, unknown>) => boolean) =>
  invokeMock.mock.calls.some((c) => c[0] === cmd && pred((c[1] ?? {}) as Record<string, unknown>));

beforeEach(() => invokeMock.mockReset());

describe('Chat recall — the context rail retrieves real cross-store matches', () => {
  it('queries search_all with the latest user turn and surfaces the hit in the rail', async () => {
    setup();
    // Select the conversation so the view (and its rail) mounts.
    fireEvent.click((await screen.findAllByText('Planning session'))[0]);

    // Recall issued a REAL search_all keyed off the user message body.
    await waitFor(() =>
      expect(calledWith('search_all', (a) => typeof a.query === 'string' && (a.query as string).includes('rotate'))).toBe(true),
    );
    // …and the recalled memory hit is rendered in the rail (not a bare counter).
    expect(await screen.findByText('API key rotation')).toBeInTheDocument();
  });
});
