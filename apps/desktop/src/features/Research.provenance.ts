import type { STR } from './Research.strings';

/**
 * How a HELD research answer is described, decided by what actually produced it.
 *
 * The sixth independent audit's `A-05`. The Research panel rendered *"Verified · held"* and
 * *"Verified desktop-side and held by the backend"* for **every** held answer — for an outcome
 * that is `development_untrusted` at best and, on the only path a shipped install can reach, has
 * no governed turn, no challenge and no receipt at all. The renderer was not lying on purpose: the
 * `ready` event never said which path produced the answer, so the page described the one it
 * assumed it was on. The fix carries the fact (`StreamEvent::Ready.provenance`); this module is
 * where that fact becomes words.
 *
 * These live in their own file rather than in `Research.tsx` for a mundane reason worth writing
 * down: `app/routes.tsx` lazy-imports feature modules as `Record<string, ComponentType>`, so a
 * non-component export from a routed page is a type error. Pure functions in their own module are
 * also the ones a unit test can reach without mounting a page.
 *
 * THE `default` ARM IS THE LOAD-BEARING ONE, and it is deliberately the worst case: a provenance
 * this version does not recognise must never read as verified. Same rule as `receiptBadge()` in
 * `Conversations.tsx`, and the same rule the cockpit follows at the wall — the declared union is a
 * hope about the backend, and the fallback is what actually holds.
 */
export interface HeldLabel {
  /** A `pill` tone that exists in the stylesheet. `success` and `bad` were added on 2026-08-17;
   *  before that they were applied and defined by no rule at all. */
  tone: 'success' | 'warn' | 'bad';
  glyph: string;
  key: keyof typeof STR;
}

export function heldLabel(provenance: string): HeldLabel {
  switch (provenance) {
    case 'trusted_verified':
      return { tone: 'success', glyph: '✓', key: 'heldVerified' };
    case 'development_untrusted':
      return { tone: 'warn', glyph: '◑', key: 'heldDevelopment' };
    case 'ungoverned':
      return { tone: 'bad', glyph: '⚠', key: 'heldUngoverned' };
    default:
      return { tone: 'bad', glyph: '⚠', key: 'heldUnknown' };
  }
}

/** The sentence under the badge, by the same rule and the same fallback. */
export function heldNoteKey(provenance: string): keyof typeof STR {
  switch (provenance) {
    case 'trusted_verified': return 'heldVerifiedNote';
    case 'development_untrusted': return 'heldDevelopmentNote';
    case 'ungoverned': return 'heldUngovernedNote';
    default: return 'heldUnknownNote';
  }
}
