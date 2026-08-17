import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { settleAnimations, unstyledClasses, styledClassTokens, reportUnstyled } from '../test/computedStyle';

/**
 * The design system's own vocabulary, measured — and the gap in `pages.browser.spec.tsx` that made
 * this file necessary.
 *
 * The page sweep measures 23 pages in three states. It cannot measure a state it has no way to
 * reach: Research's `saved` badge appears only after a governed run is saved, and that path is
 * blocked on every install the sweep can drive. So `pill success` — applied at
 * `Research.tsx`, defined by **no rule in any stylesheet** — sailed straight through a suite
 * written specifically to catch classes with no rules.
 *
 * Three more were in the same state when this was written: `pill ok` on Bridge's *"verified"*
 * outcome, `pill danger` on Research's failure, and `pill bad` on Projects' blocked count (that
 * one had a rule, scoped to `.v-agents`, so it applied everywhere except where Projects renders).
 * A verified outcome and a failed one computed to identical neutral pills.
 *
 * The lesson is the same one the page sweep already carries once: **a check only sees the states
 * it visits.** The answer is not to widen a static reader — the sixth audit's `A-03` is a worked
 * example of where that leads — it is to render the vocabulary DIRECTLY, in the browser, so the
 * tones are measured whether or not a page happens to reach them today.
 */

/** Every `pill` tone the app is allowed to use, and what each one means.
 *
 * Adding a row is how a tone joins the vocabulary; there is no way to use one that is not here
 * without this file going red, because the last assertion renders exactly this list. `ok` and
 * `danger` were folded into `success` and `bad` rather than given rules of their own — five names
 * for three colours is how the fourth one gets forgotten. */
const PILL_TONES: Array<[string, string]> = [
  ['live', 'this is running now'],
  ['success', 'this finished and it worked'],
  ['warn', 'this needs attention'],
  ['bad', 'this failed or is blocked'],
  ['info', 'neutral fact'],
  ['mint', 'a secondary accent used by the instrument surfaces'],
  ['off', 'present but inactive'],
];

describe('the pill tone vocabulary is styled, not just applied', () => {
  it('every declared tone is selected by a rule', () => {
    const { container } = render(
      <>
        {PILL_TONES.map(([tone]) => (
          <span key={tone} className={`pill ${tone}`}>{tone}</span>
        ))}
      </>,
    );
    const findings = unstyledClasses(container, styledClassTokens(), new Set());
    expect(findings, `\na pill tone the app applies is defined by no rule —\n`
      + `${reportUnstyled(findings)}\n`).toEqual([]);
  });

  it('each tone computes differently from the plain pill', async () => {
    // Stronger than "a rule exists": a rule that sets nothing visible would pass the check above.
    // `off` is excluded because it is defined as an opacity change on the BASE pill, which is the
    // one tone whose whole design is to look like the plain one, dimmed.
    const { container } = render(
      <>
        <span className="pill" id="plain">plain</span>
        {PILL_TONES.map(([tone]) => (
          <span key={tone} id={`t-${tone}`} className={`pill ${tone}`}>{tone}</span>
        ))}
      </>,
    );
    await settleAnimations();
    const plain = getComputedStyle(container.querySelector('#plain')!);
    for (const [tone] of PILL_TONES) {
      const s = getComputedStyle(container.querySelector(`#t-${tone}`)!);
      const differs = s.color !== plain.color
        || s.backgroundColor !== plain.backgroundColor
        || s.borderTopColor !== plain.borderTopColor
        || s.opacity !== plain.opacity;
      expect(differs, `.pill.${tone} computes identically to a plain pill `
        + `(color ${s.color}, background ${s.backgroundColor})`).toBe(true);
    }
  });

  it('success and bad are visually distinct from each other', async () => {
    // The failure this whole file exists for: Bridge's "verified" pill and Research's "failed"
    // pill rendered identically, because neither tone had a rule. A green that equals the red is
    // worse than no colour at all — it looks deliberate.
    const { container } = render(
      <>
        <span id="ok" className="pill success">verified</span>
        <span id="no" className="pill bad">failed</span>
      </>,
    );
    await settleAnimations();
    const ok = getComputedStyle(container.querySelector('#ok')!);
    const no = getComputedStyle(container.querySelector('#no')!);
    expect(ok.color, 'a verified badge and a failed badge must not be the same colour')
      .not.toBe(no.color);
  });
});
