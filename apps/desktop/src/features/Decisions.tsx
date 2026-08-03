import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react';
import { useApp } from '../app/store';
import {
  StatusPill, Field, Skeleton, ErrorState, EmptyState, Button,
} from '../components/ui';
import { Mark } from '../components/Ambient';
import { useAsync } from '../hooks/useAsync';
import { desktop } from '../services/desktop';
import type { GovernanceRead } from '../services/governance';
import type { Decision } from '../domain/entities';
import { STR } from './Decisions.strings';

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
@keyframes dec-reveal { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@keyframes dec-stamp { 0% { opacity: 0; transform: scale(1.12); } 60% { opacity: 1; transform: scale(0.98); } 100% { transform: none; } }
@media (prefers-reduced-motion: reduce) {
  .v-decisions .led, .v-decisions .led.dec-stamp { animation: none; }
  /* Keep the .now / .live colours (they carry meaning) but drop the motion. */
  .v-decisions .chain b.now { animation: none; }
  .v-decisions .dec-chain-strip .wire.live::after { animation: none; }
}
`;

// Honest status → presentation map. NEVER returns a "live"/green/verified tone: the
// desktop cannot verify a decision, so the power mark is `idle` for anything that is
// not an explicit block/refusal (which reads `alert`). Colour on the ledger dot is
// carried by `--st-rgb`; a settled decision simply reads neutral, never approved-green.
function statusMeta(status: string): { face: string; mark: string; tone: string } {
  const v = (status || '').toLowerCase();
  if (/block|reject|den|fail|abort|error/.test(v)) return { face: 'blocked', mark: 'alert', tone: 'var(--danger-rgb)' };
  if (/wait|pend|propos|review|hold|open|draft/.test(v)) return { face: 'waiting', mark: 'idle', tone: 'var(--warning-rgb)' };
  return { face: 'idle', mark: 'idle', tone: 'var(--muted-rgb)' };
}

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
    const isBlocked = (d: Decision) => /block|reject|den|fail|abort|error/.test((d.status || '').toLowerCase());
    const isPending = (d: Decision) => /wait|pend|propos|review|hold|open|draft/.test((d.status || '').toLowerCase());
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
      setAnnounce(r.state === 'ok'
        ? L('chainMirrored')
        : L('chainSealedAnnounce'));
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
              aria-readonly={true}
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
      const n = evidenceRead.records?.length ?? 0;
      return (
        <div role="note">
          <span className="ev-tag micro">
            {L('engineEvidenceCount')}{n}
          </span>
          <p>
            {L('mirroredReadOnly')}
          </p>
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
    // Only a real, mirrored engine chain (state === 'ok') earns the evidence node.
    const mirrored = evidenceOpenId === d.id && evidenceRead?.state === 'ok';
    const nodes: { label: string; cls: '' | 'done' | 'now' }[] = [
      // The decision is recorded in the append-only ledger — a plain, always-true fact.
      { label: L('nodeRecorded'), cls: 'done' },
      // Real ledger status: still deliberating (now) · blocked (neutral) · settled (done).
      { label: L('nodeDeliberation'), cls: blocked ? '' : inProgress ? 'now' : 'done' },
      // Earns `done` ONLY when the engine evidence chain actually mirrored read-only.
      { label: L('nodeEvidence'), cls: mirrored ? 'done' : '' },
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
    </div>
  );
}
