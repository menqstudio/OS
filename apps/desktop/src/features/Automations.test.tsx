import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';

// Mock the Tauri IPC boundary. Automations mirrors the real list_automations store; it renders only
// what the store returns and never fabricates an entry.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Automations } from './Automations';
import { STR } from './Automations.strings';

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_automations') return Promise.resolve([{ id: 'au-1', name: 'Nightly backup', trigger: 'cron', action: 'backup', enabled: true, createdAt: '1700000000000', updatedAt: '1700000000000' }]);
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Automations />
      </ToastProvider>
    </AppProvider>,
  );
}

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Automations — mirrors the real list_automations store', () => {
  it('renders the real entry from list_automations', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Nightly backup').length).toBeGreaterThan(0));
    expect(called('list_automations')).toBe(true);
  });
});

// §D: "`n` new, `/` filter, arrow-nav, `Enter` open". `/` was the one binding of the four that
// did not exist. On every other page in this cockpit `/` puts the cursor in a search box, so a
// keyboard user arriving here pressed it and nothing happened. This page filters with a CHIP
// GROUP rather than a text field, so `/` moves focus to the filter — binding it to "open a
// search box that does not exist" would have meant building a second filter to satisfy a
// keystroke.
describe('Automations — `/` reaches the state filter', () => {
  const filterGroup = () => screen.getByRole('group', { name: /state|վիճակ|состояни/i });

  it('`/` moves focus into the filter chips', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Nightly backup').length).toBeGreaterThan(0));
    expect(document.activeElement).toBe(document.body);

    fireEvent.keyDown(window, { key: '/' });

    const focused = document.activeElement as HTMLElement;
    expect(filterGroup().contains(focused)).toBe(true);
    // It lands on the ACTIVE chip, not blindly on the first, so pressing `/` twice does not
    // silently move the user off the filter they already chose.
    expect(focused).toHaveAttribute('aria-pressed', 'true');
  });

  it('arrows walk the chips once focus is there', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Nightly backup').length).toBeGreaterThan(0));
    fireEvent.keyDown(window, { key: '/' });
    const first = document.activeElement as HTMLElement;

    fireEvent.keyDown(filterGroup(), { key: 'ArrowRight' });
    expect(document.activeElement).not.toBe(first);
    expect(filterGroup().contains(document.activeElement as HTMLElement)).toBe(true);

    fireEvent.keyDown(filterGroup(), { key: 'Home' });
    expect(document.activeElement).toBe(within(filterGroup()).getAllByRole('button')[0]);
  });

  it('`/` typed INTO a field is a slash, not a shortcut', async () => {
    // The guard that keeps a page shortcut from eating a character the user meant to type.
    setup();
    await waitFor(() => expect(screen.getAllByText('Nightly backup').length).toBeGreaterThan(0));
    fireEvent.keyDown(window, { key: 'n' });                       // open the authoring form
    const field = await screen.findByRole('textbox', { name: /name|անուն|назван/i })
      .catch(() => screen.getAllByRole('textbox')[0]);
    field.focus();
    fireEvent.keyDown(field, { key: '/' });
    expect(document.activeElement).toBe(field);
  });
});

// `delete_automation` is behind a native confirmation the Rust handler raises. The page draws no
// dialog of its own: pressing Delete sends the id and the display language, and the promise stays
// pending until the person answers the system dialog. What the page owes the reader is the truth
// about that, before the press and after it.
describe('Automations — delete: the app asks natively, the page does not', () => {
  // A runnable row (manual trigger, known verb), so no standing seal draws an alert of its own.
  const ROW = { id: 'au-1', name: 'Nightly backup', trigger: 'manual', action: 'notify: backup done', enabled: true, createdAt: '1700000000000', updatedAt: '1700000000000' };

  /** Mount with `delete_automation` answered by `onDelete`; resolves once the schematic is up. */
  async function mountWithDelete(onDelete: () => Promise<unknown>) {
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'list_automations') return Promise.resolve([ROW]);
      if (cmd === 'delete_automation') return onDelete();
      return Promise.resolve(null);
    });
    render(
      <AppProvider>
        <ToastProvider>
          <Automations />
        </ToastProvider>
      </AppProvider>,
    );
    return screen.findByRole('button', { name: 'Delete' });
  }

  const deleteCalls = () => invokeMock.mock.calls.filter((c) => c[0] === 'delete_automation');

  it('says, before anything is pressed, that the app will ask in a system dialog', async () => {
    const button = await mountWithDelete(() => Promise.resolve(null));
    expect(STR.deleteAsks.en).toMatch(/the app opens a system dialog/);
    expect(STR.deleteAsks.en).toMatch(/Nothing is deleted unless you confirm there/);
    expect(screen.getByText(STR.deleteAsks.en)).toBeInTheDocument();
    expect(button).toHaveAttribute('title', STR.deleteAsks.en);
    expect(deleteCalls()).toHaveLength(0);
  });

  it('draws no confirm dialog of its own: one press goes straight to the handler that asks', async () => {
    const button = await mountWithDelete(() => new Promise(() => { /* the system dialog stays open */ }));
    fireEvent.click(button);
    // No in-page dialog stands between the press and the call…
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    // …and the call carries the id and the display language, nothing that answers for the person.
    expect(deleteCalls()).toEqual([['delete_automation', { id: 'au-1', lang: 'en' }]]);
    // While the system dialog is open the page says it is waiting, and offers no second Delete.
    // Twice: once beside the button, once in the page's polite live region.
    expect(await screen.findAllByText(STR.deleteAsking.en)).toHaveLength(2);
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(deleteCalls()).toHaveLength(1);
  });

  it('a declined system dialog is reported as nothing deleted — not as an error, and the row stays', async () => {
    const button = await mountWithDelete(() => Promise.reject(
      'native_confirmation_not_given: nothing was deleted. The system dialog was declined or dismissed.',
    ));
    fireEvent.click(button);
    expect(await screen.findAllByText(STR.deleteNotConfirmed.en)).toHaveLength(2);
    expect(screen.getAllByText('Nightly backup').length).toBeGreaterThan(0);
    // The raw machine string is not put on the page, and "no" is not rendered as a wall denial.
    expect(screen.queryByText(/native_confirmation_not_given/)).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    await waitFor(() => expect(button).not.toBeDisabled());
  });

  it('any other refusal of the delete is still shown as the failure it is', async () => {
    const button = await mountWithDelete(() => Promise.reject('another confirmation is already in progress'));
    fireEvent.click(button);
    expect((await screen.findAllByText('another confirmation is already in progress')).length).toBeGreaterThan(0);
    expect(screen.queryByText(STR.deleteNotConfirmed.en)).not.toBeInTheDocument();
  });

  it('the three languages all carry the three delete strings', () => {
    for (const key of ['deleteAsks', 'deleteAsking', 'deleteNotConfirmed'] as const) {
      for (const lang of ['en', 'hy', 'ru'] as const) {
        expect(STR[key][lang].length, `${key}.${lang}`).toBeGreaterThan(10);
      }
      expect(new Set(Object.values(STR[key])).size, `${key} is translated, not copied`).toBe(3);
    }
  });
});
