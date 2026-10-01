import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// Mock the Tauri IPC boundary. Library mirrors the real list_library store; it renders only
// what the store returns and never fabricates an entry.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Library } from './Library';

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_library') return Promise.resolve([{ id: 'l-1', title: 'Design tokens', kind: 'doc', body: '', tags: 'ui', createdAt: '1700000000000', updatedAt: '1700000000000' }]);
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Library />
      </ToastProvider>
    </AppProvider>,
  );
}

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Library — mirrors the real list_library store', () => {
  it('renders the real entry from list_library', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Design tokens').length).toBeGreaterThan(0));
    expect(called('list_library')).toBe(true);
  });
});

// §D: "Keyboard: `/` focus search, arrow-navigate results, `Enter` open."
// The rows are <button>s, so Enter already fired their onClick — which only re-selected the
// row the arrows had already selected. The preview was showing it the whole time and had no
// tab stop, so a keyboard user watched the panel change and could never reach it. "Open" now
// means move INTO the preview, which is the only reading of §D that changes anything.
function withItems(n: number) {
  const items = Array.from({ length: n }, (_, i) => ({
    id: `l-${i}`, title: `Item ${i}`, kind: 'doc', body: `Body of item ${i}`,
    tags: 'ui', createdAt: '1700000000000', updatedAt: '1700000000000',
  }));
  invokeMock.mockImplementation((cmd: string) =>
    Promise.resolve(cmd === 'list_library' ? items : null));
  return render(<AppProvider><ToastProvider><Library /></ToastProvider></AppProvider>);
}

describe('Library — Enter opens the preview, Escape comes back', () => {
  it('Enter moves focus from the list into the preview panel', async () => {
    const user = userEvent.setup();
    withItems(3);
    await waitFor(() => expect(screen.getAllByText('Item 0').length).toBeGreaterThan(0));

    const rows = screen.getAllByRole('button', { name: /Item 0/ });
    rows[0].focus();
    await user.keyboard('{Enter}');

    const preview = screen.getByRole('region', { name: /Item 0/ });
    expect(preview).toHaveFocus();
  });

  it('Escape in the preview returns focus to the row it came from', async () => {
    const user = userEvent.setup();
    withItems(3);
    await waitFor(() => expect(screen.getAllByText('Item 0').length).toBeGreaterThan(0));

    // Arrow to the second row first, so the return target is not simply the first one.
    screen.getAllByRole('button', { name: /Item 0/ })[0].focus();
    await user.keyboard('{ArrowDown}');
    await waitFor(() => expect(screen.getAllByRole('button', { name: /Item 1/ })[0]).toHaveFocus());

    await user.keyboard('{Enter}');
    await waitFor(() => expect(screen.getByRole('region', { name: /Item 1/ })).toHaveFocus());

    await user.keyboard('{Escape}');
    // Focus that goes somewhere with no way back is a trap; the row is where the user's place
    // in the list is.
    await waitFor(() => expect(screen.getAllByRole('button', { name: /Item 1/ })[0]).toHaveFocus());
  });

  it('the preview is not an extra tab stop for everyone else', async () => {
    withItems(2);
    await waitFor(() => expect(screen.getAllByText('Item 0').length).toBeGreaterThan(0));
    // -1 keeps it reachable by the Enter handoff and by a screen reader, without making every
    // mouse user Tab past it on the way to anything else.
    expect(screen.getByRole('region', { name: /Item 0/ })).toHaveAttribute('tabindex', '-1');
  });
});

// The Enter handler sits on the <ul>, and each row also holds its ✕ delete button. A bubbled
// Enter from THAT button was prevented and turned into "focus the preview", so the delete
// dialog could not be opened with Enter at all.
describe('Library — Enter on a row\'s delete button is that button\'s own', () => {
  it('does not swallow Enter on the ✕ button or move focus to the preview', async () => {
    withItems(2);
    await waitFor(() => expect(screen.getAllByText('Item 0').length).toBeGreaterThan(0));

    const del = screen.getByRole('button', { name: 'Delete: Item 0' });
    del.focus();
    // `fireEvent` returns false when a handler called preventDefault — which is exactly what
    // cancelled the button's native activation.
    const notPrevented = fireEvent.keyDown(del, { key: 'Enter' });
    expect(notPrevented).toBe(true);
    expect(screen.getByRole('region', { name: /Item 0/ })).not.toHaveFocus();
    expect(del).toHaveFocus();
  });

  it('Enter on the row itself still opens the preview', async () => {
    withItems(2);
    await waitFor(() => expect(screen.getAllByText('Item 0').length).toBeGreaterThan(0));
    const row = document.querySelector('.lib-item') as HTMLElement;
    row.focus();
    expect(fireEvent.keyDown(row, { key: 'Enter' })).toBe(false);
    expect(screen.getByRole('region', { name: /Item 0/ })).toHaveFocus();
  });
});
