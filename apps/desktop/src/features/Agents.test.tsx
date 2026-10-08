import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

// Mock the Tauri IPC boundary. The Agents roster is a pure mirror of the real
// list_agents command — only the facts an agent carries (displayName, role, status,
// model, slug, id) are shown; nothing about an agent is fabricated.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Agents } from './Agents';
import { STR as AG_STR } from './Agents.strings';

const AGENT = {
  id: 'a-1',
  slug: 'scout',
  displayName: 'Scout',
  role: 'researcher',
  status: 'active',
  model: null,
  createdAt: '1700000000000',
  updatedAt: '1700000000000',
};

function setup(agents: unknown[] = [AGENT]) {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_agents') return Promise.resolve(agents);
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Agents />
      </ToastProvider>
    </AppProvider>,
  );
}

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Agents — mirrors the real roster from list_agents', () => {
  it('renders the real agent by its display name', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Scout').length).toBeGreaterThan(0));
    expect(called('list_agents')).toBe(true);
  });
});

// The keys hint says "Esc closes". An effect re-selected the first agent whenever the selection
// was null, so Escape's `setSelectedId(null)` was undone on the next pass and the "Select an
// agent" branch could not be reached while any agent existed.
describe('Agents — Esc closes the dossier and it stays closed', () => {
  it('opens the first agent by default, closes on Escape, and does not re-open by itself', async () => {
    setup();
    await waitFor(() => expect(document.querySelector('.dossier .ag-forge')).not.toBeNull());
    expect(screen.queryByText('Select an agent')).not.toBeInTheDocument();

    const node = screen.getByRole('button', { name: /Scout · researcher/ });
    node.focus();
    fireEvent.keyDown(node, { key: 'Escape' });

    await waitFor(() => expect(screen.getByText('Select an agent')).toBeInTheDocument());
    // Give the effect that used to undo it every chance to run.
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByText('Select an agent')).toBeInTheDocument();
    expect(document.querySelector('.dossier .ag-forge')).toBeNull();
    expect(node).toHaveAttribute('aria-pressed', 'false');
  });

  it('Enter re-opens the focused agent after an Escape', async () => {
    setup();
    await waitFor(() => expect(document.querySelector('.dossier .ag-forge')).not.toBeNull());
    const node = screen.getByRole('button', { name: /Scout · researcher/ });
    node.focus();
    fireEvent.keyDown(node, { key: 'Escape' });
    await waitFor(() => expect(screen.getByText('Select an agent')).toBeInTheDocument());
    fireEvent.keyDown(node, { key: 'Enter' });
    await waitFor(() => expect(document.querySelector('.dossier .ag-forge')).not.toBeNull());
  });
});

// `agents.status` has one writer in the whole backend: `repo::seed`, which sets `shield` to
// `blocked` at startup. No governed turn writes it. The panel said "A governed turn for this agent
// was halted by the wall. Its result is withheld until a verified receipt is produced" — an event,
// a withheld result and a receipt, none of which exist behind this status.
describe('the blocked panel does not narrate a wall event nobody recorded', () => {
  it.each(['en', 'hy', 'ru'] as const)('claims no halted turn and no pending receipt (%s)', (lang) => {
    const body = AG_STR.blockedBody[lang];
    expect(body).not.toMatch(/halted by the wall|կանգնեցվեց պատի|остановлен стеной/);
    expect(body).not.toMatch(/withheld|պահվում է մինչև|удерживается/);
    expect(body).toMatch(/does not record why|չի գրանցում, թե ինչու|не записывает, почему/);
  });
});
