import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, waitFor, act } from '@testing-library/react';
import {
  settleAnimations, invisibleContent, clobberedMotion, reportInvisible, reportClobbered,
  unstyledClasses, styledClassTokens, reportUnstyled,
  emulateMedia as media,
} from '../test/computedStyle';

/**
 * T-024 — the computed-style sweep. The first test in this repository that loads a stylesheet.
 *
 * `A-01` shipped a fully-populated, completely invisible Security instrument, and every one of the
 * 713 unit tests passed while it did, because `css: false` reduces an assertion about appearance
 * to an assertion about a className string. This file asks Chromium instead, over every routed
 * page, in the states the app is actually used in.
 *
 * The invariants are page-agnostic on purpose. Asserting *"Security's instrument is visible"* would
 * require someone to have already suspected Security — and nobody did, for the whole time `A-01`
 * was on main. What is asserted here is what every page owes a reader:
 *
 *   1. Nothing a reader is meant to SEE computes to `opacity: 0` once motion has settled.
 *   2. An element whose class PROMISES an entrance actually runs it.
 *
 * # Why three states and not one — the mistake this file made first
 *
 * The first version of this sweep mounted every page, waited for its reads to SETTLE, and measured.
 * It was green. It was also green with `A-01` deliberately reintroduced, which is how the hole was
 * found: `Security.tsx` applies `sigbreathe` only while `integrity === 'checking'`, and `checking`
 * exists only while the evidence-chain read is IN FLIGHT. A sweep that waits for the load to finish
 * never visits the state the defect lives in.
 *
 * That is `css: false`'s own shape one level up — a check that only visits the state the person
 * writing it happened to reach. So each page is measured in three states, each pinned rather than
 * raced:
 *
 *   * `pending`     — every command returns a promise that NEVER resolves, so the loading state is
 *                     deterministic rather than a window the test might miss. This is where
 *                     skeletons, spinners and `A-01` live.
 *   * `settled`     — shape-correct empty results; the state a reader spends most time in.
 *   * `unreachable` — every command rejects; the fail-closed state this whole cockpit is designed
 *                     around, and the one a happy-path sweep never sees.
 *
 * # And why every state runs twice
 *
 * `.reveal` starts at `opacity: 0` and arrives at `1` only through `animation: reveal … forwards`;
 * any rule that sets `animation: none` for a reduced-motion reader therefore deletes the thing that
 * makes the element visible, unless something else puts the opacity back. That is `A-01`'s exact
 * mechanism aimed at the readers least able to absorb it, and no static check in this repository
 * can see it — the rule is correct-looking CSS inside a media query.
 */

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class { onmessage: unknown = null; },
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
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

/** Shape-correct empty results — the same table the axe sweep uses, and for the same reason:
 *  `list_dir` returns an object with an `entries` array, and answering `[]` yields
 *  `Array.prototype.entries`, a function, so the page dies on `.filter`. */
const OBJECT_SHAPED: Record<string, unknown> = {
  get_security_summary: { pendingApprovals: 0, decidedApprovals: 0, auditEvents: 0, sensitiveEvents: [] },
  list_dir: { path: '/', parent: null, entries: [] },
  read_file: { path: '/', content: '', readonly: true },
  get_ai_status: { provider: 'not-configured', governed: false, reason: '' },
};

type State = 'pending' | 'settled' | 'unreachable';

function arrange(state: State) {
  if (state === 'pending') {
    // A promise that never settles. Deterministic where a timing window would be flaky, and the
    // only way to hold a page in its loading state long enough to measure it.
    invokeMock.mockImplementation(() => new Promise(() => {}));
    return;
  }
  if (state === 'unreachable') {
    invokeMock.mockImplementation(() => {
      const rejected = Promise.reject(new Error('broker_unavailable'));
      rejected.catch(() => {});   // marks it handled without changing what the caller receives
      return rejected;
    });
    return;
  }
  invokeMock.mockImplementation((cmd: string) =>
    Promise.resolve(cmd in OBJECT_SHAPED ? OBJECT_SHAPED[cmd] : []));
}


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

