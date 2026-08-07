/// <reference types="vite/client" />
import { describe, it, expect } from 'vitest';

/**
 * Regression guard for the "always-on live indicator" class of defect.
 *
 * `.wire.live` animates a travelling pulse and `.pill.live` / `<Mark state="live">`
 * paint the green "running" affordance. Roughly fifteen of these were hard-coded as
 * string literals across the feature pages, so they rendered identically on an error,
 * on an empty result, and with zero connected — decoration pretending to be telemetry.
 *
 * A live affordance must be derived from real state, i.e. written as a template
 * expression (`` `wire${x ? ' live' : ''}` ``), not as a literal. This test fails on any
 * NEW hard-coded literal so the class of defect cannot quietly return.
 *
 * The two allowed literals are documented below; both are genuinely unconditional
 * facts rather than claims about backend state.
 */
const sources = import.meta.glob('../{features,components,app}/*.tsx', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

/** Hard-coded live affordances. Each match is a claim rendered in every state. */
const LITERALS = [
  { pattern: /className="wire live"/g, what: 'className="wire live"' },
  { pattern: /className="pill live"/g, what: 'className="pill live"' },
  { pattern: /<Mark\s+state="live"/g, what: '<Mark state="live">' },
];

/**
 * Deliberate exceptions, reviewed one by one:
 *
 *  - `Shell.tsx` — the "o" of the BroPS wordmark in the sidebar. Brand typography with
 *    `size={0}`, not a state indicator; it asserts nothing about any backend.
 *  - `Tasks.tsx` — `pill live` for "path clear" is inside the `blocked === 0` arm of a
 *    ternary, so the literal is already gated on a real derived count.
 *  - `Agents.tsx` — `pill live` for "dispatch channel present" is inside the
 *    `channel.state === 'present'` arm, reached only after a probe genuinely answered.
 *    Same shape as `Tasks.tsx`: this scan reads text, so it cannot see the branch the
 *    literal already sits behind.
 *  - `ui.tsx` / `ui.primitives*.tsx` — the `LiveMark` primitive itself, whose `state` is
 *    a prop supplied by the caller.
 */
const ALLOWED: Record<string, string[]> = {
  'Shell.tsx': ['<Mark state="live">'],
  'Tasks.tsx': ['className="pill live"'],
  'Agents.tsx': ['className="pill live"'],
  'ui.tsx': ['<Mark state="live">'],
};

/** Glob keys are relative to this file; compare on the file name alone. */
const basename = (p: string) => p.slice(p.lastIndexOf('/') + 1);

describe('no page hard-codes an always-on live indicator', () => {
  it('discovers the view sources', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(20);
  });

  it('every live affordance is derived from real state, not a literal', () => {
    const offenders: string[] = [];
    for (const [path, src] of Object.entries(sources)) {
      const allowed = ALLOWED[basename(path)] ?? [];
      for (const { pattern, what } of LITERALS) {
        pattern.lastIndex = 0;
        const hits = src.match(pattern)?.length ?? 0;
        if (hits > 0 && !allowed.includes(what)) {
          offenders.push(`${path}: ${hits}× ${what}`);
        }
      }
    }
    expect(
      offenders,
      'Bind each of these to its real state (e.g. `wire${x ? \' live\' : \'\'}`) or drop the claim',
    ).toEqual([]);
  });
});
