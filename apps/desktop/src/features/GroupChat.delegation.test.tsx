// A delegation Bro makes inside a GROUP room, drawn in the group room.
//
// Everything below drives the REAL path — `GroupChat` → the consensus deck's ask →
// `desktop.streamReply` → the `tauri::ipc::Channel` — and pushes frames shaped EXACTLY as
// `apps/desktop/src-tauri/src/commands.rs::delegation_frame` builds them, cross-checked against
// the live capture in `docs/BRO_DELEGATION_EVIDENCE.md`. Nothing is handed to a reducer directly:
// if the wiring in `GroupChat.tsx` is removed, these fail.
//
// The assertions that matter most are the negative ones:
//   * a frame naming ANOTHER conversation is not drawn in this room;
//   * a one-shot-ask frame (`conversationId: null`) is not adopted by whichever room is open;
//   * a settlement for an id this room never saw spawned materialises nothing;
//   * a stated scope is never rendered as an enforced one, and the word "verified" never appears.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';

type Frame = Record<string, unknown>;

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  // The real `Channel` the renderer constructs: `streamReply` assigns `onmessage`, hands the
  // object to `invoke`, and the backend calls it. The mock keeps that contract intact.
  Channel: class {
    onmessage: ((e: unknown) => void) | null = null;
  },
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { GroupChat } from './GroupChat';
import { STR } from './GroupChat.strings';
import { STR as CHAT_STR } from './Chat.strings';
import { SURFACE_STR } from './delegationView';

vi.setConfig({ testTimeout: 30000 });

const ROOM = {
  id: 'g-1', kind: 'group', title: 'Design room', messageCount: 0,
  lastMessageAt: '1700000000000', createdAt: '1700000000000', updatedAt: '1700000000000',
};

const agent = (slug: string, name: string) => ({
  id: slug, slug, displayName: name, role: 'specialist', status: 'active', model: null,
  createdAt: '1700000000000', updatedAt: '1700000000000',
});

/** Verbatim `delegation_frame(AgentEvent::Spawned(..), "g-1")` for a TIER spawn. `tools` +
 *  `toolsSource` present, `grant` present with `enforcement: "none"` — the only enforcement this
 *  route ever sends. */
const spawned = (id: string, conversationId: string | null): Frame => ({
  type: 'delegationSpawned',
  delegation: {
    id,
    subagentType: 'reader',
    conversationId,
    parent: 'Bro',
    startedAt: '2026-08-07T14:43:26.767Z',
    description: 'Count files in tools/',
    prompt: 'Objective: count the files.\n\nscope: tools\nprohibited_scope: .claude\n',
    tools: ['Read', 'Grep', 'Glob'],
    toolsSource: 'agent_definition',
    grant: {
      scope: ['tools'],
      prohibitedScope: ['.claude'],
      source: 'task_prompt_text',
      enforcement: 'none',
    },
  },
});

const settled = (id: string): Frame => ({
  type: 'delegationSettled',
  id,
  outcome: 'ok',
  summary: '## Answer: 28 files',
  endedAt: '2026-08-07T14:44:11.166Z',
});

/** Frames the backend will push on the `stream_reply` channel, keyed by the agent being asked. */
let framesByAgent: Record<string, Frame[]> = {};

