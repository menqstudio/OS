// What the chat actually PUTS ON SCREEN when Bro delegates — and what it refuses to put there.
//
// The cardinal rule these pin: a delegation card is a statement about capability the owner
// handed out. It may never appear over data we do not have, and it may never let "we stated a
// scope" read like "something enforced a scope".

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Chat } from './Chat';
import { DelegationSurface } from './delegationView';
import { STR } from './Chat.strings';
import { SURFACE_STR } from './delegationView';
import { classifyDelegationFailure, loadDelegations } from './delegationSource';

vi.setConfig({ testTimeout: 30000 });
beforeEach(() => invokeMock.mockReset());
// One test below fakes the Tauri runtime so the surface takes its real path; drop it again so
// no later test inherits a backend it did not ask for.
afterEach(() => { delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__; });

const yes = () => true;

const RECORD = {
  id: 'toolu_1',
  conversationId: 'c-1',
  parent: 'Bro',
  subagentType: 'builder',
  description: 'Render delegation in the chat surface',
  prompt: 'Build the delegation card. scope: apps/desktop/src/features',
  tools: ['Read', 'Edit', 'Write', 'Grep', 'Glob', 'Bash'],
  toolsSource: 'agent_definition',
  grant: {
    scope: ['apps/desktop/src/features', 'C:/Users/Admin/Desktop/ui-work'],
    prohibitedScope: ['engine', 'apps/desktop/src-tauri'],
    source: 'task_prompt_text',
  },
  startedAt: '2026-08-07T10:00:00.000Z',
  outcome: 'ok',
  summary: 'Card shipped; tsc + vitest green.',
  endedAt: '2026-08-07T10:04:00.000Z',
};

function mount(reply: () => Promise<unknown>) {
  const invokeFn = () => reply();
  return render(
    <AppProvider>
      <ToastProvider>
        <DelegationSurface invokeFn={invokeFn} backend={yes} />
      </ToastProvider>
    </AppProvider>,
  );
}

describe('Chat delegation surface — the absent state is the honest one today', () => {
  it('says nothing STORES a delegation, and quotes what the backend said', async () => {
    mount(() => Promise.reject(new Error('Command list_delegations not found')));

    // The live channel exists now, so the old "the backend does not report delegations"
    // headline would be false. What is missing is storage, and that is what it must say.
    await screen.findByText(SURFACE_STR.noLedgerTitle.en);
    expect(screen.getByText(SURFACE_STR.noLedgerBody.en)).toBeInTheDocument();
    expect(screen.queryByText(STR.notEmittedTitle.en)).not.toBeInTheDocument();
    // The backend's own words survive to the screen — a mapped headline never replaces them.
    expect(screen.getByText(/Command list_delegations not found/)).toBeInTheDocument();
    // And absolutely nothing that looks like a delegation was drawn.
    expect(document.querySelector('.dg-card')).toBeNull();
  });

  it('distinguishes a REFUSAL from an unimplemented command instead of flattening both', async () => {
    mount(() => Promise.reject(new Error('list_delegations not allowed by the window capability set')));
    await screen.findByText(STR.deniedTitle.en);
    expect(screen.queryByText(SURFACE_STR.noLedgerTitle.en)).not.toBeInTheDocument();
    // …and it is explained as a failed read, not borrowed from "there is no such command".
    expect(screen.getByText(SURFACE_STR.unreadableLedgerBody.en)).toBeInTheDocument();
    expect(screen.queryByText(SURFACE_STR.noLedgerBody.en)).not.toBeInTheDocument();
  });

  it('does not report a genuinely broken backend as "not built yet"', async () => {
    // Guessing at a failure is how a real fault ends up reading as a missing feature and stops
    // getting fixed.
    mount(() => Promise.reject(new Error('database is locked')));
    await screen.findByText(STR.errorTitle.en);
    expect(classifyDelegationFailure('database is locked')).toBe('error');
    expect(classifyDelegationFailure('Command list_delegations not found')).toBe('not_emitted');
  });

  it('refuses a reply it cannot read as a delegation list', async () => {
    mount(() => Promise.resolve({ delegations: 'lots' }));
    await screen.findByText(STR.errorTitle.en);
    expect(document.querySelector('.dg-card')).toBeNull();
  });

  it('shows an empty ledger for an empty list, not an absent-backend notice', async () => {
    mount(() => Promise.resolve([]));
    await screen.findByText(STR.noneYet.en);
    expect(screen.queryByText(SURFACE_STR.noLedgerTitle.en)).not.toBeInTheDocument();
  });

  it('asks nothing at all outside the desktop runtime, and says so', async () => {
    const feed = await loadDelegations(undefined, { backend: () => false, invokeFn: invokeMock });
    expect(feed).toEqual({ state: 'unavailable', reason: 'no_backend', detail: 'no Tauri runtime' });
    expect(invokeMock).not.toHaveBeenCalled();
  });
});

