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
import { STR as FILES_STR } from './Files.strings';

/** Verbatim: what Tauri answers for a command the window's capability set does not grant. */
const ACL_DENIAL = 'read_file not allowed. Permissions associated with this command: ';
/** Verbatim: the two strings `src-tauri/src/files.rs` `read_file` can return (`PATH_REFUSED`, `fs_err`). */
const PATH_REFUSED = 'path is not accessible in this workspace';
const READ_FAILED = 'cannot read file';

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
  // These were driven with 'scope guard: path not in the declared protected_scope', commented "the
  // engine's own words", and with 'permission denied'. Neither string is produced anywhere in
  // src-tauri, the engine or the bridge: `read_file` is `confine` + `read_text`, the engine is never
  // asked, and `fs_err` forwards one generic sentence. The guard was proven against a backend that
  // does not exist. The one refusal this page can really classify is the capability wall's.
  it('renders the blocked state with the refusal that was returned, and no content', async () => {
    mount(() => Promise.reject(new Error(ACL_DENIAL)));
    await open('sealed.key');

    const alert = await screen.findByRole('alert');
    // Announced immediately: a refusal the owner triggered is not something to queue politely.
    expect(alert).toHaveAttribute('aria-live', 'assertive');
    // The refuser's own words, not a paraphrase.
    expect(alert.textContent).toContain('read_file not allowed');
    // And the refusal is not attributed to an engine that this route never consults.
    expect(alert.textContent).not.toMatch(/engine scope guard denied/i);
    // And nothing that looks like file content came back with it.
    expect(alert.textContent).not.toContain('sealed.key contents');
  });

  it('a refused open leaves no editable surface behind', async () => {
    mount(() => Promise.reject(new Error(ACL_DENIAL)));
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

  it.each([PATH_REFUSED, READ_FAILED])('the backend\'s own "%s" is not announced as sealed', async (message) => {
    // `PATH_REFUSED` covers "does not exist", "not accessible" and "outside the root" on purpose,
    // so the page cannot know a guard refused anything; `fs_err` is a failed read.
    mount(() => Promise.reject(new Error(message)));
    await open('notes.txt');
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith('read_file', expect.anything()));
    expect(screen.queryByRole('alert')).toBeNull();
    expect(isGuardDenied(message)).toBe(false);
  });

  it.each(['en', 'hy', 'ru'] as const)('the sealed hint does not name the engine as the refuser (%s)', (lang) => {
    expect(FILES_STR.blockedHint[lang]).not.toMatch(/engine scope guard denied|Շարժիչի scope-պահակը մերժեց|Охрана области движка отклонила/);
    expect(FILES_STR.blockedHint[lang]).toMatch(/not consulted|չեն դիմում|не запрашивается/);
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

describe('Files — a file nobody has read is not announced as open', () => {
  it('names an unread row "not opened yet", and "open" only once a read established it', async () => {
    mount(() => Promise.resolve({ path: '/home/gev/notes.txt', content: 'hello', readonly: false, sizeBytes: 5 }));
    await screen.findByText('notes.txt');
    // `guards` is empty: nothing was read. The label used to end ", open" for every such row.
    const unread = screen.getByRole('row', { name: /notes\.txt/ });
    expect(unread).toHaveAccessibleName('notes.txt, file, not opened yet');
    expect(screen.getByRole('row', { name: /sealed\.key/ })).toHaveAccessibleName('sealed.key, file, not opened yet');

    await open('notes.txt');
    await waitFor(() =>
      expect(screen.getByRole('row', { name: /notes\.txt/ })).toHaveAccessibleName('notes.txt, file, open'));
    // The other row was still never read.
    expect(screen.getByRole('row', { name: /sealed\.key/ })).toHaveAccessibleName('sealed.key, file, not opened yet');
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
