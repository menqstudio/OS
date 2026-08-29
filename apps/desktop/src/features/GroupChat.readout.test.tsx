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

  // THIS TEST USED TO ASSERT THE DEFECT — sixth independent audit, `A-07`.
  //
  // It read *"an empty roster is also not established, rather than zero participants"* and passed,
  // because `RoomReadout` tested `roster.length > 0` — truthiness on a length, one line above a
  // `messageCount === null` that was already correct. The auditor measured both halves with the
  // real component: a roster read that SUCCEEDS returning `[]` and one that REJECTS rendered the
  // same em dash, so an empty room and an unreadable one were indistinguishable.
  //
  // Two facts got swapped. A read that succeeded and returned nothing is a MEASURED ZERO — the
  // sibling test below already says so for messages, in the same file, three cases down. Encoding
  // the inverse here is how a defect survives a suite written to prevent it.
  it('an empty roster that was READ is zero participants, not "not established"', async () => {
    mount({ roster: [] });
    // Settle on a value that DOES arrive, so this is not passing on first paint — before the
    // reads resolve every cell reads "—" and the assertion would be vacuous.
    await waitFor(() => expect(valueFor(/MESSAGE/i)).toBe('2'));
    expect(valueFor(/PARTICIPANT/i)).toBe('0');
  });

  it('a roster read that FAILS is not established, and is not zero either', async () => {
    // The other side of the pair, which nothing tested. This is the case the em dash is for.
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'list_conversations') return Promise.resolve([ROOM]);
      if (cmd === 'list_conversation_participants') {
        const rejected = Promise.reject(new Error('roster_unreadable'));
        rejected.catch(() => {});
        return rejected;
      }
      if (cmd === 'list_messages') return Promise.resolve([{
        id: 'm1', conversationId: 'g-1', role: 'user', author: 'Gev', body: 'start', createdAt: '1',
      }]);
      return Promise.resolve([]);
    });
    render(<AppProvider><ToastProvider><GroupChat /></ToastProvider></AppProvider>);
    await waitFor(() => expect(valueFor(/MESSAGE/i)).toBe('1'));
    expect(valueFor(/PARTICIPANT/i)).toBe('—');
    expect(valueFor(/PARTICIPANT/i)).not.toBe('0');
  });

  it('a failed message read does not leave Messages and Rounds stating a measured zero', async () => {
    // `useAsync` never clears `data` on error, so before this fix the caller's null guard held
    // only on the very FIRST load: after any failed refresh both figures reported a count for a
    // read that had failed. Here the very first read fails, which is the case the old guard did
    // cover — and the assertion below is that BOTH cells refuse, not just Messages.
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'list_conversations') return Promise.resolve([ROOM]);
      if (cmd === 'list_conversation_participants') return Promise.resolve(['Bro', 'Auditor']);
      if (cmd === 'list_messages') {
        const rejected = Promise.reject(new Error('messages_unreadable'));
        rejected.catch(() => {});
        return rejected;
      }
      return Promise.resolve([]);
    });
    render(<AppProvider><ToastProvider><GroupChat /></ToastProvider></AppProvider>);
    await waitFor(() => expect(valueFor(/PARTICIPANT/i)).toBe('2'));
    expect(valueFor(/MESSAGE/i)).toBe('—');
    expect(valueFor(/ROUND|ՇՐՋԱՆ|РАУНД/i)).toBe('—');
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

  it('`T-040`: the raised asyncUtilTimeout is actually in force', async () => {
    // Deterministic, and it deliberately touches no product code: `configure({ asyncUtilTimeout })`
    // in `src/test/setup.ts` is a global whose effect is otherwise only visible as the ABSENCE of a
    // flake, which is not something a test can assert. This one waits for a value that appears at
    // 1 500 ms — past the 1000 ms default, inside the 5 000 ms ceiling. Revert the `configure` call
    // and it fails in 1 second with `Unable to find`, which is exactly the failure `T-040` is about.
    const host = document.createElement('div');
    host.setAttribute('data-testid', 't040-late');
    document.body.appendChild(host);
    setTimeout(() => { host.textContent = 'arrived'; }, 1_500);
    try {
      await waitFor(() => expect(host).toHaveTextContent('arrived'));
    } finally {
      host.remove();
    }
  });

  it('the readout arrives well inside the isolated budget — `T-040`', async () => {
    // The guard for the timeout `T-040` raised. `asyncUtilTimeout` went from 1000 ms to 5000 ms
    // because the value takes **200 ms** to arrive in isolation and a 5x margin does not survive a
    // full run of 80 files — this test failed three times in five. Waiting longer hides nothing a
    // broken test would have shown, but it COULD hide a real slowdown behind a generous ceiling.
    //
    // So the isolated latency is pinned here, where "fast" is measurable at all: 1000 ms is five
    // times the observed figure and still well under the raised ceiling, so a genuine regression
    // fails this even while the rest of the suite goes on tolerating a loaded machine. If this ever
    // goes red, the answer is not a bigger number — it is that the readout got slow.
    const started = performance.now();
    mount();
    await waitFor(() => expect(valueFor(/PARTICIPANT/i)).toBe('3'), { timeout: 1_000 });
    const elapsed = performance.now() - started;
    expect(elapsed, `the readout took ${elapsed.toFixed(0)} ms with nothing else running; `
      + 'it was 200 ms when the budget was set').toBeLessThan(1_000);
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
