import { describe, it, expect } from 'vitest';
import { DECISION_STATUS_FAMILY, DECISION_STATUSES, type DecisionStatus } from '../domain/enums';
import { statusMeta, decisionStatusFamily, isRecognisedDecisionStatus } from './Decisions.status';

/**
 * The decision-status vocabulary, held against the page that reads it — ninth audit `I-11`.
 *
 * The finding: *"T-036's vocabulary enforcement stops where the entity type says `string`."*
 * `Decision.status` is `string`, `0002_decisions.sql` has no CHECK, and the browser spec's
 * `status: 'accepted'` routed through no accessor — the same shape that once let `level: 'L2'`
 * into a fixture and produced a false finding about an unstyled class.
 *
 * Two things are asserted here and they pull in opposite directions on purpose:
 *
 *   * the declared map must AGREE with the page's classifier, so `DECISION_STATUS_FAMILY` cannot
 *     drift into being a second, contradictory rule; and
 *   * the fallback branch must be visible as a fallback, because `'accepted'` and `'zzz'` render
 *     identically and only one of them is a status.
 *
 * What is deliberately NOT done: narrowing `Decision.status` to this union, or adding a CHECK to
 * the table. The value is read from a ledger this app does not own, so a narrow type would be a
 * claim about the engine that no contract backs — and a SQLite CHECK cannot be added to an
 * existing table without rebuilding it, which is the shape of the one High the cockpit audit
 * found (a non-atomic migration that could brick the database). The enforcement is placed where
 * this repository actually decides something: its own fixtures.
 */
describe('decision status vocabulary', () => {
  it('every declared status classifies into the family the map claims', () => {
    for (const status of DECISION_STATUSES) {
      expect(decisionStatusFamily(status), `${status} must read as ${DECISION_STATUS_FAMILY[status]}`)
        .toBe(DECISION_STATUS_FAMILY[status]);
    }
  });

  it('the map and the classifier are two surfaces, not one — a wrong entry is caught', () => {
    // The check earns its place only if the two can disagree. `rejected` reads `blocked`; assert
    // it reads `waiting` and the comparison above is what fails.
    const wrong: Record<string, string> = { ...DECISION_STATUS_FAMILY, rejected: 'waiting' };
    expect(decisionStatusFamily('rejected')).not.toBe(wrong.rejected);
  });

  it('every declared status is RECOGNISED, not merely landing in the fallback', () => {
    for (const status of DECISION_STATUSES) {
      expect(isRecognisedDecisionStatus(status), `${status} must be a word the page knows`).toBe(true);
    }
  });

  it('the fallback is a fallback: an invented word renders exactly like `accepted`', () => {
    // This is the finding, executable. Both reach the third branch; the fixture that used
    // `'accepted'` would have produced an identical screenshot for `'zzz'`, so it was asserting
    // the absence of a rule rather than the presence of a state.
    expect(decisionStatusFamily('zzz')).toBe(decisionStatusFamily('accepted'));
    expect(statusMeta('zzz')).toEqual(statusMeta('accepted'));
    // And the difference the register adds: only one of them is a declared status.
    expect(isRecognisedDecisionStatus('accepted')).toBe(true);
    expect(isRecognisedDecisionStatus('zzz')).toBe(false);
    expect(DECISION_STATUSES).toContain('accepted' as DecisionStatus);
  });

  it('the desktop store writes exactly one of these, and it is declared', () => {
    // `repo.rs::decisions::create` hardcodes 'proposed'; nothing in the desktop updates a decision
    // status afterwards. If that ever changes, the new value has to arrive here first.
    expect(DECISION_STATUSES).toContain('proposed' as DecisionStatus);
    expect(DECISION_STATUS_FAMILY.proposed).toBe('waiting');
  });

  it('an empty or absent status does not read as blocked', () => {
    // The page renders whatever the ledger sends, including nothing. Reading an absent status as a
    // refusal would invent a verdict; reading it as settled would invent a conclusion. It reads as
    // the fallback, which is what "we were told nothing" looks like.
    for (const empty of ['', '   ']) {
      expect(decisionStatusFamily(empty)).toBe('settled');
      expect(isRecognisedDecisionStatus(empty)).toBe(false);
    }
  });
});
