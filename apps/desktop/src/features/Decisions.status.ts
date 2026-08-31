import type { DecisionStatusFamily } from '../domain/enums';

/**
 * How a decision's status is read on screen — extracted from `Decisions.tsx` for `I-11`.
 *
 * It lives in its own module for a reason the router enforces: `app/routes.tsx` types a page module
 * as `Record<string, ComponentType>`, so a page file may export components and nothing else. A
 * classifier only the page can see is a classifier no test can hold to a vocabulary, which is how
 * the fixture in `pages.browser.spec.tsx` came to assert a rendered state using a word the
 * classifier does not recognise.
 *
 * The rules themselves are unchanged and deliberately tolerant. The status is READ from a ledger
 * this app does not own, `Decision.status` is `string` on the entity and `TEXT` with no CHECK in
 * `0002_decisions.sql`, and narrowing either would claim an engine contract nobody has written.
 */

/**
 * Honest status → presentation map. NEVER returns a "live"/green/verified tone: the desktop cannot
 * verify a decision, so the power mark is `idle` for anything that is not an explicit
 * block/refusal (which reads `alert`). Colour on the ledger dot is carried by `--st-rgb`; a settled
 * decision simply reads neutral, never approved-green.
 */
export function statusMeta(status: string): { face: string; mark: string; tone: string } {
  const v = (status || '').toLowerCase();
  if (/block|reject|den|fail|abort|error/.test(v)) return { face: 'blocked', mark: 'alert', tone: 'var(--danger-rgb)' };
  if (/wait|pend|propos|review|hold|open|draft/.test(v)) return { face: 'waiting', mark: 'idle', tone: 'var(--warning-rgb)' };
  return { face: 'idle', mark: 'idle', tone: 'var(--muted-rgb)' };
}

/**
 * Which family {@link statusMeta} puts a status in.
 *
 * Exported so `DECISION_STATUS_FAMILY` in `domain/enums.ts` can be checked AGAINST the page rather
 * than written beside it. `settled` is the fallback branch, and that is the honest name for it: it
 * is where every word the classifier does not recognise also lands.
 */
export function decisionStatusFamily(status: string): DecisionStatusFamily {
  const face = statusMeta(status).face;
  return face === 'blocked' ? 'blocked' : face === 'waiting' ? 'waiting' : 'settled';
}

/**
 * Does the classifier recognise this word at all, or is it landing in the fallback?
 *
 * `'accepted'` and `'zzz'` both render as `settled`; only one of them is a status. A fixture that
 * cannot tell them apart is measuring the fallback and calling it a state.
 */
export function isRecognisedDecisionStatus(status: string): boolean {
  const v = (status || '').toLowerCase();
  return /block|reject|den|fail|abort|error/.test(v)
    || /wait|pend|propos|review|hold|open|draft/.test(v)
    || /accept|supersede|settle|final|closed|adopted/.test(v);
}
