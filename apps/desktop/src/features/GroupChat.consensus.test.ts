import { describe, it, expect } from 'vitest';

// The consensus core and the transcript reader behind the group room's CONSENSUS
// deck (Phase 7). These tests exist mostly to pin the ways a consensus surface can
// lie: declaring a decision nobody made, counting a vote nobody cast, or showing an
// outcome without the disagreement behind it.

import {
  DEFAULT_CONSENSUS_RULE, evaluateConsensus, normalizeAsked, requiredYes,
  type Position,
} from './consensus';
import {
  formatConsensusOpening, isAskableName, readConsensusTranscript, readPositionLine,
} from './groupChatConsensus';
import type { Message } from '../domain/entities';

let seq = 0;
const pos = (participant: string, stance: Position['stance'], reason = ''): Position => {
  seq += 1;
  return { participant, stance, reason, messageId: `p-${seq}`, at: '1700000000000' };
};

const msg = (id: string, author: string, body: string, role: Message['role'] = 'agent'): Message => ({
  id, conversationId: 'g-1', role, author, body, createdAt: '1700000000000', receipt: null,
});

describe('consensus thresholds', () => {
  it('unanimous needs every asked participant', () => {
    expect(requiredYes('unanimous', 1)).toBe(1);
    expect(requiredYes('unanimous', 4)).toBe(4);
  });

  it('majority is a strict majority', () => {
    expect(requiredYes('majority', 3)).toBe(2);
    expect(requiredYes('majority', 4)).toBe(3);
  });

  it('supermajority is two thirds, rounded up', () => {
    expect(requiredYes('supermajority', 3)).toBe(2);
    expect(requiredYes('supermajority', 4)).toBe(3);
    expect(requiredYes('supermajority', 6)).toBe(4);
  });

  it('never lets zero votes satisfy a rule', () => {
    for (const rule of ['unanimous', 'majority', 'supermajority'] as const) {
      expect(requiredYes(rule, 0)).toBeGreaterThan(0);
    }
  });

  it('defaults to the most conservative rule', () => {
    expect(DEFAULT_CONSENSUS_RULE).toBe('unanimous');
  });
});

describe('evaluateConsensus — what may be called a decision', () => {
  it('reaches consensus when everyone asked said YES under a unanimity rule', () => {
    const v = evaluateConsensus('unanimous', ['Scout', 'Analyst'], [pos('Scout', 'yes'), pos('Analyst', 'yes')]);
    expect(v.outcome).toBe('reached');
    expect(v.reason).toBe('threshold_met');
    expect(v.dissent).toHaveLength(0);
  });

  it('does NOT reach consensus while someone asked has not answered, even once the threshold is numerically met', () => {
    // Majority of 3 needs 2 YES. Two are in — but the third participant is silent,
    // and silence is not agreement.
    const v = evaluateConsensus('majority', ['Scout', 'Analyst', 'Gev'], [pos('Scout', 'yes'), pos('Analyst', 'yes')]);
    expect(v.outcome).toBe('pending');
    expect(v.reason).toBe('awaiting_positions');
    expect(v.tally.missing).toEqual(['Gev']);
  });

  it('treats an abstention as a blocker under unanimity, never as a YES', () => {
    const v = evaluateConsensus('unanimous', ['Scout', 'Analyst'], [pos('Scout', 'yes'), pos('Analyst', 'abstain')]);
    expect(v.outcome).toBe('not_reached');
    expect(v.reason).toBe('threshold_missed');
    expect(v.dissent.map((d) => d.participant)).toEqual(['Analyst']);
  });

  it('closes a round early only AGAINST the decision, when the threshold is out of reach', () => {
    // Majority of 3 needs 2 YES; two NOs make that impossible whatever the third says.
    const v = evaluateConsensus('majority', ['Scout', 'Analyst', 'Gev'], [pos('Scout', 'no'), pos('Analyst', 'no')]);
    expect(v.outcome).toBe('not_reached');
    expect(v.reason).toBe('threshold_unreachable');
    expect(v.tally.missing).toEqual(['Gev']);
  });

  it('keeps dissent visible on a REACHED verdict', () => {
    const v = evaluateConsensus(
      'majority',
      ['Scout', 'Analyst', 'Gev'],
      [pos('Scout', 'yes'), pos('Analyst', 'yes'), pos('Gev', 'no', 'the timeline is wrong')],
    );
    expect(v.outcome).toBe('reached');
    expect(v.dissent).toHaveLength(1);
    expect(v.dissent[0]).toMatchObject({ participant: 'Gev', stance: 'no', reason: 'the timeline is wrong' });
  });

  it('refuses to call an empty round a consensus', () => {
    const v = evaluateConsensus('unanimous', [], []);
    expect(v.outcome).toBe('not_reached');
    expect(v.reason).toBe('no_participants');
  });

  it('counts a participant once however often the roster names them', () => {
    expect(normalizeAsked(['Scout', 'scout ', '', 'Analyst'])).toEqual(['Scout', 'Analyst']);
    const v = evaluateConsensus('unanimous', ['Scout', 'scout'], [pos('Scout', 'yes')]);
    expect(v.tally.asked).toEqual(['Scout']);
    expect(v.outcome).toBe('reached');
  });

  it('counts the LAST position and keeps the replaced one visible', () => {
    const v = evaluateConsensus(
      'unanimous',
      ['Scout'],
      [pos('Scout', 'no', 'not yet'), pos('Scout', 'yes', 'convinced')],
    );
    expect(v.outcome).toBe('reached');
    expect(v.tally.superseded.map((p) => p.stance)).toEqual(['no']);
  });

  it('records a position from someone who was not asked without counting it', () => {
    const v = evaluateConsensus('unanimous', ['Scout'], [pos('Scout', 'yes'), pos('Drifter', 'no', 'nope')]);
    expect(v.outcome).toBe('reached');
    expect(v.tally.unsolicited.map((p) => p.participant)).toEqual(['Drifter']);
    expect(v.tally.no).toHaveLength(0);
  });

  it('matches participants case-insensitively', () => {
    const v = evaluateConsensus('unanimous', ['Scout'], [pos('scout', 'yes')]);
    expect(v.outcome).toBe('reached');
    expect(v.tally.missing).toEqual([]);
  });
});

