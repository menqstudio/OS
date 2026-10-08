import { describe, it, expect, vi } from 'vitest';

// `computedStyle.ts` imports `cdp` from `vitest/browser` for its media-emulation helper, and that
// module refuses to load outside Browser Mode. Nothing under test here touches it.
vi.mock('vitest/browser', () => ({ cdp: () => ({}) }));

import { contrastRatio } from './computedStyle';

// `contrastRatio` is the number a real-Chromium spec gates `>= 4.5` on. It is pure arithmetic over
// the strings the browser computed, so the arithmetic can be held here, outside a browser.
//
// What it did with a colour it could not read: treat it as BLACK. `parseRgb` reads only
// `rgb()` / `rgba()`, and Chromium serialises every `color-mix()` as `color(srgb …)`. So text in
// a colour the helper cannot parse, on white, scored 21:1 — the best possible result, for a
// measurement that was never taken.

describe('contrastRatio — a colour it cannot read is not a passing colour', () => {
  it('measures what it can read: black on white is 21, a mid grey on white is below AA', () => {
    expect(contrastRatio('rgb(0, 0, 0)', 'rgb(255, 255, 255)')).toBeCloseTo(21, 5);
    expect(contrastRatio('rgb(150, 150, 150)', 'rgb(255, 255, 255)')).toBeLessThan(4.5);
  });

  it.each([
    ['a color-mix, as Chromium serialises it', 'color(srgb 0.6 0.6 0.6)'],
    ['an empty string', ''],
    ['a keyword', 'transparent'],
  ])('%s as the FOREGROUND does not pass a 4.5 gate', (_name, unreadable) => {
    const ratio = contrastRatio(unreadable, 'rgb(255, 255, 255)');
    expect(ratio >= 4.5).toBe(false);
    expect(Number.isNaN(ratio)).toBe(true);
  });

  it('an unreadable BACKGROUND does not pass either', () => {
    const ratio = contrastRatio('rgb(255, 255, 255)', 'color(srgb 0.1 0.1 0.1)');
    expect(ratio >= 4.5).toBe(false);
    expect(Number.isNaN(ratio)).toBe(true);
  });
});
