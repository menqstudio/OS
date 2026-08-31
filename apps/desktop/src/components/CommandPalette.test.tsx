import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// The palette searches entities over the IPC boundary when a backend is present. Mock the
// boundary, not the service, so the debounce + stale-response guard are the real ones.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from './toast';
import { CommandPalette } from './CommandPalette';
import { ALL_ITEMS } from '../app/nav';

/**
 * Tests for the ⌘K command dock — §D's `cmd-dock`, and the shell's only modal.
 *
 * This surface had NO tests. It is the keyboard route to all 23 pages, which makes a keyboard-only
 * owner its primary user, and it was the one part of the shell that served them worst: no dialog
 * role, no focus trap, no focus restoration, no `aria-activedescendant`. What is pinned here is
 * that set of properties, because every one of them is invisible on screen and therefore the kind
 * of thing that regresses without anyone noticing.
 */
function setup() {
  // Resolve rather than reject: `hasBackend()` is false in jsdom so the palette never calls the
  // boundary itself, and a rejected startup call from the provider would surface as an unhandled
  // rejection and fail tests for a reason that has nothing to do with the palette.
  invokeMock.mockImplementation(() => Promise.resolve([]));
  return render(
    <AppProvider>
      <ToastProvider>
        <button type="button" data-testid="opener">opener</button>
        <CommandPalette />
      </ToastProvider>
    </AppProvider>,
  );
}

/** Open via the real global shortcut, the way a user does. */
async function openWithShortcut(user: ReturnType<typeof userEvent.setup>) {
  await user.keyboard('{Control>}k{/Control}');
  await screen.findByRole('dialog');
}

beforeEach(() => invokeMock.mockReset());
afterEach(() => { vi.useRealTimers(); });

describe('CommandPalette — ⌘K opens a real dialog', () => {
  it('is absent until the shortcut, then is a labelled modal dialog', async () => {
    const user = userEvent.setup();
    setup();
    expect(screen.queryByRole('dialog')).toBeNull();
    await openWithShortcut(user);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog.getAttribute('aria-label')).toBeTruthy();
  });

  it('moves focus into the search field on open', async () => {
    const user = userEvent.setup();
    setup();
    await openWithShortcut(user);
    await waitFor(() => expect(screen.getByRole('combobox')).toHaveFocus());
  });

  it('hands focus BACK to whatever opened it when it closes', async () => {
    const user = userEvent.setup();
    setup();
    const opener = screen.getByTestId('opener');
    act(() => opener.focus());
    await openWithShortcut(user);
    await waitFor(() => expect(screen.getByRole('combobox')).toHaveFocus());
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    // Without this, Escape drops a keyboard user at the top of the document.
    await waitFor(() => expect(opener).toHaveFocus());
  });

  // fifth audit, A-02. The trap was bound to the input, so it stopped existing the moment focus
  // left it — and one click on the panel's padding, the list container or the empty row does
  // exactly that. Found with trusted CDP input in a real browser; jsdom's tab model never saw it,
  // which is why the guard is now BOTH a mousedown that stops the blur and a document-level Tab
  // handler that recovers if focus left anyway.
  it('keeps focus in the field when a non-focusable part of the panel is clicked', async () => {
    const user = userEvent.setup();
    setup();
    await openWithShortcut(user);
    await waitFor(() => expect(screen.getByRole('combobox')).toHaveFocus());
    await user.click(screen.getByRole('listbox'));
    expect(document.activeElement).not.toBe(document.body);
    expect(screen.getByRole('combobox')).toHaveFocus();
  });

  it('recovers the trap even if focus has already reached <body>', async () => {
    const user = userEvent.setup();
    setup();
    const opener = screen.getByTestId('opener');
    act(() => opener.focus());
    await openWithShortcut(user);
    // Simulate the state the audit reached: focus on <body>, palette still open.
    act(() => (document.activeElement as HTMLElement)?.blur());
    expect(document.activeElement).toBe(document.body);
    await user.keyboard('{Tab}');
    expect(screen.getByRole('combobox')).toHaveFocus();
    expect(opener).not.toHaveFocus();
  });

  it('traps Tab — a modal the keyboard can walk out of is not a modal', async () => {
    const user = userEvent.setup();
    setup();
    const opener = screen.getByTestId('opener');
    act(() => opener.focus());
    await openWithShortcut(user);
    await waitFor(() => expect(screen.getByRole('combobox')).toHaveFocus());
    await user.tab();
    expect(screen.getByRole('combobox')).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByRole('combobox')).toHaveFocus();
    expect(opener).not.toHaveFocus();
  });
});

