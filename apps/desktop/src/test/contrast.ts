/**
 * WCAG contrast, computed from the live CSSOM — for the backgrounds axe-core cannot read.
 *
 * `axe-core`'s colour parser understands `rgb()` and `rgba()`. It does **not** understand
 * `color(srgb r g b)`, which is what Chromium's *computed* value is for any `color-mix()`. This app
 * uses `color-mix()` for 21 background rules in `ui.css` and for the selected notification band, so
 * axe reported those elements as violations with a ratio of **NaN** and a background of
 * `#0NaN0NaN0NaN`.
 *
 * That is a tooling limit, not a defect, and both of the easy answers are wrong:
 *
 *   * treating `NaN` as a pass hides real failures — and those elements are badges and the
 *     *selected* row, which is exactly where the eighth audit's `H-03` defect lived;
 *   * treating `NaN` as a failure invents findings in working code, which is how a gate gets
 *     switched off.
 *
 * So the ratio is computed instead: parse whatever Chromium reports, composite the element's
 * background over its ancestors until something opaque is reached, and apply the WCAG 2.x formula.
 * The same formula `tools/check_contrast.py` uses on the committed token pairs — that one checks
 * declared colours, this one checks what was actually painted.
 */

/** `[r, g, b, a]` with channels 0–255 and alpha 0–1, or `null` when the value is not a colour. */
export type Rgba = [number, number, number, number];

/**
 * Parse the forms a browser's *computed* style can hand back.
 *
 * `color(srgb …)` carries 0–1 components, which is the shape Chromium resolves `color-mix()` to and
 * the one that makes axe return NaN. `transparent` is a colour with zero alpha rather than an
 * absence, because compositing needs it to behave like one.
 */
export function parseColor(value: string): Rgba | null {
  const v = value.trim();
  if (!v || v === 'none') return null;
  if (v === 'transparent') return [0, 0, 0, 0];

  const rgb = v.match(/^rgba?\(([^)]*)\)$/i);
  if (rgb) {
    const parts = rgb[1].split(/[\s,/]+/).filter(Boolean).map(Number);
    if (parts.length < 3 || parts.slice(0, 3).some(Number.isNaN)) return null;
    const alpha = parts.length > 3 && !Number.isNaN(parts[3]) ? parts[3] : 1;
    return [parts[0], parts[1], parts[2], alpha];
  }

  const srgb = v.match(/^color\(\s*srgb\s+([^)]*)\)$/i);
  if (srgb) {
    const parts = srgb[1].split(/[\s/]+/).filter(Boolean).map(Number);
    if (parts.length < 3 || parts.slice(0, 3).some(Number.isNaN)) return null;
    const alpha = parts.length > 3 && !Number.isNaN(parts[3]) ? parts[3] : 1;
    return [parts[0] * 255, parts[1] * 255, parts[2] * 255, alpha];
  }
  return null;
}

/** `src` painted over `dst`, both opaque-or-not, in straight sRGB — the browser's own model. */
export function composite(src: Rgba, dst: Rgba): Rgba {
  const a = src[3] + dst[3] * (1 - src[3]);
  if (a === 0) return [0, 0, 0, 0];
  const ch = (i: number) => (src[i] * src[3] + dst[i] * dst[3] * (1 - src[3])) / a;
  return [ch(0), ch(1), ch(2), a];
}

/** Relative luminance, WCAG 2.x. */
export function luminance([r, g, b]: Rgba): number {
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

/** Contrast ratio between two OPAQUE colours, WCAG 2.x. */
export function ratio(fg: Rgba, bg: Rgba): number {
  const [a, b] = [luminance(fg), luminance(bg)].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}

/**
 * The colour actually behind `el`: its own background composited over each ancestor's, stopping at
 * the first fully opaque result. Falls back to white, the assumption a browser itself makes when
 * nothing in the tree paints.
 */
export function effectiveBackground(el: Element): Rgba {
  let acc: Rgba = [0, 0, 0, 0];
  let node: Element | null = el;
  while (node) {
    const own = parseColor(getComputedStyle(node).backgroundColor);
    if (own && own[3] > 0) {
      acc = composite(acc, own);
      if (acc[3] >= 0.999) return acc;
    }
    node = node.parentElement;
  }
  return composite(acc, [255, 255, 255, 1]);
}

/**
 * The AA threshold for this element's text: 3.0 for large text (≥ 24px, or ≥ 18.66px bold),
 * 4.5 otherwise. Same rule `contrast-pairs.json` encodes as `size: large`.
 */
export function threshold(el: Element): number {
  const style = getComputedStyle(el);
  const px = parseFloat(style.fontSize) || 16;
  const weight = Number(style.fontWeight) || 400;
  const large = px >= 24 || (px >= 18.66 && weight >= 700);
  return large ? 3 : 4.5;
}

/** The measured ratio for an element's own text against what is really behind it. */
export function measuredContrast(el: Element): { ratio: number; fg: Rgba; bg: Rgba; need: number } {
  const style = getComputedStyle(el);
  const fgRaw = parseColor(style.color) ?? [0, 0, 0, 1];
  const bg = effectiveBackground(el);
  // Text alpha composites over the background exactly as any other layer does; `opacity` on an
  // ancestor is NOT in `color`, which is why an opacity-dimmed label can pass a token check and
  // fail on screen. `opacity` is folded in below.
  const inherited = ancestorOpacity(el);
  const fg = composite([fgRaw[0], fgRaw[1], fgRaw[2], fgRaw[3] * inherited], bg);
  return { ratio: ratio(fg, bg), fg, bg, need: threshold(el) };
}

/** The product of every `opacity` from `el` up to the document — the multiplier a token gate cannot see. */
function ancestorOpacity(el: Element): number {
  let total = 1;
  let node: Element | null = el;
  while (node) {
    const o = parseFloat(getComputedStyle(node).opacity);
    if (!Number.isNaN(o)) total *= o;
    node = node.parentElement;
  }
  return total;
}