const STATES: State[] = ['pending', 'settled', 'unreachable'];

beforeEach(() => invokeMock.mockReset());
afterEach(async () => {
  invokeMock.mockReset();
  await media([]);           // never leak an emulated feature into the next test
});

async function mount(node: React.ReactElement) {
  const view = render(<AppProvider><ToastProvider>{node}</ToastProvider></AppProvider>);
  await waitFor(() => expect(invokeMock).toHaveBeenCalled());
  await act(async () => { await Promise.resolve(); });
  return view;
}

describe('computed style — nothing a reader should see renders invisible', () => {
  for (const [name, page] of PAGES) {
    for (const state of STATES) {
      it(`${name} · ${state} paints everything it renders`, async () => {
        arrange(state);
        const { container } = await mount(page());
        await settleAnimations();
        const findings = invisibleContent(container);
        expect(findings, `\n${name} (${state}): content present in the DOM and invisible on `
          + `screen —\n${reportInvisible(findings)}\n`).toEqual([]);
      });

      it(`${name} · ${state} paints everything under prefers-reduced-motion`, async () => {
        // The state where `animation: none` is a correct-looking instruction that can silently
        // delete an element's only path to `opacity: 1`.
        await media([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
        arrange(state);
        const { container } = await mount(page());
        await settleAnimations();
        const findings = invisibleContent(container);
        expect(findings, `\n${name} (${state}, reduced motion): content present in the DOM and `
          + `invisible on screen —\n${reportInvisible(findings)}\n`).toEqual([]);
      });
    }
  }
});

/**
 * Class tokens carried for a reason other than styling. Empty, and it must stay empty.
 *
 * The seventh audit's `G-15` names the shape to avoid: a baseline list is where defects hide, and
 * a 785-entry one would make this check theatre. If a genuine JS-hook class ever needs an entry,
 * it gets a written reason beside it — not a quiet widening.
 */
const EXEMPT = new Set<string>([]);

describe('computed style — every class a page applies is styled by something', () => {
  /**
   * `unstyledClasses` was built for the sixth audit's `A-01` and pointed at **two** surfaces: the
   * palette (already known broken) and a hand-written list of seven pill tones. Not at any of the
   * 23 routed pages.
   *
   * The seventh audit ran it across all 69 page/state pairs and found four classes applied by
   * shipped pages that no rule selects — `set-theme`, `sec-page`, `rsx-rail-card`, `cal-runs`.
   * Its sentence is the one worth keeping: *"the repository built the detector for this exact
   * defect class and pointed it at one modal and one hand-written list."* The sixth round's §E had
   * said *"nothing checks that a class the app applies is styled by anything"*; the fix built the
   * check and aimed it at the finding rather than at the class of finding.
   *
   * `styledClassTokens()` is computed AFTER mount, deliberately: 28 of these pages inject their
   * CSS as a `<style>` block when they render, so reading the stylesheet list before mounting
   * would report every one of their classes as unstyled.
   */
  for (const [name, page] of PAGES) {
    for (const state of STATES) {
      it(`${name} · ${state} applies no class that nothing selects`, async () => {
        arrange(state);
        const { container } = await mount(page());
        const findings = unstyledClasses(container, styledClassTokens(), EXEMPT);
        expect(findings, `\n${name} (${state}): classes applied and defined by no rule —\n`
          + `${reportUnstyled(findings)}\n`).toEqual([]);
      });
    }
  }
});

describe('computed style — an element that promises an entrance runs it', () => {
  for (const [name, page] of PAGES) {
    for (const state of STATES) {
      it(`${name} · ${state} runs every animation its classes declare`, async () => {
        arrange(state);
        const { container } = await mount(page());
        // Deliberately NOT settled: this check is about the DECLARATION reaching the element, and
        // `animation-name` says so whether or not the animation has been seeked.
        const findings = clobberedMotion(container);
        expect(findings, `\n${name} (${state}): a class promises a keyframe animation the cascade `
          + `does not run —\n${reportClobbered(findings)}\n`).toEqual([]);
      });
    }
  }
});
