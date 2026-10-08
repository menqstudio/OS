import { describe, it, expect, vi } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';

// `computedStyle.ts` imports `cdp` from `vitest/browser` for its media-emulation helper, and that
// module refuses to load outside Browser Mode. Nothing under test here touches it.
vi.mock('vitest/browser', () => ({ cdp: () => ({}) }));

import { contrastRatio } from './computedStyle';
import { belowNeed } from './contrast';

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

// The real-Chromium accessibility spec measures the nodes axe cannot read and filtered them with
// `u.ratio + 0.005 < u.need`: a ratio of 4.4995 passed a 4.5 requirement. That is the rounding
// toward passing the ninth audit removed from `tools/check_contrast.py`, which compares the RAW
// ratio and names 4.4996 and 4.4995 as the cases. And a ratio that is not a number compared
// false both ways, so a measurement that was never taken passed too.
describe('belowNeed — the verdict is on the raw ratio, and no number is not a pass', () => {
  it('fails a ratio a hair under the requirement', () => {
    expect(belowNeed(4.4995, 4.5)).toBe(true);
    expect(belowNeed(4.4999, 4.5)).toBe(true);
    expect(belowNeed(2.9996, 3)).toBe(true);
  });

  it('passes a ratio that meets it exactly or exceeds it', () => {
    expect(belowNeed(4.5, 4.5)).toBe(false);
    expect(belowNeed(7.1, 4.5)).toBe(false);
  });

  it('fails a ratio that was never measured', () => {
    expect(belowNeed(Number.NaN, 4.5)).toBe(true);
  });
});

// A `transition` or `animation` item takes ONE easing function. `--slow` is
// `220ms cubic-bezier(…)` — a duration AND an easing — so `var(--slow) var(--spring)` expands to two
// easings, and the browser drops the whole declaration: the page-enter animation, the active-icon
// pop and three spring transitions in `aios-shell.css` were written and never ran. Nothing failed,
// because an invalid declaration is not an error anywhere; this reads the stylesheets and counts.
describe('no transition or animation item carries two easing functions', () => {
  const SRC = resolve(__dirname, '..');
  const cssFiles = (dir: string): string[] => readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? cssFiles(join(dir, e.name)) : e.name.endsWith('.css') ? [join(dir, e.name)] : []);
  const files = cssFiles(SRC);
  const sheets = files.map((f) => ({ f, css: readFileSync(f, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '') }));

  // Every custom property declared anywhere, last one wins — enough to expand the motion tokens.
  const tokens = new Map<string, string>();
  for (const { css } of sheets) {
    for (const m of css.matchAll(/(--[\w-]+)\s*:\s*([^;}]+)/g)) tokens.set(m[1], m[2].trim());
  }
  const expand = (value: string, depth = 0): string => depth > 8 ? value
    : value.replace(/var\(\s*(--[\w-]+)\s*(?:,[^()]*)?\)/g, (_all, name: string) => expand(tokens.get(name) ?? '', depth + 1));
  const topLevelItems = (value: string): string[] => {
    const out: string[] = []; let depth = 0; let cur = '';
    for (const ch of value) {
      if (ch === '(') depth += 1;
      if (ch === ')') depth -= 1;
      if (ch === ',' && depth === 0) { out.push(cur); cur = ''; } else cur += ch;
    }
    return [...out, cur];
  };
  const EASING = /cubic-bezier\(|steps\(|linear\(|\b(?:ease-in-out|ease-in|ease-out|ease|linear|step-start|step-end)\b/g;

  it('finds the stylesheets and the motion tokens it needs', () => {
    expect(files.length).toBeGreaterThan(3);
    expect(tokens.get('--slow')).toMatch(/cubic-bezier/);
    expect(tokens.get('--spring')).toMatch(/cubic-bezier/);
  });

  it('holds across every stylesheet under src/', () => {
    const doubled: string[] = [];
    for (const { f, css } of sheets) {
      for (const m of css.matchAll(/(?:^|[;{\s])(transition|animation)\s*:\s*([^;}]+)/g)) {
        for (const item of topLevelItems(expand(m[2]))) {
          const n = (item.match(EASING) ?? []).length;
          if (n > 1) doubled.push(`${f.slice(SRC.length + 1)} — ${m[1]}: ${m[2].trim().replace(/\s+/g, ' ')}`);
        }
      }
    }
    expect(doubled).toEqual([]);
  });
});
