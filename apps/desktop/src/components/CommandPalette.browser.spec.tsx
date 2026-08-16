import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import {
  settleAnimations, invisibleContent, clobberedMotion, unstyledClasses, styledClassTokens,
  reportUnstyled,
} from '../test/computedStyle';

/**
 * The ⌘K palette, measured — sixth independent audit, `A-01`.
 *
 * The finding, in its own words: the palette *"has had no CSS since 2026-07-28; it is not a
 * modal."* Its five classes were defined in `layout.css`, deleted whole in `0c08dd8` (PR #47,
 * "UI refreshes") and never replaced. `layout.css` still exists and is still imported at
 * `Shell.tsx:2`. The component kept rendering `palette-scrim`, `palette`, `palette-list`,
 * `palette-item` and `palette-section-label` into a stylesheet that had stopped defining them.
 *
 * For nineteen days the app's only modal was a stack of unstyled block divs in normal flow: no
 * overlay, no backdrop, no panel box, no width limit, no scroll container for 23 nav rows, and an
 * `active` row that highlighted nothing while `aria-activedescendant` told a screen reader the
 * selection had moved. Three PRs touched the file. Thirty-three green checks per PR.
 *
 * Two audits examined this component and both probed the MECHANISM — the focus trap, the mousedown
 * guard, the keyboard route — rather than the rendering. This round's own trap fix reasons in a
 * comment about "pressing on the panel's padding"; the panel has no padding.
 *
 * So the assertions below are about the palette being a MODAL, not about it having a class list.
 * Each is a fact the auditor measured in Chromium at `b16e572` and each one failed there.
 */

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class { onmessage: unknown = null; },
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { CommandPalette } from './CommandPalette';

beforeEach(() => {
  invokeMock.mockReset();
  invokeMock.mockImplementation(() => Promise.resolve([]));
});

/** Mount the palette with a real, clickable control behind it, and open it. */
async function openPalette() {
  const view = render(
    <AppProvider>
      <ToastProvider>
        <CommandPalette />
        <main>
          <h1>Stage</h1>
          <button type="button" id="behind" style={{ position: 'fixed', top: 200, left: 40 }}>
            a control the modal must cover
          </button>
        </main>
      </ToastProvider>
    </AppProvider>,
  );
  act(() => {
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }));
  });
  await screen.findByRole('dialog');
  await settleAnimations();
  return view;
}

const q = (sel: string) => document.querySelector(sel) as HTMLElement;

describe('⌘K palette — the classes it renders are styled by something', () => {
  it('every class the palette applies is selected by at least one rule', async () => {
    // THE GATE THE REPOSITORY DID NOT HAVE. `check_c1_tokens.py` proves every custom-property
    // reference resolves; nothing proved that `.palette-item.active` resolves. Both defects are
    // one query apart and only one had a gate.
    const { container } = await openPalette();
    const findings = unstyledClasses(container, styledClassTokens(), EXEMPT);
    expect(findings, `\nthe palette renders classes no stylesheet defines —\n`
      + `${reportUnstyled(findings)}\n`).toEqual([]);
  });
});

/**
 * Class tokens carried for a reason other than styling. Each needs a reason; a bare list is how an
 * exemption becomes a place to hide a defect.
 *
 * Empty today, deliberately. It exists so that the first genuine JS-hook class gets an entry with
 * a justification rather than a quiet widening of the check.
 */
const EXEMPT = new Set<string>([]);