describe('Chat delegation surface — the card, when there is real data behind it', () => {
  it('shows who was spawned, at which tier, with which tools and which paths', async () => {
    mount(() => Promise.resolve([RECORD]));

    await screen.findByText('builder');
    expect(screen.getByText('Render delegation in the chat surface')).toBeInTheDocument();
    // The capability half.
    for (const tool of ['Read', 'Edit', 'Write', 'Grep', 'Glob', 'Bash']) {
      expect(screen.getByText(tool)).toBeInTheDocument();
    }
    // The path half — including the absolute grant outside this repo, which is the case the
    // owner most needs to see at a glance.
    expect(screen.getByText('apps/desktop/src/features')).toBeInTheDocument();
    expect(screen.getByText('C:/Users/Admin/Desktop/ui-work')).toBeInTheDocument();
    expect(screen.getByText('engine')).toBeInTheDocument();
    expect(screen.getByText(STR.mustNotTouch.en)).toBeInTheDocument();
    // And the outcome.
    expect(screen.getByText(STR.outcomeOk.en)).toBeInTheDocument();
  });

  it('says the tool grant is ENFORCED and the path grant is only STATED', async () => {
    mount(() => Promise.resolve([RECORD]));
    await screen.findByText(STR.capabilityEnforced.en);
    expect(screen.getByText(STR.scopeUnenforced.en)).toBeInTheDocument();
    // The engine-enforced wording must not appear for a grant nothing bounded.
    expect(screen.queryByText(STR.scopeEnforcedByEngine.en)).not.toBeInTheDocument();
  });

  it('only says a scope was enforced when the backend actually reports enforce_scope', async () => {
    mount(() => Promise.resolve([
      { ...RECORD, grant: { ...RECORD.grant, enforcement: 'engine_enforce_scope' } },
    ]));
    await screen.findByText(STR.scopeEnforcedByEngine.en);
    expect(screen.queryByText(STR.scopeUnenforced.en)).not.toBeInTheDocument();
  });

  it('a hopeful `enforced: true` still renders as unenforced', async () => {
    mount(() => Promise.resolve([{ ...RECORD, grant: { ...RECORD.grant, enforcement: 'enforced' } }]));
    await screen.findByText(STR.scopeUnenforced.en);
    expect(screen.queryByText(STR.scopeEnforcedByEngine.en)).not.toBeInTheDocument();
  });

  it('renders a malformed scope as raw text, never as a grant', async () => {
    mount(() => Promise.resolve([
      { ...RECORD, grant: { scope: ['apps/desktop/src', '../../etc'], prohibitedScope: [] } },
    ]));
    await screen.findByText(STR.grantInvalid.en);
    // No "MAY TOUCH" row: nothing here was accepted as a scope.
    expect(screen.queryByText(STR.mayTouch.en)).not.toBeInTheDocument();
    expect(screen.getByText('../../etc')).toBeInTheDocument();
  });

  it('states plainly when no scope was given at all', async () => {
    const { grant, ...noGrant } = RECORD;
    void grant;
    mount(() => Promise.resolve([noGrant]));
    await screen.findByText(STR.grantNotStated.en);
    expect(screen.queryByText(STR.mayTouch.en)).not.toBeInTheDocument();
  });

  it('flags a capability list that disagrees with the tier table, and shows the wider one', async () => {
    mount(() => Promise.resolve([
      { ...RECORD, subagentType: 'reader', tools: ['Read', 'Grep', 'Glob', 'Bash'] },
    ]));
    await screen.findByText(STR.capabilityConflict.en);
    // The extra tool is on screen: an owner reading this card is not told the reader is safe.
    expect(screen.getByText('Bash')).toBeInTheDocument();
  });

  it('says capability is unknown rather than inventing one for an unresolved agent', async () => {
    mount(() => Promise.resolve([
      { ...RECORD, subagentType: 'some-pack--some-role', tools: undefined, toolsSource: undefined },
    ]));
    await screen.findByText(STR.capabilityUnknown.en);
    expect(screen.queryByText(STR.capabilityEnforced.en)).not.toBeInTheDocument();
  });

  it('never paints a running delegation as a successful one', async () => {
    mount(() => Promise.resolve([{ ...RECORD, outcome: undefined, summary: undefined, endedAt: undefined }]));
    await screen.findByText(STR.outcomeRunning.en);
    expect(screen.queryByText(STR.outcomeOk.en)).not.toBeInTheDocument();
    expect(document.querySelector('.dg-card .badge--success')).toBeNull();
  });

  it('never paints an unreadable outcome as a successful one', async () => {
    mount(() => Promise.resolve([{ ...RECORD, outcome: 'sort_of' }]));
    await screen.findByText(STR.outcomeUnknown.en);
    expect(document.querySelector('.dg-card .badge--success')).toBeNull();
  });
});

