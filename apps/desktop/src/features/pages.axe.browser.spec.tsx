import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, cleanup } from '@testing-library/react';
import axe from 'axe-core';

/**
 * Accessibility in a REAL browser, with the stylesheet attached — the word `production`.
 *
 * Phase 10 asks for a *"production a11y + performance gate pass over all 22 pages"*. Two of the
 * three pieces were already there and one was not, and the missing one is not a detail:
 *
 *   * `pages.a11y.spec.tsx` runs axe over all 23 route components — in **jsdom**, with
 *     `css: false`. Its own docstring says what that costs: *"axe's `color-contrast` rule cannot
 *     execute here and does not."* Under jsdom that rule is reported **incomplete**, never as a
 *     violation, so a page could ship unreadable text and the gate would stay green.
 *   * `tools/check_contrast.py` checks **56 declared token pairs**. That is a different claim from
 *     *"this rendered page passes"*: it cannot see a colour set inline, a composite built by
 *     stacking translucent layers, text over a gradient, an inherited colour, or a pair nobody
 *     thought to declare.
 *   * `pages.browser.spec.tsx` has the real browser and the real CSS, and measures opacity and
 *     animation — not accessibility.
 *
 * This file is the intersection nobody had: **axe, with `color-contrast` enabled, in Chromium, over
 * the same 23 pages, with the app's whole stylesheet graph loaded.** The rule set is otherwise the
 * same one the jsdom sweep uses, so the two do not disagree about what an accessible page is; this
 * one simply gets to run the rules that need layout.
 *
 * # The two states, and why not four
 *
 * `pages.browser.spec.tsx` measures four states because invisibility is a *transient* defect —
 * `A-01` lived only while a read was in flight. Contrast is not transient: it is a property of
 * colours and composites, and a skeleton's shimmer is not text anybody reads. So this sweep visits
 * the two states a person actually reads:
 *
 *   * `populated`   — a page with data in it, which is where nearly all real text lives;
 *   * `unreachable` — the fail-closed state every governed surface permanently ships in, whose copy
 *                     is written in danger and warning tones and is therefore the most likely to be
 *                     the one that fails.
 *
 * Skipping `pending` is a decision, not an oversight: a loading skeleton has no text to contrast,
 * and adding 23 more browser mounts to assert that would buy a slower gate and no finding.
 */

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class { onmessage: unknown = null; },
}));

import { AppProvider } from '../app/store';
import { Shell } from '../components/Shell';
import { CommandPalette } from '../components/CommandPalette';
import { ToastProvider } from '../components/toast';
import { PAGES, arrange as arrangeInvoke, type State } from './pages.fixtures';
import { settleAnimations } from '../test/computedStyle';
import { measuredContrast } from '../test/contrast';

/**
 * The rule set. WCAG 2.0/2.1 A and AA, which is the standard this cockpit's design gates already
 * hold themselves to (`check_contrast.py` uses the AA 4.5:1 floor).
 *
 * `region` is disabled for the same reason `src/test/axe.ts` disables it: these specs mount a page
 * component in isolation rather than the whole document, so *"all page content must be inside a
 * landmark"* is a fact about a harness, not about the page. Nothing else is disabled — in
 * particular `color-contrast` is deliberately left ON, because it is the entire reason this file
 * exists and turning it off would make the sweep a slower copy of the jsdom one.
 */
const AXE_OPTIONS: axe.RunOptions = {
  runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
  rules: { region: { enabled: false } },
};

/** The states a person reads. See the file docstring for why `pending` is not one of them. */
const STATES: State[] = ['populated', 'unreachable'];

/**
 * BOTH themes, and the light one is not an afterthought — it is where the failures have been.
 *
 * The eighth audit's `H-03` (the palette's SELECTED row was the least readable row in the list) and
 * the ninth's `I-04` (two shipped pairs at 4.4995 and 4.4996) were both **light-theme** defects. The
 * app boots dark, so a sweep that only mounts and measures gets the safer half of the product and
 * reports it as the whole.
 */
const THEMES = ['dark', 'light'] as const;

