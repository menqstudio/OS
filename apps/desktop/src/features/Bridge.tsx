// The governed BRIDGE panel — the renderer-side surface of the Phase-1 bridge.
//
// Three things were fully implemented on the desktop side and reachable from no screen:
//
//   * `read_decision_ledger`   — the engine's own decision ledger (registered in Rust, no TS wrapper)
//   * `read_verifier_verdicts` — the independent-verifier receipts (registered in Rust, no TS wrapper)
//   * `governed_turn_execute`  — wrapped in `services/desktop.ts` as `governedTurn()`, called by nothing
//
// This panel is the only place any of them is reachable. It is deliberately austere: every row states
// what the desktop actually received and nothing else. The rules it follows, in order of importance:
//
//   1. A verdict is shown ONLY when someone who can issue one issued it. `isVerified` — a broker-emitted
//      `committed` frame carrying `trusted_verified` — is the sole gate for a "Verified" affordance, and
//      the renderer has no other path to it.
//   2. "The broker refused" and "no broker was reached" are rendered as DIFFERENT outcomes with different
//      words. The Rust proxy keeps three non-decision prefixes mutually distinguishable precisely so this
//      distinction survives to the screen; collapsing them here would throw that work away.
//   3. An absence is rendered as an absence. A mirror that answered with zero records is "nothing to
//      mirror", never a satisfied surface; records with no checkable signature are labelled as such.
//   4. Nothing is sent without an explicit click. The mirrors are read-only reads; the governed turn is
//      a user-initiated action, never an on-mount side effect.

import { useState } from 'react';
import { useApp } from '../app/store';
import { Button, ErrorState, Select, Skeleton } from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { desktop, governedTurnAttempt } from '../services/desktop';
import { isUnauthenticatedMirror, recordCount, type GovernanceRead } from '../services/governance';
import { isVerified, type GovernedTurnAttempt, type NonDecision } from '../services/governedTurn';
import type { Conversation } from '../domain/entities';
import { STR } from './Bridge.strings';

const styles = `
.v-bridge { margin-top: 26px; }
.v-bridge .br-panel { padding: var(--s5, 18px); border-radius: var(--r-md, 12px); }
.v-bridge .br-intro { color: var(--ink-muted); max-width: 72ch; }
.v-bridge .br-sec { margin-top: var(--s5, 18px); }
.v-bridge .br-sec > h3 { font-size: var(--t-small, 13px); letter-spacing: .1em; text-transform: uppercase; color: var(--cyan-soft); margin: 0 0 10px; }
.v-bridge .br-row { padding: 12px 0; border-top: 1px solid var(--hairline, rgba(127,127,127,.24)); }
.v-bridge .br-row:first-of-type { border-top: none; }
.v-bridge .br-row-head { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.v-bridge .br-row-name { font-weight: 600; }
.v-bridge .br-note, .v-bridge .br-why { color: var(--ink-muted); margin: 6px 0 0; }
.v-bridge .br-why { word-break: break-word; }
.v-bridge .br-turn-controls { display: flex; flex-wrap: wrap; align-items: end; gap: 12px; margin: 12px 0; }
.v-bridge .br-body { margin: 6px 0 0; max-width: 72ch; }
.v-bridge .br-msg { margin-top: 10px; padding: 10px 12px; border-radius: var(--r-sm, 8px); background: var(--surface-2, rgba(127,127,127,.08)); white-space: pre-wrap; }
`;

/** Every non-decision maps to exactly one plain-language gloss. A `Record` (not a lookup by string
 *  concatenation) so a new taxonomy member is a compile error here rather than a blank line on screen. */
const NON_DECISION_COPY: Record<NonDecision, keyof typeof STR> = {
  broker_unsupported_platform: 'nd_broker_unsupported_platform',
  broker_unavailable: 'nd_broker_unavailable',
  broker_transport_failed: 'nd_broker_transport_failed',
  malformed_request: 'nd_malformed_request',
  malformed_broker_reply: 'nd_malformed_broker_reply',
  no_desktop_backend: 'nd_no_desktop_backend',
  unclassified_transport_failure: 'nd_unclassified_transport_failure',
};

