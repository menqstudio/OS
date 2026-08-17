/**
 * The measurement `A-01` needed and no test in this repository could make.
 *
 * `A-01`: `Security.tsx` gained a second `animation` declaration whose shorthand REPLACED the
 * entrance animation it shared a rule with. `.reveal` starts at `opacity: 0` and reaches `1` only
 * because `animation: reveal … forwards` fills it there; clobber that list and the element stays
 * at zero. The page rendered a fully-populated, completely invisible instrument. Every unit test
 * passed, because with `css: false` a test can only ask *"is the string in the className?"* — and
 * it was.
 *
 * These helpers ask the browser instead. They run only in the browser project, where a real CSSOM
 * exists; imported into jsdom they would answer confidently and wrongly, which is why the specs
 * that use them carry the `.browser.spec` suffix that jsdom's globs do not match.
 *
 * Deliberately GENERIC. A per-page assertion ("Security's instrument is visible") would have
 * needed someone to already suspect Security. The invariants below are properties every page must
 * hold, so the next `A-01` is caught on a page nobody was looking at.
 */
import { cdp } from 'vitest/browser';

/**
 * Emulate a media feature for real, through the browser, so it reaches the CASCADE.
 *
 * A `window.matchMedia` stub — what `src/test/setup.ts` installs for jsdom — satisfies the JS that
 * reads the query and leaves the stylesheet untouched, which for a reduced-motion check is
 * theatre: the whole subject is which rules apply. CDP changes what the engine matches.
 *
 * The cast is deliberate and narrow. Vitest declares `interface CDPSession {}` — empty, for a
 * provider package to augment — and the playwright provider does not augment it, so `send` is
 * untyped rather than absent. This states the one method used, in one place, instead of scattering
 * `as any` through the specs.
 */
type CdpSend = { send(method: string, params?: Record<string, unknown>): Promise<unknown> };

export function emulateMedia(features: Array<{ name: string; value: string }>): Promise<unknown> {
  return (cdp() as unknown as CdpSend).send('Emulation.setEmulatedMedia', { features });
}

/** How an element ended up invisible, with the ancestor actually responsible. */
export interface Invisible {
  /** A readable path to the element that should have been visible. */
  where: string;
  /** The text or accessible name a reader was supposed to see. */
  what: string;
  /** The element in the ancestor chain whose own opacity is 0 — often not `where` itself. */
  cause: string;
  /** That element's `animation-name`, because a clobbered entrance is the usual reason. */
  animationName: string;
}

/** An element whose class list promises a keyframe animation the computed style does not run. */
export interface Clobbered {
  where: string;
  /** The class that promises it, e.g. `reveal`. */
  promisedBy: string;
  /** The keyframes name that class declares, e.g. `reveal`. */
  expected: string;
  /** What `animation-name` actually computed to — `none`, or a list that dropped `expected`. */
  actual: string;
}

/** A short, human-findable path: tag + id + classes, two levels up. */
export function describeEl(el: Element): string {
  const one = (e: Element) => {
    const cls = (e.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean);
    return e.tagName.toLowerCase()
      + (e.id ? `#${e.id}` : '')
      + (cls.length ? `.${cls.slice(0, 4).join('.')}` : '');
  };
  const parent = el.parentElement;
  return parent ? `${one(parent)} > ${one(el)}` : one(el);
}

/**
 * Drive every running animation to a DETERMINISTIC point, then let styles recompute.
 *
 * Finite animations are finished, because that is the state a reader sees a moment after the page
 * settles and the state `forwards` is supposed to hold. Infinite ones are parked at mid-cycle
 * rather than finished — `finish()` on an infinite animation throws `InvalidStateError`, and
 * sampling one at whatever moment the test happened to run is how a check becomes flaky.
 *
 * The point of driving them at all: `A-01`'s element was at `opacity: 0` *permanently*, but so is
 * every `.reveal` element for the first frames of a normal, healthy load. Measuring without
 * settling first would flag the whole app.
 */
export async function settleAnimations(): Promise<void> {
  for (const animation of document.getAnimations()) {
    try {
      const timing = animation.effect?.getComputedTiming();
      const iterations = timing?.iterations ?? 1;
      if (Number.isFinite(iterations)) {
        animation.finish();
      } else {
        const duration = typeof timing?.duration === 'number' ? timing.duration : 0;
        animation.pause();
        animation.currentTime = duration / 2;
      }
    } catch {
      // An animation can be cancelled between the enumeration and the call; a browser may also
      // refuse `finish()` on an effect with no resolved duration. Neither is a finding, and
      // neither should abort the sweep of the ones that matter.
    }
  }
  // Two frames: one for the style recalculation the seeks above scheduled, one for anything a
  // resize/intersection observer queued in response to it.
  await new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));
}

