// Consensus rounds read out of the group room's REAL transcript (Phase 7).
//
// There is no consensus table in the backend and this feature does not invent one.
// A round lives where the room's other facts live — in the persisted messages —
// exactly like the handoff chain, which is derived from real message authors. That
// buys three things that a side-channel could not:
//
//  - a position is a message a participant actually wrote, under their own author,
//    persisted by the server (agent messages are minted server-side; the renderer
//    cannot forge one);
//  - the rule and the asked roster are fixed in the OPENING message, so neither can
//    be chosen after the positions are known;
//  - the whole round is auditable by reading the chat.
//
// The grammar is deliberately narrow. Anything that does not match exactly is NOT a
// position, and a round with a missing question / unknown rule / empty roster is not
// a round at all — it is surfaced as malformed so it is visible rather than silently
// dropped. Under-reading is safe here (an unread position leaves the round pending);
// over-reading would mean counting a vote nobody cast.

import type { Message } from '../domain/entities';
import {
  DEFAULT_CONSENSUS_RULE, isConsensusRule, normalizeAsked,
  type ConsensusRule, type Position, type Stance,
} from './consensus';

/** The first line of an opening message, matched case-insensitively after trimming. */
export const CONSENSUS_OPEN_MARKER = 'CONSENSUS OPEN';

/** A round as recorded in the transcript. `id` is the opening message's id, so a
 *  round is identified by the message that opened it and nothing else. */
export interface ConsensusRound {
  id: string;
  question: string;
  rule: ConsensusRule;
  asked: string[];
  openedBy: string;
  openedAt: string;
  /** Positions in transcript order (later ones supersede earlier ones per author). */
  positions: Position[];
  /** Messages that look like a position but do not state one unambiguously. Never
   *  counted; surfaced so the room can see that someone's answer was not readable. */
  ambiguous: AmbiguousPosition[];
}

export interface AmbiguousPosition {
  messageId: string;
  author: string;
  at: string;
}

export type MalformedProblem = 'missing_question' | 'unknown_rule' | 'missing_asked';

/** An opening message that could not be read as a round. It opens nothing — but it
 *  still terminates the previous round, because whoever wrote it intended to move on. */
export interface MalformedRound {
  messageId: string;
  author: string;
  at: string;
  problem: MalformedProblem;
}

export interface ConsensusTranscript {
  /** Oldest first, matching transcript order. */
  rounds: ConsensusRound[];
  malformed: MalformedRound[];
}

/** `POSITION: YES — because …`. The stance token must be the first thing after the
 *  colon; everything after it is the reason. */
const POSITION_LINE = /^\s*POSITION\s*:\s*(YES|NO|ABSTAIN)\b(.*)$/i;

/** Stance words written in CAPITALS, used only to detect a copied instruction line
 *  (`POSITION: YES | NO | ABSTAIN`). Case-sensitive on purpose: a prose reason like
 *  "no strong objection" must not trip it. */
const SHOUTED_STANCE = /\b(YES|NO|ABSTAIN)\b/g;

/** Leading separators between the stance and the reason. */
const REASON_LEAD = /^[\s:—–\-·|]+/;

const FIELD = (name: string) => new RegExp(`^\\s*${name}\\s*:\\s*(.*)$`, 'i');
const QUESTION_FIELD = FIELD('question');
const RULE_FIELD = FIELD('rule');
const ASKED_FIELD = FIELD('asked');

const lines = (body: string) => body.split(/\r?\n/);

/** The message's first non-empty line, trimmed. */
function firstLine(body: string): string {
  for (const line of lines(body)) {
    const t = line.trim();
    if (t) return t;
  }
  return '';
}

/** True when this message is an attempt to open a round — well-formed or not. An
 *  opener always ends the preceding round. */
export function isConsensusOpening(body: string): boolean {
  return firstLine(body).toUpperCase() === CONSENSUS_OPEN_MARKER;
}

function field(body: string, re: RegExp): string {
  for (const line of lines(body)) {
    const m = re.exec(line);
    if (m) return m[1].trim();
  }
  return '';
}

/**
 * Read a single message as a position.
 *
 * Returns `null` when the message states no position at all (the ordinary case —
 * most chat is not a vote), `'ambiguous'` when it states more than one, and the
 * stance otherwise. Ambiguity is resolved AGAINST counting: two different stances,
 * or a line that is plainly the copied instruction template, yield no vote.
 */