/**
 * Set the theme the way the app does — through the store, not by poking the attribute.
 *
 * The first version of this wrote `document.documentElement.dataset.theme` before mounting and the
 * light half of the matrix was **vacuous**: `AppProvider` reads `localStorage['brops.theme']` into
 * state and writes `data-theme` from an effect, so it overwrote the attribute a moment later and
 * every "light" test measured the dark theme. It was green, twice, and meant nothing. Seeding the
 * key is the same switch a reader flips, and `both themes really differ` is what stops this from
 * silently coming back.
 */
function useTheme(theme: (typeof THEMES)[number]) {
  localStorage.setItem('brops.theme', JSON.stringify(theme));
  document.documentElement.setAttribute('data-theme', theme);
}

const inert = () => invokeMock.mockReset().mockImplementation(() => Promise.resolve(null));
beforeEach(inert);
afterEach(() => {
  inert();
  // Never leak a theme into the next test — the mistake `emulateMedia` already records next door.
  localStorage.removeItem('brops.theme');
  document.documentElement.setAttribute('data-theme', 'dark');
});

async function mount(node: React.ReactElement, { reads = true } = {}) {
  const view = render(<AppProvider><ToastProvider>{node}</ToastProvider></AppProvider>);
  // `reads: false` for a surface that talks to no backend. The command palette is one: it is a
  // keyboard router over static route metadata, so waiting for an IPC call that never comes
  // would time out and read exactly like a page defect.
  if (reads) await waitFor(() => expect(invokeMock).toHaveBeenCalled());
  await act(async () => { await Promise.resolve(); });
  // Settle the entrance animations BEFORE axe looks. Not a softening — the opposite. Nearly every
  // element in this app arrives through `.reveal`, which starts at `opacity: 0`, and axe computes
  // contrast against the BLENDED colour it can see. Measuring mid-entrance produced ratios of
  // 1.01 and 1.02 with foregrounds like `#07090f` on `#05070c`: black on black, which is a
  // description of an animation frame and not of anything a reader ever sees. The same call, for
  // the same reason, is what `pages.browser.spec.tsx` does before measuring opacity.
  await settleAnimations();
  return view;
}

/** A contrast node axe could not read, with the ratio measured from the CSSOM instead. */
type Unreadable = { target: string; ratio: number; need: number; fg: string; bg: string };

const hex = (c: readonly number[]) =>
  '#' + [c[0], c[1], c[2]].map((n) => Math.round(n).toString(16).padStart(2, '0')).join('');

/**
 * Separate the violations axe really measured from the ones it could not read.
 *
 * `axe-core` parses `rgb()`/`rgba()` and not `color(srgb …)`, which is Chromium's computed value for
 * every `color-mix()`. This app uses `color-mix()` for 21 background rules in `ui.css` and for the
 * selected notification band, so axe reported those as violations with a ratio of **NaN** and a
 * background of `#0NaN0NaN0NaN`. Both easy answers are wrong — treating NaN as a pass hides real
 * failures on badges and *selected* rows, which is exactly where `H-03` lived, and treating it as a
 * failure invents findings in working code. So they are measured here, by `src/test/contrast.ts`,
 * and reported with a real number.
 */
function split(results: axe.AxeResults) {
  const real: axe.Result[] = [];
  const unreadable: Unreadable[] = [];
  for (const violation of results.violations) {
    if (violation.id !== 'color-contrast') { real.push(violation); continue; }
    const kept: typeof violation.nodes = [];
    for (const node of violation.nodes) {
      const unresolved = (node.any ?? []).some((c) => Number.isNaN((c.data as { contrastRatio?: number })?.contrastRatio ?? NaN))
        || (node.failureSummary ?? '').includes('NaN');
      // `element` is present at runtime and absent from axe's published type. The selector is the
      // documented route, and it is the one used: a node's `target` is a CSS path axe built from
      // the live tree, so it resolves to the same element.
      const el = document.querySelector(String(node.target[node.target.length - 1]));
      if (unresolved && el) {
        const m = measuredContrast(el);
        unreadable.push({
          target: node.target.join(' '),
          ratio: m.ratio, need: m.need, fg: hex(m.fg), bg: hex(m.bg),
        });
      } else {
        kept.push(node);
      }
    }
    if (kept.length) real.push({ ...violation, nodes: kept });
  }
  return { real, unreadable };
}

