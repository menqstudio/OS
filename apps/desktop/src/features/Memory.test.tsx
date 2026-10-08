import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

// Mock the Tauri IPC boundary. Memory mirrors the real list_memory store; it renders only
// what the store returns and never fabricates an entry.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Memory } from './Memory';
import { STR as MEM_STR } from './Memory.strings';

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_memory') return Promise.resolve([{ id: 'm-1', scope: 'user', kind: 'fact', content: 'Rotate the API key monthly', pinned: false, createdAt: '1700000000000', updatedAt: '1700000000000' }]);
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Memory />
      </ToastProvider>
    </AppProvider>,
  );
}

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Memory — mirrors the real list_memory store', () => {
  it('renders the real entry from list_memory', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Rotate the API key monthly').length).toBeGreaterThan(0));
    expect(called('list_memory')).toBe(true);
  });
});

// The page shortcuts read `e.key` and nothing else, so Ctrl+N, Alt+E and Cmd+N were taken and
// `preventDefault`ed: the browser's or the OS's own chord was swallowed and a dialog opened.
describe('Memory — the page shortcuts leave modified chords alone', () => {
  it.each([
    ['Ctrl+N', { key: 'n', ctrlKey: true }],
    ['Cmd+N', { key: 'n', metaKey: true }],
    ['Alt+N', { key: 'n', altKey: true }],
    ['Ctrl+/', { key: '/', ctrlKey: true }],
  ])('%s is not captured', async (_name, init) => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Rotate the API key monthly').length).toBeGreaterThan(0));
    // `fireEvent` returns false when a handler called preventDefault.
    expect(fireEvent.keyDown(window, init)).toBe(true);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('the bare key still works', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Rotate the API key monthly').length).toBeGreaterThan(0));
    expect(fireEvent.keyDown(window, { key: 'n' })).toBe(false);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });
});

// The metric is `blockedIds.size`: the number of MEMORIES that contain a sealed reference. It was
// labelled "sealed refs", which is a different count the moment one memory holds two.
describe('Memory — the sealed metric is named for what it counts', () => {
  it.each(['en', 'hy', 'ru'] as const)('names memories, not references (%s)', (lang) => {
    expect(MEM_STR.sealedRefs[lang]).toMatch(/memories|հիշողությ|воспоминани/);
  });
});