type Localize = (k: keyof typeof STR) => string;

/**
 * One governance-mirror row. `read` is `null` while the read is still in flight — rendered as
 * "reading…", never as an empty or satisfied surface.
 *
 * The state word is chosen from the real `GovernanceRead` and nothing else:
 *   ok + records   → the count (plus an explicit unauthenticated-origin label; the backend reports
 *                    `authenticated: false` in this build and this row must say so)
 *   ok + none      → "answered · nothing to mirror" — an absence, which is not a satisfied surface
 *   blocked        → the engine refused
 *   unreachable    → nothing was reached
 */
function MirrorRow({ name, note, read, L }: {
  name: string;
  note: string;
  read: GovernanceRead | null;
  L: Localize;
}) {
  const n = read ? recordCount(read) : 0;
  const state = read === null
    ? L('stateReading')
    : read.state === 'ok'
      ? (n > 0 ? `${L('stateRecords')}${n}` : L('stateEmpty'))
      : read.state === 'blocked'
        ? L('stateBlocked')
        : L('stateUnreachable');
  // The mirror is unauthenticated whenever records arrived without the backend asserting otherwise.
  const unauthenticated = !!read && n > 0 && isUnauthenticatedMirror(read);
  return (
    <div className="br-row">
      <div className="br-row-head">
        <span className="br-row-name">{name}</span>
        <span className="pill">{state}</span>
        {unauthenticated ? <span className="pill warn">{L('unverifiedOrigin')}</span> : null}
      </div>
      <p className="micro br-note">{note}</p>
      {unauthenticated ? <p className="micro br-why">{L('unverifiedOriginBody')}</p> : null}
      {read && read.state !== 'ok' && read.reason ? (
        <p className="micro br-why">{L('whyPrefix')}{read.reason}</p>
      ) : null}
    </div>
  );
}

/** The governed-turn outcome readout. Renders exactly one of three mutually exclusive facts. */
function TurnOutcome({ attempt, L }: { attempt: GovernedTurnAttempt; L: Localize }) {
  // The ONE gate for a verified affordance. False for every `unavailable` outcome by construction,
  // and false for any committed frame that is not `trusted_verified` (which `parseResult` already
  // refuses to build).
  if (isVerified(attempt) && attempt.status === 'committed') {
    return (
      <div role="note">
        <span className="pill ok">{L('outcomeVerified')}</span>
        <p className="br-body">{L('outcomeVerifiedBody')}</p>
        <p className="micro br-why">{L('turnIdLabel')}<b className="mono">{attempt.brokerTurnId}</b></p>
        <div className="br-msg">{attempt.message.body}</div>
      </div>
    );
  }
  if (attempt.status === 'blocked') {
    // A real broker verdict. It is a refusal, and it is named as one — with the closed machine reason.
    return (
      <div role="note">
        <span className="pill warn">{L('outcomeBlocked')}</span>
        <p className="br-body">{L('outcomeBlockedBody')}</p>
        <p className="micro br-why">{L('reasonLabel')}<b className="mono">{attempt.reason}</b></p>
        <p className="micro br-why">{L('turnIdLabel')}<b className="mono">{attempt.brokerTurnId}</b></p>
      </div>
    );
  }
  // Everything else is a NON-decision: nobody allowed or refused this turn. `committed`-but-not-verified
  // cannot occur (parseResult rejects it), so the only way here is `unavailable`.
  if (attempt.status !== 'unavailable') return null;
  return (
    <div role="note">
      <span className="pill">{L('outcomeUnavailable')}</span>
      <p className="br-body">{L('outcomeUnavailableBody')}</p>
      <p className="micro br-why">{L('kindLabel')}<b className="mono">{attempt.kind}</b></p>
      <p className="micro br-why">{L(NON_DECISION_COPY[attempt.kind])}</p>
      <p className="micro br-why">{attempt.detail}</p>
    </div>
  );
}

/**
 * The bridge panel. `taskId` scopes the verifier-verdicts mirror to one decision; without it the mirror
 * is read unfiltered and the row says so, rather than implying the verdicts belong to something.
 */