/** Is this element (or an ancestor) hidden ON PURPOSE, in a way a reader and a screen reader agree on? */
function deliberatelyHidden(el: Element): boolean {
  for (let node: Element | null = el; node; node = node.parentElement) {
    if (node.hasAttribute('hidden')) return true;
    if (node.getAttribute('aria-hidden') === 'true') return true;
    // The escape hatch, and the only one. An element that is invisible by design — a hover
    // reveal, a pre-open overlay — declares it in the markup where a reviewer reading the
    // component sees it, rather than in a list in this file that drifts from the page.
    if (node.hasAttribute('data-invisible-by-design')) return true;
    const style = getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') {
      return true;
    }
  }
  return false;
}

/** Does this element hold text of its own (not merely wrap a descendant that does)? */
function ownText(el: Element): string {
  let text = '';
  for (const node of Array.from(el.childNodes)) {
    if (node.nodeType === Node.TEXT_NODE) text += node.nodeValue ?? '';
  }
  return text.trim();
}

/** Controls must be visible even when their label is an icon rather than a text node. */
const CONTROLS = 'button, a[href], input, select, textarea, [role="button"], [role="link"], [role="tab"]';

/**
 * Every element a reader is meant to SEE, that the browser computes as fully transparent.
 *
 * Effective opacity is the product down the ancestor chain — `A-01` set it on a section eight
 * levels above the text that disappeared — so the chain is walked and the ancestor actually
 * responsible is reported. Being told "this heading is invisible" without being told which
 * container zeroed it is most of the debugging.
 */
export function invisibleContent(root: ParentNode = document.body): Invisible[] {
  const findings: Invisible[] = [];
  const candidates = new Set<Element>();
  for (const el of Array.from(root.querySelectorAll('*'))) {
    if (ownText(el) || el.matches(CONTROLS)) candidates.add(el);
  }

  for (const el of candidates) {
    if (deliberatelyHidden(el)) continue;
    let culprit: Element | null = null;
    for (let node: Element | null = el; node; node = node.parentElement) {
      if (parseFloat(getComputedStyle(node).opacity || '1') === 0) { culprit = node; break; }
    }
    if (!culprit) continue;
    const label = ownText(el) || el.getAttribute('aria-label') || el.textContent?.trim() || '(no name)';
    findings.push({
      where: describeEl(el),
      what: label.slice(0, 80),
      cause: describeEl(culprit),
      animationName: getComputedStyle(culprit).animationName,
    });
  }
  return findings;
}

/**
 * The classes in this app that PROMISE a keyframe animation, and the keyframes each promises.
 *
 * This is the dynamic half of `tools/check_c1_tokens.py::animation_clobber`. The static check
 * reads the source for a shorthand that replaces an entrance; this one asks the browser whether
 * the animation the class advertises is in the computed `animation-name` on a real element — so
 * it also catches a clobber written somewhere the static reader does not look, or arriving from a
 * cascade the source cannot show.
 */
export const MOTION_CLASSES: Record<string, string> = {
  reveal: 'reveal',
  rise: 'reveal',
  'u-float': 'float',
  'u-breathe': 'breathe',
  'u-pulse': 'pulse',
  'u-spin': 'spin',
};

/** Elements whose class promises an animation the computed style does not name. */
export function clobberedMotion(root: ParentNode = document.body): Clobbered[] {
  const findings: Clobbered[] = [];
  for (const el of Array.from(root.querySelectorAll('*'))) {
    if (deliberatelyHidden(el)) continue;
    const actual = getComputedStyle(el).animationName;
    const running = actual.split(',').map((s) => s.trim());
    for (const [cls, keyframes] of Object.entries(MOTION_CLASSES)) {
      if (!el.classList.contains(cls)) continue;
      if (running.includes(keyframes)) continue;
      findings.push({ where: describeEl(el), promisedBy: cls, expected: keyframes, actual });
    }
  }
  return findings;
}

/** A class the markup applies that no CSS rule anywhere selects. */
export interface Unstyled {
  /** The class token, e.g. `palette-scrim`. */
  className: string;
  /** One element that carries it, so the finding is findable. */
  where: string;
  /** How many elements in this render carry it. */
  count: number;
}

/** Every class token named by any selector in any attached stylesheet. */
export function styledClassTokens(): Set<string> {
  const tokens = new Set<string>();
  const walk = (rules: CSSRuleList) => {
    for (const rule of Array.from(rules)) {
      if (rule instanceof CSSStyleRule) {
        for (const m of rule.selectorText.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)) tokens.add(m[1]);
      }
      // @media, @supports, @layer, @container — the rules inside are still rules, and a check
      // that only read the top level would call every responsive-only class unstyled.
      const nested = (rule as CSSGroupingRule).cssRules;
      if (nested) walk(nested);
    }
  };
  for (const sheet of Array.from(document.styleSheets)) {
    try { walk(sheet.cssRules); } catch { /* a cross-origin sheet cannot be read; none here */ }
  }
  return tokens;
}

