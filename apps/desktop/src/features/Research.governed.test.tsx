import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';

// The IPC boundary. `stream_ask` is a CHANNEL command: the Rust side pushes events, so the mock
// has to hand the caller's channel back to the test rather than resolve a value.
const invokeMock = vi.fn();
let lastChannel: { onmessage?: (e: unknown) => void } | null = null;
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (cmd: string, args?: Record<string, unknown>) => {
    if (args && typeof args === 'object' && 'onEvent' in args) {
      lastChannel = args.onEvent as { onmessage?: (e: unknown) => void };
    }
    return invokeMock(cmd, args);
  },
  Channel: class { onmessage: ((e: unknown) => void) | null = null; },
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Research } from './Research';

const ITEM = {
  id: 'rs-1',
  title: 'Where does the anchor live',
  question: 'Which principal owns the anti-rollback floor?',
  findings: '',
  status: 'open',
  createdAt: '1700000000000',
  updatedAt: '1700000000000',
};

/**
 * §D `research`: "run status (governed — with verified-receipt badge) … `blocked`(governed
 * provider off/sidecar down → no result)".
 *
 * None of it existed. This page was a local CRUD list with no run, no receipt and no refusal —
 * the one page in Phase 5 whose entire point is that it crosses the wall.
 *
 * The run goes through `stream_ask`, the same governed path chat uses: buffered, verified
 * desktop-side, and the answer HELD server-side under a one-time id rather than streamed into
 * the window. That is why saving is a backend command taking the id: the window never receives
 * the text, so it cannot save something the engine did not produce.
 */
function emit(ev: unknown) {
  act(() => { lastChannel?.onmessage?.(ev); });
}

async function openRecord() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_research') return Promise.resolve([ITEM]);
    if (cmd === 'stream_ask') return new Promise(() => {});   // settles via the channel
    if (cmd === 'save_ask_to_knowledge') {
      return Promise.resolve({ id: 'k-1', title: ITEM.title, body: 'held body', source: '', tags: '' });
    }
    return Promise.resolve(null);
  });
  render(<AppProvider><ToastProvider><Research /></ToastProvider></AppProvider>);
  fireEvent.click(await screen.findByRole('option', { name: new RegExp(ITEM.title) }));
  return await screen.findByRole('button', { name: /Run this question/ });
}

beforeEach(() => { invokeMock.mockReset(); lastChannel = null; });

describe('Research — the run goes through the governed wall', () => {
  it('runs the record’s question through stream_ask, not a local shortcut', async () => {
    fireEvent.click(await openRecord());
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith(
      'stream_ask', expect.objectContaining({ prompt: ITEM.question }),
    ));
  });

  it('a REFUSAL renders as a refusal, with the engine reason and no result', async () => {
    fireEvent.click(await openRecord());
    emit({ type: 'blocked', reason: 'governed_verification_unconfigured' });

    const alert = await screen.findByRole('alert');
    expect(alert.className).toContain('rsx-run-out--blocked');
    expect(alert.textContent).toContain('governed_verification_unconfigured');
    // Nothing to save: a refusal produced no held answer, so the save action must not exist.
    expect(screen.queryByRole('button', { name: /Save to knowledge/ })).toBeNull();
  });

  it('a FAILURE is not dressed up as a refusal', async () => {
    fireEvent.click(await openRecord());
    emit({ type: 'error', message: 'connection reset by peer' });
    const alert = await screen.findByRole('alert');
    expect(alert.className).toContain('rsx-run-out--failed');
    expect(alert.className).not.toContain('rsx-run-out--blocked');
  });

  it('a verified answer is HELD, and saving passes the id — never a body', async () => {
    fireEvent.click(await openRecord());
    emit({ type: 'ready', resultId: 'one-time-42' });

    fireEvent.click(await screen.findByRole('button', { name: /Save to knowledge/ }));
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith(
      'save_ask_to_knowledge', { resultId: 'one-time-42', title: ITEM.title },
    ));
    // The whole point of the held-answer design: no call from this window ever carries the text.
    for (const [, args] of invokeMock.mock.calls) {
      expect(JSON.stringify(args ?? {})).not.toContain('held body');
    }
    expect(await screen.findByText(/Saved to knowledge/)).toBeInTheDocument();
  });

  it('deltas are ignored — a governed ask is buffered, and unverified text is not shown', async () => {
    fireEvent.click(await openRecord());
    emit({ type: 'delta', text: 'PARTIAL UNVERIFIED TEXT' });
    expect(screen.queryByText(/PARTIAL UNVERIFIED TEXT/)).toBeNull();
  });

  it('selecting another record clears the held id', async () => {
    // Otherwise saving would file one question's answer under another question's title.
    const second = { ...ITEM, id: 'rs-2', title: 'A different question', question: 'And this one?' };
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'list_research') return Promise.resolve([ITEM, second]);
      if (cmd === 'stream_ask') return new Promise(() => {});
      return Promise.resolve(null);
    });
    render(<AppProvider><ToastProvider><Research /></ToastProvider></AppProvider>);
    fireEvent.click(await screen.findByRole('option', { name: new RegExp(ITEM.title) }));
    fireEvent.click(await screen.findByRole('button', { name: /Run this question/ }));
    emit({ type: 'ready', resultId: 'one-time-42' });
    expect(await screen.findByRole('button', { name: /Save to knowledge/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('option', { name: new RegExp(second.title) }));
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /Save to knowledge/ })).toBeNull());
  });
});

