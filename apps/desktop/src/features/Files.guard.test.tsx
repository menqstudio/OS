import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (cmd: string, args?: unknown) => invokeMock(cmd, args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Files } from './Files';
import { isGuardDenied } from './filesModel';

/**
 * Phase 5: *"Files honor engine guard states (open/read/sealed); no unlawful open"*, and the
 * phase's merge gate says **files guard proven**.
 *
 * It was implemented and untested. `Files.test.tsx` covered the listing mirror and that browsing
 * issues no `read_file` — both worth having, neither touching the guard. The state that matters
 * most on this page is the one where the engine says **no**, and nothing asserted what happens
 * then. A guard nobody tests is a guard that has never been shown to hold.
 */
const LISTING = {
  path: '/home/gev',
  parent: '/home',
  entries: [
    { name: 'sealed.key', path: '/home/gev/sealed.key', isDir: false, sizeBytes: 64, modified: '1700000000000' },
    { name: 'notes.txt', path: '/home/gev/notes.txt', isDir: false, sizeBytes: 128, modified: '1700000000000' },
  ],
};

function mount(readFile: (path: string) => Promise<unknown>) {
  invokeMock.mockImplementation((cmd: string, args?: Record<string, unknown>) => {
    if (cmd === 'list_dir') return Promise.resolve(LISTING);
    if (cmd === 'read_file') return readFile(String(args?.path ?? ''));
    return Promise.resolve(null);
  });
  return render(<AppProvider><ToastProvider><Files /></ToastProvider></AppProvider>);
}

async function open(name: string) {
  const row = await screen.findByText(name);
  fireEvent.click(row);
}

beforeEach(() => invokeMock.mockReset());

describe('Files — a sealed file is refused, and the page says why', () => {
  it('renders the blocked state with the engine guard reason, and no content', async () => {
    mount(() => Promise.reject(new Error('scope guard: path not in the declared protected_scope')));
    await open('sealed.key');

    const alert = await screen.findByRole('alert');
    // Announced immediately: a refusal the owner triggered is not something to queue politely.
    expect(alert).toHaveAttribute('aria-live', 'assertive');
    // The engine's own words, not a paraphrase.
    expect(alert.textContent).toContain('not in the declared protected_scope');
    // And nothing that looks like file content came back with it.
    expect(alert.textContent).not.toContain('sealed.key contents');
  });

  it('a refused open leaves no editable surface behind', async () => {
    mount(() => Promise.reject(new Error('permission denied')));
    await open('sealed.key');
    await screen.findByRole('alert');
    // No textarea, no save: a sealed file must not present the affordances of an open one.
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.queryByRole('button', { name: /save/i })).toBeNull();
  });

  it('an ordinary read failure is NOT dressed as a guard refusal', async () => {
    // The fail-open direction here is the opposite of most: calling a disk error a guard
    // refusal would tell the owner the system is protecting them when it is simply broken.
    mount(() => Promise.reject(new Error('EIO: input/output error')));
    await open('notes.txt');
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith('read_file', expect.anything()));
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('a readable file still opens — the guard is a gate, not a wall', async () => {
    mount((path) => Promise.resolve({ path, content: 'PLAINTEXTBODY', readonly: true }));
    await open('notes.txt');
    await waitFor(() =>
      expect(invokeMock).toHaveBeenCalledWith('read_file',
        expect.objectContaining({ path: '/home/gev/notes.txt' })));
    // A successful read must not raise the guard alert. This is the control that stops the
    // three tests above from passing against a build where EVERY open is refused.
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('isGuardDenied — the classifier the blocked state turns on', () => {
  it('recognises the engine vocabulary for a refusal', () => {
    for (const m of ['permission denied', 'not permitted', 'not allowed', 'sealed',
                     'forbidden', 'outside declared scope', 'scope guard refused']) {
      expect(isGuardDenied(m)).toBe(true);
    }
  });

  it('does not claim an ordinary failure as a refusal', () => {
    for (const m of ['EIO: input/output error', 'no such file or directory',
                     'connection reset by peer', 'unexpected end of file']) {
      expect(isGuardDenied(m)).toBe(false);
    }
  });
});