/**
 * Markup with no rules — the inverse of dead CSS, and the defect that had been shipping longest.
 *
 * The sixth independent audit's §E named this gap in one sentence: *"Nothing checks that a class
 * the app applies is styled by anything."* Its A-01 is what the gap costs. The ⌘K palette's five
 * classes — `palette-scrim`, `palette`, `palette-list`, `palette-item`, `palette-section-label` —
 * were defined in `layout.css`, deleted whole in PR #47 on 2026-07-28, and never replaced. The
 * component kept rendering them. For nineteen days the app's only modal was a stack of unstyled
 * block divs: no overlay, no panel, no scroll container, and an "active" row that highlighted
 * nothing while `aria-activedescendant` told a screen reader it had moved.
 *
 * NEITHER of the other two detectors here can see that. Nothing is at `opacity: 0` — the palette
 * is perfectly visible, it is simply undesigned — and no class promises an animation. A repository
 * that already had a gate for *rules with no markup* had none for *markup with no rules*, and the
 * two are one query apart.
 *
 * The check is deliberately shallow: it asks whether ANY rule anywhere names the token, not
 * whether the rule that names it applies to this element or declares anything useful. A class can
 * still be styled by a rule that never matches. But "no rule mentions this class at all" is
 * unambiguous, cheap, and is exactly the state A-01 was in.
 */
export function unstyledClasses(root: ParentNode, styled: Set<string>, exempt: Set<string>): Unstyled[] {
  const seen = new Map<string, { where: string; count: number }>();
  for (const el of Array.from(root.querySelectorAll('*'))) {
    for (const token of Array.from(el.classList)) {
      if (styled.has(token) || exempt.has(token)) continue;
      const prior = seen.get(token);
      if (prior) prior.count += 1;
      else seen.set(token, { where: describeEl(el), count: 1 });
    }
  }
  return [...seen.entries()]
    .map(([className, v]) => ({ className, ...v }))
    .sort((a, b) => a.className.localeCompare(b.className));
}

/** `rgb()` / `rgba()` as computed by the browser → `[r, g, b, a]`. */
function parseRgb(value: string): [number, number, number, number] | null {
  const m = /^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/
    .exec(value.trim());
  if (!m) return null;
  const alpha = m[4] === undefined ? 1
    : m[4].endsWith('%') ? parseFloat(m[4]) / 100 : parseFloat(m[4]);
  return [Number(m[1]), Number(m[2]), Number(m[3]), alpha];
}

/**
 * What is ACTUALLY behind this element's text, as an opaque `rgb()`.
 *
 * A translucent background has no contrast ratio of its own — `rgba(61,90,254,.12)` is not a
 * colour a reader ever sees. The palette's active row is painted with exactly that, over whatever
 * the panel behind it is, so measuring the declared value would measure a colour that never
 * reaches a screen. This walks up compositing each translucent layer until it reaches an opaque
 * one, which is what the eye does.
 *
 * Falls back to white only when the whole chain is transparent, which in a mounted page means the
 * document background — and that is the honest default rather than a guess, because a page whose
 * every ancestor is transparent really is on the canvas.
 */
export function effectiveBackground(el: Element): string {
  let r = 255, g = 255, b = 255;
  const layers: Array<[number, number, number, number]> = [];
  for (let node: Element | null = el; node; node = node.parentElement) {
    const parsed = parseRgb(getComputedStyle(node).backgroundColor);
    if (!parsed || parsed[3] === 0) continue;
    layers.push(parsed);
    if (parsed[3] === 1) break;
  }
  // Composite from the bottom up: the last layer found is the furthest back.
  for (let i = layers.length - 1; i >= 0; i -= 1) {
    const [lr, lg, lb, la] = layers[i];
    r = lr * la + r * (1 - la);
    g = lg * la + g * (1 - la);
    b = lb * la + b * (1 - la);
  }
  return `rgb(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)})`;
}

/** WCAG 2.x relative luminance / contrast ratio, on computed `rgb()` strings.
 *
 *  The same arithmetic `tools/check_contrast.py` runs over the token manifest — deliberately, so
 *  a page measured here and a pair measured there cannot disagree about what 4.5:1 means. What
 *  differs is the input: that reads hexes a human typed into JSON, this reads what Chromium
 *  computed. The eighth audit's `H-03` is the gap between those two. */
export function contrastRatio(fg: string, bg: string): number {
  const lum = (value: string): number => {
    const parsed = parseRgb(value);
    if (!parsed) return 0;
    const [r, g, b] = parsed.map((c, i) => {
      if (i === 3) return c;
      const s = c / 255;
      return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const a = lum(fg);
  const b = lum(bg);
  const [hi, lo] = a > b ? [a, b] : [b, a];
  return (hi + 0.05) / (lo + 0.05);
}

/** A failure message someone can act on without opening a debugger. */
export function reportInvisible(findings: Invisible[]): string {
  return findings.map((f) =>
    `  • ${f.what}\n      in   ${f.where}\n      zeroed by ${f.cause} (animation-name: ${f.animationName})`
  ).join('\n');
}

export function reportClobbered(findings: Clobbered[]): string {
  return findings.map((f) =>
    `  • ${f.where}\n      .${f.promisedBy} promises @keyframes ${f.expected}; animation-name is "${f.actual}"`
  ).join('\n');
}

export function reportUnstyled(findings: Unstyled[]): string {
  return findings.map((f) =>
    `  • .${f.className} — applied to ${f.count} element(s), selected by no rule in any stylesheet\n`
    + `      e.g. ${f.where}`
  ).join('\n');
}
