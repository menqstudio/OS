import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

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
