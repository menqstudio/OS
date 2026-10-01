import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

// Mock the Tauri IPC boundary. Tasks mirrors the real list_tasks store and mutates
// only through the real set_task_status command — nothing is fabricated.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider, Toaster } from '../components/toast';
import { Tasks } from './Tasks';

const TASK = {
  id: 't-1',
  projectId: null,
  title: 'Draft the specification',
  description: 'first cut of the spec',
  status: 'active',
  priority: 'high',
  assignedAgentId: null,
  dueAt: null,
  position: 1,
  createdAt: '1700000000000',
  updatedAt: '1700000000000',
  completedAt: null,
};

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_tasks') return Promise.resolve([TASK]);
    if (cmd === 'list_projects') return Promise.resolve([]);
    if (cmd === 'list_task_dependencies') return Promise.resolve([]);
    if (cmd === 'set_task_status') return Promise.resolve({ ...TASK, status: 'done' });
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Tasks />
      </ToastProvider>
    </AppProvider>,
  );
}

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Tasks — mirrors the real task store', () => {
  it('renders the real task from list_tasks', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Draft the specification').length).toBeGreaterThan(0));
    expect(called('list_tasks')).toBe(true);
  });
});

// §D: "board columns `role=list`, cards labeled." A lane is a LIST of cards and was a bare
// <div>, so a screen reader announced the section and then read the cards as loose content —
// no count, no position, no "3 of 7".
describe('Tasks — the board lanes are lists', () => {
  it('every lane exposes its cards as a list', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Draft the specification').length).toBeGreaterThan(0));
    const lists = screen.getAllByRole('list');
    expect(lists.length).toBeGreaterThan(0);
    // Every lane is named, so "list, 3 items" is not the whole announcement.
    for (const l of lists) expect(l).toHaveAccessibleName();
    // The one real task is inside one of them, as an item.
    expect(screen.getAllByRole('listitem').length).toBeGreaterThan(0);
  });

  it('an empty lane says so in words, not with a dash', async () => {
    // An em dash is a character to a screen reader, not an empty state.
    setup();
    await waitFor(() => expect(screen.getAllByText('Draft the specification').length).toBeGreaterThan(0));
    // THE EMPTY LANES THEMSELVES. This used to assert `some(…)` over EVERY listitem — and the
    // fixture's one task card is a listitem with text, so it was true whatever the empty lanes
    // rendered, a bare dash included.
    const empty = Array.from(document.querySelectorAll('.lane-empty'));
    expect(empty.length).toBeGreaterThan(0);
    for (const lane of empty) {
      expect(lane).toHaveAttribute('role', 'listitem');
      const words = (lane.textContent ?? '').replace(/—/g, '').trim();
      expect(words, 'an empty lane must say it is empty in words').not.toBe('');
      // …and the dash that IS drawn is hidden from the accessibility tree.
      expect(lane.querySelector('[aria-hidden="true"]')?.textContent).toBe('—');
    }
  });
});

// The card's Enter handler opened the edit modal on ANY Enter that bubbled to it. Its Release and
// Dispatch buttons stop propagation only on click, so Enter on either was prevented at the card
// and opened the modal instead of activating the button.
describe('Tasks — Enter on a card\'s own button is that button\'s', () => {
  const BLOCKED = { ...TASK, status: 'blocked' };
  function mount(task = BLOCKED, setStatus: () => Promise<unknown> = () => Promise.resolve({ ...task, status: 'active' })) {
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'list_tasks') return Promise.resolve([task]);
      if (cmd === 'list_projects') return Promise.resolve([]);
      if (cmd === 'list_agents') return Promise.resolve([]);
      if (cmd === 'list_task_dependencies') return Promise.resolve([]);
      if (cmd === 'set_task_status') return setStatus();
      return Promise.resolve(null);
    });
    return render(<AppProvider><ToastProvider><Toaster /><Tasks /></ToastProvider></AppProvider>);
  }
  const live = () => document.querySelector('.t-sr-only')?.textContent ?? '';

  it('Enter on Dispatch or Release is not swallowed and does not open the edit modal', async () => {
    mount();
    const dispatch = await screen.findByRole('button', { name: 'Dispatch: Draft the specification' });
    const release = screen.getByRole('button', { name: 'Release: Draft the specification' });
    for (const button of [dispatch, release]) {
      button.focus();
      // false would mean the card called preventDefault and cancelled the button's activation.
      expect(fireEvent.keyDown(button, { key: 'Enter' })).toBe(true);
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    }
  });

  it('Enter on the card itself still opens it', async () => {
    mount();
    await screen.findByRole('button', { name: 'Dispatch: Draft the specification' });
    const card = document.querySelector('article.mtask') as HTMLElement;
    card.focus();
    expect(fireEvent.keyDown(card, { key: 'Enter' })).toBe(false);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('the Release button is named for what it does, not "Open"', async () => {
    mount();
    const release = await screen.findByRole('button', { name: 'Release: Draft the specification' });
    expect(release).toHaveTextContent('Release');
    expect(screen.queryByRole('button', { name: 'Open: Draft the specification' })).not.toBeInTheDocument();
  });

  it('a REFUSED status change is not announced as a move, and its reason is shown', async () => {
    mount(BLOCKED, () => Promise.reject(new Error('task t-1 has unfinished dependencies')));
    fireEvent.click(await screen.findByRole('button', { name: 'Release: Draft the specification' }));

    await waitFor(() => expect(live()).toMatch(/Status not changed — task t-1 has unfinished dependencies/));
    // Never the arrow that means "moved to a lane".
    expect(live()).not.toContain('→');
    expect(await screen.findByText('Status not changed: task t-1 has unfinished dependencies')).toBeInTheDocument();
  });

  it('an ACCEPTED status change is announced once the backend has answered', async () => {
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Release: Draft the specification' }));
    await waitFor(() => expect(live()).toMatch(/Draft the specification → /));
  });
});