describe('CommandPalette — the listbox says which row Enter is aimed at', () => {
  it('exposes a combobox owning a listbox of options', async () => {
    const user = userEvent.setup();
    setup();
    await openWithShortcut(user);
    const input = screen.getByRole('combobox');
    const list = screen.getByRole('listbox');
    expect(input).toHaveAttribute('aria-controls', list.id);
    expect(input).toHaveAttribute('aria-expanded', 'true');
    // One option per nav entry — the palette is the keyboard route to every page.
    expect(screen.getAllByRole('option')).toHaveLength(ALL_ITEMS.length);
  });

  it('names the active row with aria-activedescendant, and moves it with the arrows', async () => {
    const user = userEvent.setup();
    setup();
    await openWithShortcut(user);
    const input = screen.getByRole('combobox');
    const options = screen.getAllByRole('option');
    expect(input.getAttribute('aria-activedescendant')).toBe(options[0].id);
    expect(options[0]).toHaveAttribute('aria-selected', 'true');

    await user.keyboard('{ArrowDown}');
    expect(input.getAttribute('aria-activedescendant')).toBe(screen.getAllByRole('option')[1].id);
    expect(screen.getAllByRole('option')[1]).toHaveAttribute('aria-selected', 'true');
    expect(screen.getAllByRole('option')[0]).toHaveAttribute('aria-selected', 'false');

    await user.keyboard('{ArrowUp}');
    expect(input.getAttribute('aria-activedescendant')).toBe(screen.getAllByRole('option')[0].id);
  });

  it('Home and End jump to the ends of the list', async () => {
    const user = userEvent.setup();
    setup();
    await openWithShortcut(user);
    const input = screen.getByRole('combobox');
    await user.keyboard('{End}');
    const opts = screen.getAllByRole('option');
    expect(input.getAttribute('aria-activedescendant')).toBe(opts[opts.length - 1].id);
    await user.keyboard('{Home}');
    expect(input.getAttribute('aria-activedescendant')).toBe(screen.getAllByRole('option')[0].id);
  });

  it('never points aria-activedescendant at a row that is not there', async () => {
    const user = userEvent.setup();
    setup();
    await openWithShortcut(user);
    const input = screen.getByRole('combobox');
    await user.type(input, 'zzzzz-no-such-page');
    await waitFor(() => expect(screen.queryAllByRole('option')).toHaveLength(0));
    // A dangling id reference is worse than none: the screen reader announces nothing and the
    // user is told nothing is wrong.
    expect(input.getAttribute('aria-activedescendant')).toBeNull();
  });

  // fifth audit, A-03. On the palette's PRIMARY path the opener has unmounted with the old page
  // by the time the restore runs, so `focus()` on a detached node was a silent no-op that left
  // the keyboard on <body> — the exact failure the restore was written to prevent.
  it('does not chase a detached opener when navigation unmounted it', async () => {
    const user = userEvent.setup();
    function Harness({ showOpener }: { showOpener: boolean }) {
      return (
        <AppProvider>
          <ToastProvider>
            {showOpener && <button type="button" data-testid="opener">opener</button>}
            <button type="button" data-testid="survivor">survivor</button>
            <CommandPalette />
          </ToastProvider>
        </AppProvider>
      );
    }
    invokeMock.mockImplementation(() => Promise.resolve([]));
    const { rerender } = render(<Harness showOpener />);
    const opener = screen.getByTestId('opener');
    act(() => opener.focus());
    await openWithShortcut(user);
    // React unmounts the opener, exactly as a route change does to the page that owned it.
    rerender(<Harness showOpener={false} />);
    expect(opener.isConnected).toBe(false);
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    // The restore must not "succeed" against a node that is no longer in the document. Nothing
    // pretends otherwise, and nothing throws; the route's own focus handoff owns the destination
    // from here. What must NOT happen is a no-op dressed as a restore.
    expect(screen.getByTestId('survivor')).not.toHaveFocus();
  });

  it('filters to the typed page and Enter navigates to it', async () => {
    const user = userEvent.setup();
    setup();
    await openWithShortcut(user);
    await user.type(screen.getByRole('combobox'), 'security');
    await waitFor(() => expect(screen.getAllByRole('option').length).toBeLessThan(ALL_ITEMS.length));
    expect(screen.getAllByRole('option').length).toBeGreaterThan(0);
    await user.keyboard('{Enter}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(window.location.hash).toContain('security');
  });
});