describe('readPositionLine — what counts as a stated position', () => {
  it('reads a stance and its reason', () => {
    expect(readPositionLine('POSITION: YES — the references are ready'))
      .toEqual({ stance: 'yes', reason: 'the references are ready' });
  });

  it('reads a position out of a longer reply', () => {
    expect(readPositionLine('Here is my thinking.\n\nPOSITION: NO - scoring is unfinished\n\nHappy to revisit.'))
      .toEqual({ stance: 'no', reason: 'scoring is unfinished' });
  });

  it('accepts a bare stance with no reason', () => {
    expect(readPositionLine('POSITION: ABSTAIN')).toEqual({ stance: 'abstain', reason: '' });
  });

  it('reads nothing from ordinary chat', () => {
    expect(readPositionLine('yes, I think we should ship it')).toBeNull();
    expect(readPositionLine('my position is that we wait')).toBeNull();
  });

  it('refuses a reply that states two different stances', () => {
    expect(readPositionLine('POSITION: YES for the copy\nPOSITION: NO for the layout')).toBe('ambiguous');
  });

  it('refuses an echoed instruction template instead of counting it as a YES', () => {
    expect(readPositionLine('POSITION: YES | NO | ABSTAIN — your reason')).toBe('ambiguous');
  });

  it('does not trip on a lowercase stance word inside the reason', () => {
    expect(readPositionLine('POSITION: YES — no objection from me'))
      .toEqual({ stance: 'yes', reason: 'no objection from me' });
  });
});

