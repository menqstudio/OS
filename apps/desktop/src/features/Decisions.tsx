import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react';
import { useApp } from '../app/store';
import {
  StatusPill, Field, Skeleton, ErrorState, EmptyState, Button,
} from '../components/ui';
import { Mark } from '../components/Ambient';
import { useAsync } from '../hooks/useAsync';
import { desktop } from '../services/desktop';
import {
  hasRecords, recordCount, engineEmptyReason, engineSourceKind, engineDoesNotKnowTask,
  type GovernanceRead,
} from '../services/governance';
import type { Decision } from '../domain/entities';
// `I-11`: the status classifier moved to its own module so a test can hold it to a vocabulary;
// `app/routes.tsx` types a page module as Record<string, ComponentType>, so it cannot live here.
import { statusMeta, decisionStatusFamily } from './Decisions.status';
import { STR } from './Decisions.strings';
import { BridgePanel } from './Bridge';

// Scoped supplements to the global `aios.css` decision-chamber design. The page is
// re-skinned to the "VERDICT CHAMBER" mockup, but every value it shows is REAL:
// the append-only engine ledger (`list_decisions`) and the read-only engine
// evidence-chain mirror. The mockup's fabricated instruments — the weighted balance
// beam, the A/B option pans, the confidence %, the winner/margin — have NO backing
// in the `Decision` entity and are therefore OMITTED, never faked. Motion is
// disabled under prefers-reduced-motion, per §D.
const styles = `
.v-decisions .ledger:focus-visible { outline: none; box-shadow: 0 0 0 2px var(--menq-color-focus); }
.v-decisions .ledger { border-radius: var(--r-md, 12px); outline: none; max-height: 62vh; overflow-y: auto; padding-right: 2px; }
.v-decisions .led { grid-template-columns: auto 1fr auto; cursor: pointer; animation: dec-reveal var(--menq-motion-med, .3s) ease both; }
.v-decisions .led.dec-stamp { animation: dec-stamp var(--menq-motion-med, .4s) cubic-bezier(0.2, 1.2, 0.3, 1) both; }
.v-decisions .ch-verdict { align-items: center; }
.v-decisions .vcore .mark { width: 46px; height: 46px; }
.dec-meta { display: flex; flex-wrap: wrap; gap: var(--s5, 18px); margin: var(--s4, 14px) 0; }
.dec-hint { font-size: var(--t-small, 13px); color: var(--ink-muted); }
.dec-sr-live { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
/* Evidence-chain lifecycle strip — real facts only (see renderChain). The .chain
   node colours and the .wire.live traveling pulse are the design-system classes
   whose @keyframes (nowPulse / travel) already live in aios.css. */
.v-decisions .dec-chain-strip { margin: var(--s4, 14px) 0 var(--s2, 8px); }
.v-decisions .dec-chain-lbl { display: block; color: var(--cyan-soft); letter-spacing: .1em; margin-bottom: 8px; }
.v-decisions .dec-chain-strip .wire { margin: 10px 0 0; }
/* The engine's own account of an empty surface. Set apart from the desktop's copy by a
   quiet rule, because it is a QUOTATION, not the page speaking. */
.v-decisions .dec-engine-said { margin-top: 10px; padding-left: 10px; border-left: 2px solid var(--brops-border); }
.v-decisions .dec-engine-said p { margin: 0 0 4px; color: var(--ink-muted); }
.v-decisions .dec-engine-said p:last-child { margin-bottom: 0; }
.v-decisions .dec-engine-attr { letter-spacing: .06em; }
@keyframes dec-reveal { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
/* The 100% keyframe MUST restate opacity. This row carries the "rise" class, which is opacity:0
   until an animation lifts it, and .led.dec-stamp REPLACES that animation with this one using
   "both". A property missing from the last keyframe gets an implicit 100% built from the
   UNDERLYING value - rise's opacity:0 - so a stamped decision row animated in and then faded
   back out to nothing. Same family as the fifth audit's A-01, and found by the check written in
   answer to it (tools/check_c1_tokens.py::animation_clobber). */
@keyframes dec-stamp { 0% { opacity: 0; transform: scale(1.12); } 60% { opacity: 1; transform: scale(0.98); } 100% { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) {
  .v-decisions .led, .v-decisions .led.dec-stamp { animation: none; }
  /* Keep the .now / .live colours (they carry meaning) but drop the motion. */
  .v-decisions .chain b.now { animation: none; }
  .v-decisions .dec-chain-strip .wire.live::after { animation: none; }
}
`;

