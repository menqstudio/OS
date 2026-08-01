import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, StatusPill, Field, Skeleton, ErrorState, EmptyState,
} from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { desktop } from '../services/desktop';
import type { Decision } from '../domain/entities';

// Scoped styles for the decision chamber. All colour/space/motion resolves
// through the shared MenQ tokens; nothing is hard-coded. Motion is disabled
// under prefers-reduced-motion, per §D.
const styles = `
.dec-ledger { display: flex; flex-direction: column; gap: 2px; max-height: 62vh; overflow-y: auto;
  padding-right: 4px; outline: none; border-radius: var(--menq-radius-md); }
.dec-ledger:focus-visible { box-shadow: 0 0 0 2px var(--menq-color-focus); }
.dec-row { position: relative; display: flex; flex-direction: column; gap: 4px; width: 100%;
  text-align: left; cursor: pointer; padding: 10px 12px 10px 16px;
  background: var(--brops-surface); color: var(--brops-text);
  border: 1px solid var(--brops-border); border-radius: var(--menq-radius-md);
  animation: dec-reveal var(--menq-motion-med) ease both;
  transition: background var(--menq-motion-fast), border-color var(--menq-motion-fast); }
.dec-row::before { content: ""; position: absolute; left: 0; top: 8px; bottom: 8px; width: 3px;
  border-radius: var(--menq-radius-pill); background: var(--brops-border); }
.dec-row:hover { background: var(--menq-color-hover); }
.dec-row--sel { background: var(--menq-color-selected); border-color: var(--brops-accent); }
.dec-row--sel::before { background: var(--brops-accent); }
.dec-row--stamp { animation: dec-stamp var(--menq-motion-med) cubic-bezier(0.2, 1.2, 0.3, 1) both; }
.dec-row-top { display: flex; align-items: center; justify-content: space-between; gap: var(--menq-space-3); }
.dec-row-title { font-weight: 600; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dec-row-meta { display: flex; gap: var(--menq-space-3); font-size: 11px; color: var(--brops-muted);
  font-variant-numeric: tabular-nums; }
.dec-seal { font-size: 11px; color: var(--brops-muted); letter-spacing: 0.03em; }

.dec-chamber { display: flex; flex-direction: column; gap: var(--menq-space-4); }
.dec-chamber-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--menq-space-3); }
.dec-chamber-title { font-size: 16px; font-weight: 700; letter-spacing: -0.01em; }
.dec-rationale { line-height: 1.5; }
.dec-section { border-top: 1px solid var(--brops-border); padding-top: var(--menq-space-4);
  display: flex; flex-direction: column; gap: var(--menq-space-3); }
.dec-sec-head { display: flex; align-items: center; justify-content: space-between; gap: var(--menq-space-3); }

.dec-blocked { display: flex; flex-direction: column; align-items: center; gap: 6px; text-align: center;
  padding: var(--menq-space-5) var(--menq-space-4);
  border: 1px dashed color-mix(in srgb, var(--menq-color-warning) 45%, transparent);
  border-radius: var(--menq-radius-md);
  background: color-mix(in srgb, var(--menq-color-warning) 8%, transparent); }
.dec-blocked-glyph { font-size: 26px; color: var(--menq-color-warning); }
.dec-blocked-title { font-weight: 700; color: var(--brops-text); }
.dec-blocked-body { max-width: 460px; color: var(--brops-muted); font-size: 13px; }

.dec-reweigh-hint { flex: 1; min-width: 0; font-size: 13px; }
.dec-sr-live { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }

@keyframes dec-reveal { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@keyframes dec-stamp {
  0% { opacity: 0; transform: scale(1.14) rotate(-1.5deg); }
  60% { opacity: 1; transform: scale(0.97); }
  100% { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) {
  .dec-row, .dec-row--stamp { animation: none; }
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
  const [announce, setAnnounce] = useState('');

  // Bilingual inline strings (HY + EN) the way the thin pages do; shared i18n
  // keys are used where they already exist.
  const L = (en: string, hy: string) => (lang === 'hy' ? hy : en);

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
    // Verdict/evidence outcome announced via the polite live region.
    setAnnounce(L(
      `Evidence for “${d.title}” is sealed — the engine chain is not exposed to the desktop.`,
      `«${d.title}» որոշման ապացույցները կնքված են — շարժիչի շղթան հասանելի չէ desktop-ին։`,
    ));
  };

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
      if (d) setAnnounce(L(`Selected: ${d.title}`, `Ընտրված է՝ ${d.title}`));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      openEvidence(ledger[selIdx] ?? null);
    }
  };

  const ledgerLabel = L('Decision ledger (append-only, read-only)', 'Որոշումների մատյան (միայն ավելացվող, կարդալու)');

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
          title={L('No decisions yet', 'Դեռ որոշումներ չկան')}
          hint={L('The engine ledger is empty. Accepted decisions will appear here.',
            'Շարժիչի մատյանը դատարկ է։ Ընդունված որոշումները կհայտնվեն այստեղ։')}
        />
      );
    }
    return (
      <div
        className="dec-ledger"
        role="log"
        aria-label={ledgerLabel}
        aria-live="polite"
        tabIndex={0}
        onKeyDown={onLedgerKey}
      >
        {ledger.map((d, i) => {
          const isSel = i === selIdx;
          return (
            <div
              key={d.id}
              ref={isSel ? selRowRef : undefined}
              id={`dec-row-${d.id}`}
              className={`dec-row${isSel ? ' dec-row--sel' : ''}${stampIds.has(d.id) ? ' dec-row--stamp' : ''}`}
              aria-readonly={true}
              style={{ animationDelay: `${Math.min(i, 12) * 40}ms` }}
              onClick={() => { setSelectedIndex(i); }}
              onDoubleClick={() => openEvidence(d)}
            >
              <div className="dec-row-top">
                <span className="dec-row-title">{d.title}</span>
                <StatusPill status={d.status} />
              </div>
              <div className="dec-row-meta">
                <span>{d.owner}</span>
                <span>{fmtDate(d.createdAt)}</span>
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  const renderChamber = () => {
    if (loading) return <Panel><Skeleton rows={5} /></Panel>;
    if (s.error) {
      return (
        <Panel>
          <EmptyState
            glyph="⚖"
            title={L('Chamber unavailable', 'Պալատն անհասանելի է')}
            hint={L('The decision ledger could not be read from the engine.',
              'Որոշումների մատյանը չհաջողվեց կարդալ շարժիչից։')}
          />
        </Panel>
      );
    }
    if (!selected) {
      return (
        <Panel>
          <EmptyState
            glyph="⚖"
            title={L('Select a decision', 'Ընտրիր որոշում')}
            hint={L('Arrow-navigate the ledger; press Enter to open its evidence.',
              'Սլաքներով շրջիր մատյանում, Enter-ով բացիր ապացույցները։')}
          />
        </Panel>
      );
    }
    return (
      <Panel>
        <div className="dec-chamber">
          <div className="dec-chamber-head">
            <div className="dec-chamber-title">{selected.title}</div>
            <StatusPill status={selected.status} />
          </div>

          <Field label={t('field.owner')}>{selected.owner}</Field>
          <div className="field">
            <span className="field-label">{L('Rationale', 'Հիմնավորում')}</span>
            <span className="dec-rationale">{selected.rationale || '—'}</span>
          </div>
          <div className="row" style={{ gap: 'var(--menq-space-5)', flexWrap: 'wrap' }}>
            <Field label={L('Recorded', 'Գրանցված')}>{fmtDate(selected.createdAt)}</Field>
            <Field label={L('Updated', 'Թարմացված')}>{fmtDate(selected.updatedAt)}</Field>
          </div>

          {/* chEvidence — evidence viewer. Read-only. Opening it reveals the
              honest `blocked` (evidence sealed) state: the engine evidence chain
              has no desktop command, so no evidence is fabricated. */}
          <section className="dec-section" aria-label={L('Evidence chain', 'Ապացույցների շղթա')}>
            <div className="dec-sec-head">
              <span className="field-label">{L('Evidence chain', 'Ապացույցների շղթա')}</span>
              <Button small onClick={() => openEvidence(selected)}>
                {L('Open evidence', 'Բացել ապացույցները')}
              </Button>
            </div>
            {evidenceOpen ? (
              <div className="dec-blocked" role="note">
                <div className="dec-blocked-glyph" aria-hidden="true">⛓</div>
                <div className="dec-blocked-title">{L('Evidence sealed', 'Ապացույցները կնքված են')}</div>
                <div className="dec-blocked-body">
                  {L(
                    'The engine evidence chain is read-only and is not exposed to the desktop. The ledger mirrors the decision; it never holds the sealed evidence.',
                    'Շարժիչի ապացույցների շղթան կարդալու է և հասանելի չէ desktop-ին։ Մատյանն արտացոլում է որոշումը, բայց երբեք չի պահում կնքված ապացույցը։',
                  )}
                </div>
              </div>
            ) : (
              <div className="muted" style={{ fontSize: 13 }}>
                {L('Press Enter or Open to inspect this decision’s evidence.',
                  'Enter-ով կամ «Բացել»-ով դիտիր այս որոշման ապացույցը։')}
              </div>
            )}
          </section>

          {/* chReweigh — reweigh control. Disabled by design: reweighing is
              adjudicated by the engine (mirror, never decide); the desktop holds
              no decision authority and there is no reweigh command to call. */}
          <section className="dec-section">
            <span className="field-label">{L('Reweigh', 'Վերակշռում')}</span>
            <div className="row between">
              <span className="muted dec-reweigh-hint">
                {L('Reweighing is adjudicated by the engine. The desktop mirrors, never decides.',
                  'Վերակշռումը որոշում է շարժիչը։ Desktop-ն արտացոլում է, երբեք չի որոշում։')}
              </span>
              <Button
                small
                disabled
                title={L('Reweigh is adjudicated by the engine — the desktop cannot alter the ledger.',
                  'Վերակշռումը որոշում է շարժիչը — desktop-ը չի կարող փոխել մատյանը։')}
              >
                {L('Reweigh decision', 'Վերակշռել որոշումը')}
              </Button>
            </div>
          </section>
        </div>
      </Panel>
    );
  };

  return (
    <>
      <style>{styles}</style>
      <PageHeader title={t('nav.decisions')} subtitle={t('decisions.subtitle')} />

      {/* Polite live region — announces ledger selection and the sealed-evidence verdict. */}
      <div className="dec-sr-live" role="status" aria-live="polite">{announce}</div>

      <div className="chat-layout">
        {/* chamber (left rail: the append-only ledger) */}
        <Panel title={ledgerLabel}>
          {renderLedger()}
        </Panel>
        {/* chamber (right: selected decision + evidence + reweigh) */}
        <div>{renderChamber()}</div>
      </div>
    </>
  );
}