// The section's keymap skipped only INPUT/TEXTAREA/SELECT, so Enter on the focused "Save to
// knowledge" button bubbled, was prevented, and ran `start()`: the held id was dropped and a NEW
// model call was issued instead of the save.
describe('Research — Enter on a button is that button\'s own', () => {
  it('Enter on the focused Save button does not re-run the question', async () => {
    fireEvent.click(await openRecord());
    emit({ type: 'ready', resultId: 'one-time-42', provenance: 'development_untrusted' });
    const save = await screen.findByRole('button', { name: /Save to knowledge/ });
    const asks = () => invokeMock.mock.calls.filter((c) => c[0] === 'stream_ask').length;
    expect(asks()).toBe(1);

    save.focus();
    const notPrevented = fireEvent.keyDown(save, { key: 'Enter' });

    expect(notPrevented).toBe(true);
    expect(asks()).toBe(1);
    // The held answer is still there to be saved.
    expect(screen.getByRole('button', { name: /Save to knowledge/ })).toBeInTheDocument();
  });
});

// The panel was titled "GOVERNED RUN" and its hint said "The question goes through the governed
// turn — the same path chat uses", unconditionally. `stream_ask` takes the governed path only
// when the resolved provider is the governed engine; with no provider configured it sends
// `error` before any turn exists.
describe('Research — the run panel does not promise a governed path', () => {
  it('names the action, and says the configured provider decides the path', async () => {
    await openRecord();
    const panel = screen.getByRole('region', { name: 'RUN THE QUESTION' });
    expect(panel).toHaveTextContent(/The configured provider decides the path/);
    expect(panel).not.toHaveTextContent(/goes through the governed turn/);
    expect(screen.queryByText('GOVERNED RUN')).not.toBeInTheDocument();
  });

  it('no provider configured renders the failure with the backend message — not a refusal', async () => {
    fireEvent.click(await openRecord());
    emit({ type: 'error', message: 'no AI provider configured: set BROPS_AI_PROVIDER=governed-engine' });
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('The run failed');
    expect(alert).toHaveTextContent(/no AI provider configured/);
    expect(alert).not.toHaveTextContent(/Refused at the governed wall/);
  });
});

// `delete_research_item` cannot delete: the capability set denies it and the handler returns
// `forbidden_hard_delete` unconditionally. The dialog used to say "This permanently removes the
// record."
describe('Research — the delete dialog does not promise a delete', () => {
  it('says nothing will be removed, and names a policy refusal as permanent', async () => {
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'list_research') return Promise.resolve([ITEM]);
      if (cmd === 'delete_research_item') {
        return Promise.reject(new Error('delete_research_item not allowed. Permissions associated with this command: '));
      }
      return Promise.resolve(null);
    });
    render(<AppProvider><ToastProvider><Research /></ToastProvider></AppProvider>);
    fireEvent.click(await screen.findByRole('option', { name: new RegExp(ITEM.title) }));
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent(/Nothing will be removed/);
    expect(dialog).not.toHaveTextContent(/permanently removes/i);

    const confirm = Array.from(dialog.querySelectorAll('button')).find((b) => b.className.includes('danger'));
    fireEvent.click(confirm as HTMLButtonElement);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/standing policy refusal.*retrying cannot succeed/i);
    expect(alert).toHaveTextContent(/delete_research_item not allowed/);
    // The record is still listed.
    expect(screen.getAllByText(ITEM.title).length).toBeGreaterThan(0);
  });
});
