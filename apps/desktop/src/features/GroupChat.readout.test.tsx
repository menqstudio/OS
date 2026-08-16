import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (cmd: string, args?: unknown) => invokeMock(cmd, args),
  Channel: class { onmessage: unknown = null; },
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { GroupChat } from './GroupChat';

/**
 * §D's room readout — *"consensus readout (participants/handoffs/messages/consensus %)"* and
 * `grpElapsed` in the room header. The consensus machinery existed in full; the readout did not.
 *
 * The property worth testing is not that five numbers appear. It is that **"nothing happened" and
 * "this is not observable from here" are told apart.** The delegation trail arrives on the LIVE
 * event channel while a turn runs and cannot be reconstructed from stored messages, so a room the
 * owner has merely opened must not report `0 handoffs` — that states a fact the page cannot know.
 */
const ROOM = {
  id: 'g-1', kind: 'group', title: 'Boundary review',
  createdAt: String(Date.now() - 3 * 60 * 60 * 1000),   // three hours ago
  updatedAt: String(Date.now()),
};

function mount(over: Record<string, unknown> = {}) {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_conversations') return Promise.resolve([ROOM]);
    if (cmd === 'list_conversation_participants') {
      return Promise.resolve((over.roster as string[] | undefined) ?? ['Bro', 'Auditor', 'Builder']);
    }
    if (cmd === 'list_messages') return Promise.resolve(over.messages ?? [
      { id: 'm1', conversationId: 'g-1', role: 'user', author: 'Gev', body: 'start', createdAt: '1' },
      { id: 'm2', conversationId: 'g-1', role: 'agent', author: 'Bro', body: 'ack', createdAt: '2' },
    ]);
    if (cmd === 'list_agents') return Promise.resolve([]);
    return Promise.resolve([]);
  });
  return render(<AppProvider><ToastProvider><GroupChat /></ToastProvider></AppProvider>);
}

const readout = () => screen.getByRole('group', { name: /room readout|սրահի|сводка/i })
  ?? screen.getByLabelText(/room readout/i);

/** The value cell that follows a given label, by walking the description list. */
function valueFor(label: RegExp): string {
  const dl = screen.getByLabelText(/room readout|սրահի|сводка/i);
  for (const cell of Array.from(dl.querySelectorAll('.cs-readout-cell'))) {
    const dt = cell.querySelector('dt')?.textContent ?? '';
    if (label.test(dt)) return cell.querySelector('dd')?.textContent ?? '';
  }
  return '(label not found)';
}

beforeEach(() => invokeMock.mockReset());

describe('GroupChat — the room readout counts only what it can establish', () => {
  it('reports the participants and messages it actually read', async () => {
    mount();
    // Wait for the VALUE, not for the shell: the readout renders as soon as the room is known,
    // and the roster/message reads land after it. Asserting on first paint would be asserting
    // that the reads had not finished yet.
    await waitFor(() => expect(valueFor(/PARTICIPANT/i)).toBe('3'));
    expect(valueFor(/MESSAGE/i)).toBe('2');
  });

  it('reports handoffs as NOT ESTABLISHED, not as zero', async () => {
    // The whole point. The delegation trail is live-channel only; a stored room cannot be read
    // for it. `0` would state "no handoffs happened" while meaning "I cannot see handoffs".
    mount();
    await waitFor(() => expect(valueFor(/PARTICIPANT/i)).toBe('3'));
    expect(valueFor(/HANDOFF/i)).toBe('—');
    expect(valueFor(/HANDOFF/i)).not.toBe('0');
  });

  it('an empty roster is also not established, rather than zero participants', async () => {
    mount({ roster: [] });
    // Settle on a value that DOES arrive, so this is not passing on first paint — before the
    // roster read resolves, every cell reads "—" and the assertion would be vacuous.
    await waitFor(() => expect(valueFor(/MESSAGE/i)).toBe('2'));
    expect(valueFor(/PARTICIPANT/i)).toBe('—');
  });

  it('a room with no messages reports zero, because that IS established', async () => {
    // The other half of the distinction: a read that succeeded and returned nothing is a real
    // zero, and flattening it to "—" would be the same failure in the other direction.
    mount({ messages: [] });
    await waitFor(() => expect(valueFor(/PARTICIPANT/i)).toBe('3'));
    expect(valueFor(/MESSAGE/i)).toBe('0');
  });

  it('elapsed is coarse and derived from the room’s own createdAt', async () => {
    mount();
    await waitFor(() => expect(valueFor(/PARTICIPANT/i)).toBe('3'));
    expect(valueFor(/OPEN FOR|ԲԱՑ|ОТКРЫТА/i)).toMatch(/^3h \d+m$/);
  });

  it('a room with an unreadable createdAt says so instead of showing a wrong duration', async () => {
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'list_conversations') return Promise.resolve([{ ...ROOM, createdAt: 'not-a-time' }]);
      if (cmd === 'list_conversation_participants') return Promise.resolve(['Bro']);
      if (cmd === 'list_messages') return Promise.resolve([]);
      return Promise.resolve([]);
    });
    render(<AppProvider><ToastProvider><GroupChat /></ToastProvider></AppProvider>);
    await waitFor(() => expect(screen.getByLabelText(/room readout/i)).toBeInTheDocument());
    expect(valueFor(/OPEN FOR|ԲԱՑ|ОТКРЫТА/i)).toBe('—');
  });

  it('the readout is a labelled description list, not five loose numbers', async () => {
    mount();
    const dl = await screen.findByLabelText(/room readout/i);
    expect(dl.tagName).toBe('DL');
    // Every figure is paired with its term, so a screen reader never reads a bare number.
    expect(within(dl).getAllByRole('term').length).toBe(within(dl).getAllByRole('definition').length);
    void readout;
  });
});
