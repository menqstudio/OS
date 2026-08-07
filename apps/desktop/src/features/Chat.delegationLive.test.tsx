// The seam this wave keeps breaking: the backend emits and nothing listens.
//
// Everything below drives the REAL path — `Chat` → `Conversations` → `MessageThread` →
// `desktop.streamReply` → the `tauri::ipc::Channel` — and pushes frames shaped EXACTLY as
// `apps/desktop/src-tauri/src/commands.rs::delegation_frame` builds them, cross-checked against
// the live capture in `docs/BRO_DELEGATION_EVIDENCE.md`. The three shapes a hand-written fixture
// always gets wrong are pinned here:
//
//   * `tools` / `toolsSource` are OMITTED (not `null`) when capability could not be established;
//   * `grant` is `null` when the task stated no scope;
//   * `conversationId` is `null` for a one-shot ask — and must NOT then be adopted by whichever
//     chat happens to be open.
//
// If a field the reader wants stops arriving, or one the backend sends starts being ignored,
// these fail rather than the app quietly drawing nothing.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

type Frame = Record<string, unknown>;
let emit: (frame: Frame) => void = () => {};

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  // The real `Channel` the renderer constructs: `streamReply` assigns `onmessage`, hands the
  // object to `invoke`, and the backend calls it. The mock keeps that contract intact, so the
  // frames below travel the same route a real turn's frames do.
  Channel: class {
    onmessage: ((e: unknown) => void) | null = null;
  },
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Chat } from './Chat';
import { STR } from './Chat.strings';
import { SURFACE_STR } from './delegationView';

vi.setConfig({ testTimeout: 30000 });

const ROOM = {
  id: 'c-1', kind: 'direct', title: 'Bro', messageCount: 0,
  lastMessageAt: '1700000000000', createdAt: '1700000000000', updatedAt: '1700000000000',
};

