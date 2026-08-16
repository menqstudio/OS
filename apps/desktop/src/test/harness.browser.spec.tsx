import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import {
  settleAnimations, invisibleContent, clobberedMotion, describeEl, emulateMedia,
} from './computedStyle';

/**
 * The harness measuring itself, because the failure mode of a computed-style suite is not a false
 * alarm — it is SILENT AGREEMENT.
 *
 * If `styles.css` fails to resolve, every element computes to the browser's initial values:
 * `opacity: 1`, `animation-name: none`, nothing hidden, nothing invisible. `pages.browser.spec`
 * then passes all 69 of its assertions against a page with no design on it at all, and reports
 * green forever. That is precisely the shape T-024's own text warns about — *"a hand-written
 * markup fixture that drifts from the component is worse than no check, because it goes green
 * while the page is broken"* — and it applies to the stylesheet just as much as to the markup.
 *
 * So this file proves, before any page is measured, that the four things the sweep depends on are
 * real: the tokens resolve, the app's keyframes exist, the browser honours an emulated media
 * feature, and each detector fires on a deliberate defect.
 */

describe('the harness itself is measuring something', () => {
  it('the app stylesheet is attached and its tokens resolve', () => {
    // `--enter` is the entrance duration every `.reveal` reads. If this is empty the cascade never
    // arrived, and every other assertion in this project is vacuous.
    const root = getComputedStyle(document.documentElement);
    expect(root.getPropertyValue('--enter').trim(), 'styles.css did not load — every computed-style '
      + 'assertion in this project would pass against an unstyled page').not.toBe('');
    expect(root.getPropertyValue('--stagger').trim()).not.toBe('');
    expect(root.getPropertyValue('--s4').trim()).not.toBe('');
  });

  it('the app keyframes are registered, not just referenced', () => {
    const names = new Set<string>();
    for (const sheet of Array.from(document.styleSheets)) {
      let rules: CSSRuleList;
      try { rules = sheet.cssRules; } catch { continue; }
      for (const rule of Array.from(rules)) {
        if (rule instanceof CSSKeyframesRule) names.add(rule.name);
      }
    }
    expect(names.has('reveal'), `@keyframes reveal is not registered; found: ${[...names].sort().join(', ')}`)
      .toBe(true);
  });

  it('an element that reveals is at opacity 0 before settling and 1 after', async () => {
    // The load-bearing behaviour of the whole sweep. If `.reveal` did not actually start
    // transparent, `settleAnimations()` would be doing nothing and `A-01` would be invisible to
    // this suite too.
    const { container } = render(<div className="reveal">visible eventually</div>);
    const el = container.firstElementChild as HTMLElement;
    expect(parseFloat(getComputedStyle(el).opacity)).toBe(0);
    await settleAnimations();
    expect(parseFloat(getComputedStyle(el).opacity)).toBe(1);
  });

  it('the emulated media feature reaches the CASCADE, not just matchMedia', async () => {
    // A `matchMedia` stub — what `src/test/setup.ts` installs for jsdom — would satisfy the JS
    // that reads the query and leave the stylesheet untouched. Reduced-motion coverage would then
    // be theatre. This asserts the rule actually changes.
    const { container } = render(<div className="u-spin">spinner</div>);
    const el = container.firstElementChild as HTMLElement;
    expect(getComputedStyle(el).animationName).toBe('spin');

    await emulateMedia([{ name: 'prefers-reduced-motion', value: 'reduce' }]);

    // aios.css's reduced-motion block collapses duration (`.01ms !important`) rather than removing
    // the name; either is a real cascade change, and both are invisible to a matchMedia stub.
    //
    // Compared NUMERICALLY. The first version of this assertion compared the string against
    // `'0.00001s'` and failed: Chromium serialises that duration as `1e-05s`. A string match on a
    // computed value is a check on the browser's serialiser, not on the cascade.
    const reduced = getComputedStyle(el);
    expect(
      parseFloat(reduced.animationDuration) < 0.001 || reduced.animationName === 'none',
      `reduced motion did not reach the cascade (duration ${reduced.animationDuration}, `
      + `name ${reduced.animationName})`,
    ).toBe(true);
    await emulateMedia([]);
  });
});

describe('each detector fires on a deliberate defect', () => {
  it('invisibleContent finds text zeroed by an ANCESTOR, and names that ancestor', () => {
    const { container } = render(
      <section className="outer" style={{ opacity: 0 }}>
        <div><p className="inner">a fact the reader never sees</p></div>
      </section>,
    );
    const findings = invisibleContent(container);
    expect(findings.length).toBe(1);
    expect(findings[0].what).toBe('a fact the reader never sees');
    expect(findings[0].cause).toContain('.outer');
  });

  it('invisibleContent finds an icon-only CONTROL with no text of its own', () => {
    const { container } = render(
      <button aria-label="Close" style={{ opacity: 0 }}><svg /></button>,
    );
    expect(invisibleContent(container).map((f) => f.what)).toEqual(['Close']);
  });

  it('invisibleContent does not flag what is hidden on purpose', () => {
    const { container } = render(
      <>
        <div hidden><span>hidden attribute</span></div>
        <div aria-hidden="true" style={{ opacity: 0 }}><span>decorative</span></div>
        <div style={{ display: 'none' }}><span>display none</span></div>
        <div style={{ visibility: 'hidden' }}><span>visibility hidden</span></div>
        <div data-invisible-by-design style={{ opacity: 0 }}><span>a hover reveal</span></div>
      </>,
    );
    expect(invisibleContent(container)).toEqual([]);
  });

  it('clobberedMotion reproduces A-01 exactly: a shorthand that replaces the entrance', () => {
    // The defect, in miniature. `.reveal` declares `animation: reveal …`; a later, more specific
    // rule declares `animation: <something else>` and the shorthand REPLACES the list rather than
    // adding to it. The class still says `reveal`. The element never reveals.
    const { container } = render(
      <>
        <style>{'.a01 { animation: spin 2s linear infinite; }'}</style>
        <div className="reveal a01">populated, and invisible</div>
      </>,
    );
    const findings = clobberedMotion(container);
    expect(findings.length).toBe(1);
    expect(findings[0].promisedBy).toBe('reveal');
    expect(findings[0].expected).toBe('reveal');
    expect(findings[0].actual).toBe('spin');
  });

  it('clobberedMotion accepts a COMPOSED list — the shape of the A-01 fix', () => {
    const { container } = render(
      <>
        <style>{'.fixed { animation: reveal var(--enter) forwards, spin 2s linear infinite; }'}</style>
        <div className="reveal fixed">populated, and visible</div>
      </>,
    );
    expect(clobberedMotion(container)).toEqual([]);
  });

  it('describeEl gives a path someone can find in the source', () => {
    const { container } = render(<div className="outer"><p id="x" className="a b">t</p></div>);
    expect(describeEl(container.querySelector('#x')!)).toBe('div.outer > p#x.a.b');
  });
});