export function readPositionLine(body: string): { stance: Stance; reason: string } | 'ambiguous' | null {
  const found: { stance: Stance; reason: string }[] = [];
  let sawTemplateEcho = false;

  for (const line of lines(body)) {
    const m = POSITION_LINE.exec(line);
    if (!m) continue;

    // A line offering the menu of stances ("POSITION: YES | NO | ABSTAIN") is the
    // instruction being echoed back, not an answer.
    SHOUTED_STANCE.lastIndex = 0;
    const shouted = new Set((line.match(SHOUTED_STANCE) ?? []).map((w) => w.toUpperCase()));
    if (shouted.size > 1) {
      sawTemplateEcho = true;
      continue;
    }

    found.push({
      stance: m[1].toLowerCase() as Stance,
      reason: m[2].replace(REASON_LEAD, '').trim(),
    });
  }

  if (found.length === 0) return sawTemplateEcho ? 'ambiguous' : null;
  // Repeating the SAME stance is not ambiguous; stating two different ones is.
  if (new Set(found.map((f) => f.stance)).size > 1) return 'ambiguous';
  return found[0];
}

/**
 * Derive every consensus round from a room's messages, oldest first.
 *
 * `messages` must be in transcript order (the order `list_messages` returns). A
 * round runs from its opening message up to the next opening message (well-formed
 * or not) or the end of the transcript. The opening message itself is never read as
 * a position: it carries the instruction text, and the opener's job is to ask, not
 * to vote — the opener may still vote in a later message like anyone else.
 */
export function readConsensusTranscript(messages: readonly Message[]): ConsensusTranscript {
  const rounds: ConsensusRound[] = [];
  const malformed: MalformedRound[] = [];
  let current: ConsensusRound | null = null;

  for (const m of messages) {
    const body = m.body ?? '';
    const author = (m.author ?? '').trim();

    if (isConsensusOpening(body)) {
      // Any opener closes the previous round, including a malformed one.
      current = null;

      const question = field(body, QUESTION_FIELD);
      const ruleText = field(body, RULE_FIELD).toLowerCase();
      const asked = normalizeAsked(field(body, ASKED_FIELD).split(','));

      const problem: MalformedProblem | null =
        !question ? 'missing_question'
        : !isConsensusRule(ruleText) ? 'unknown_rule'
        : asked.length === 0 ? 'missing_asked'
        : null;

      if (problem) {
        malformed.push({ messageId: m.id, author, at: m.createdAt, problem });
        continue;
      }

      current = {
        id: m.id,
        question,
        rule: ruleText as ConsensusRule,
        asked,
        openedBy: author,
        openedAt: m.createdAt,
        positions: [],
        ambiguous: [],
      };
      rounds.push(current);
      continue;
    }

    if (!current || !author) continue;

    const read = readPositionLine(body);
    if (read === null) continue;
    if (read === 'ambiguous') {
      current.ambiguous.push({ messageId: m.id, author, at: m.createdAt });
      continue;
    }
    current.positions.push({
      participant: author,
      stance: read.stance,
      reason: read.reason,
      messageId: m.id,
      at: m.createdAt,
    });
  }

  return { rounds, malformed };
}

/** Collapse a question to a single line so it cannot break the field grammar or
 *  smuggle a second `rule:` / `asked:` line into the opening message. */
export function sanitizeQuestion(question: string): string {
  return question.replace(/\s+/g, ' ').trim();
}

/**
 * Build the opening message body. This is the text that is actually posted into the
 * room, so it must be readable by a person AND parseable by `readConsensusTranscript`.
 *
 * The instruction line deliberately does not spell `POSITION:` followed by a stance —
 * writing the template literally would make the opener look like a vote to any reader
 * (human or model) skimming for the pattern.
 */
export function formatConsensusOpening(
  question: string,
  rule: ConsensusRule = DEFAULT_CONSENSUS_RULE,
  asked: readonly string[] = [],
): string {
  return [
    CONSENSUS_OPEN_MARKER,
    `question: ${sanitizeQuestion(question)}`,
    `rule: ${rule}`,
    `asked: ${normalizeAsked(asked).join(', ')}`,
    'Everyone asked: answer with one line that starts with the word POSITION, a colon,',
    'then exactly one of YES / NO / ABSTAIN, then a short reason. One line, your own answer.',
  ].join('\n');
}

/** Participant names must survive the `asked:` comma list unchanged. A name holding
 *  a comma or a newline would silently split into two participants and change the
 *  round's threshold, so it is refused at the point of asking. */
export function isAskableName(name: string): boolean {
  const n = name.trim();
  return n.length > 0 && !/[,\r\n]/.test(n);
}