function setup(messages: unknown[] = []) {
  (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
  invokeMock.mockImplementation((cmd: string, args?: Record<string, unknown>) => {
    if (cmd === 'list_conversations') return Promise.resolve([ROOM]);
    if (cmd === 'list_messages') return Promise.resolve(messages);
    if (cmd === 'list_agents') {
      return Promise.resolve([agent('scout', 'Scout'), agent('analyst', 'Analyst')]);
    }
    if (cmd === 'list_conversation_participants') return Promise.resolve(['Scout', 'Analyst']);
    if (cmd === 'ai_status') {
      return Promise.resolve({
        provider: 'claude-cli', model: 'm', ready: true, detail: 'ok', governed: false,
      });
    }
    if (cmd === 'search_all') return Promise.resolve([]);
    if (cmd === 'post_user_message') {
      return Promise.resolve({
        id: 'open-1', conversationId: 'g-1', role: 'user', author: 'You',
        body: String(args?.body ?? ''), createdAt: '1700000000000', receipt: null,
      });
    }
    if (cmd === 'stream_reply') {
      const channel = args?.onEvent as { onmessage: ((e: unknown) => void) | null };
      const who = String(args?.agent ?? '');
      for (const frame of framesByAgent[who] ?? []) channel.onmessage?.(frame);
      return Promise.resolve(null);
    }
    // The read-side command still does not exist. That is the honest backend today, and it is
    // what makes the surface print its live-only note.
    if (cmd === 'list_delegations') {
      return Promise.reject(new Error('Command list_delegations not found'));
    }
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <GroupChat />
      </ToastProvider>
    </AppProvider>,
  );
}

/** Open a consensus round in the room, which is what actually sends the asks. */
async function askTheRoom(question = 'Ship the redesign this week?') {
  const field = await screen.findByLabelText(STR.questionLabel.en);
  fireEvent.change(field, { target: { value: question } });
  const open = await screen.findByRole('button', { name: STR.openRound.en });
  fireEvent.click(open);
  await waitFor(() =>
    expect(invokeMock.mock.calls.some((c) => c[0] === 'stream_reply')).toBe(true));
}

// The room now shows TWO delegation panels: the thread's own, for the room's chat turns, and
// this one, for the asks the consensus deck sends. They cover different streams, so they carry
// different accessible names — and this suite is about the deck's.
const surface = () => screen.findByRole('region', { name: STR.deckDelegationsLabel.en });

beforeEach(() => {
  invokeMock.mockReset();
  framesByAgent = {};
});
afterEach(() => {
  delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
});

describe('Group room · delegations reported by the room’s asks', () => {
  it('draws the delegation a group-room turn reported, with the grant it carried', async () => {
    framesByAgent = { Scout: [spawned('toolu_a', 'g-1'), settled('toolu_a')] };
    setup();
    await askTheRoom();

    const s = await surface();
    // The card itself: who was spawned, at which tier, with which tools.
    expect(await within(s).findByText('reader')).toBeInTheDocument();
    expect(within(s).getByText(CHAT_STR.tierLabel.en)).toBeInTheDocument();
    for (const tool of ['Read', 'Grep', 'Glob']) {
      expect(within(s).getByText(tool)).toBeInTheDocument();
    }
    // The paths, drawn as a grant because every entry passed the task-contract grammar.
    expect(within(s).getByText('tools')).toBeInTheDocument();
    expect(within(s).getByText('.claude')).toBeInTheDocument();
    // It came back, and the summary the backend reported is shown.
    expect(within(s).getByText(CHAT_STR.outcomeOk.en)).toBeInTheDocument();
    expect(within(s).getByText(/28 files/)).toBeInTheDocument();
  });

  it('files it under the room the frame names, and refuses one naming another room', async () => {
    framesByAgent = {
      Scout: [spawned('toolu_here', 'g-1')],
      // Same shape, different conversation: this belongs to some other room and must not be
      // adopted by the room on screen.
      Analyst: [spawned('toolu_elsewhere', 'g-OTHER'), settled('toolu_elsewhere')],
    };
    setup();
    await askTheRoom();

    const s = await surface();
    await within(s).findByText('reader');
    // Exactly one card — the foreign one was dropped, not merely styled differently.
    expect(within(s).getAllByText('reader')).toHaveLength(1);
    // …and the foreign delegation's own settlement did not sneak a second outcome in either.
    expect(within(s).queryByText(CHAT_STR.outcomeOk.en)).toBeNull();
  });

  it('does not adopt a one-shot-ask frame, whose conversationId is null', async () => {
    framesByAgent = { Scout: [spawned('toolu_oneshot', null), settled('toolu_oneshot')] };
    setup();
    await askTheRoom();

    const s = await surface();
    // The live-only note is the proof the surface rendered at all; the card is not there.
    expect(await within(s).findByText(SURFACE_STR.noLedgerTitle.en)).toBeInTheDocument();
    expect(within(s).queryByText('reader')).toBeNull();
  });

  it('materialises nothing from a settlement for an id it never saw spawned', async () => {
    framesByAgent = { Scout: [settled('toolu_never_spawned')] };
    setup();
    await askTheRoom();

    const s = await surface();
    expect(await within(s).findByText(SURFACE_STR.noLedgerTitle.en)).toBeInTheDocument();
    expect(within(s).queryByText('reader')).toBeNull();
    expect(within(s).queryByText(CHAT_STR.outcomeOk.en)).toBeNull();
  });

  it('keeps every honesty property of the direct path: live-only, unenforced scope, no “verified”', async () => {
    framesByAgent = { Scout: [spawned('toolu_a', 'g-1')] };
    setup();
    await askTheRoom();

    const s = await surface();
    await within(s).findByText('reader');

    // A reload empties this list, and an empty list is not "Bro delegated nothing".
    expect(within(s).getByText(SURFACE_STR.noLedgerTitle.en)).toBeInTheDocument();
    expect(within(s).getByText(/an empty list means\s+nothing was reported/i)).toBeInTheDocument();

    // `enforcement: "none"` — the scope is STATED, and the card says only that.
    expect(within(s).getByText(CHAT_STR.scopeUnenforced.en)).toBeInTheDocument();
    expect(within(s).queryByText(CHAT_STR.scopeEnforcedByEngine.en)).toBeNull();

    // Nothing in the group room's delegation block claims verification.
    const block = s.closest('.dl-block') as HTMLElement;
    expect(block).not.toBeNull();
    expect(block.textContent ?? '').not.toMatch(/verif/i);
  });

  it('states which turns this window can see, instead of letting the list read as the whole room', async () => {
    framesByAgent = { Scout: [spawned('toolu_a', 'g-1')] };
    setup();
    await askTheRoom();

    await surface();
    expect(screen.getByText(STR.delegationLabel.en)).toBeInTheDocument();
    expect(screen.getByText(STR.delegationScopeNote.en)).toBeInTheDocument();
  });
});

describe('Group room · what the delegation is and is not connected to', () => {
  it('names the ask that reported it, and the round that ask belonged to', async () => {
    framesByAgent = { Scout: [spawned('toolu_a', 'g-1'), settled('toolu_a')] };
    setup();
    await askTheRoom('Ship the redesign this week?');

    const trail = await screen.findByRole('list', { name: STR.delegationTrailLabel.en });
    // The turn that reported it was the ask to Scout — not "Bro", which the backend stamps on
    // every frame regardless of whose turn produced it.
    expect(within(trail).getByText(`${STR.delegationAskPrefix.en} Scout`)).toBeInTheDocument();
    expect(within(trail).getByText('reader')).toBeInTheDocument();
    expect(
      within(trail).getByText(`${STR.delegationRoundPrefix.en} Ship the redesign this week?`),
    ).toBeInTheDocument();
    // …and it says out loud that the frame carried none of this.
    expect(screen.getByText(STR.delegationTrailNote.en)).toBeInTheDocument();
  });

  it('attributes each delegation to its own ask, never to whichever ask came last', async () => {
    framesByAgent = {
      Scout: [spawned('toolu_scout', 'g-1')],
      Analyst: [spawned('toolu_analyst', 'g-1')],
    };
    setup();
    await askTheRoom();

    const trail = await screen.findByRole('list', { name: STR.delegationTrailLabel.en });
    const rows = within(trail).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain(`${STR.delegationAskPrefix.en} Scout`);
    expect(rows[1].textContent).toContain(`${STR.delegationAskPrefix.en} Analyst`);
  });
});
