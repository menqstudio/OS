import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// `delete_library_item` is DENIED in the window capability set. The confirm handler had
// no `.catch` at ALL — only `.then` and a `.finally` that closed the dialog and
// reloaded. So a refusal produced an unhandled rejection, the dialog closed as if the
// delete had worked, and the item simply reappeared with nothing said.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Library } from './Library';

const ITEM = {
  id: 'l-1',
  kind: 'component',
  title: 'Accessible form field',
  body: '<Field/>',
  tags: 'react,form',
  createdAt: '1700000000000',
  updatedAt: '1700000000000',
};

const DENIAL = 'delete_library_item not allowed. Permissions associated with this command: ';

/** What the HANDLER returns if the ACL ever let the call through (`forbidden_hard_delete`). */
const HANDLER_REFUSAL = 'forbidden_command:delete_library_item: nothing was deleted.';

function setup(deleteOutcome: 'refuse' | 'accept' | 'handler' | 'broken') {
  const store = [ITEM];
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_library') return Promise.resolve([...store]);
    if (cmd === 'delete_library_item') {
      if (deleteOutcome === 'refuse') return Promise.reject(new Error(DENIAL));
      if (deleteOutcome === 'handler') return Promise.reject(new Error(HANDLER_REFUSAL));
      if (deleteOutcome === 'broken') return Promise.reject(new Error('database is locked'));
      store.length = 0;
      return Promise.resolve(null);
    }
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

async function deleteTheItem() {
  await waitFor(() => expect(screen.getAllByText('Accessible form field').length).toBeGreaterThan(0));
  // The row's own remove control (an icon button labelled for the item).
  const remove = document.querySelector('.lib-row-del, .lib-del, button[aria-label*="Delete"], button[title*="Delete"]');
  expect(remove).toBeTruthy();
  fireEvent.click(remove as HTMLElement);
  const dialog = await screen.findByRole('dialog');
  // The confirmation does not promise a delete the backend cannot perform. It used to read
  // "Delete this item? This can't be undone."
  expect(dialog).toHaveTextContent(/Nothing will be removed/);
  expect(dialog).not.toHaveTextContent(/can.t be undone/i);
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

describe('Library — a REFUSED delete is surfaced, never swallowed', () => {
  it('keeps the item, shows the refusal with its reason', async () => {
    setup('refuse');
    await deleteTheItem();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Delete refused — nothing was removed');
    expect(alert).toHaveTextContent(/still in the archive/i);
    expect(alert).toHaveTextContent(/delete_library_item not allowed/);

    // The row is provably still listed.
    expect(screen.getAllByText('Accessible form field').length).toBeGreaterThan(0);
  });
});

// `researchLibraryDeleteRefusal.ts` was written to tell a PERMANENT policy refusal from a failure
// that might be worth retrying, and was imported by nothing — so every refusal read the same and
// the row coming back looked like "try again".
describe('Library — a policy refusal is named as permanent; an unknown failure is not', () => {
  const PERMANENT = /standing policy refusal.*retrying cannot succeed/i;

  it('the capability wall\'s refusal is a standing one', async () => {
    setup('refuse');
    await deleteTheItem();
    expect(await screen.findByRole('alert')).toHaveTextContent(PERMANENT);
  });

  it('so is the handler\'s own `forbidden_command:` refusal', async () => {
    setup('handler');
    await deleteTheItem();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(PERMANENT);
    expect(alert).toHaveTextContent(/forbidden_command:delete_library_item/);
  });

  it('a failure the page cannot classify is NOT called permanent', async () => {
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
    try {
      setup('broken');
      await deleteTheItem();
      const alert = await screen.findByRole('alert');
      expect(alert).toHaveTextContent('database is locked');
      expect(alert).not.toHaveTextContent(PERMANENT);
    } finally {
      delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
    }
  });
});

// No backend in this tree can produce this outcome: `delete_library_item` is denied by the window
// capability set and its handler returns `forbidden_hard_delete` unconditionally. The test pins
// the renderer's success arm for the day T-011 lands; it is not evidence a delete works today.
describe('Library — an ACCEPTED delete reports the real outcome', () => {
  it('removes the item and raises no refusal alert', async () => {
    setup('accept');
    await deleteTheItem();

    await waitFor(() => expect(screen.queryByText('Accessible form field')).not.toBeInTheDocument());
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