const describeUnreadable = (u: Unreadable) =>
  `  ${u.target}\n      measured ${u.ratio.toFixed(2)}:1, needs ${u.need}:1 `
  + `(text ${u.fg} on ${u.bg})`;

/** One line per violation, with the element and the measured ratio when axe reports one. */
function report(violations: axe.Result[]): string {
  return violations.map((v) => {
    const where = v.nodes.slice(0, 3).map((n) => {
      const summary = (n.failureSummary ?? '').split('\n').filter(Boolean).slice(1).join(' ');
      return `      ${n.target.join(' ')}\n        ${summary}`;
    }).join('\n');
    const more = v.nodes.length > 3 ? `\n      … and ${v.nodes.length - 3} more element(s)` : '';
    return `  [${v.impact}] ${v.id} — ${v.help}\n${where}${more}`;
  }).join('\n');
}

describe('accessibility in a real browser, with the stylesheet attached', () => {
  for (const [name, page] of PAGES) {
    for (const state of STATES) {
      for (const theme of THEMES) {
        it(`${name} · ${state} · ${theme} has no WCAG A/AA violation`, async () => {
          useTheme(theme);
          arrangeInvoke(invokeMock, state);
          const { container } = await mount(page());
          const results = await axe.run(container, AXE_OPTIONS);
          const { real, unreadable } = split(results);
          expect(real, `\n${name} (${state}, ${theme}) — WCAG A/AA violations in a real `
            + `browser with real CSS:\n${report(real)}\n`).toEqual([]);
          // The nodes axe could not read are measured here instead of being dropped. See `split`.
          const failed = unreadable.filter((u) => u.ratio + 0.005 < u.need);
          expect(failed, `\n${name} (${state}, ${theme}) — contrast axe could not compute, measured `
            + `directly from the CSSOM:\n${failed.map(describeUnreadable).join('\n')}\n`).toEqual([]);
        });
      }
    }
  }

  it('both themes really differ — the light half of the matrix is not vacuous', async () => {
    // The guard for the mistake this file already made once. `AppProvider` writes `data-theme` from
    // its own state in an effect, so setting the attribute before mounting is overwritten and every
    // "light" test silently measures the dark theme. Two greens proved nothing until this existed.
    const background = async (theme: (typeof THEMES)[number]) => {
      useTheme(theme);
      arrangeInvoke(invokeMock, 'populated');
      const { container } = await mount(PAGES[0][1]());
      const value = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();
      return { value, attr: document.documentElement.getAttribute('data-theme'), container };
    };
    const dark = await background('dark');
    cleanup();
    const light = await background('light');
    expect(dark.attr).toBe('dark');
    expect(light.attr, 'AppProvider must not have overwritten the theme back to dark').toBe('light');
    expect(light.value, `--bg must differ between themes; got ${dark.value} and ${light.value}`)
      .not.toBe(dark.value);
  });

  it('color-contrast really runs here — the rule this file exists for is not silently skipped', async () => {
    // The jsdom sweep reports `color-contrast` as INCOMPLETE and never as a violation, and a
    // reader has no way to tell that apart from "it passed". So this asserts the rule actually
    // EXECUTED: axe must place it in `passes` or `violations`, never in `inapplicable`, and the
    // incomplete list must not be where it ends up either.
    arrangeInvoke(invokeMock, 'populated');
    const { container } = await mount(PAGES[0][1]());
    const results = await axe.run(container, AXE_OPTIONS);
    const ran = [...results.passes, ...results.violations].some((r) => r.id === 'color-contrast');
    const inapplicable = results.inapplicable.some((r) => r.id === 'color-contrast');
    expect(ran, 'color-contrast must have executed against real CSS').toBe(true);
    expect(inapplicable, 'color-contrast must not be inapplicable here — under jsdom it always is')
      .toBe(false);
    // `incomplete` is NOT asserted against. axe puts a node there when it cannot resolve a
    // background, and this app has such nodes by construction (`color-mix()`); the first draft of
    // this test failed for that reason and would have been "fixed" by deleting the check. Those
    // nodes are measured by `split()` instead, which is a stronger claim than the one this
    // assertion was reaching for.
  });

  // The shell and its modal, with CSS. `pages.a11y.spec.tsx` covers both in jsdom; the palette is
  // where the eighth audit's `H-03` lived — the SELECTED row, the one the keyboard cursor points at,
  // was the least readable row in the list — and a selected row's colour is exactly what a sweep
  // without a stylesheet cannot see.
  it('the app frame has no WCAG A/AA violation, with real CSS', async () => {
    arrangeInvoke(invokeMock, 'populated');
    const { container } = await mount(<Shell><h1>Stage</h1></Shell>);
    const { real, unreadable } = split(await axe.run(container, AXE_OPTIONS));
    expect(real, `\nshell — ${report(real)}\n`).toEqual([]);
    expect(unreadable.filter((u) => u.ratio + 0.005 < u.need)
      .map(describeUnreadable)).toEqual([]);
  });

  it('the ⌘K command dock has no WCAG A/AA violation while OPEN, with real CSS', async () => {
    arrangeInvoke(invokeMock, 'populated');
    const { container } = await mount(<><CommandPalette /><main><h1>Stage</h1></main></>, { reads: false });
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }));
    });
    await screen.findByRole('dialog');
    await settleAnimations();
    const { real, unreadable } = split(await axe.run(container, AXE_OPTIONS));
    expect(real, `\ncommand dock — ${report(real)}\n`).toEqual([]);
    const failed = unreadable.filter((u) => u.ratio + 0.005 < u.need);
    expect(failed, `\ncommand dock — contrast axe could not compute, measured directly:\n`
      + `${failed.map(describeUnreadable).join('\n')}\n`).toEqual([]);
  });

  it('the measured route is not a sink: it reports a real ratio, and a low one fails', async () => {
    // `split()` sends every node axe could not read to a measurement of our own, and a measurement
    // that always passes would be indistinguishable from deleting the check. `contrast.browser.spec.ts`
    // pins the maths against hand-computed values; this pins the WIRING — that the numbers reaching
    // the assertion are real, finite, and on the right side of the threshold.
    arrangeInvoke(invokeMock, 'populated');
    const { container } = await mount(PAGES[0][1]());

    const good = document.createElement('p');
    good.setAttribute('style', 'color:#ffffff;background:#000000;font-size:14px');
    good.textContent = 'readable';
    const bad = document.createElement('p');
    bad.setAttribute('style', 'color:#bbbbbb;background:#ffffff;font-size:14px');
    bad.textContent = 'unreadable';
    container.append(good, bad);

    const g = measuredContrast(good);
    const b = measuredContrast(bad);
    expect(Number.isFinite(g.ratio) && Number.isFinite(b.ratio), 'ratios must be real numbers').toBe(true);
    expect(g.ratio).toBeGreaterThan(g.need);
    expect(b.ratio).toBeLessThan(b.need);
  });

  it('the sweep is not vacuous: a deliberately unreadable element IS caught', async () => {
    // A positive control, because a green accessibility gate and a broken one look identical.
    // Grey-on-white at roughly 1.6:1 — well under the 4.5:1 floor.
    arrangeInvoke(invokeMock, 'populated');
    const { container } = await mount(PAGES[0][1]());
    const bad = document.createElement('p');
    bad.textContent = 'this text is deliberately unreadable';
    bad.setAttribute('style', 'color:#bbbbbb;background:#ffffff;font-size:14px');
    container.appendChild(bad);
    const results = await axe.run(container, AXE_OPTIONS);
    const { real, unreadable } = split(results);
    const caught = real.some((v) => v.id === 'color-contrast')
      || unreadable.some((u) => u.ratio < u.need);
    expect(caught, 'the planted low-contrast paragraph must be reported by one route or the other')
      .toBe(true);
  });
});