describe('⌘K palette — it behaves as a modal, not as block divs in normal flow', () => {
  it('the scrim covers the viewport and sits above the page', async () => {
    await openPalette();
    const scrim = q('.palette-scrim');
    const style = getComputedStyle(scrim);
    expect(style.position, 'a scrim in normal flow is not a scrim').toBe('fixed');
    expect(parseInt(style.zIndex || '0', 10)).toBeGreaterThan(0);

    const rect = scrim.getBoundingClientRect();
    expect(rect.width).toBeGreaterThanOrEqual(window.innerWidth);
    expect(rect.height).toBeGreaterThanOrEqual(window.innerHeight);
  });

  it('the scrim is a visible backdrop, not transparent', async () => {
    // Measured at b16e572 as `rgba(0, 0, 0, 0)` — present in the DOM, absent on screen.
    await openPalette();
    const bg = getComputedStyle(q('.palette-scrim')).backgroundColor;
    const alpha = /rgba?\([^)]*?,\s*([\d.]+)\)$/.exec(bg);
    expect(alpha ? parseFloat(alpha[1]) : 1,
      `the scrim's background is ${bg} — a backdrop nobody can see`).toBeGreaterThan(0);
  });

  it('the page behind is not clickable while aria-modal says it is inert', async () => {
    // `aria-modal="true"` is a PROMISE to assistive technology. Without a scrim that covers the
    // page, `document.elementFromPoint` over a background control still returns that control, and
    // the promise is false for everyone who is not using a screen reader.
    await openPalette();
    const behind = document.getElementById('behind')!;
    const r = behind.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    expect(hit === behind || behind.contains(hit),
      'a control behind the open modal is still the top element at its own coordinates').toBe(false);
  });

  it('the panel is a bounded box, not a full-width run of text', async () => {
    await openPalette();
    const panel = q('.palette');
    const style = getComputedStyle(panel);
    expect(panel.getBoundingClientRect().width).toBeLessThan(window.innerWidth);
    expect(parseFloat(style.paddingTop) + parseFloat(style.paddingBottom),
      'the trap fix reasons about "the panel\'s padding"; this asserts it exists').toBeGreaterThan(0);
    expect(style.borderTopWidth === '0px' && style.backgroundColor === 'rgba(0, 0, 0, 0)',
      'the panel has neither a border nor a background — it is not a panel').toBe(false);
  });

  it('the result list scrolls instead of running off the page', async () => {
    // 23 nav rows plus entity results, in a container with `max-height: none; overflow-y: visible`.
    await openPalette();
    const style = getComputedStyle(q('.palette-list'));
    expect(style.maxHeight, 'an unbounded list is not a list').not.toBe('none');
    expect(['auto', 'scroll'], `overflow-y is ${style.overflowY}`).toContain(style.overflowY);
  });

  it('the ACTIVE row is visually distinct — the keyboard cursor a sighted user follows', async () => {
    // The audit's sharpest sentence: arrow down moves `aria-activedescendant` and a screen reader
    // announces the row, "while a sighted keyboard user sees no change whatsoever".
    await openPalette();
    const active = q('.palette-item.active');
    const inactive = document.querySelector('.palette-item:not(.active)') as HTMLElement;
    expect(active, 'no row is active on open').toBeTruthy();
    expect(inactive, 'only one row rendered; cannot compare').toBeTruthy();

    const a = getComputedStyle(active);
    const b = getComputedStyle(inactive);
    const distinct = a.backgroundColor !== b.backgroundColor
      || a.color !== b.color
      || a.outlineWidth !== b.outlineWidth
      || a.borderLeftColor !== b.borderLeftColor
      || a.boxShadow !== b.boxShadow;
    expect(distinct, `active and inactive rows compute identically `
      + `(background ${a.backgroundColor}, color ${a.color})`).toBe(true);
  });

  it('rows have hit area — a zero-padding row is a text line, not a target', async () => {
    await openPalette();
    const row = q('.palette-item');
    expect(row.getBoundingClientRect().height,
      'measured 0px padding at b16e572').toBeGreaterThanOrEqual(32);
  });
});

describe('⌘K palette — the two detectors that could NOT see this, recorded as fact', () => {
  it('nothing in the palette is invisible, and nothing clobbers an animation', async () => {
    // Kept as a positive assertion because it is the honest boundary of the other two checks: the
    // palette was never at `opacity: 0` and never promised an animation it did not run. It was
    // simply undesigned. A suite that only measured opacity and animation-name would have gone
    // green on the worst-shipping defect in the app, which is why `unstyledClasses` exists.
    const { container } = await openPalette();
    expect(invisibleContent(container)).toEqual([]);
    expect(clobberedMotion(container)).toEqual([]);
  });
});
