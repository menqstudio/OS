import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

// The group room's CONSENSUS deck rendered over a real transcript. The assertions
// that matter are the negative ones: a round is never shown as reached while anyone
// asked is still silent, and no outcome is ever rendered without its dissent.

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { GroupChat } from './GroupChat';
import { formatConsensusOpening } from './groupChatConsensus';
import { STR as GC_STR } from './GroupChat.strings';

const ROOM = {
  id: 'g-1', kind: 'group', title: 'Design room', messageCount: 4,
  lastMessageAt: '1700000000000', createdAt: '1700000000000', updatedAt: '1700000000000',
};
const agent = (slug: string, name: string) => ({
  id: slug, slug, displayName: name, role: 'specialist', status: 'active', model: null,
  createdAt: '1700000000000', updatedAt: '1700000000000',
});
const msg = (id: string, author: string, body: string, role = 'agent') => ({
  id, conversationId: 'g-1', role, author, body, createdAt: '1700000000000', receipt: null,
});

const OPEN_MAJORITY = formatConsensusOpening('Ship the redesign this week?', 'majority', ['Scout', 'Analyst', 'Gev']);
const OPEN_UNANIMOUS = formatConsensusOpening('Ship the redesign this week?', 'unanimous', ['Scout', 'Analyst']);

function setup(messages: ReturnType<typeof msg>[]) {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_conversations') return Promise.resolve([ROOM]);
    if (cmd === 'list_messages') return Promise.resolve(messages);
    if (cmd === 'list_agents') {
      return Promise.resolve([agent('scout', 'Scout'), agent('analyst', 'Analyst')]);
    }
    if (cmd === 'list_conversation_participants') return Promise.resolve(['Scout', 'Analyst']);
    if (cmd === 'ai_status') {
      return Promise.resolve({ provider: 'claude-cli', model: 'm', ready: true, detail: 'ok', governed: false });
    }
    if (cmd === 'search_all') return Promise.resolve([]);
    return Promise.resolve(null);
  });
  render(
    <AppProvider>
      <ToastProvider>
        <GroupChat />
      </ToastProvider>
    </AppProvider>,
  );
}

const deck = () => screen.findByRole('region', { name: 'CONSENSUS' });

beforeEach(() => invokeMock.mockReset());

