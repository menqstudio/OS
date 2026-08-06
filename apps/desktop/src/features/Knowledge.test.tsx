import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// Mock the Tauri IPC boundary. Knowledge mirrors the real list_knowledge store; it renders only
// what the store returns and never fabricates an entry.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Knowledge } from './Knowledge';

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    // The article list is driven by search_knowledge (empty query); list_knowledge
    // backs the tag collections. Both mirror the same real store.
    if (cmd === 'search_knowledge' || cmd === 'list_knowledge')
      return Promise.resolve([{ id: 'k-1', title: 'Onboarding notes', body: 'welcome', source: 'internal', tags: 'hr', createdAt: '1700000000000', updatedAt: '1700000000000' }]);
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Knowledge />
      </ToastProvider>
    </AppProvider>,
  );
}

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Knowledge — mirrors the real list_knowledge store', () => {
  it('renders the real entry from list_knowledge', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Onboarding notes').length).toBeGreaterThan(0));
    expect(called('search_knowledge')).toBe(true);
  });
});
