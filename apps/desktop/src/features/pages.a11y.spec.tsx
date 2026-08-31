import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { axe } from '../test/axe';

// The IPC boundary. Every page here reads real commands and has no fixture layer behind it, so
// the mock decides which STATE each page renders. That is the point: an accessibility pass over
// the happy path only is a pass over the state a user is least often stuck in.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class { onmessage: unknown = null; },
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Shell } from '../components/Shell';
import { CommandPalette } from '../components/CommandPalette';
import { Home } from './Home';
import { Settings } from './Settings';
import { Approvals } from './Approvals';
import { Decisions } from './Decisions';
import { Security } from './Security';
import { Notifications } from './Notifications';
import { Activity } from './Activity';
import { Agents } from './Agents';
import { Analytics } from './Analytics';
import { Automations } from './Automations';
import { BridgePanel } from './Bridge';
import { Calendar } from './Calendar';
import { Chat } from './Chat';
import { Command } from './Command';
import { Files } from './Files';
import { GroupChat } from './GroupChat';
import { Integrations } from './Integrations';
import { Knowledge } from './Knowledge';
import { Library } from './Library';
import { Memory } from './Memory';
import { Projects } from './Projects';
import { Research } from './Research';
import { Tasks } from './Tasks';

/**
 * Accessibility (axe) coverage for the SURFACES, not just the primitives.
 *
 * The fifth independent audit's §E named this gap precisely: the only `*.a11y.spec.tsx` files in
 * this repository covered `ui.tsx` and the shared primitives, so *"the modal this round rebuilt
 * for accessibility is not in the axe pass, and neither is Security, Approvals, or any of the 23
 * pages."* A component library can be perfectly accessible while every page composed from it is
 * not — the violations that matter (a heading level skipped, two elements sharing an id, a live
 * region with no accessible name, a control labelled only by an icon) are properties of the
 * composition, and the composition was untested.
 *
 * WHAT THIS CANNOT DO, said plainly rather than implied. jsdom attaches no stylesheet — this
 * project runs with `css: false`, which is what let A-01 ship — so axe's `color-contrast` rule
 * cannot execute here and does not. Contrast is covered separately and statically by
 * `tools/check_contrast.py` over the committed token pairs. What runs here is the structural
 * half: roles, accessible names, ARIA validity, duplicate ids, landmark and heading structure.
 * That is most of what a page gets wrong, and none of it was being checked.
 */

/** Resolve every command to something shaped like an empty result set.
 *
 *  SHAPE matters, not just emptiness. `list_dir` returns an OBJECT with an `entries` array, and
 *  answering it with `[]` is not a harmless approximation: `[].entries` is
 *  `Array.prototype.entries`, a function, so `s.data?.entries ?? []` happily yields a function and
 *  the page dies on `.filter`. An empty-result mock that returns the wrong shape tests the page's
 *  behaviour against a value the backend can never send. */
const OBJECT_SHAPED: Record<string, unknown> = {
  get_security_summary: { pendingApprovals: 0, decidedApprovals: 0, auditEvents: 0, sensitiveEvents: [] },
  list_dir: { path: '/', parent: null, entries: [] },
  read_file: { path: '/', content: '', readonly: true },
  get_ai_status: { provider: 'not-configured', governed: false, reason: '' },
};

function empty() {
  invokeMock.mockImplementation((cmd: string) =>
    Promise.resolve(cmd in OBJECT_SHAPED ? OBJECT_SHAPED[cmd] : []));
}

/** Every command rejects — the `error` / `unreachable` state each page must render honestly.
 *
 *  The no-op `.catch` marks the rejection as handled without changing what the caller receives:
 *  the same rejected promise is returned, so every page still takes its error path. It is here as
 *  hygiene for a suite that deliberately rejects everything, not as a diagnosed fix — the failure
 *  that actually blocked these tests was `vi.restoreAllMocks()` in `afterEach`, which restored
 *  the boundary mock to a no-op mid-suite so a later render received `undefined` where a promise
 *  was expected. Said plainly because "it passes now" is not the same as knowing why. */
function unreachable() {
  invokeMock.mockImplementation(() => {
    const rejected = Promise.reject(new Error('broker_unavailable'));
    rejected.catch(() => {});
    return rejected;
  });
}

function mount(node: React.ReactNode) {
  return render(<AppProvider><ToastProvider>{node}</ToastProvider></AppProvider>);
}

/** Let the page's `useAsync` reads settle before axe looks at the DOM. */
async function settled() {
  await waitFor(() => expect(invokeMock).toHaveBeenCalled());
  await act(async () => { await Promise.resolve(); });
}

beforeEach(() => invokeMock.mockReset());
afterEach(() => { invokeMock.mockReset(); });

// EVERY routed feature page, not a sample. The first version of this file covered six, which was
// the six the fifth audit's §E named plus the ones nearest them — and a sample is how a page ends
// up being the one nobody checked. `Chat` and `GroupChat` both render `Conversations`, so the
// shared surface is covered through them rather than twice.
const PAGES: Array<[string, () => React.ReactElement]> = [
  ['home', () => <Home />],
  ['settings', () => <Settings />],
  ['approvals', () => <Approvals />],
  ['decisions', () => <Decisions />],
  ['security', () => <Security />],
  ['notifications', () => <Notifications />],
  ['activity', () => <Activity />],
  ['agents', () => <Agents />],
  ['analytics', () => <Analytics />],
  ['automations', () => <Automations />],
  ['bridge', () => <BridgePanel />],
  ['calendar', () => <Calendar />],
  ['chat', () => <Chat />],
  ['command', () => <Command />],
  ['files', () => <Files />],
  ['groupChat', () => <GroupChat />],
  ['integrations', () => <Integrations />],
  ['knowledge', () => <Knowledge />],
  ['library', () => <Library />],
  ['memory', () => <Memory />],
  ['projects', () => <Projects />],
  ['research', () => <Research />],
  ['tasks', () => <Tasks />],
];

describe('accessibility (axe) — the pages, in the state a reader actually meets', () => {
  for (const [name, page] of PAGES) {
    it(`${name} has no violations with data`, async () => {
      empty();
      const { container } = mount(<main>{page()}</main>);
      await settled();
      expect(await axe(container)).toHaveNoViolations();
    });

    it(`${name} has no violations when the engine is unreachable`, async () => {
      // The state this whole cockpit is designed around — a fail-closed engine — and the one an
      // accessibility pass over the happy path would never visit.
      unreachable();
      const { container } = mount(<main>{page()}</main>);
      await settled();
      expect(await axe(container)).toHaveNoViolations();
    });
  }
});

describe('accessibility (axe) — the shell and its modal', () => {
  it('the app frame has no violations', async () => {
    empty();
    const { container } = mount(<Shell><h1>Stage</h1></Shell>);
    await settled();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('the ⌘K command dock has no violations while OPEN', async () => {
    // The surface §D nominates as the keyboard route to all 23 pages, rebuilt for accessibility
    // in this phase and — until now — absent from the axe pass entirely.
    empty();
    const { container } = mount(<><CommandPalette /><main><h1>Stage</h1></main></>);
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }));
    });
    await screen.findByRole('dialog');
    expect(await axe(container)).toHaveNoViolations();
  });
});