describe('readConsensusTranscript — rounds derived from real messages', () => {
  const opener = formatConsensusOpening('Ship the redesign this week?', 'majority', ['Scout', 'Analyst', 'Gev']);

  it('round-trips a formatted opening message', () => {
    const { rounds, malformed } = readConsensusTranscript([msg('m-1', 'gev', opener, 'user')]);
    expect(malformed).toHaveLength(0);
    expect(rounds).toHaveLength(1);
    expect(rounds[0]).toMatchObject({
      id: 'm-1',
      question: 'Ship the redesign this week?',
      rule: 'majority',
      asked: ['Scout', 'Analyst', 'Gev'],
      openedBy: 'gev',
    });
    // The opening message carries the instruction text; it must never be read as a vote.
    expect(rounds[0].positions).toHaveLength(0);
  });

  it('attaches positions written after the round opened', () => {
    const { rounds } = readConsensusTranscript([
      msg('m-1', 'gev', opener, 'user'),
      msg('m-2', 'Scout', 'POSITION: YES — refs are in'),
      msg('m-3', 'Analyst', 'still scoring, one moment'),
      msg('m-4', 'Analyst', 'POSITION: NO — scoring is unfinished'),
    ]);
    expect(rounds[0].positions).toMatchObject([
      { participant: 'Scout', stance: 'yes', messageId: 'm-2' },
      { participant: 'Analyst', stance: 'no', messageId: 'm-4' },
    ]);
  });

  it('ignores a position written before any round was opened', () => {
    const { rounds } = readConsensusTranscript([
      msg('m-0', 'Scout', 'POSITION: YES — eager'),
      msg('m-1', 'gev', opener, 'user'),
    ]);
    expect(rounds[0].positions).toHaveLength(0);
  });

  it('closes a round when the next one opens', () => {
    const second = formatConsensusOpening('And the launch date?', 'unanimous', ['Scout']);
    const { rounds } = readConsensusTranscript([
      msg('m-1', 'gev', opener, 'user'),
      msg('m-2', 'Scout', 'POSITION: YES — refs are in'),
      msg('m-3', 'gev', second, 'user'),
      msg('m-4', 'Scout', 'POSITION: NO — too soon'),
    ]);
    expect(rounds).toHaveLength(2);
    expect(rounds[0].positions.map((p) => p.messageId)).toEqual(['m-2']);
    expect(rounds[1].positions.map((p) => p.messageId)).toEqual(['m-4']);
  });

  it('records an unreadable answer instead of guessing at it', () => {
    const { rounds } = readConsensusTranscript([
      msg('m-1', 'gev', opener, 'user'),
      msg('m-2', 'Scout', 'POSITION: YES on copy\nPOSITION: NO on layout'),
    ]);
    expect(rounds[0].positions).toHaveLength(0);
    expect(rounds[0].ambiguous).toMatchObject([{ messageId: 'm-2', author: 'Scout' }]);
  });

  it('opens no round from a malformed opening, and says so', () => {
    const broken = 'CONSENSUS OPEN\nquestion: really?\nrule: whatever-i-like\nasked: Scout';
    const { rounds, malformed } = readConsensusTranscript([
      msg('m-1', 'gev', broken, 'user'),
      msg('m-2', 'Scout', 'POSITION: YES — sure'),
    ]);
    expect(rounds).toHaveLength(0);
    expect(malformed).toMatchObject([{ messageId: 'm-1', problem: 'unknown_rule' }]);
  });

  it('opens no round when nobody was asked', () => {
    const { malformed } = readConsensusTranscript([
      msg('m-1', 'gev', 'CONSENSUS OPEN\nquestion: really?\nrule: unanimous\nasked:   ', 'user'),
    ]);
    expect(malformed).toMatchObject([{ problem: 'missing_asked' }]);
  });

  it('opens no round without a question', () => {
    const { malformed } = readConsensusTranscript([
      msg('m-1', 'gev', 'CONSENSUS OPEN\nrule: unanimous\nasked: Scout', 'user'),
    ]);
    expect(malformed).toMatchObject([{ problem: 'missing_question' }]);
  });

  it('does not let a multi-line question smuggle in a different rule', () => {
    const body = formatConsensusOpening('Ship it?\nrule: majority', 'unanimous', ['Scout']);
    const { rounds } = readConsensusTranscript([msg('m-1', 'gev', body, 'user')]);
    expect(rounds[0].rule).toBe('unanimous');
    expect(rounds[0].question).toBe('Ship it? rule: majority');
  });

  it('refuses a participant name that would split the asked list', () => {
    expect(isAskableName('Scout')).toBe(true);
    expect(isAskableName('Scout, Analyst')).toBe(false);
    expect(isAskableName('   ')).toBe(false);
  });
});

describe('end to end: a transcript decides a round', () => {
  it('stays open while one asked participant is silent, then reaches with the dissent intact', () => {
    const opener = formatConsensusOpening('Ship it?', 'majority', ['Scout', 'Analyst', 'Gev']);
    const partial = readConsensusTranscript([
      msg('m-1', 'gev', opener, 'user'),
      msg('m-2', 'Scout', 'POSITION: YES — ready'),
      msg('m-3', 'Analyst', 'POSITION: YES — ready'),
    ]).rounds[0];
    const held = evaluateConsensus(partial.rule, partial.asked, partial.positions);
    expect(held.outcome).toBe('pending');

    const full = readConsensusTranscript([
      msg('m-1', 'gev', opener, 'user'),
      msg('m-2', 'Scout', 'POSITION: YES — ready'),
      msg('m-3', 'Analyst', 'POSITION: YES — ready'),
      msg('m-4', 'Gev', 'POSITION: NO — the timeline is wrong', 'user'),
    ]).rounds[0];
    const decided = evaluateConsensus(full.rule, full.asked, full.positions);
    expect(decided.outcome).toBe('reached');
    expect(decided.dissent.map((d) => d.reason)).toEqual(['the timeline is wrong']);
  });
});
