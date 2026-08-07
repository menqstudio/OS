import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Agents } from './Agents';
import { STR } from './Agents.strings';

const en = (k: keyof typeof STR) => STR[k].en;

const AGENT = {
  id: 'a-1',
  slug: 'boundary-auditor',
  displayName: 'Boundary Auditor',
  role: 'auditor',
  status: 'idle',
  model: null,
  createdAt: '1700000000000',
  updatedAt: '1700000000000',
};

function setup(agents: unknown[] = [AGENT], onDispatch?: () => Promise<unknown>) {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_agents') return Promise.resolve(agents);
    if (cmd === 'dispatch_task_contract') {
      return onDispatch ? onDispatch() : Promise.reject(new Error('Command dispatch_task_contract not found'));
    }
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

beforeEach(() => invokeMock.mockReset());
afterEach(() => { delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__; });

describe('Agents — the dossier states the grant, and states what it cannot know', () => {
  it('derives the contract agent_id from the real slug and says whether it is usable', async () => {
    setup();
    await screen.findByText(en('grantTitle'));
    expect(screen.getAllByText('boundary-auditor').length).toBeGreaterThan(0);
    expect(screen.getByText(en('idValid'))).toBeTruthy();
  });

  it('refuses to pretend a slug that cannot be written into a contract is fine', async () => {
    setup([{ ...AGENT, slug: 'X' }]);
    await screen.findByText(en('grantTitle'));
    expect(screen.getByText(en('idInvalid'))).toBeTruthy();
    expect(screen.getByText(en('idInvalidNote'))).toBeTruthy();
    expect(screen.queryByText(en('idValid'))).toBeNull();
  });

  it('shows only the DEFAULT authority and says an override is not readable here', async () => {
    setup();
    await screen.findByText(en('authorityTitle'));
    expect(screen.getByText('review')).toBeTruthy();
    expect(screen.getByText('work')).toBeTruthy();
    // The desktop cannot prove a release override, so it never offers one as fact.
    expect(screen.queryByText('release')).toBeNull();
    expect(screen.getByText('high')).toBeTruthy();
    expect(screen.getByText(en('authorityNote'))).toBeTruthy();
  });

  it('lists the tiers Bro may grant with the exact tools their definitions declare', async () => {
    setup();
    await screen.findByText(en('tiersTitle'));
    expect(screen.getByText('Read · Grep · Glob')).toBeTruthy();
    expect(screen.getByText('Read · Grep · Glob · Bash')).toBeTruthy();
    expect(screen.getByText('Read · Edit · Write · Grep · Glob · Bash')).toBeTruthy();
    expect(screen.getByText('.claude/agents/builder.md')).toBeTruthy();
  });

  it('reports no dispatch channel when there is no Tauri runtime, without calling out', async () => {
    setup();
    await screen.findByText(en('channelTitle'));
    fireEvent.click(screen.getByRole('button', { name: en('channelCheck') }));
    await waitFor(() => expect(screen.getByText(en('channelAbsent'))).toBeTruthy());
    expect(screen.getByText(/no Tauri runtime/)).toBeTruthy();
    expect(invokeMock.mock.calls.some((c) => c[0] === 'dispatch_task_contract')).toBe(false);
  });

  it('reports no dispatch channel when the command is not registered', async () => {
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
    setup();
    await screen.findByText(en('channelTitle'));
    fireEvent.click(screen.getByRole('button', { name: en('channelCheck') }));
    await waitFor(() => expect(screen.getByText(en('channelAbsent'))).toBeTruthy());
    expect(screen.getByText(/Command dispatch_task_contract not found/)).toBeTruthy();
    expect(screen.queryByText(en('channelPresent'))).toBeNull();
  });

  it('claims no more than "something answered" when the command does exist', async () => {
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
    setup([AGENT], async () => ({ protocol: 'brops.agent-dispatch-result.v1' }));
    await screen.findByText(en('channelTitle'));
    fireEvent.click(screen.getByRole('button', { name: en('channelCheck') }));
    await waitFor(() => expect(screen.getByText(en('channelPresent'))).toBeTruthy());
    expect(screen.getByText(en('channelPresentNote'))).toBeTruthy();
  });
});
