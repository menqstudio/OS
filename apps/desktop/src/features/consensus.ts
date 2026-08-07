// Consensus for the group room — the pure decision core (Phase 7).
//
// This module answers exactly one question: given the participants a round ASKED
// and the positions that were actually RECORDED, what does the stated rule decide?
// It performs no I/O, touches no transcript, and never invents a position. Its
// only inputs are positions someone really wrote (see groupChatConsensus.ts, which
// derives them from persisted messages) — the same honesty posture as the handoff
// chain, which is derived from real message authors and never fabricated.
//
// Three properties are deliberate and must not be relaxed:
//
//  1. Silence is never consent. A participant who was asked and has not answered
//     is `missing`, never an implicit YES, and (see 2) blocks a `reached` verdict.
//  2. A verdict of `reached` requires FULL PARTICIPATION — every asked participant
//     has a recorded position AND the YES count meets the rule's threshold. A
//     majority that is only a majority of the people who bothered to answer is not
//     a decision; it is a quorum failure wearing a decision's clothes.
//  3. Dissent is part of the verdict, not a footnote. `dissent` (every recorded
//     non-YES) and `tally.missing` are returned even when the outcome is `reached`,
//     so a surface cannot render the outcome without also having the disagreement
//     in hand.

/** How one participant answered. `abstain` is a real, recorded answer — it is not
 *  a YES and, under a unanimity rule, it blocks the decision. */
export type Stance = 'yes' | 'no' | 'abstain';

export const STANCES: readonly Stance[] = ['yes', 'no', 'abstain'];

/** The decision rules a round may state. The rule is chosen when the round is
 *  OPENED and is recorded in the transcript, so it can never be picked after the
 *  positions are known. */
export type ConsensusRule = 'unanimous' | 'majority' | 'supermajority';

export const CONSENSUS_RULES: readonly ConsensusRule[] = ['unanimous', 'majority', 'supermajority'];

export function isConsensusRule(v: string): v is ConsensusRule {
  return (CONSENSUS_RULES as readonly string[]).includes(v);
}

/**
 * OWNER-GATED DEFAULT. `unanimous` is the most conservative rule that is still
 * defensible: it can never declare a decision over anyone's stated objection.
 * Combined with `REQUIRE_FULL_PARTICIPATION` it means a round is decided only when
 * every asked participant has spoken and none of them said NO or abstained.
 *
 * The owner may legitimately prefer a cheaper rule (e.g. `majority`) as the default;
 * changing this constant is the whole change — every rule is implemented and any
 * round may state any of them at open time.
 */
export const DEFAULT_CONSENSUS_RULE: ConsensusRule = 'unanimous';

/**
 * OWNER-GATED DEFAULT. A `reached` verdict requires every asked participant to have
 * a recorded position. This is deliberately stricter than "the threshold is already
 * mathematically locked in": one silent agent holds the round at `pending` rather
 * than letting the room decide on that agent's behalf.
 *
 * Note the asymmetry, which is the fail-closed direction: a round may still be
 * declared NOT reached early, when the outstanding participants could not reach the
 * threshold even if all of them said YES. Closing a round early against a decision
 * is safe; closing it early in favour of one is not.
 */
export const REQUIRE_FULL_PARTICIPATION = true;

/** One recorded position, carrying the id of the real message it was read from so
 *  every counted vote can be traced back to something a participant actually wrote. */
export interface Position {
  /** The message author, exactly as persisted. */
  participant: string;
  stance: Stance;
  /** The reason given on the position line. May be empty — surfaces say so. */
  reason: string;
  /** Provenance: the transcript message this position was read from. */
  messageId: string;
  /** The message's createdAt, unmodified. */
  at: string;
}

export type ConsensusOutcome = 'reached' | 'not_reached' | 'pending';

/** Why the outcome is what it is — a machine reason a surface can translate rather
 *  than re-derive (re-deriving is how a surface starts disagreeing with the core). */
export type ConsensusReason =
  | 'no_participants'
  | 'threshold_met'
  | 'threshold_missed'
  | 'threshold_unreachable'
  | 'awaiting_positions';

export interface ConsensusTally {
  /** The asked roster as recorded at open time, de-duplicated, original spelling. */
  asked: string[];
  /** How many YES this rule needs over `asked.length`. */
  requiredYes: number;
  yes: Position[];
  no: Position[];
  abstain: Position[];
  /** Asked participants with no recorded position. Never counted as anything. */
  missing: string[];
  /** Earlier positions from a participant who later posted another one. Kept so a
   *  changed vote is visible rather than silently overwritten. */
  superseded: Position[];
  /** Positions from someone who was NOT asked. Recorded and shown, never counted —
   *  hiding them would be dishonest, counting them would rewrite the round. */
  unsolicited: Position[];
}

export interface ConsensusVerdict {
  outcome: ConsensusOutcome;
  rule: ConsensusRule;
  tally: ConsensusTally;
  /** Every recorded position that is not a YES (NO first, then abstain). Returned
   *  for every outcome, including `reached` — an outcome shown without its dissent
   *  is the defect this feature exists to avoid. */
  dissent: Position[];
  reason: ConsensusReason;
}

