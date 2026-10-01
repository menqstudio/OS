import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';

// The `trusted_verified` → green "Verified" badge path is LIVE code, but the backend
// never emits that string today: the production trust gate is fail-closed. The mapping
// is unit-tested in Conversations.test.tsx; this spec locks the rendered consequence —
// with the receipt the backend actually sends (null), nothing on screen reads as
// verified. A regression that painted the badge by default would fail here.
//
// It also pins the two non-production receipts to their own badges, so demonstration
// custody can never be mistaken for the production green.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Conversations } from './Conversations';

const ROOM = {
  id: 'c-1', kind: 'direct', title: 'Bro', messageCount: 2,
  lastMessageAt: '1700000000000', createdAt: '1700000000000', updatedAt: '1700000000000',
};

const msg = (id: string, receipt: string | null) => ({
  id,
  conversationId: 'c-1',
  role: 'agent',
  author: 'Bro',
  body: `reply ${id}`,
  createdAt: '1700000000000',
  receipt,
});

function setup(messages: ReturnType<typeof msg>[]) {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_conversations') return Promise.resolve([ROOM]);
    if (cmd === 'list_messages') return Promise.resolve(messages);
    if (cmd === 'list_agents') return Promise.resolve([]);
    if (cmd === 'list_conversation_participants') return Promise.resolve([]);
    if (cmd === 'ai_status') {
      return Promise.resolve({ provider: 'claude-cli', model: 'm', ready: true, detail: 'ok', governed: false });
    }
    if (cmd === 'search_all') return Promise.resolve([]);
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

async function openTheRoom(body: string) {
  fireEvent.click((await screen.findAllByText('Bro'))[0]);
  await waitFor(() => expect(screen.getByText(body)).toBeInTheDocument());
}

// Rendering a whole feature page under jsdom can exceed the 5s default on a loaded
// machine. The assertions below are about honesty, not speed — give them room so a
// slow environment cannot be mistaken for a regression.
vi.setConfig({ testTimeout: 30000 });

beforeEach(() => invokeMock.mockReset());

describe('Chat — nothing renders as Verified without a trusted_verified receipt', () => {
  it('shows NO trust badge for the null receipt the backend actually sends', async () => {
    setup([msg('m-1', null)]);
    await openTheRoom('reply m-1');

    expect(screen.queryByText('Verified')).not.toBeInTheDocument();
    expect(screen.queryByText('Verified · demo')).not.toBeInTheDocument();
    // No badge element at all on the turn.
    expect(document.querySelector('.turn .badge')).toBeNull();
  });

  it('shows NO Verified badge for an unrecognised receipt value (fails closed)', async () => {
    setup([msg('m-1', 'something_new_from_the_backend')]);
    await openTheRoom('reply m-1');

    expect(screen.queryByText('Verified')).not.toBeInTheDocument();
    expect(document.querySelector('.turn .badge')).toBeNull();
  });

  it('renders the AMBER dev badge — not the green one — for development_untrusted', async () => {
    setup([msg('m-1', 'development_untrusted')]);
    await openTheRoom('reply m-1');

    expect(screen.queryByText('Verified')).not.toBeInTheDocument();
    expect(document.querySelector('.turn .badge--warning')).not.toBeNull();
    expect(document.querySelector('.turn .badge--success')).toBeNull();
  });

  it('renders demonstration custody as its OWN badge, never the production green', async () => {
    setup([msg('m-1', 'demonstration_verified')]);
    await openTheRoom('reply m-1');

    expect(screen.getByText('Verified · demo')).toBeInTheDocument();
    // The production wording and the success tone are both absent.
    expect(screen.queryByText('Verified')).not.toBeInTheDocument();
    expect(document.querySelector('.turn .badge--success')).toBeNull();
  });

  // `demonstration_custody` is the label a COMMITTED governed row carries when every chain and
  // manifest check passed but the anchor that vouched for the signing key is kit-generated or the
  // compiled-in demonstration key (production_trust.rs). The turn is real; the custody claim is
  // not. Both ways of getting this wrong are asserted below.
  it('renders a committed demonstration_custody row with the demo badge, not the production green', async () => {
    setup([msg('m-1', 'demonstration_custody')]);
    await openTheRoom('reply m-1');

    expect(screen.getByText('Verified · demo')).toBeInTheDocument();
    expect(screen.queryByText('Verified')).not.toBeInTheDocument();
    expect(document.querySelector('.turn .badge--success')).toBeNull();
  });

  it('does NOT render a demonstration_custody turn as nothing (the chain really ran)', async () => {
    setup([msg('m-1', 'demonstration_custody')]);
    await openTheRoom('reply m-1');

    // A badge is present on the turn — silence would erase the evidence that a governed
    // chain produced this body.
    expect(document.querySelector('.turn .badge')).not.toBeNull();
    expect(document.querySelector('.turn .badge--info')).not.toBeNull();
  });

  // Both committed trust states on screen at once: the ONLY row wearing the production green is
  // the one whose committed row genuinely says `trusted_verified`.
  it('separates the two committed trust states side by side', async () => {
    setup([msg('m-1', 'trusted_verified'), msg('m-2', 'demonstration_custody')]);
    await openTheRoom('reply m-1');
    await waitFor(() => expect(screen.getByText('reply m-2')).toBeInTheDocument());

    expect(document.querySelectorAll('.turn .badge--success')).toHaveLength(1);
    expect(document.querySelectorAll('.turn .badge--info')).toHaveLength(1);
    expect(screen.getByText('Verified')).toBeInTheDocument();
    expect(screen.getByText('Verified · demo')).toBeInTheDocument();
  });
});

// ── Stop, then send again ────────────────────────────────────────────────────────────────
//
// One shared `cancelledRef` boolean said whether "the" turn was cancelled. Stop set it; the next
// send() cleared it — while the STOPPED turn's stream was still pending. So when that old stream
// finally settled, its `finally` saw "not cancelled", switched off `thinking`, wiped the streamed
// text and drained the queue, all underneath the turn that had replaced it.
describe('Chat — a stopped turn that finishes late leaves the next turn alone', () => {
  it('does not switch off the running turn, and its late text does not leak into it', async () => {
    const streams: Array<{ finish: () => void; channel: { onmessage?: (e: unknown) => void } }> = [];
    invokeMock.mockImplementation((cmd: string, args?: Record<string, unknown>) => {
      if (cmd === 'list_conversations') return Promise.resolve([ROOM]);
      if (cmd === 'list_messages') return Promise.resolve([msg('m-1', null)]);
      if (cmd === 'list_agents') return Promise.resolve([]);
      if (cmd === 'list_conversation_participants') return Promise.resolve([]);
      if (cmd === 'ai_status') {
        return Promise.resolve({ provider: 'claude-cli', model: 'm', ready: true, detail: 'ok', governed: false });
      }
      if (cmd === 'search_all') return Promise.resolve([]);
      if (cmd === 'post_user_message') {
        return Promise.resolve({
          id: `u-${String(args?.body)}`, conversationId: 'c-1', role: 'user', author: 'gev',
          body: String(args?.body ?? ''), createdAt: '1700000000000', receipt: null,
        });
      }
      if (cmd === 'stream_reply') {
        return new Promise<null>((res) => {
          streams.push({
            finish: () => res(null),
            channel: args?.onEvent as { onmessage?: (e: unknown) => void },
          });
        });
      }
      return Promise.resolve(null);
    });
    render(<AppProvider><ToastProvider><Conversations kind="direct" /></ToastProvider></AppProvider>);
    await openTheRoom('reply m-1');

    const composer = screen.getByLabelText('Message, mention @agent…');
    const sendIt = async (text: string) => {
      fireEvent.change(composer, { target: { value: text } });
      fireEvent.submit(composer.closest('form') as HTMLFormElement);
    };

    await sendIt('first');
    await waitFor(() => expect(streams).toHaveLength(1));
    fireEvent.click(await screen.findByRole('button', { name: 'Stop' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument());

    await sendIt('second');
    await waitFor(() => expect(streams).toHaveLength(2));
    await screen.findByRole('button', { name: 'Stop' });

    // The STOPPED turn's stream now delivers a late delta and settles.
    await act(async () => {
      streams[0].channel.onmessage?.({ type: 'delta', text: 'STALE TEXT FROM THE STOPPED TURN' });
      streams[0].finish();
      await Promise.resolve();
    });
    await new Promise((r) => setTimeout(r, 30));

    // The second turn is still running: Stop is still the primary action…
    expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send' })).not.toBeInTheDocument();
    // …and the stopped turn's text is not in its stream.
    expect(screen.queryByText(/STALE TEXT FROM THE STOPPED TURN/)).not.toBeInTheDocument();
    // Only two streams were ever started: the old turn did not go on to another responder.
    expect(streams).toHaveLength(2);
  });
});

// `createConversation` had no `.catch` at all. A rejection was an unhandled promise, and the New
// button did nothing and said nothing.
describe('Chat — a conversation the backend did not create is reported', () => {
  it('shows the backend reason instead of doing nothing', async () => {
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'list_conversations') return Promise.resolve([ROOM]);
      if (cmd === 'list_messages') return Promise.resolve([msg('m-1', null)]);
      if (cmd === 'create_conversation') return Promise.reject(new Error('database is locked'));
      if (cmd === 'ai_status') {
        return Promise.resolve({ provider: 'claude-cli', model: 'm', ready: true, detail: 'ok', governed: false });
      }
      if (cmd === 'list_agents' || cmd === 'list_conversation_participants' || cmd === 'search_all') {
        return Promise.resolve([]);
      }
      return Promise.resolve(null);
    });
    render(<AppProvider><ToastProvider><Conversations kind="direct" /></ToastProvider></AppProvider>);
    await openTheRoom('reply m-1');

    fireEvent.click(screen.getByRole('button', { name: 'New' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Conversation not created');
    expect(alert).toHaveTextContent('database is locked');
  });
});

// The delete control is hard-disabled until T-011. It carried an onClick that staged a confirm
// dialog with a delete handler, busy state and a "delete refused" panel behind it — a flow a
// disabled button cannot reach, described in the source as "the expected path".
describe('Chat — delete stays parked: disabled, with its reason, wired to nothing', () => {
  it('offers no dialog and never calls delete_conversation', async () => {
    setup([msg('m-1', null)]);
    await openTheRoom('reply m-1');
    const del = document.querySelector('.chat-item-action--danger') as HTMLButtonElement;
    expect(del).not.toBeNull();
    expect(del).toBeDisabled();
    expect(del.getAttribute('title')).toMatch(/disabled for safety/);
    fireEvent.click(del);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(invokeMock.mock.calls.some((c) => c[0] === 'delete_conversation')).toBe(false);
  });

  it('the page carries no delete call at all', async () => {
    const { readFileSync } = await import('node:fs');
    const { resolve } = await import('node:path');
    const src = readFileSync(resolve(process.cwd(), 'src/features/Conversations.tsx'), 'utf8');
    expect(src).not.toMatch(/\.deleteConversation\s*\(/);
  });
});
