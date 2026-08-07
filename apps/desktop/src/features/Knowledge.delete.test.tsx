import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// `delete_knowledge` is one of the six hard-delete commands DENIED in the window
// capability set, so a refusal is the ordinary outcome, not an edge case. The page used
// to announce "Article … deleted" BEFORE the call, drop the selection, then swallow the
// rejection in `.catch(reloadAll)` — the row reappeared on the reload and the user was
// never told the store had refused.
//
// What must hold now: nothing is announced as deleted until the backend confirms, and a
// refusal is readable on screen with the backend's own reason.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Knowledge } from './Knowledge';

const NOTE = {
  id: 'k-1',
  title: 'Onboarding notes',
  body: 'welcome',
  source: 'internal',
  tags: 'hr',
  createdAt: '1700000000000',
  updatedAt: '1700000000000',
};

const DENIAL = 'delete_knowledge not allowed. Permissions associated with this command: ';

function setup(deleteOutcome: 'refuse' | 'accept') {
  const store = [NOTE];
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'search_knowledge' || cmd === 'list_knowledge') return Promise.resolve([...store]);
    if (cmd === 'delete_knowledge') {
      if (deleteOutcome === 'refuse') return Promise.reject(new Error(DENIAL));
      store.length = 0;
      return Promise.resolve(null);
    }
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Knowledge />
      </ToastProvider>
    </AppProvider>,
  );
}

/** The page's polite live region (what a screen-reader user is told). */
const liveText = () => document.querySelector('.kb-sr-live')?.textContent ?? '';

async function deleteTheArticle() {
  await waitFor(() => expect(screen.getAllByText('Onboarding notes').length).toBeGreaterThan(0));
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
  // Confirm inside the dialog — the danger-variant control, not the row's own button.
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

describe('Knowledge — a REFUSED delete is surfaced, never swallowed', () => {
  it('keeps the article, shows the refusal with its reason, and never says "deleted"', async () => {
    setup('refuse');
    await deleteTheArticle();

    // The refusal is on screen as an alert the user can read.
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Delete refused — nothing was removed');
    expect(alert).toHaveTextContent(/still in the store/i);
    // The backend's own reason is quoted rather than paraphrased away.
    expect(alert).toHaveTextContent(/delete_knowledge not allowed/);

    // The row is still there — the store kept it and the list proves it.
    expect(screen.getAllByText('Onboarding notes').length).toBeGreaterThan(0);

    // And the live region never claimed a deletion.
    expect(liveText()).not.toMatch(/deleted/i);
    expect(liveText()).toMatch(/refused/i);
  });
});

describe('Knowledge — an ACCEPTED delete reports the real outcome', () => {
  it('announces the deletion only after the backend confirms, and raises no alert', async () => {
    setup('accept');
    await deleteTheArticle();

    await waitFor(() => expect(liveText()).toMatch(/deleted/i));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('Onboarding notes')).not.toBeInTheDocument());
  });
});