/**
 * How many YES votes `rule` needs when `askedCount` participants were asked.
 *
 * `Math.max(1, …)` is a floor, not a rounding convenience: with zero participants
 * every rule would otherwise be satisfied by zero votes, i.e. an empty room would
 * "agree" on anything. `evaluateConsensus` rejects an empty roster outright; this
 * floor makes the arithmetic unable to produce that result even in isolation.
 */
export function requiredYes(rule: ConsensusRule, askedCount: number): number {
  const n = Math.max(0, Math.floor(askedCount));
  switch (rule) {
    case 'unanimous':
      return Math.max(1, n);
    case 'majority':
      // Strict majority: more than half, so 2 of 3 and 3 of 4.
      return Math.max(1, Math.floor(n / 2) + 1);
    case 'supermajority':
      // Two thirds, rounded up: 2 of 3, 3 of 4, 4 of 5.
      return Math.max(1, Math.ceil((2 * n) / 3));
  }
}

/** Case-insensitive participant identity. Display names arrive from the roster and
 *  from message authors, which can differ in case; matching must not depend on it. */
const key = (name: string) => name.trim().toLowerCase();

/** De-duplicate an asked roster case-insensitively, keeping the first spelling and
 *  dropping blanks. A roster that names the same participant twice must not raise
 *  that participant's weight or the round's threshold. */
export function normalizeAsked(asked: readonly string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of asked) {
    const name = raw.trim();
    if (!name || seen.has(key(name))) continue;
    seen.add(key(name));
    out.push(name);
  }
  return out;
}

/**
 * Sort `recorded` into the tally. `recorded` must be in transcript order: when a
 * participant posted more than one position the LAST one counts and the earlier
 * ones become `superseded` — a participant may change their mind, but the change
 * stays visible.
 */
export function tallyConsensus(
  rule: ConsensusRule,
  asked: readonly string[],
  recorded: readonly Position[],
): ConsensusTally {
  const roster = normalizeAsked(asked);
  const rosterKeys = new Set(roster.map(key));

  const latest = new Map<string, Position>();
  const superseded: Position[] = [];
  const unsolicited: Position[] = [];

  for (const p of recorded) {
    const k = key(p.participant);
    if (!rosterKeys.has(k)) {
      unsolicited.push(p);
      continue;
    }
    const prev = latest.get(k);
    if (prev) superseded.push(prev);
    latest.set(k, p);
  }

  const yes: Position[] = [];
  const no: Position[] = [];
  const abstain: Position[] = [];
  const missing: string[] = [];

  // Iterate the roster (not the map) so the tally is ordered as the round asked,
  // and so a participant with no position is counted exactly once as missing.
  for (const name of roster) {
    const p = latest.get(key(name));
    if (!p) {
      missing.push(name);
      continue;
    }
    if (p.stance === 'yes') yes.push(p);
    else if (p.stance === 'no') no.push(p);
    else abstain.push(p);
  }

  return {
    asked: roster,
    requiredYes: requiredYes(rule, roster.length),
    yes,
    no,
    abstain,
    missing,
    superseded,
    unsolicited,
  };
}

/**
 * Decide a round. The only function permitted to say a consensus was reached.
 *
 * Order of the branches matters and is the fail-closed guarantee:
 *  - an empty roster is `not_reached`, never a vacuous success;
 *  - with everyone answered, the threshold decides;
 *  - with answers outstanding, the round is `reached` NEVER (see
 *    REQUIRE_FULL_PARTICIPATION) — only `not_reached` (when the threshold is already
 *    out of reach) or `pending`.
 */
export function evaluateConsensus(
  rule: ConsensusRule,
  asked: readonly string[],
  recorded: readonly Position[],
): ConsensusVerdict {
  const tally = tallyConsensus(rule, asked, recorded);
  const n = tally.asked.length;
  const dissent = [...tally.no, ...tally.abstain];
  const base = { rule, tally, dissent };

  // Nobody was asked: there is no room to agree. Never a decision.
  if (n === 0) return { ...base, outcome: 'not_reached', reason: 'no_participants' };

  const yes = tally.yes.length;
  const outstanding = tally.missing.length;

  if (outstanding === 0) {
    return yes >= tally.requiredYes
      ? { ...base, outcome: 'reached', reason: 'threshold_met' }
      : { ...base, outcome: 'not_reached', reason: 'threshold_missed' };
  }

  // Answers outstanding. Safe to close early only AGAINST the decision: even if
  // every remaining participant said YES the threshold could not be met.
  if (yes + outstanding < tally.requiredYes) {
    return { ...base, outcome: 'not_reached', reason: 'threshold_unreachable' };
  }

  // The threshold may still be met, but not everyone has spoken. Deciding here
  // would be deciding on the silent participants' behalf.
  return { ...base, outcome: 'pending', reason: 'awaiting_positions' };
}