export function BridgePanel({ taskId }: { taskId?: string } = {}) {
  const { lang } = useApp();
  const L: Localize = (k) => STR[k][lang] ?? STR[k].en;

  // Read-only governance mirrors. Safe to read on mount: they carry no authority, mutate nothing, and
  // fail closed to a typed blocked/unreachable state rather than rejecting.
  const ledger = useAsync<GovernanceRead>(() => desktop.readDecisionLedger(), []);
  const verdicts = useAsync<GovernanceRead>(() => desktop.readVerifierVerdicts(taskId), [taskId]);
  // Real conversations, so a governed turn addresses something that exists rather than a typed-in id.
  const convos = useAsync<Conversation[]>(() => desktop.listConversations(), []);

  // The user's explicit pick, or `null` for "whatever the default is". The selection is DERIVED rather
  // than copied into state by an effect: an effect leaves one committed frame in which the conversation
  // list is on screen but nothing is selected yet, and in that frame the send button is disabled and a
  // click is silently swallowed. Deriving it means the control is never offered before it works.
  const [picked, setPicked] = useState<string | null>(null);
  const [attempt, setAttempt] = useState<GovernedTurnAttempt | null>(null);
  const [sending, setSending] = useState(false);

  const conversations = convos.data ?? [];
  // Never invent an id: this is empty until a real conversation exists to address.
  const conversationId = picked ?? conversations[0]?.id ?? '';

  const send = async () => {
    if (!conversationId || sending) return;
    setSending(true);
    // Clear the previous outcome first: a stale verdict must never sit on screen beside a new request.
    setAttempt(null);
    // `governedTurnAttempt` resolves with a decision OR an honest non-decision, and never rejects, so
    // there is no failure mode in which this panel is left claiming an outcome it does not have.
    const r = await governedTurnAttempt(conversationId);
    setAttempt(r);
    setSending(false);
  };

  return (
    <section className="v-bridge" aria-label={STR.panelTitle.en}>
      <style>{styles}</style>
      <div className="surface soft br-panel">
        <header className="br-row-head">
          <div>
            <span className="eyebrow">{L('panelEyebrow')}</span>
            <h2>{L('panelTitle')}</h2>
          </div>
          <span className="pill info">{L('rendererCannotVerify')}</span>
        </header>
        <p className="micro br-intro">{L('panelIntro')}</p>

        <div className="br-sec">
          <h3>{L('mirrorsTitle')}</h3>
          <MirrorRow
            name={L('surfaceLedger')}
            note={L('surfaceLedgerNote')}
            read={ledger.data}
            L={L}
          />
          <MirrorRow
            name={L('surfaceVerdicts')}
            note={taskId ? L('surfaceVerdictsNote') : L('surfaceVerdictsNoSelection')}
            read={verdicts.data}
            L={L}
          />
        </div>

        <div className="br-sec">
          <h3>{L('turnTitle')}</h3>
          <p className="micro br-intro">{L('turnIntro')}</p>

          {convos.loading && convos.data === null ? (
            <Skeleton rows={2} />
          ) : convos.error ? (
            <ErrorState message={convos.error} onRetry={convos.reload} />
          ) : conversations.length === 0 ? (
            <p className="micro br-why">{L('turnNoConversations')}</p>
          ) : (
            <div className="br-turn-controls">
              <label className="micro">
                <span style={{ display: 'block', marginBottom: 4 }}>{L('turnConversation')}</span>
                <Select
                  value={conversationId}
                  aria-label={L('turnConversation')}
                  onChange={(e) => setPicked(e.target.value)}
                >
                  {conversations.map((c) => (
                    <option key={c.id} value={c.id}>{c.title || c.id}</option>
                  ))}
                </Select>
              </label>
              <Button onClick={send} disabled={sending || !conversationId}>
                {sending ? L('turnRunning') : L('turnRun')}
              </Button>
            </div>
          )}

          <div aria-live="polite">
            {sending ? (
              <p className="micro br-why">{L('turnRunning')}</p>
            ) : attempt ? (
              <TurnOutcome attempt={attempt} L={L} />
            ) : (
              <p className="micro br-why">{L('turnIdle')}</p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