describe('Group chat consensus deck', () => {
  it('states that no round has been opened rather than showing an empty verdict', async () => {
    setup([msg('m-1', 'Scout', 'morning')]);
    const d = await deck();
    expect(await within(d).findByText(/No consensus round has been opened/i)).toBeInTheDocument();
    expect(within(d).queryByText('CONSENSUS REACHED')).toBeNull();
  });

  it('holds the round OPEN while an asked participant is silent, even once the threshold is met', async () => {
    setup([
      msg('m-1', 'gev', OPEN_MAJORITY, 'user'),
      msg('m-2', 'Scout', 'POSITION: YES — the references are ready'),
      msg('m-3', 'Analyst', 'POSITION: YES — scoring is done'),
    ]);
    const d = await deck();

    // 2 of 3 YES clears a strict majority, but Gev has not answered.
    expect(await within(d).findByText('STILL OPEN')).toBeInTheDocument();
    expect(within(d).queryByText('CONSENSUS REACHED')).toBeNull();
    expect(within(d).getByText(/Silence is not agreement/i)).toBeInTheDocument();

    // The silent participant is named in the dissent block, not quietly dropped.
    const dissent = within(d).getByRole('list', { name: 'DISSENT' });
    expect(within(dissent).getByText('Gev')).toBeInTheDocument();
    expect(within(dissent).getByText('ASKED, NOT ANSWERED')).toBeInTheDocument();
  });

  it('shows the rule and the threshold that produced the verdict', async () => {
    setup([msg('m-1', 'gev', OPEN_MAJORITY, 'user')]);
    const d = await deck();
    expect(await within(d).findByText(/Rule: Majority · 2\/3 YES needed/)).toBeInTheDocument();
    expect(within(d).getByText(/everyone asked must answer/i)).toBeInTheDocument();
  });

  it('renders the dissent beside a REACHED outcome, never the outcome alone', async () => {
    setup([
      msg('m-1', 'gev', OPEN_MAJORITY, 'user'),
      msg('m-2', 'Scout', 'POSITION: YES — the references are ready'),
      msg('m-3', 'Analyst', 'POSITION: YES — scoring is done'),
      msg('m-4', 'Gev', 'POSITION: NO — the timeline is wrong', 'user'),
    ]);
    const d = await deck();
    expect(await within(d).findByText('CONSENSUS REACHED')).toBeInTheDocument();

    const dissent = within(d).getByRole('list', { name: 'DISSENT' });
    expect(within(dissent).getByText('Gev')).toBeInTheDocument();
    expect(within(dissent).getByText('the timeline is wrong')).toBeInTheDocument();
  });

  it('states plainly when there was no dissent, instead of leaving the block blank', async () => {
    setup([
      msg('m-1', 'gev', OPEN_UNANIMOUS, 'user'),
      msg('m-2', 'Scout', 'POSITION: YES — ready'),
      msg('m-3', 'Analyst', 'POSITION: YES — ready'),
    ]);
    const d = await deck();
    expect(await within(d).findByText('CONSENSUS REACHED')).toBeInTheDocument();
    const dissent = within(d).getByRole('list', { name: 'DISSENT' });
    expect(within(dissent).getByText(/Nobody recorded a NO and nobody abstained/i)).toBeInTheDocument();
  });

  it('does not reach a unanimous round over an abstention', async () => {
    setup([
      msg('m-1', 'gev', OPEN_UNANIMOUS, 'user'),
      msg('m-2', 'Scout', 'POSITION: YES — ready'),
      msg('m-3', 'Analyst', 'POSITION: ABSTAIN — I have no view'),
    ]);
    const d = await deck();
    expect(await within(d).findByText('NOT REACHED')).toBeInTheDocument();
    expect(within(d).queryByText('CONSENSUS REACHED')).toBeNull();
    const dissent = within(d).getByRole('list', { name: 'DISSENT' });
    expect(within(dissent).getByText('Analyst')).toBeInTheDocument();
    expect(within(dissent).getByText('I have no view')).toBeInTheDocument();
  });

  it('counts nothing from a malformed opening and reports it', async () => {
    setup([
      msg('m-1', 'gev', 'CONSENSUS OPEN\nquestion: ship it?\nrule: whatever\nasked: Scout', 'user'),
      msg('m-2', 'Scout', 'POSITION: YES — sure'),
    ]);
    const d = await deck();
    expect(await within(d).findByText(/this opened no round/i)).toBeInTheDocument();
    expect(within(d).getByText(/unknown rule/i)).toBeInTheDocument();
    expect(within(d).queryByText('CONSENSUS REACHED')).toBeNull();
  });

  it('shows a position from someone who was not asked without counting it', async () => {
    setup([
      msg('m-1', 'gev', OPEN_UNANIMOUS, 'user'),
      msg('m-2', 'Scout', 'POSITION: YES — ready'),
      msg('m-3', 'Analyst', 'POSITION: YES — ready'),
      msg('m-4', 'Drifter', 'POSITION: NO — I object'),
    ]);
    const d = await deck();
    expect(await within(d).findByText(/recorded, not counted/i)).toBeInTheDocument();
    expect(within(d).getByText(/Drifter/)).toBeInTheDocument();
    // The uncounted objection does not change the tally of the people who were asked.
    expect(within(d).getByText('CONSENSUS REACHED')).toBeInTheDocument();
  });
});