describe('the Chat screen carries the surface', () => {
  it('renders the conversation AND the delegation ledger, without a fabricated card', async () => {
    // Stand the whole screen up on the REAL path — no injected seams, so `hasBackend()` and the
    // real `invoke` wrapper are what the surface uses. Only the IPC itself is mocked.
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'list_conversations') {
        return Promise.resolve([{
          id: 'c-1', kind: 'direct', title: 'Bro', messageCount: 0,
          lastMessageAt: '1700000000000', createdAt: '1700000000000', updatedAt: '1700000000000',
        }]);
      }
      if (cmd === 'list_messages') return Promise.resolve([]);
      if (cmd === 'list_agents') return Promise.resolve([]);
      if (cmd === 'list_conversation_participants') return Promise.resolve([]);
      if (cmd === 'ai_status') {
        return Promise.resolve({ provider: 'claude-cli', model: 'm', ready: true, detail: 'ok', governed: false });
      }
      if (cmd === 'search_all') return Promise.resolve([]);
      // The real answer from the real backend today: there is no such command.
      if (cmd === 'list_delegations') return Promise.reject(new Error('Command list_delegations not found'));
      return Promise.resolve(null);
    });

    render(
      <AppProvider>
        <ToastProvider>
          <Chat />
        </ToastProvider>
      </AppProvider>,
    );

    await waitFor(() => expect(screen.getByLabelText(STR.sectionTitle.en)).toBeInTheDocument());
    expect(screen.getByText(STR.eyebrow.en)).toBeInTheDocument();
    await screen.findByText(SURFACE_STR.noLedgerTitle.en);
    expect(document.querySelector('.dg-card')).toBeNull();
    // The surface asked the real command name — a probe, not a simulation — and it asked for
    // the conversation the screen actually has open, not for "everything".
    await waitFor(() =>
      expect(invokeMock).toHaveBeenCalledWith('list_delegations', { conversationId: 'c-1' }));
  });
});
