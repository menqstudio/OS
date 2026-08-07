import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// Two honesty defects lived on this page:
//
//   * A "Verifiable memory" pill rendered UNCONDITIONALLY in the header. Nothing
//     verifies a memory row — `list_memory` returns plain local SQLite rows with no
//     signature, receipt or chain behind them — so the badge claimed more than the
//     backend can prove, in every state including a failed read.
//   * `delete_memory` (DENIED in the window capability set) and `set_memory_pinned`
//     both ended in `.catch(() => s.reload())`: the refusal vanished, the row came
//     straight back on the reload, and the user was told nothing.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Memory } from './Memory';

const ENTRY = {
  id: 'm-1',
  scope: 'user',
  kind: 'fact',
  content: 'Rotate the API key monthly',
  pinned: false,
  createdAt: '1700000000000',
  updatedAt: '1700000000000',
};

const DENIAL = 'delete_memory not allowed. Permissions associated with this command: ';

function setup(opts: { listFails?: boolean; deleteRefuses?: boolean; pinRefuses?: boolean } = {}) {
  const store = [ENTRY];
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_memory') {
      return opts.listFails
        ? Promise.reject(new Error('store_unavailable'))
        : Promise.resolve([...store]);
    }
    if (cmd === 'delete_memory') {
      if (opts.deleteRefuses) return Promise.reject(new Error(DENIAL));
      store.length = 0;
      return Promise.resolve(null);
    }
    if (cmd === 'set_memory_pinned') {
      if (opts.pinRefuses) return Promise.reject(new Error('set_memory_pinned not allowed.'));
      return Promise.resolve(null);
    }
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Memory />
      </ToastProvider>
    </AppProvider>,
  );
}

/** The page's polite live region (what a screen-reader user is told). */
const liveText = () => document.querySelector('.mem-sr-only')?.textContent ?? '';

async function selectTheEntry() {
  await waitFor(() => expect(screen.getAllByText(/Rotate the API key monthly/).length).toBeGreaterThan(0));
  fireEvent.click(screen.getAllByText(/Rotate the API key monthly/)[0]);
  await screen.findByRole('button', { name: 'Delete' });
}

async function confirmDeleteDialog() {
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
  const dialog = await screen.findByRole('dialog');
  const confirm = Array.from(dialog.querySelectorAll('button')).find(
    (b) => b.className.includes('danger'),
  );
  expect(confirm).toBeTruthy();
  fireEvent.click(confirm as HTMLButtonElement);
}

// Rendering a whole feature page under jsdom can exceed the 5s default on a loaded
// machine. The assertions below are about honesty, not speed — give them room so a
// slow environment cannot be mistaken for a regression.
vi.setConfig({ testTimeout: 30000 });

beforeEach(() => invokeMock.mockReset());

describe('Memory — nothing claims the memory is verifiable', () => {
  it('never renders the unbacked "Verifiable memory" pill on a loaded page', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText(/Rotate the API key monthly/).length).toBeGreaterThan(0));

    expect(screen.queryByText('Verifiable memory')).not.toBeInTheDocument();
    expect(screen.queryByText(/verifiable/i)).not.toBeInTheDocument();

    // What is shown instead is a real fact: the outcome of the one `list_memory` read,
    // plus an explicit statement that these rows carry no verification chain.
    expect(screen.getByText('Read from the store')).toBeInTheDocument();
    expect(screen.getByText(/no verification chain/i)).toBeInTheDocument();
  });

  it('never renders it when the store read FAILED either', async () => {
    setup({ listFails: true });
    await waitFor(() => expect(screen.getByText('Store unavailable')).toBeInTheDocument());
    expect(screen.queryByText(/verifiable/i)).not.toBeInTheDocument();
  });
});

describe('Memory — a REFUSED delete is surfaced, never swallowed', () => {
  it('keeps the entry, shows the refusal with its reason, and says nothing was removed', async () => {
    setup({ deleteRefuses: true });
    await selectTheEntry();
    await confirmDeleteDialog();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Delete refused — nothing was removed');
    expect(alert).toHaveTextContent(/still in the store/i);
    expect(alert).toHaveTextContent(/delete_memory not allowed/);

    // The row is provably still listed.
    expect(screen.getAllByText(/Rotate the API key monthly/).length).toBeGreaterThan(0);
    // And the live region announced the refusal rather than a count as if nothing happened.
    await waitFor(() => expect(liveText()).toMatch(/refused/i));
  });
});

describe('Memory — a REFUSED pin change is surfaced, never swallowed', () => {
  it('states that the pin state did not change', async () => {
    setup({ pinRefuses: true });
    await selectTheEntry();
    fireEvent.click(screen.getByRole('button', { name: 'Pin' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Pin change refused — nothing was changed');
    expect(alert).toHaveTextContent(/set_memory_pinned not allowed/);
    await waitFor(() => expect(liveText()).toMatch(/refused/i));
  });
});

describe('Memory — an ACCEPTED delete reports the real outcome', () => {
  it('removes the entry and raises no refusal alert', async () => {
    setup();
    await selectTheEntry();
    await confirmDeleteDialog();

    await waitFor(() => expect(screen.queryByText(/Rotate the API key monthly/)).not.toBeInTheDocument());
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