/** Verbatim `delegation_frame(AgentEvent::Spawned(..), "c-1")` for a TIER spawn. */
const SPAWNED: Frame = {
  type: 'delegationSpawned',
  delegation: {
    id: 'toolu_018eiZUCt21zUYTGZ5C8Esau',
    subagentType: 'reader',
    conversationId: 'c-1',
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
};

/** Verbatim `delegation_frame(AgentEvent::Settled(..))`. */
const SETTLED: Frame = {
  type: 'delegationSettled',
  id: 'toolu_018eiZUCt21zUYTGZ5C8Esau',
  outcome: 'ok',
  summary: '## Answer: 28 files',
  endedAt: '2026-08-07T14:44:11.166Z',
};

function setup() {
  (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
  invokeMock.mockImplementation((cmd: string, args?: Record<string, unknown>) => {
    if (cmd === 'list_conversations') return Promise.resolve([ROOM]);
    if (cmd === 'list_messages') return Promise.resolve([]);
    if (cmd === 'list_agents') return Promise.resolve([]);
    if (cmd === 'list_conversation_participants') return Promise.resolve([]);
    if (cmd === 'ai_status') {
      return Promise.resolve({
        provider: 'claude-cli', model: 'm', ready: true, detail: 'ok', governed: false,
      });
    }
    if (cmd === 'search_all') return Promise.resolve([]);
    if (cmd === 'post_user_message') {
      return Promise.resolve({
        id: 'm-1', conversationId: 'c-1', role: 'user', author: 'You',
        body: String(args?.body ?? ''), createdAt: '1700000000000', receipt: null,
      });
    }
    if (cmd === 'stream_reply') {
      const channel = args?.onEvent as { onmessage: ((e: unknown) => void) | null };
      emit = (frame) => channel.onmessage?.(frame);
      return Promise.resolve(null);
    }
    // The read-side command still does not exist. That is the honest backend today.
    if (cmd === 'list_delegations') {
      return Promise.reject(new Error('Command list_delegations not found'));
    }
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Chat />
      </ToastProvider>
    </AppProvider>,
  );
}

/** Open the thread and send a turn, so a `stream_reply` channel actually exists. */
async function talkToBro() {
  const composer = await screen.findByLabelText('Message, mention @agent…');
  fireEvent.change(composer, { target: { value: 'Count the files in tools/.' } });
  fireEvent.submit(composer.closest('form') as HTMLFormElement);
  await waitFor(() =>
    expect(invokeMock).toHaveBeenCalledWith('stream_reply', expect.anything()));
}

const cards = () => document.querySelectorAll('.dg-card');

beforeEach(() => { invokeMock.mockReset(); emit = () => {}; });
afterEach(() => { delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__; });

describe('a delegation reported on the live stream reaches the chat screen', () => {
  it('draws the card the backend actually described, and settles it', async () => {
    setup();
    await talkToBro();

    emit(SPAWNED);
    // Who, at which tier, on what — from the payload, not from anything invented here.
    await screen.findByText('reader');
    expect(screen.getByText('Count files in tools/')).toBeInTheDocument();
    expect(screen.getByText(STR.tierLabel.en)).toBeInTheDocument();
    for (const tool of ['Read', 'Grep', 'Glob']) {
      expect(screen.getByText(tool)).toBeInTheDocument();
    }
    // The grant, both halves, each labelled for what it actually is.
    expect(screen.getByText('tools')).toBeInTheDocument();
    expect(screen.getByText('.claude')).toBeInTheDocument();
    expect(screen.getByText(STR.capabilityEnforced.en)).toBeInTheDocument();
    expect(screen.getByText(STR.scopeUnenforced.en)).toBeInTheDocument();
    expect(screen.queryByText(STR.scopeEnforcedByEngine.en)).not.toBeInTheDocument();
    // In flight is not success.
    expect(screen.getByText(STR.outcomeRunning.en)).toBeInTheDocument();
    expect(document.querySelector('.dg-card .badge--success')).toBeNull();

    emit(SETTLED);
    await screen.findByText(STR.outcomeOk.en);
    expect(screen.getByText('## Answer: 28 files')).toBeInTheDocument();
    // One delegation, one card — the spawn and its settlement are the same row.
    expect(cards()).toHaveLength(1);
  });

  it('keeps saying the ledger is not stored, with live cards right above it', async () => {
    setup();
    await talkToBro();
    emit(SPAWNED);
    await screen.findByText('reader');

    // A live feed is not a history, and the surface must not start looking like one just
    // because a card finally appeared on it.
    expect(screen.getByText(SURFACE_STR.noLedgerTitle.en)).toBeInTheDocument();
    expect(screen.getByText(SURFACE_STR.noLedgerBody.en)).toBeInTheDocument();
    expect(screen.getByText(/Command list_delegations not found/)).toBeInTheDocument();
  });

  it('ignores an unknown event type instead of crashing or drawing it', async () => {
    setup();
    await talkToBro();

    // A variant a future backend adds, a spawn with no payload, and a frame with no `type` at
    // all. None may become a delegation, and none may break the turn the user is reading.
    emit({ type: 'somethingNew', delegation: { id: 'x', subagentType: 'builder', conversationId: 'c-1' } });
    emit({ type: 'delegationSpawned' });
    emit({ delegation: { id: 'y', subagentType: 'builder', conversationId: 'c-1' } });
    emit({ type: 'delta', text: 'still streaming' });
    emit(SPAWNED);

    // The stream survived every one of them and the real spawn still landed.
    await screen.findByText('reader');
    expect(cards()).toHaveLength(1);
    expect(screen.queryByText('builder')).not.toBeInTheDocument();
  });

  it('drops a settlement for an id it never saw spawned', async () => {
    setup();
    await talkToBro();

    // Every nested tool return the specialist makes arrives as a settlement too (evidence §6):
    // 13 of 14 in the real capture were the specialist's own Read/Grep output. Materialising a
    // card from an ending would draw a delegation carrying no grant at all.
    emit({
      type: 'delegationSettled', id: 'toolu_nested_read', outcome: 'ok',
      summary: 'the entire contents of CLAUDE.md', endedAt: '2026-08-07T14:43:40.000Z',
    });
    emit(SPAWNED);
    await screen.findByText('reader');
    expect(cards()).toHaveLength(1);
    expect(screen.queryByText('the entire contents of CLAUDE.md')).not.toBeInTheDocument();
  });

  it('files nothing under this conversation that the backend did not file there', async () => {
    setup();
    await talkToBro();

    // `stream_ask` emits `conversationId: null`; another thread's frame carries its own id.
    // Adopting either would tell the owner a specialist was given tools inside a chat where
    // that never happened.
    const spawn = SPAWNED.delegation as Record<string, unknown>;
    emit({ type: 'delegationSpawned', delegation: { ...spawn, id: 'a', conversationId: null } });
    emit({ type: 'delegationSpawned', delegation: { ...spawn, id: 'b', conversationId: 'c-9' } });
    // …and their settlements, which must then find no card to attach to.
    emit({ type: 'delegationSettled', id: 'a', outcome: 'ok', summary: 'one-shot', endedAt: 'x' });
    emit({ type: 'delegationSettled', id: 'b', outcome: 'ok', summary: 'other room', endedAt: 'x' });

    emit(SPAWNED);
    await screen.findByText('reader');
    expect(cards()).toHaveLength(1);
    expect(screen.queryByText('one-shot')).not.toBeInTheDocument();
    expect(screen.queryByText('other room')).not.toBeInTheDocument();
  });

  it('says capability is UNKNOWN when the backend omitted tools, and invents none', async () => {
    setup();
    await talkToBro();

    // `delegation_frame` omits `tools` AND `toolsSource` together when `delegation_tools`
    // resolved nothing — a CLI built-in such as `general-purpose` (evidence §7), which actually
    // holds `*`. The card must not fill that silence in.
    emit({
      type: 'delegationSpawned',
      delegation: {
        id: 'toolu_builtin', subagentType: 'general-purpose', conversationId: 'c-1',
        parent: 'Bro', startedAt: '2026-08-07T14:43:26.767Z',
        description: 'Look into it', grant: null,
      },
    });

    await screen.findByText('general-purpose');
    expect(screen.getByText(STR.capabilityUnknown.en)).toBeInTheDocument();
    expect(screen.queryByText(STR.capabilityEnforced.en)).not.toBeInTheDocument();
    expect(screen.getByText(STR.packRoleLabel.en)).toBeInTheDocument();
    // `grant: null` is a fact the backend stated, not a missing field to paper over.
    expect(screen.getByText(STR.grantNotStated.en)).toBeInTheDocument();
    expect(screen.queryByText(STR.mayTouch.en)).not.toBeInTheDocument();
  });

  it('shows a pack role file list without ever calling it enforced', async () => {
    setup();
    await talkToBro();

    // `ai.rs::ToolsSource::PackRoleFile`: the backend really read the role's `tools:` line, but
    // `--setting-sources ""` means that file bounded nothing on this run. Dropping the list
    // would hide capability the owner handed out; promoting it would claim an enforcement that
    // never happened.
    emit({
      type: 'delegationSpawned',
      delegation: {
        id: 'toolu_pack', subagentType: 'audit--verifier', conversationId: 'c-1',
        parent: 'Bro', startedAt: '2026-08-07T14:43:26.767Z',
        tools: ['Read', 'Grep', 'Bash'], toolsSource: 'pack_role_file', grant: null,
      },
    });

    await screen.findByText('audit--verifier');
    expect(screen.getByText('Bash')).toBeInTheDocument();
    expect(screen.getByText(SURFACE_STR.capabilityFromRoleFile.en)).toBeInTheDocument();
    expect(screen.queryByText(STR.capabilityEnforced.en)).not.toBeInTheDocument();
    expect(screen.queryByText(STR.capabilityUnknown.en)).not.toBeInTheDocument();
  });
});