describe('GroupChat — a room created in the workspace appears in the deck beneath it', () => {
  // The deck read the room list once, on mount, and its copy tells the user to "create a room
  // above, then a consensus round can be opened in it". The room was created, the workspace
  // reloaded its own list, and the deck went on offering the rooms it had seen at mount.
  it('the deck\'s room selector gains the new room without a remount', async () => {
    const rooms = [{ ...ROOM }];
    invokeMock.mockImplementation((cmd: string, args?: Record<string, unknown>) => {
      if (cmd === 'list_conversations') return Promise.resolve(rooms.map((r) => ({ ...r })));
      if (cmd === 'create_conversation') {
        const made = { ...ROOM, id: 'g-2', title: String(args?.title ?? ''), messageCount: 0 };
        rooms.push(made);
        return Promise.resolve(made);
      }
      if (cmd === 'list_messages') return Promise.resolve([]);
      if (cmd === 'list_agents') return Promise.resolve([agent('scout', 'Scout'), agent('analyst', 'Analyst')]);
      if (cmd === 'list_conversation_participants') return Promise.resolve(['Scout', 'Analyst']);
      if (cmd === 'ai_status') {
        return Promise.resolve({ provider: 'claude-cli', model: 'm', ready: true, detail: 'ok', governed: false });
      }
      if (cmd === 'search_all') return Promise.resolve([]);
      return Promise.resolve(null);
    });
    render(<AppProvider><ToastProvider><GroupChat /></ToastProvider></AppProvider>);

    const d = await deck();
    const selector = () => within(d).getByRole('combobox', { name: 'Room' }) as HTMLSelectElement;
    await waitFor(() => expect(Array.from(selector().options).map((o) => o.text)).toEqual(['Design room']));

    fireEvent.click(screen.getByRole('button', { name: 'New' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'Fresh room' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith('create_conversation', expect.anything()));

    await waitFor(() =>
      expect(Array.from(selector().options).map((o) => o.text)).toEqual(['Design room', 'Fresh room']));
  });
});

describe('GroupChat — a position posted in the thread reaches the deck', () => {
  // The deck and the thread each read the room's messages on their own. A POSITION typed into the
  // thread was stored, shown in the thread, and never counted by the deck under it until the page
  // was left and re-entered.
  it('the deck counts a position the moment the thread has posted it', async () => {
    const log = [msg('m-1', 'gev', formatConsensusOpening('Ship it?', 'unanimous', ['gev']), 'user')];
    invokeMock.mockImplementation((cmd: string, args?: Record<string, unknown>) => {
      if (cmd === 'list_conversations') return Promise.resolve([ROOM]);
      if (cmd === 'list_messages') return Promise.resolve(log.map((m) => ({ ...m })));
      if (cmd === 'post_user_message') {
        const made = msg(`m-${log.length + 1}`, String(args?.author ?? 'gev'), String(args?.body ?? ''), 'user');
        log.push(made);
        return Promise.resolve(made);
      }
      if (cmd === 'list_agents') return Promise.resolve([agent('scout', 'Scout'), agent('analyst', 'Analyst')]);
      if (cmd === 'list_conversation_participants') return Promise.resolve(['Scout', 'Analyst']);
      if (cmd === 'ai_status') {
        return Promise.resolve({ provider: 'claude-cli', model: 'm', ready: true, detail: 'ok', governed: false });
      }
      if (cmd === 'search_all') return Promise.resolve([]);
      if (cmd === 'stream_reply') return new Promise(() => {});
      return Promise.resolve(null);
    });
    render(<AppProvider><ToastProvider><GroupChat /></ToastProvider></AppProvider>);

    const d = await deck();
    await within(d).findByText('Ship it?');
    expect(within(d).queryByText('CONSENSUS REACHED')).toBeNull();

    const composer = document.querySelector('form.composer')!;
    const field = composer.querySelector('textarea, input') as HTMLTextAreaElement;
    fireEvent.change(field, { target: { value: 'POSITION: YES — ready' } });
    fireEvent.submit(composer);
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith('post_user_message', expect.anything()));

    await waitFor(() => expect(within(d).getByText('CONSENSUS REACHED')).toBeInTheDocument());
  });
});

describe('GroupChat — a round the deck opens appears in the thread above it', () => {
  // The other direction of the same seam. The deck posts the opening message into the room; the
  // thread had read the room once and went on showing a transcript without it.
  it('the opening the deck posted is in the thread without a remount', async () => {
    const log: ReturnType<typeof msg>[] = [];
    invokeMock.mockImplementation((cmd: string, args?: Record<string, unknown>) => {
      if (cmd === 'list_conversations') return Promise.resolve([ROOM]);
      if (cmd === 'list_messages') return Promise.resolve(log.map((m) => ({ ...m })));
      if (cmd === 'post_user_message') {
        const made = msg(`m-${log.length + 1}`, String(args?.author ?? 'gev'), String(args?.body ?? ''), 'user');
        log.push(made);
        return Promise.resolve(made);
      }
      if (cmd === 'list_agents') return Promise.resolve([agent('scout', 'Scout'), agent('analyst', 'Analyst')]);
      if (cmd === 'list_conversation_participants') return Promise.resolve(['Scout', 'Analyst']);
      if (cmd === 'ai_status') {
        return Promise.resolve({ provider: 'claude-cli', model: 'm', ready: true, detail: 'ok', governed: false });
      }
      if (cmd === 'search_all') return Promise.resolve([]);
      return Promise.resolve(null);
    });
    render(<AppProvider><ToastProvider><GroupChat /></ToastProvider></AppProvider>);
    await deck();
    const thread = () => document.querySelector('.chat-canvas')!;
    await waitFor(() => expect(thread()).not.toBeNull());
    expect(thread().textContent).not.toContain('Does the deck reach the thread');

    fireEvent.change(await screen.findByLabelText(GC_STR.questionLabel.en), {
      target: { value: 'Does the deck reach the thread' },
    });
    const open = await screen.findByRole('button', { name: GC_STR.openRound.en });
    await waitFor(() => expect(open).toBeEnabled());
    fireEvent.click(open);
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith('post_user_message', expect.anything()));

    await waitFor(() => expect(thread().textContent).toContain('Does the deck reach the thread'));
  });
});
