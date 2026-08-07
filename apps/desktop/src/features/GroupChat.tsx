import { useMemo, useState } from 'react';
import { useApp } from '../app/store';
import {
  Badge, Button, EmptyState, ErrorState, FormRow, Input, Select, Skeleton,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import type { Tone } from '../domain/enums';
import { Conversations } from './Conversations';
import { STR } from './GroupChat.strings';
import {
  CONSENSUS_RULES, DEFAULT_CONSENSUS_RULE, evaluateConsensus,
  type ConsensusOutcome, type ConsensusReason, type ConsensusRule,
  type ConsensusVerdict, type Position,
} from './consensus';
import {
  formatConsensusOpening, isAskableName, readConsensusTranscript,
  type ConsensusRound, type MalformedProblem,
} from './groupChatConsensus';

type Key = keyof typeof STR;

const RULE_KEY: Record<ConsensusRule, Key> = {
  unanimous: 'ruleUnanimous',
  majority: 'ruleMajority',
  supermajority: 'ruleSupermajority',
};

const OUTCOME_KEY: Record<ConsensusOutcome, Key> = {
  reached: 'outcomeReached',
  not_reached: 'outcomeNotReached',
  pending: 'outcomePending',
};

/** `pending` is amber and `not_reached` is red — neither may ever borrow the green
 *  that means a decision was made. */
const OUTCOME_TONE: Record<ConsensusOutcome, Tone> = {
  reached: 'success',
  not_reached: 'danger',
  pending: 'warning',
};

const REASON_KEY: Record<ConsensusReason, Key> = {
  threshold_met: 'reasonThresholdMet',
  threshold_missed: 'reasonThresholdMissed',
  threshold_unreachable: 'reasonThresholdUnreachable',
  awaiting_positions: 'reasonAwaitingPositions',
  no_participants: 'reasonNoParticipants',
};

const MALFORMED_KEY: Record<MalformedProblem, Key> = {
  missing_question: 'malformedMissingQuestion',
  unknown_rule: 'malformedUnknownRule',
  missing_asked: 'malformedMissingAsked',
};

/** Per-view CSS for the consensus deck, scoped under `.v-group` so it cannot leak
 *  into the shared chat styling that `<Conversations>` brings with it. */
const VIEW_CSS = `
.v-group .cs-deck{margin-top:18px;padding:16px 18px}
.v-group .cs-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:6px}
.v-group .cs-note{margin:0 0 14px;font-size:12px;color:var(--ink-muted);line-height:1.55;max-width:78ch}
.v-group .cs-roompick{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:16px}
.v-group .cs-roompick .select{width:auto;min-width:180px;max-width:320px}
.v-group .cs-round{border:1px solid var(--line);border-radius:var(--r);padding:14px 15px;margin-bottom:14px}
.v-group .cs-round.is-old{opacity:.82}
.v-group .cs-q{margin:0 0 10px;font-size:14.5px;line-height:1.5;color:var(--ink)}
.v-group .cs-verdict{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.v-group .cs-rule{font-size:11.5px;color:var(--ink-muted);letter-spacing:.02em}
.v-group .cs-why{margin:7px 0 0;font-size:12.5px;line-height:1.55;color:var(--ink-muted)}
.v-group .cs-fixed{margin:4px 0 0;font-size:11.5px;line-height:1.5;color:var(--ink-muted)}
.v-group .cs-block{margin-top:14px}
.v-group .cs-lbl{display:block;color:var(--ink-muted);letter-spacing:.08em;margin-bottom:5px}
.v-group .cs-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:5px}
.v-group .cs-row{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;font-size:12.5px;line-height:1.5}
.v-group .cs-who{min-width:0;overflow-wrap:anywhere}
.v-group .cs-stance{font-size:11px;letter-spacing:.06em;padding:1px 6px;border-radius:999px;border:1px solid var(--line);flex:0 0 auto}
.v-group .cs-yes .cs-stance{color:var(--success);border-color:rgb(var(--success-rgb)/.45)}
.v-group .cs-no .cs-stance{color:var(--danger);border-color:rgb(var(--danger-rgb)/.45)}
.v-group .cs-abstain .cs-stance,.v-group .cs-silent .cs-stance{color:var(--warning);border-color:rgb(var(--warning-rgb)/.45)}
.v-group .cs-reason{color:var(--ink-muted);overflow-wrap:anywhere}
.v-group .cs-none{margin:0;font-size:12.5px;color:var(--ink-muted)}
.v-group .cs-count{display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px;margin-bottom:6px}
.v-group .cs-count b{font-family:var(--f-mono);color:var(--ink)}
.v-group .cs-caveat{margin-top:12px;font-size:12px;line-height:1.5;color:var(--warning)}
.v-group .cs-caveat ul{list-style:none;margin:4px 0 0;padding:0;display:flex;flex-direction:column;gap:3px}
.v-group .cs-form{border-top:1px solid var(--line);padding-top:14px;margin-top:4px}
.v-group .cs-pick{display:flex;flex-wrap:wrap;gap:6px}
.v-group .cs-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:10px}
.v-group .cs-error{margin:10px 0 0;font-size:12.5px;line-height:1.5;color:var(--danger)}
.v-group .cs-error ul{list-style:none;margin:4px 0 0;padding:0;display:flex;flex-direction:column;gap:3px}
`;

/** One recorded position, rendered with its participant, stance and stated reason.
 *  The reason is never dropped: an unexplained vote says so out loud. */
function PositionRow({ position, stanceLabel, noReason }: {
  position: Position;
  stanceLabel: string;
  noReason: string;
}) {
  return (
    <li className={`cs-row cs-${position.stance}`}>
      <b className="cs-who">{position.participant}</b>
      <span className="cs-stance mono">{stanceLabel}</span>
      <span className="cs-reason">{position.reason || noReason}</span>
    </li>
  );
}

function RoundCard({ round, verdict, old }: {
  round: ConsensusRound;
  verdict: ConsensusVerdict;
  old?: boolean;
}) {
  const { lang } = useApp();
  const L = (k: Key) => STR[k][lang] ?? STR[k].en;
  const { tally } = verdict;
  const stance = { yes: L('stanceYes'), no: L('stanceNo'), abstain: L('stanceAbstain') } as const;
  const noReason = L('noReason');

  // Dissent = every recorded non-YES, plus everyone who was asked and stayed silent.
  // Rendered for EVERY outcome, `reached` included — an outcome shown without the
  // disagreement behind it is the defect this deck exists to prevent.
  const hasDissent = verdict.dissent.length > 0 || tally.missing.length > 0;

  return (
    <article className={`cs-round${old ? ' is-old' : ''}`}>
      <p className="cs-q">{round.question}</p>

      <div className="cs-verdict" role="status" data-outcome={verdict.outcome}>
        <Badge tone={OUTCOME_TONE[verdict.outcome]}>{L(OUTCOME_KEY[verdict.outcome])}</Badge>
        <span className="cs-rule mono">
          {L('ruleStated')}: {L(RULE_KEY[verdict.rule])} · {tally.requiredYes}/{tally.asked.length}{' '}
          {L('needsYes')} {L('fullParticipation')}
        </span>
      </div>
      <p className="cs-why">{L(REASON_KEY[verdict.reason])}</p>
      <p className="cs-fixed">
        {L('askedByLabel')} {round.openedBy || '—'} · {L('ruleFixedNote')}
      </p>

      <div className="cs-block">
        <span className="micro cs-lbl">{L('tallyLabel')}</span>
        <div className="cs-count">
          <span>{L('stanceYes')}&nbsp;<b>{tally.yes.length}</b></span>
          <span>{L('stanceNo')}&nbsp;<b>{tally.no.length}</b></span>
          <span>{L('stanceAbstain')}&nbsp;<b>{tally.abstain.length}</b></span>
          <span>{L('noAnswer')}&nbsp;<b>{tally.missing.length}</b></span>
        </div>
        <ul className="cs-list" aria-label={L('tallyLabel')}>
          {tally.yes.map((p) => (
            <PositionRow key={p.messageId} position={p} stanceLabel={stance.yes} noReason={noReason} />
          ))}
          {tally.no.map((p) => (
            <PositionRow key={p.messageId} position={p} stanceLabel={stance.no} noReason={noReason} />
          ))}
          {tally.abstain.map((p) => (
            <PositionRow key={p.messageId} position={p} stanceLabel={stance.abstain} noReason={noReason} />
          ))}
          {tally.missing.map((name) => (
            <li className="cs-row cs-silent" key={`missing-${name}`}>
              <b className="cs-who">{name}</b>
              <span className="cs-stance mono">{L('noAnswer')}</span>
              <span className="cs-reason">{L('silentLabel')}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="cs-block">
        <span className="micro cs-lbl">{L('dissentLabel')}</span>
        <ul className="cs-list" aria-label={L('dissentLabel')}>
          {verdict.dissent.map((p) => (
            <PositionRow
              key={`d-${p.messageId}`}
              position={p}
              stanceLabel={p.stance === 'no' ? stance.no : stance.abstain}
              noReason={noReason}
            />
          ))}
          {tally.missing.map((name) => (
            <li className="cs-row cs-silent" key={`d-missing-${name}`}>
              <b className="cs-who">{name}</b>
              <span className="cs-stance mono">{L('noAnswer')}</span>
              <span className="cs-reason">{L('silentLabel')}</span>
            </li>
          ))}
          {/* Absence of dissent is STATED, never merely absent — an empty area reads
              as "not shown" just as easily as "there was none". */}
          {!hasDissent && <li className="cs-none">{L('noDissent')}</li>}
        </ul>
      </div>

      {(tally.superseded.length > 0 || tally.unsolicited.length > 0 || round.ambiguous.length > 0) && (
        <div className="cs-caveat">
          {tally.superseded.length > 0 && (
            <>
              <span className="micro cs-lbl">{L('revisedLabel')}</span>
              <ul>
                {tally.superseded.map((p) => (
                  <li key={`s-${p.messageId}`}>
                    {p.participant} — {stance[p.stance]}
                    {p.reason ? ` · ${p.reason}` : ''}
                  </li>
                ))}
              </ul>
            </>
          )}
          {tally.unsolicited.length > 0 && (
            <>
              <span className="micro cs-lbl">{L('unsolicitedLabel')}</span>
              <ul>
                {tally.unsolicited.map((p) => (
                  <li key={`u-${p.messageId}`}>
                    {p.participant} — {stance[p.stance]}
                    {p.reason ? ` · ${p.reason}` : ''}
                  </li>
                ))}
              </ul>
            </>
          )}
          {round.ambiguous.length > 0 && (
            <>
              <span className="micro cs-lbl">{L('ambiguousLabel')}</span>
              <ul>
                {round.ambiguous.map((a) => <li key={`a-${a.messageId}`}>{a.author}</li>)}
              </ul>
            </>
          )}
        </div>
      )}
    </article>
  );
}

/** The consensus deck for one group room: every round the transcript records, plus
 *  the form that opens a new one and actually asks the participants. */
function ConsensusDeck() {
  const { t, lang, openEntity } = useApp();
  const L = (k: Key) => STR[k][lang] ?? STR[k].en;

  const rooms = useAsync(() => desktop.listConversations('group'), []);
  const agents = useAsync(() => desktop.listAgents(), []);
  const [pickedRoom, setPickedRoom] = useState<string | null>(null);

  const roomList = rooms.data ?? [];
  const room = roomList.find((c) => c.id === pickedRoom) ?? roomList[0] ?? null;
  const roomId = room?.id ?? null;

  const messages = useAsync(
    () => (roomId ? desktop.listMessages(roomId) : Promise.resolve([])),
    [roomId],
  );
  const roster = useAsync(
    () => (roomId ? desktop.listConversationParticipants(roomId) : Promise.resolve([] as string[])),
    [roomId],
  );

  const transcript = useMemo(() => readConsensusTranscript(messages.data ?? []), [messages.data]);
  const rounds = transcript.rounds;
  const latest = rounds.length > 0 ? rounds[rounds.length - 1] : null;
  const latestVerdict = latest ? evaluateConsensus(latest.rule, latest.asked, latest.positions) : null;

  // Who the form offers to ask: the room's own roster when it has one, otherwise the
  // known agents. Whoever is actually asked is written into the opening message, so
  // this is only a starting selection — never the record of what was asked.
  const agentNames = (agents.data ?? []).map((a) => a.displayName);
  const candidates = useMemo(() => {
    const base = (roster.data ?? []).length > 0 ? (roster.data ?? []) : agentNames;
    return base.filter(isAskableName);
  }, [roster.data, agents.data]);

  const [question, setQuestion] = useState('');
  const [rule, setRule] = useState<ConsensusRule>(DEFAULT_CONSENSUS_RULE);
  const [picked, setPicked] = useState<string[] | null>(null);
  const chosen = (picked ?? candidates).filter((n) => candidates.includes(n));
  const togglePick = (n: string) =>
    setPicked((prev) => {
      const base = prev ?? candidates;
      return base.includes(n) ? base.filter((x) => x !== n) : [...base, n];
    });

  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [askErrors, setAskErrors] = useState<{ who: string; detail: string }[]>([]);

  /**
   * Ask each participant, in turn, through the ordinary reply path. Their answer is
   * persisted server-side under their own author, which is the only reason a position
   * read back out of the transcript means anything.
   *
   * Every failure mode is recorded and shown, and NONE of them produces a position: a
   * blocked governed turn persists no message, so that participant simply stays
   * unanswered and the round stays open. The renderer never writes a position on an
   * agent's behalf.
   */
  const collect = async (conversationId: string, who: string[]): Promise<{ who: string; detail: string }[]> => {
    const errors: { who: string; detail: string }[] = [];
    for (const name of who) {
      try {
        await desktop.streamReply(conversationId, (ev) => {
          if (ev.type === 'error') errors.push({ who: name, detail: ev.message });
          else if (ev.type === 'blocked') {
            errors.push({ who: name, detail: `${t('chat.governedBlocked')}: ${ev.reason}` });
          }
        }, name);
      } catch (e: unknown) {
        errors.push({ who: name, detail: e instanceof Error ? e.message : String(e) });
      }
    }
    return errors;
  };

  const openRound = async () => {
    if (!roomId || busy) return;
    const q = question.trim();
    if (!q) { setFormError(L('needQuestion')); return; }
    const asked = chosen.filter(isAskableName);
    if (asked.length === 0) { setFormError(L('needParticipants')); return; }

    setBusy(true);
    setFormError(null);
    setAskErrors([]);
    try {
      await desktop.postMessage({
        conversationId: roomId,
        author: t('chat.you'),
        body: formatConsensusOpening(q, rule, asked),
      });
    } catch (e: unknown) {
      // The opening message is the round. If it was not persisted there is no round,
      // and nobody is asked — say so instead of leaving a half-open round on screen.
      setFormError(`${L('postFailed')}: ${e instanceof Error ? e.message : String(e)}`);
      setBusy(false);
      return;
    }
    setQuestion('');
    const errors = await collect(roomId, asked);
    setAskErrors(errors);
    setBusy(false);
    messages.reload();
  };

  const askMissing = async () => {
    if (!roomId || busy || !latestVerdict || latestVerdict.tally.missing.length === 0) return;
    setBusy(true);
    setAskErrors([]);
    const errors = await collect(roomId, latestVerdict.tally.missing);
    setAskErrors(errors);
    setBusy(false);
    messages.reload();
  };

  const loading = rooms.loading && rooms.data === null;

  return (
    <section className="surface soft cs-deck" aria-label={L('consensusEyebrow')}>
      <div className="cs-head">
        <span className="eyebrow">{L('consensusEyebrow')}</span>
      </div>
      <p className="cs-note">{L('consensusNote')}</p>

      {loading && <Skeleton rows={3} />}
      {rooms.error && <ErrorState message={rooms.error} onRetry={rooms.reload} retryLabel={t('action.retry')} />}

      {!loading && !rooms.error && roomList.length === 0 && (
        <EmptyState glyph="👥" title={L('noRooms')} hint={L('noRoomsHint')} />
      )}

      {room && (
        <>
          <div className="cs-roompick">
            <label className="micro" htmlFor="cs-room">{L('roomLabel')}</label>
            <Select
              id="cs-room"
              value={room.id}
              aria-label={L('roomLabel')}
              onChange={(e) => { setPickedRoom(e.target.value); setPicked(null); }}
            >
              {roomList.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
            </Select>
            <Button small variant="ghost" onClick={() => openEntity('groupChat', 'conversation', room.id)}>
              {L('showRoom')}
            </Button>
          </div>

          {messages.loading && messages.data === null && <Skeleton rows={3} />}
          {messages.error && (
            <ErrorState message={messages.error} onRetry={messages.reload} retryLabel={t('action.retry')} />
          )}

          {messages.data !== null && !messages.error && rounds.length === 0 && (
            <EmptyState glyph="⚖" title={L('noRounds')} hint={L('noRoundsHint')} />
          )}

          {latest && latestVerdict && <RoundCard round={latest} verdict={latestVerdict} />}

          {rounds.length > 1 && (
            <div className="cs-block">
              <span className="micro cs-lbl">{L('earlierRounds')}</span>
              {rounds.slice(0, -1).reverse().map((r) => (
                <RoundCard key={r.id} round={r} old verdict={evaluateConsensus(r.rule, r.asked, r.positions)} />
              ))}
            </div>
          )}

          {transcript.malformed.length > 0 && (
            <div className="cs-caveat">
              <span className="micro cs-lbl">{L('malformedLabel')}</span>
              <ul>
                {transcript.malformed.map((m) => (
                  <li key={m.messageId}>{m.author} — {L(MALFORMED_KEY[m.problem])}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="cs-form">
            <span className="micro cs-lbl">{L('openRoundTitle')}</span>
            <FormRow label={L('questionLabel')}>
              <Input
                value={question}
                placeholder={L('questionPlaceholder')}
                aria-label={L('questionLabel')}
                onChange={(e) => setQuestion(e.target.value)}
              />
            </FormRow>
            <FormRow label={L('ruleLabel')}>
              <Select
                value={rule}
                aria-label={L('ruleLabel')}
                onChange={(e) => setRule(e.target.value as ConsensusRule)}
              >
                {CONSENSUS_RULES.map((r) => (
                  <option key={r} value={r}>{L(RULE_KEY[r])}</option>
                ))}
              </Select>
            </FormRow>
            {candidates.length > 0 && (
              <FormRow label={L('askLabel')}>
                <div className="cs-pick">
                  {candidates.map((n) => (
                    <button
                      key={n}
                      type="button"
                      className={`pp-chip${chosen.includes(n) ? ' on' : ''}`}
                      aria-pressed={chosen.includes(n)}
                      onClick={() => togglePick(n)}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </FormRow>
            )}
            <div className="cs-actions">
              <Button variant="primary" onClick={() => void openRound()} disabled={busy}>
                {busy ? L('opening') : L('openRound')}
              </Button>
              {latestVerdict && latestVerdict.tally.missing.length > 0 && (
                <Button variant="ghost" small onClick={() => void askMissing()} disabled={busy}>
                  {L('askMissing')}
                </Button>
              )}
            </div>
            {formError && <p className="cs-error" role="alert">⚠ {formError}</p>}
            {askErrors.length > 0 && (
              <div className="cs-error" role="status">
                <ul>
                  {askErrors.map((e, i) => (
                    <li key={`${e.who}-${i}`}>⚠ {L('askFailed')} {e.who}: {e.detail}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}

/**
 * Group Chat (Phase 7) — the collaboration hall: the shared conversation workspace,
 * plus the CONSENSUS deck underneath it.
 *
 * The deck carries its own room selector because the workspace above owns its
 * selection privately; "Show this room above" pushes the deck's choice up through
 * the store's deep-link. The one seam still missing is the other direction — see the
 * note in the handoff report.
 */
export function GroupChat() {
  return (
    <div className="v-group">
      <style>{VIEW_CSS}</style>
      <Conversations kind="group" />
      <ConsensusDeck />
    </div>
  );
}
