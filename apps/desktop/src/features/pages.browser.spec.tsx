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
import {
  PAGES, POPULATED, arrange as arrangeInvoke, type State,
} from './pages.fixtures';

/** `arrange` moved to `pages.fixtures.tsx` so the axe sweep mounts the same pages with the same
 *  data; it takes the mock because `vi.mock` is hoisted per file and cannot be shared. */
function arrange(state: State) {
  arrangeInvoke(invokeMock, state);
}

const STATES: State[] = ['pending', 'settled', 'unreachable'];

/**
 * `mockReset()` clears the implementation as well as the calls, so a bare reset leaves `invoke`
 * returning `undefined`. React runs a component's unmount cleanup AFTER `afterEach`, and
 * `Conversations.tsx` cancels its in-flight reply there — `desktop.cancelReply(id).catch(…)` — so an
 * unimplemented mock turns teardown into `Cannot read properties of undefined (reading 'catch')` and
 * fails the NEXT test with a stack trace pointing at product code that is behaving correctly.
 *
 * It only surfaced with `populated`, because that is the first state in which a conversation is ever
 * selected and `MessageThread` therefore ever mounts. Resetting to a resolved promise keeps the reset
 * (no call history, no leaked implementation) without making teardown throw.
 */
const inert = () => invokeMock.mockReset().mockImplementation(() => Promise.resolve(null));

beforeEach(inert);
afterEach(async () => {
  inert();
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

describe('populated — every page renders real rows without crashing', () => {
  /**
   * `populated` is NOT in `STATES` yet, and the reason is written here rather than left to be
   * inferred. Running the three sweeps above over it turns **13 of them red**: 24 class tokens that
   * no rule selects, on 12 pages, plus one entrance the `decisions` ledger substitutes rather than
   * runs. Every one is a real finding — they are exactly the 1 886 tokens the eighth audit measured
   * as never shown — and none of them is a defect in these fixtures.
   *
   * Three ways to make the suite green were available and all three are refused:
   *   - add the 24 to `EXEMPT` — this file's own header says a baseline list is where defects hide;
   *   - relax `clobberedMotion` so a substituted entrance passes — that is weakening an assertion to
   *     quiet CI, and the substitution deserves its own decision;
   *   - write 24 CSS rules for surfaces nobody has looked at — inventing a design from a test log.
   *
   * So the fixtures land with the finding, and adding `'populated'` to `STATES` is one line once the
   * 24 are decided. See `T-036`.
   *
   * What this describe DOES assert is the half that is ready and is not vacuous: every page mounts
   * against real rows and renders something. A page that throws on populated data, or renders empty
   * when given rows, fails here — and both were unreachable before, because `arrange('settled')`
   * answered `[]` to everything.
   */
  for (const [name, page] of PAGES) {
    it(`${name} puts its own fixture rows on the screen`, async () => {
      // "It rendered something" is vacuous -- an empty page renders its empty state, and that is
      // text too. "It rendered MORE" was tried and is wrong in three different legitimate ways
      // (`settings` is answered with an object, `security` and `files` fold rows into counts). The
      // property that actually says the fixtures reached the page is that a VALUE from them is
      // readable on it. That cannot be satisfied by an empty state, and it fails on the real ways a
      // fixture table goes wrong: a mistyped command key, a shape the page discards, a row filtered
      // out by a status the page does not recognise.
      arrange('populated');
      const { container } = await mount(page());
      const asked = new Set(invokeMock.mock.calls.map((c) => String(c[0])));
      const wanted: string[] = [];
      for (const cmd of asked) {
        const rows = POPULATED[cmd];
        if (!Array.isArray(rows) || rows.length === 0) continue;
        for (const value of Object.values(rows[0] as Record<string, unknown>)) {
          // Long enough to be this fixture's own words rather than a status token every page shows.
          if (typeof value === 'string' && value.length >= 8 && !value.includes('T0')) {
            wanted.push(value);
          }
        }
      }
      if (wanted.length === 0) return;      // no row-shaped fixture reaches this page; nothing to prove
      const shown = container.textContent ?? '';
      expect(wanted.some((v) => shown.includes(v)),
        `${name} asked for rows and none of their values is on the screen. Looked for any of: `
        + `${wanted.slice(0, 6).join(' | ')}`).toBe(true);
      // WHAT THIS DOES NOT PROVE, written down rather than left to be assumed.
      //
      // `some`, not `every`: a page whose fixtures are ALL wrong fails here, a page where one of
      // three is wrong does not. That was measured, not guessed -- emptying `list_projects` AND
      // `list_agents` left this green, because `projects` also asks for tasks and one surviving
      // fixture satisfied the whole assertion.
      //
      // The per-command version was built and turns FIVE pages red: `home`, `security`, `analytics`,
      // `calendar` and `tasks` each ask for a row command and display no value from it. Some of
      // those are pages folding rows into counts, which is correct and would want a written reason;
      // at least one -- `tasks` not showing a task title -- looks like a real filter the fixtures do
      // not satisfy. Shipping the stronger form would mean either five investigations or a
      // reason-list written to make it green, and a reason-list written that way is the baseline
      // this file's own header refuses. So the weaker form ships with its limit stated, and the five
      // are recorded in `T-036` as the next slice rather than left for someone to rediscover.
    });
  }

  it('no fixture in the table is dead — every key is a command some page actually asks for', async () => {
    // Measured from behaviour, not from a second list: mount all 23 pages, collect the command names
    // they really invoke, and require every fixture key to appear. A renamed or deleted command
    // leaves its fixture behind, and this is what notices — the alternative is a table that grows
    // entries for commands nothing calls, which is the shape `check_reachability` exists to refuse
    // one layer down.
    const asked = new Set<string>();
    for (const [, page] of PAGES) {
      arrange('populated');
      const view = await mount(page());
      for (const call of invokeMock.mock.calls) asked.add(String(call[0]));
      view.unmount();
    }
    const dead = Object.keys(POPULATED).filter((cmd) => !asked.has(cmd));
    expect(dead, 'these fixtures are keyed to commands no page invokes').toEqual([]);
  });
});
