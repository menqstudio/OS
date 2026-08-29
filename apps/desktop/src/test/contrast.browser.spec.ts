import { describe, it, expect, afterEach } from 'vitest';
import {
  parseColor, composite, luminance, ratio, effectiveBackground, threshold, measuredContrast,
} from './contrast';

/**
 * The arithmetic behind the real-browser accessibility sweep, pinned against hand-computed values.
 *
 * `pages.axe.browser.spec.tsx` routes every contrast node axe cannot read to `measuredContrast`.
 * That makes this file's numbers decide whether a page passes an accessibility gate, and a measurer
 * with no test of its own is a measurer that can quietly return a passing number for everything —
 * the precise failure the routing exists to avoid.
 *
 * It runs in the BROWSER project because half of it is `getComputedStyle`, which jsdom answers
 * differently from Chromium; measuring it under jsdom would be the `css: false` mistake again.
 */

const mounted: HTMLElement[] = [];
function el(style: string, tag = 'p'): HTMLElement {
  const node = document.createElement(tag);
  node.setAttribute('style', style);
  node.textContent = 'text';
  document.body.appendChild(node);
  mounted.push(node);
  return node;
}
afterEach(() => { while (mounted.length) mounted.pop()!.remove(); });

describe('parseColor', () => {
  it('reads the forms a computed style hands back', () => {
    expect(parseColor('rgb(10, 20, 30)')).toEqual([10, 20, 30, 1]);
    expect(parseColor('rgba(10, 20, 30, 0.5)')).toEqual([10, 20, 30, 0.5]);
    expect(parseColor('rgb(10 20 30 / 0.25)')).toEqual([10, 20, 30, 0.25]);
    // The form Chromium produces for a `color-mix()` it cannot simplify — the one axe-core
    // cannot parse, and the reason this module exists.
    expect(parseColor('color(srgb 0 0.5 1)')).toEqual([0, 127.5, 255, 1]);
    expect(parseColor('color(srgb 0 0.5 1 / 0.4)')).toEqual([0, 127.5, 255, 0.4]);
  });

  it('treats `transparent` as a colour with no alpha, not as an absence', () => {
    // Compositing needs it to behave like a colour; returning null would make a transparent
    // background indistinguishable from an unparseable one.
    expect(parseColor('transparent')).toEqual([0, 0, 0, 0]);
  });

  it('returns null rather than guessing', () => {
    for (const v of ['', 'none', 'not-a-colour', 'linear-gradient(red, blue)']) {
      expect(parseColor(v), v).toBeNull();
    }
  });
});

describe('the WCAG arithmetic', () => {
  it('reproduces the reference luminances', () => {
    expect(luminance([255, 255, 255, 1])).toBeCloseTo(1, 5);
    expect(luminance([0, 0, 0, 1])).toBeCloseTo(0, 5);
  });

  it('reproduces the reference ratios', () => {
    // Black on white is the definitional 21:1.
    expect(ratio([0, 0, 0, 1], [255, 255, 255, 1])).toBeCloseTo(21, 4);
    // And it is symmetric — the formula sorts, so the caller cannot get it backwards.
    expect(ratio([255, 255, 255, 1], [0, 0, 0, 1])).toBeCloseTo(21, 4);
    // #767676 on white is the canonical "exactly AA" grey.
    expect(ratio([118, 118, 118, 1], [255, 255, 255, 1])).toBeGreaterThanOrEqual(4.5);
    expect(ratio([119, 119, 119, 1], [255, 255, 255, 1])).toBeLessThan(4.5);
  });

  it('composites the way a browser does', () => {
    // 50% white over black is mid-grey, and the result is opaque.
    expect(composite([255, 255, 255, 0.5], [0, 0, 0, 1])).toEqual([127.5, 127.5, 127.5, 1]);
    // Nothing over nothing is still nothing, and does not divide by zero.
    expect(composite([0, 0, 0, 0], [0, 0, 0, 0])).toEqual([0, 0, 0, 0]);
  });
});

describe('effectiveBackground', () => {
  it('walks up to the first opaque ancestor', () => {
    const outer = el('background:#000000;padding:4px', 'div');
    const inner = document.createElement('div');
    inner.setAttribute('style', 'background:transparent');
    outer.appendChild(inner);
    expect(effectiveBackground(inner).slice(0, 3)).toEqual([0, 0, 0]);
  });

  it('composites a translucent background over what is behind it', () => {
    const outer = el('background:#000000;padding:4px', 'div');
    const inner = document.createElement('div');
    inner.setAttribute('style', 'background:rgba(255,255,255,0.5)');
    outer.appendChild(inner);
    const bg = effectiveBackground(inner);
    expect(bg[0]).toBeCloseTo(127.5, 0);
    expect(bg[3]).toBeCloseTo(1, 5);
  });
});

describe('threshold', () => {
  it('is 4.5 for body text and 3.0 for large text', () => {
    expect(threshold(el('font-size:14px'))).toBe(4.5);
    expect(threshold(el('font-size:24px'))).toBe(3);
    expect(threshold(el('font-size:19px;font-weight:700'))).toBe(3);
    // 19px at normal weight is NOT large — the bold half of the rule is not optional.
    expect(threshold(el('font-size:19px;font-weight:400'))).toBe(4.5);
  });
});

describe('measuredContrast', () => {
  it('agrees with the reference values on plain colours', () => {
    expect(measuredContrast(el('color:#000000;background:#ffffff')).ratio).toBeCloseTo(21, 3);
  });

  it('folds in ancestor `opacity` — the multiplier a token gate cannot see', () => {
    // This is the defect mechanism the sweep actually found: `.pill.off { opacity: .62 }` took
    // muted text from 6.53:1 to a measured 3.07:1 while every declared token pair stayed green.
    const box = el('background:#05070c;padding:4px', 'div');
    const full = document.createElement('span');
    full.setAttribute('style', 'color:#8993a8;font-size:10px');
    full.textContent = 'muted';
    const dimmed = document.createElement('span');
    dimmed.setAttribute('style', 'color:#8993a8;font-size:10px;opacity:.62');
    dimmed.textContent = 'muted';
    box.append(full, dimmed);

    const undimmed = measuredContrast(full).ratio;
    const withOpacity = measuredContrast(dimmed).ratio;
    expect(undimmed).toBeGreaterThan(4.5);
    expect(withOpacity).toBeLessThan(4.5);
    expect(withOpacity).toBeLessThan(undimmed);
  });

  it('does not invent a background when nothing paints one', () => {
    // A browser shows white behind an unpainted tree; assuming black would turn every light-theme
    // page into a wall of false findings.
    const orphan = document.createElement('p');
    orphan.setAttribute('style', 'color:#000000');
    expect(effectiveBackground(orphan)).toEqual([255, 255, 255, 1]);
  });
});
