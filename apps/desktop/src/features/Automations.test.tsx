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