export function Decisions() {
  const { t, lang, focus, clearFocus } = useApp();
  // Data source: the engine decision ledger, read-only, via the real
  // `list_decisions` Tauri command. No decision is minted or altered here.
  const s = useAsync<Decision[]>(() => desktop.listDecisions());

  const [selectedIndex, setSelectedIndex] = useState(0);
  // Which decision's evidence viewer is open. The evidence chain itself has no
  // desktop-facing command — opening it reveals the honest `blocked` (evidence
  // sealed) state the spec requires, never fabricated evidence.
  const [evidenceOpenId, setEvidenceOpenId] = useState<string | null>(null);
  // Real, READ-ONLY engine evidence-chain read for the open decision. Steady state in
  // Phase-2 is `blocked`/`unreachable` (the engine chain read is not answering yet) —
  // rendered honestly, never as fabricated evidence. `null` = still reading.
  const [evidenceRead, setEvidenceRead] = useState<GovernanceRead | null>(null);
  const [announce, setAnnounce] = useState('');

  // Visible strings are re-sourced from `Decisions.strings.ts` (EN + HY + RU), so the
  // Russian locale is correct too; shared i18n keys via `t(...)` are used where they
  // already exist. Falls back to EN if a locale value is ever missing.
  const L = (k: keyof typeof STR) => STR[k][lang] ?? STR[k].en;

  const dateFmt = useMemo(
    () => new Intl.DateTimeFormat(lang, { dateStyle: 'medium', timeStyle: 'short' }),
    [lang],
  );
  const fmtDate = (raw: string): string => {
    const v = raw?.trim();
    if (!v) return '—';
    const d = new Date(isNaN(Number(v)) ? v : Number(v));
    return isNaN(d.getTime()) ? v : dateFmt.format(d);
  };

  // Append-only ledger order: oldest → newest (new decisions land at the end,
  // matching log semantics and the `stamp`-on-append motion).
  const ledger = useMemo(() => {
    const list = s.data ?? [];
    return [...list].sort((a, b) => (a.createdAt || '').localeCompare(b.createdAt || ''));
  }, [s.data]);

  // Decision-stats strip — derived ENTIRELY from the real ledger. No mockup metric
  // (avg confidence, reversal %, evidence coverage) has any backing in the `Decision`
  // entity, so those are omitted; only honestly-countable facts are shown.
  const stats = useMemo(() => {
    // `I-11`: these two used to restate the classifier's regexes a third time, in a file where a
    // change to one copy and not the others would show up as a count that disagrees with the row
    // beside it. One classifier, three readers.
    const isBlocked = (d: Decision) => decisionStatusFamily(d.status) === 'blocked';
    const isPending = (d: Decision) => decisionStatusFamily(d.status) === 'waiting';
    return [
      { v: ledger.length, label: L('ledgerCount'), tone: '' },
      { v: new Set(ledger.map((d) => d.owner).filter(Boolean)).size, label: L('owners'), tone: 'info' },
      { v: ledger.filter(isPending).length, label: L('awaiting'), tone: 'warn' },
      { v: ledger.filter(isBlocked).length, label: L('blocked'), tone: 'warn' },
    ];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ledger, lang]);

  const loading = s.loading && s.data === null;
  const selIdx = ledger.length === 0 ? 0 : Math.min(selectedIndex, ledger.length - 1);
  const selected: Decision | null = ledger[selIdx] ?? null;
  const evidenceOpen = selected != null && evidenceOpenId === selected.id;

  // `stamp` the rows that appear after the first load (a genuinely new
  // decision), not the whole initial ledger.
  const seen = useRef<Set<string>>(new Set());
  const [stampIds, setStampIds] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (s.data === null) return;
    const prev = seen.current;
    const first = prev.size === 0;
    const fresh = new Set<string>();
    const next = new Set<string>();
    for (const d of s.data) {
      next.add(d.id);
      if (!prev.has(d.id)) fresh.add(d.id);
    }
    seen.current = next;
    if (first || fresh.size === 0) return;
    setStampIds(fresh);
    const timer = window.setTimeout(() => setStampIds(new Set()), 700);
    return () => window.clearTimeout(timer);
  }, [s.data]);

  // Consume a command-palette deep-link (e.g. a global-search hit) that targets
  // a specific decision: select it once the ledger has loaded, then clear focus.
  useEffect(() => {
    if (focus?.kind !== 'decision' || s.loading || s.data === null) return;
    const idx = ledger.findIndex((d) => d.id === focus.id);
    if (idx >= 0) {
      setSelectedIndex(idx);
      clearFocus();
    }
  }, [focus, ledger, s.loading, s.data, clearFocus]);

  // Keep the selected row visible as the keyboard moves through the ledger.
  const selRowRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    selRowRef.current?.scrollIntoView({ block: 'nearest' });
  }, [selIdx]);

  const openEvidence = (d: Decision | null) => {
    if (!d) return;
    setEvidenceOpenId(d.id);
    setAnnounce(`${L('readingChainFor')}${d.title}${L('readingChainForEnd')}`);
  };

  // Fetch the evidence chain (read-only) whenever a decision's evidence viewer opens.
  // The desktop mirrors the engine chain; it never holds or fabricates the evidence.
  useEffect(() => {
    if (!evidenceOpenId) { setEvidenceRead(null); return; }
    let alive = true;
    setEvidenceRead(null);
    desktop.readEvidenceChain(evidenceOpenId).then((r) => {
      if (!alive) return;
      setEvidenceRead(r);
      // An `ok` read that carried nothing is announced as "no evidence" — announcing
      // it as "mirrored" would tell a screen-reader user evidence arrived when none did.
      setAnnounce(r.state !== 'ok'
        ? L('chainSealedAnnounce')
        : hasRecords(r)
          ? L('chainMirrored')
          : L('chainEmptyAnnounce'));
    });
    return () => { alive = false; };
  }, [evidenceOpenId]);

  const onLedgerKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (ledger.length === 0) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Home' || e.key === 'End') {
      e.preventDefault();
      let nextIdx = selIdx;
      if (e.key === 'ArrowDown') nextIdx = Math.min(selIdx + 1, ledger.length - 1);
      else if (e.key === 'ArrowUp') nextIdx = Math.max(selIdx - 1, 0);
      else if (e.key === 'Home') nextIdx = 0;
      else nextIdx = ledger.length - 1;
      setSelectedIndex(nextIdx);
      const d = ledger[nextIdx];
      if (d) setAnnounce(`${L('selectedPrefix')}${d.title}`);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      openEvidence(ledger[selIdx] ?? null);
    }
  };

  const ledgerLabel = L('ledgerAria');

  const renderLedger = () => {
    if (loading) return <Skeleton rows={6} />;
    if (s.error) {
      // ErrorState renders the calm offline state when there is no backend at
      // all, and the engine-unreachable error otherwise.
      return <ErrorState message={s.error} onRetry={s.reload} />;
    }
    if (ledger.length === 0) {
      return (
        <EmptyState
          glyph="⚖"
          title={L('noDecisions')}
          hint={L('ledgerEmptyHint')}
        />
      );
    }
    return (
      <div
        className="ledger"
        role="log"
        aria-label={ledgerLabel}
        aria-live="polite"
        tabIndex={0}
        onKeyDown={onLedgerKey}
      >
        {ledger.map((d, i) => {
          const isSel = i === selIdx;
          const m = statusMeta(d.status);
          return (
            <div
              key={d.id}
              ref={isSel ? selRowRef : undefined}
              id={`dec-row-${d.id}`}
              className={`led surface soft rise state-${m.face}${isSel ? ' on' : ''}${stampIds.has(d.id) ? ' dec-stamp' : ''}`}
              /* `aria-readonly` was here and is not an allowed attribute on a role-less `div`
                 (axe `aria-allowed-attr`, critical — found by the real-browser sweep). The
                 intent was real: this ledger is append-only. But an invalid ARIA attribute
                 communicates nothing to a screen reader while telling a reader of the source
                 that something was handled, which is worse than the silence it replaced. What
                 actually says the ledger is not editable is that it contains no controls, and
                 the container's `role="log"` says what it is. */
              style={{ ['--i' as string]: i + 2, ['--st-rgb' as string]: m.tone } as CSSProperties}
              onClick={() => { setSelectedIndex(i); }}
              onDoubleClick={() => openEvidence(d)}
            >
              <span className="l-ix">
                <span className="l-dot" aria-hidden="true" />
                <b className="mono">{String(i + 1).padStart(2, '0')}</b>
              </span>
              <span className="l-main">
                <b className="l-ti">{d.title}</b>
                <span className="l-vs">
                  <em>{d.owner || '—'}</em><i>·</i><em>{fmtDate(d.createdAt)}</em>
                </span>
              </span>
              <StatusPill status={d.status} />
            </div>
          );
        })}
      </div>
    );
  };

  // What the ENGINE said about its own store, quoted and attributed.
  //
  // The three-valued read used to arrive stripped of its reason, so an empty surface
  // rendered as a blank panel: the owner could not tell "there is nothing to show" from
  // "there is nothing to show BECAUSE the orchestration runtime holds no tasks". The
  // sentence is the engine's claim, so it is shown as a quotation under an explicit
  // attribution and is never paraphrased into the page's own voice. It sits BESIDE the
  // honest ok/empty/blocked state, never in place of it — `engineEmptyReason` answers
  // only for an `ok` read that carried nothing, so an explanation of emptiness can
  // reach neither a list of records nor a refusal.
  const renderEngineAccount = (r: GovernanceRead) => {
    const said = engineEmptyReason(r);
    const source = engineSourceKind(r);
    // Only where it answers the question being asked. The engine can legitimately hold
    // a chain for a task its runtime no longer lists, so "it has never heard of this id"
    // is a fact about an EMPTY surface — printed over records it would read as a
    // contradiction rather than the explanation it is.
    const unknownTask = engineDoesNotKnowTask(r) && recordCount(r) === 0;
    if (!said && !source && !unknownTask) return null;
    return (
      <div className="dec-engine-said">
        {said ? (
          <p className="micro">
            <b className="dec-engine-attr">{L('engineSaysLabel')}</b>{' '}
            <q>{said}</q>
          </p>
        ) : null}
        {unknownTask ? <p className="micro">{L('engineUnknownTask')}</p> : null}
        {source ? (
          <p className="micro">
            {L('engineSourceLabel')}<span className="mono">{source}</span>
          </p>
        ) : null}
      </div>
    );
  };

  const renderEvidence = () => {
    if (!evidenceOpen) {
      return (
        <div className="dec-hint">
          {L('evidenceInspectHint')}
        </div>
      );
    }
    if (evidenceRead === null) {
      return (
        <div role="status">
          <span className="ev-tag micro">{L('evidenceChainLabel')}</span>
          <p>{L('readingChainShort')}</p>
        </div>
      );
    }
    if (evidenceRead.state === 'ok') {
      const n = recordCount(evidenceRead);
      // Zero records is the honest ABSENCE of evidence. Reporting it with the
      // "mirrored read-only" copy (and a count of 0) let an empty chain read as a
      // satisfied one — the defect this branch exists to prevent.
      if (n === 0) {
        return (
          <div role="note">
            <span className="ev-tag micro">{L('evidenceNone')}</span>
            <p>{L('evidenceNoneBody')}</p>
            {/* ...and the engine's own reason for the emptiness, in its words. */}
            {renderEngineAccount(evidenceRead)}
          </div>
        );
      }
      // Records exist — but they are schema-checked only, from a source the desktop
      // does not authenticate. Say so beside them, every time.
      return (
        <div role="note">
          <span className="ev-tag micro">
            {L('engineEvidenceCount')}{n}
          </span>
          {!evidenceRead.authenticated && (
            <span className="pill warn" style={{ marginLeft: 8 }}>{L('unauthenticatedTag')}</span>
          )}
          <p>
            {L('mirroredReadOnly')}
          </p>
          {!evidenceRead.authenticated && (
            <p className="micro" style={{ marginTop: 6 }}>{L('unauthenticatedBody')}</p>
          )}
          {/* Which store the engine says these came from. Provenance, not proof — the
              desktop opened nothing and verified nothing, so the line stays attributed
              and the unauthenticated notice above still applies to every record. */}
          {renderEngineAccount(evidenceRead)}
        </div>
      );
    }
    // Honest fail-closed states: unreachable OR blocked/sealed. NEVER fabricated evidence.
    return (
      <div role="note">
        <span className="ev-tag micro">
          {evidenceRead.state === 'unreachable'
            ? L('evidenceUnreachable')
            : L('evidenceSealed')}
        </span>
        <p>
          {L('sealedBody')}
          {evidenceRead.reason ? (
            <span className="micro" style={{ display: 'block', marginTop: 6 }}>
              {L('reasonPrefix')}{evidenceRead.reason}
            </span>
          ) : null}
        </p>
      </div>
    );
  };

  // Evidence-chain lifecycle — a `.chain` where EVERY node maps to a real fact,
  // never a decorative "all verified" row. `done` (mint) and `now` (cyan pulse)
  // are earned only by the real ledger status / evidence read; the traveling
  // `wire.live` pulse runs ONLY while a step is genuinely in-progress. Fail-closed:
  // an unopened, sealed, or unreachable evidence chain leaves the evidence node
  // NEUTRAL — no green, no pulse.
  const renderChain = (d: Decision) => {
    const face = statusMeta(d.status).face;
    const blocked = face === 'blocked';
    const inProgress = face === 'waiting';
    // The evidence read belonging to THIS decision (null while closed/loading).
    const ev = evidenceOpenId === d.id ? evidenceRead : null;
    // Two things used to be conflated into a green node here:
    //   * `state === 'ok'` with an EMPTY record set — zero evidence painted as
    //     satisfied evidence;
    //   * records whose origin is unauthenticated (schema-shape only, from whatever
    //     process the governed-sidecar setting names).
    // So the node goes mint ONLY if records actually arrived AND the backend states
    // they were authenticated — which it does not today. Otherwise the node stays
    // neutral and its LABEL says which honest case it is.
    const mirroredCount = ev ? recordCount(ev) : 0;
    const evidenceProven = !!ev && ev.state === 'ok' && mirroredCount > 0 && ev.authenticated === true;
    const evidenceLabel = !ev || ev.state !== 'ok'
      ? L('nodeEvidence')
      : mirroredCount === 0
        ? L('nodeEvidenceNone')
        : evidenceProven
          ? L('nodeEvidence')
          : L('nodeEvidenceUnauthenticated');
    const nodes: { label: string; cls: '' | 'done' | 'now' }[] = [
      // The decision is recorded in the append-only ledger — a plain, always-true fact.
      { label: L('nodeRecorded'), cls: 'done' },
      // Real ledger status: still deliberating (now) · blocked (neutral) · settled (done).
      { label: L('nodeDeliberation'), cls: blocked ? '' : inProgress ? 'now' : 'done' },
      // Earns `done` ONLY for records that exist AND are authenticated.
      { label: evidenceLabel, cls: evidenceProven ? 'done' : '' },
    ];
    const live = nodes.some((n) => n.cls === 'now');
    return (
      <div className="dec-chain-strip">
        <span className="micro dec-chain-lbl">{L('evidenceChainLabel')}</span>
        <div className="chain" aria-label={L('chainAria')}>
          {nodes.map((n, i) => (
            <b key={i} className={n.cls || undefined}>{n.label}</b>
          ))}
        </div>
        {/* Decorative traveling pulse — present only while a step is truly `now`. */}
        <div className={`wire${live ? ' live' : ''}`} aria-hidden="true" />
      </div>
    );
  };

  const renderChamber = () => {
    if (loading) {
      return <section className="chamber surface soft lg hud"><Skeleton rows={5} /></section>;
    }
    if (s.error) {
      return (
        <section className="chamber surface soft lg hud">
          <span className="bracket tl" aria-hidden="true" /><span className="bracket tr" aria-hidden="true" />
          <span className="bracket bl" aria-hidden="true" /><span className="bracket br" aria-hidden="true" />
          <EmptyState
            glyph="⚖"
            title={L('chamberUnavailable')}
            hint={L('chamberUnavailableHint')}
          />
        </section>
      );
    }
    if (!selected) {
      return (
        <section className="chamber surface soft lg hud">
          <span className="bracket tl" aria-hidden="true" /><span className="bracket tr" aria-hidden="true" />
          <span className="bracket bl" aria-hidden="true" /><span className="bracket br" aria-hidden="true" />
          <EmptyState
            glyph="⚖"
            title={L('selectDecision')}
            hint={L('selectDecisionHint')}
          />
        </section>
      );
    }

    const m = statusMeta(selected.status);
    return (
      <section className={`chamber surface soft lg hud st-${m.face}`} id="chamber">
        <span className="bracket tl" aria-hidden="true" /><span className="bracket tr" aria-hidden="true" />
        <span className="bracket bl" aria-hidden="true" /><span className="bracket br" aria-hidden="true" />
        <span className="ticks" aria-hidden="true">
          <i /><i /><i /><i /><i /><i /><i /><i /><i />
        </span>

        <div className="ch-head">
          <div className="ch-title">
            <span className="eyebrow">{L('deliberationEyebrow')}</span>
            <h2>{selected.title}</h2>
            {/* The rationale is the real "why" the engine recorded — shown verbatim,
                in place of the mockup's fabricated weighted-criteria instrument. */}
            <p className="ch-q">{selected.rationale || '—'}</p>
          </div>
          {/* Verdict readout: the power mark leans by REAL status (never forced green/
              live) and the pill mirrors the recorded status. No fabricated confidence %. */}
          <div className={`ch-verdict vcore face-${m.face}`}>
            <Mark state={m.mark} size={46} />
            <StatusPill status={selected.status} />
          </div>
        </div>

        <div className="dec-meta">
          <Field label={t('field.owner')}>{selected.owner || '—'}</Field>
          <Field label={L('recordedField')}>{fmtDate(selected.createdAt)}</Field>
          <Field label={L('updatedField')}>{fmtDate(selected.updatedAt)}</Field>
        </div>

        {/* Evidence-chain lifecycle — real facts only; `done`/`now` are earned,
            never a decorative "everything verified" animation. */}
        {renderChain(selected)}

        {/* chEvidence — evidence readout. Read-only. Opening it reveals the honest
            `ok`/`blocked`/`unreachable` engine state; no evidence is fabricated. */}
        <section className="ch-foot" aria-label={L('evidenceChainSection')}>
          <div className="evidence" id="chEvidence" aria-live="polite">
            {renderEvidence()}
          </div>
          <div className="ch-actions">
            <span className="ch-by micro">{selected.owner || '—'}</span>
            <Button small onClick={() => openEvidence(selected)}>
              {L('openEvidence')}
            </Button>
            {/* chReweigh — disabled by design: reweighing is adjudicated by the engine
                (mirror, never decide); the desktop holds no decision authority. */}
            <Button
              small
              disabled
              title={L('reweighTitle')}
            >
              {L('reweigh')}
            </Button>
          </div>
        </section>
      </section>
    );
  };

  const renderStats = () => (
    <section className="surface soft dstats-wrap rise" style={{ ['--i' as string]: 2 } as CSSProperties}>
      <div className="dstats">
        {stats.map((x, i) => (
          <div
            key={i}
            className={`dstat rise${x.tone ? ` ds-${x.tone}` : ''}`}
            style={{ ['--i' as string]: i + 2 } as CSSProperties}
          >
            <b className="count num mono">{x.v}</b>
            <span className="micro">{x.label}</span>
          </div>
        ))}
      </div>
    </section>
  );

  return (
    <div className="v-decisions">
      <style>{styles}</style>

      <header className="pageHead">
        <div>
          <span className="eyebrow">{L('pageEyebrow')}</span>
          <h1>{t('nav.decisions')}</h1>
          <p className="sub">{t('decisions.subtitle')}</p>
        </div>
        <div className="right">
          {/* Honest posture: the desktop only MIRRORS the engine ledger, read-only. */}
          <span className="pill info">{L('readOnlyMirror')}</span>
        </div>
      </header>

      {/* Polite live region — announces ledger selection and the sealed-evidence verdict. */}
      <div className="dec-sr-live" role="status" aria-live="polite">{announce}</div>

      {renderChamber()}

      <div className="sec-head" style={{ marginTop: 26 }}>
        <h2>{L('decisionLedger')}</h2>
        <span className="note">
          {L('selectRowHint')}
          {' · '}<b className="mono">{ledger.length}</b>{' '}
          {L('activeDecisions')}
        </span>
      </div>

      {renderLedger()}

      {!loading && !s.error && ledger.length > 0 ? renderStats() : null}

      {/* The governed bridge. The ledger above is the desktop's LOCAL decision table; the panel below
          is the only place the engine's own ledger mirror, the independent-verifier verdicts, and the
          renderer→broker governed turn are reachable at all. `taskId` scopes the verdict mirror to the
          decision currently selected here, so the two halves of the page are about the same thing. */}
      <BridgePanel taskId={selected?.id} />
    </div>
  );
}
