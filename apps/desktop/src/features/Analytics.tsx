import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { useApp } from '../app/store';
import { Button, Skeleton, ErrorState, EmptyState } from '../components/ui';
import { BarChart } from '../components/charts/Chart';
import { Mark } from '../components/Ambient';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import type { Metric } from '../domain/entities';
import type { Lang } from '../domain/enums';
import { metricLabel } from '../domain/statusLabels';
import { STR } from './Analytics.strings';

// ---------------------------------------------------------------------------
// analytics ◈ Վերլուծություն — §D page, re-dressed into the AI-OS "Signal Deck".
//
// Real data source: the `get_analytics` Tauri command (desktop.getAnalytics()),
// which returns all-time aggregate `Metric[]` (key/label/value). That single
// aggregate backs the hero deck's distribution plot (the shared, accessible
// `BarChart`, wrapped in the mockup's `.an-deck .surface .lg .hud` framing) and
// the deck foot's live total.
//
// The engine does NOT (yet) expose a geographic/district aggregate, an autonomy
// split, or a per-channel split. Per the spec's honesty rule we never fabricate
// any of them: the `.an-districts` panel and both `.an-side` panels (`.an-auto`,
// `.an-chan`) render their honest `empty` state, naming the missing engine
// aggregate instead of inventing districts, an autonomy ring, or a channel mix.
// ---------------------------------------------------------------------------

// Trilingual translator: resolves a STR key to the active language (en fallback).
type Tr = (k: keyof typeof STR) => string;

// --- staggered-entrance index → the shared `.reveal/.rise` CSS reads `--i` -----
// (the entrance itself is stilled under prefers-reduced-motion by aios.css).
const iv = (i: number): CSSProperties => ({ ['--i']: i } as CSSProperties);

// --- decorative HUD chrome for the deck frame (corner brackets + tick rail) ----
// Purely ornamental, so the whole thing is aria-hidden.
function DeckChrome() {
  return (
    <>
      <span className="bracket tl" aria-hidden="true" />
      <span className="bracket tr" aria-hidden="true" />
      <span className="bracket bl" aria-hidden="true" />
      <span className="bracket br" aria-hidden="true" />
      <span className="ticks" aria-hidden="true">
        <i /><i /><i /><i /><i /><i /><i /><i /><i />
      </span>
    </>
  );
}

// --- prefers-reduced-motion, live ---------------------------------------------
function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState<boolean>(
    () => typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  );
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener?.('change', onChange);
    return () => mq.removeEventListener?.('change', onChange);
  }, []);
  return reduced;
}

// --- count-up on a REAL integer (the mockup's `init()` count animation, ported).
// Honesty: only ever counts up to the true value; reduced motion jumps to it.
function useCountUp(value: number, reduced: boolean): number {
  const [shown, setShown] = useState<number>(reduced ? value : 0);
  useEffect(() => {
    if (reduced) { setShown(value); return; }
    let raf = 0;
    let start = 0;
    const dur = 900;
    const step = (ts: number) => {
      if (!start) start = ts;
      const p = Math.min(1, (ts - start) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      setShown(Math.round(value * eased));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value, reduced]);
  return shown;
}

// --- the distribution plot: the shared accessible BarChart over real metrics --
// Delegates to the library `BarChart` (horizontal bars + focusable legend + share%
// + accessible one-line summary + <details> table fallback). This page only maps
// the real `Metric[]` to the primitive's data shape and supplies bilingual labels.
function AnPlot(
  { metrics, hidden, onToggle, tr, lang }:
  { metrics: Metric[]; hidden: ReadonlySet<string>; onToggle: (key: string) => void; tr: Tr; lang: Lang },
) {
  // Localize each metric's label from its key (falls back to backend label / humanized key).
  const labeled = metrics.map((m) => ({ ...m, label: metricLabel(m.key, lang, m.label) }));
  const visible = labeled.filter((m) => !hidden.has(m.key));
  const total = visible.reduce((sum, m) => sum + m.value, 0);
  const top = visible.reduce<Metric | null>((best, m) => (best && best.value >= m.value ? best : m), null);

  const summary = visible.length === 0
    ? tr('noNodesSelected')
    : `${visible.length} ${tr('nodesTotal')} ${total}${tr('sentenceDot')}`
      + (top ? ` ${tr('highestPrefix')}${top.label} (${top.value})${tr('sentenceDot')}` : '');

  return (
    <BarChart
      data={labeled.map((m) => ({ key: m.key, label: m.label, value: m.value }))}
      caption={tr('distByNode')}
      summary={summary}
      hidden={hidden}
      onToggle={onToggle}
      legendLabel={tr('toggleNodes')}
      showLabel={tr('showNode')}
      hideLabel={tr('hideNode')}
      hiddenWord={tr('hiddenWord')}
      allHiddenNote={tr('allNodesHidden')}
      totalLabel={tr('totalAcrossNodes')}
      nodeHeader={tr('nodeHeader')}
      valueHeader={tr('value')}
      shareHeader={tr('share')}
      tableToggle={tr('showDataTable')}
    />
  );
}

// --- the rank scrubber (anScrub) ----------------------------------------------
// §D: "scrubber (`anScrub`) … Keyboard: scrubber is a slider (role=slider, arrows)".
//
// WHAT IT SCRUBS, and why it is not a timeline. `get_analytics` returns one ALL-TIME
// aggregate with no time dimension anywhere in it. A time scrubber would therefore be
// drawing an axis the engine does not expose — the exact fabrication this page refuses
// three times over in `AnHonest`, where the districts, autonomy and channel panels
// render an honest empty instead of inventing a split. So the scrub is over the one
// ordering the data really has: RANK. It moves the cut-off — how far down the ranked
// distribution is plotted — and every position it can take is a true statement about
// real values.
//
// A native <input type=range> would give keyboard support for free and is the usual
// right answer, but §D names `role=slider` and this deck's chrome is a custom rail;
// so the ARIA slider pattern is implemented in full rather than approximated: the
// value, its bounds and a human-readable `aria-valuetext` are all published, and the
// whole keyboard contract the pattern requires is here — not only the two arrows §D
// mentions. Home/End and PageUp/PageDown are part of that contract, and a slider that
// ignores them is one a keyboard user has to hold an arrow key down on.
function AnScrub(
  { value, max, onChange, tr }:
  { value: number; max: number; onChange: (next: number) => void; tr: Tr },
) {
  const clamp = (n: number) => Math.max(1, Math.min(max, n));
  const page = Math.max(1, Math.round(max / 5));
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const step: Record<string, number> = {
      ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1,
      PageUp: page, PageDown: -page,
    };
    if (e.key in step) {
      e.preventDefault();
      onChange(clamp(value + step[e.key]));
      return;
    }
    if (e.key === 'Home') { e.preventDefault(); onChange(1); }
    else if (e.key === 'End') { e.preventDefault(); onChange(max); }
  };
  const valueText = value >= max
    ? tr('scrubAll')
    : `${tr('scrubTop')} ${value} ${tr('scrubOf')} ${max}`;
  return (
    <div className="an-scrub">
      <span className="micro an-scrub-label" id="an-scrub-label">{tr('scrubLabel')}</span>
      <div
        className="an-scrub-rail"
        role="slider"
        tabIndex={0}
        aria-labelledby="an-scrub-label"
        aria-valuemin={1}
        aria-valuemax={max}
        aria-valuenow={value}
        aria-valuetext={valueText}
        aria-describedby="an-scrub-hint"
        onKeyDown={onKeyDown}
      >
        <span className="an-scrub-fill" style={{ width: `${(value / max) * 100}%` }} aria-hidden="true" />
        <span className="an-scrub-knob" style={{ left: `${(value / max) * 100}%` }} aria-hidden="true" />
      </div>
      {/* The value is TEXT as well as an aria attribute: a sighted mouse user gets no
          screen reader, and a rail with a knob and no number is a guess. */}
      <b className="mono an-scrub-value">{valueText}</b>
      <span className="micro muted an-scrub-hint" id="an-scrub-hint">{tr('scrubHint')}</span>
    </div>
  );
}

// --- honest empty panel: the engine exposes no such split aggregate yet -------
// Names what's missing (with a keyboard-reachable <details> table) instead of
// fabricating a breakdown. Reused for the districts, autonomy and channel panels.
function AnHonest(
  { panelClass, title, note, glyph, hint, tableHint, segLabel, valLabel, i, tr }:
  {
    panelClass: string; title: string; note?: string; glyph: string; hint: string;
    tableHint: string; segLabel: string; valLabel: string; i: number; tr: Tr;
  },
) {
  return (
    <section className={`surface soft ${panelClass} rise`} style={iv(i)}>
      <div className="sec-head">
        <h2>{title}</h2>
        {note ? <span className="note">{note}</span> : null}
      </div>
      <EmptyState glyph={glyph} title={tr('noBreakdown')} hint={hint} />
      <details className="an-table">
        <summary>{tr('showDataTable')}</summary>
        <table>
          <caption className="an-sr">{title}</caption>
          <thead>
            <tr>
              <th scope="col">{segLabel}</th>
              <th scope="col">{valLabel}</th>
            </tr>
          </thead>
          <tbody>
            <tr><td colSpan={2} className="muted">{tableHint}</td></tr>
          </tbody>
        </table>
      </details>
    </section>
  );
}

export function Analytics() {
  const { t, lang } = useApp();
  const Lz: Tr = (k) => STR[k][lang] ?? STR[k].en;
  const s = useAsync(() => desktop.getAnalytics(), []);

  const [hidden, setHidden] = useState<ReadonlySet<string>>(() => new Set());

  const toggle = (key: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const all = s.data ?? [];
  // Ranked once, here, so the scrubber's "top N" means the same thing everywhere on the
  // page and the plot is not re-sorted per render by a component that does not own the cut.
  const ranked = useMemo(() => [...all].sort((a, b) => b.value - a.value), [all]);
  const [cut, setCut] = useState<number | null>(null);
  // `null` = untouched, which shows everything. Storing a number instead would freeze the
  // cut at whatever the FIRST read happened to return, so a later read with more nodes
  // would silently keep hiding the new ones.
  const shownCount = cut === null ? ranked.length : Math.min(cut, ranked.length);
  const metrics = ranked.slice(0, shownCount);
  // The deck total follows the CUT, not the whole set: a number that ignores the control
  // right above it is the page contradicting itself.
  const total = metrics.reduce((sum, m) => sum + m.value, 0);
  const reduced = useReducedMotion();
  const totalShown = useCountUp(total, reduced);
  const denied = s.error ? /denied|not permitted|permission|blocked|forbidden/i.test(s.error) : false;

  // Header posture from the REAL read state. `live`/green is unreachable: the page has
  // one aggregate read and no stream, so the best it can ever claim is "snapshot".
  const readPill: { tone: string; mark: string; key: 'readReading' | 'readBlocked' | 'readUnavailable' | 'readSnapshot' } =
    s.loading && s.data === null
      ? { tone: 'off', mark: 'thinking', key: 'readReading' }
      : denied
        ? { tone: 'warn', mark: 'alert', key: 'readBlocked' }
        : s.error
          ? { tone: 'warn', mark: 'alert', key: 'readUnavailable' }
          : { tone: 'info', mark: 'idle', key: 'readSnapshot' };

  // aria-live announcement: current data state (node count from real metrics).
  const liveMsg = useMemo(() => {
    if (s.loading && s.data === null) return Lz('loadingAnalytics');
    if (s.error) return Lz('analyticsUnavailable');
    if (metrics.length === 0) return Lz('noAnalyticsData');
    return `${metrics.length} ${Lz('nodesDot')}`;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.loading, s.error, s.data, metrics.length, lang]);

  const renderBody = () => {
    // loading
    if (s.loading && s.data === null) {
      return (
        <section className="an-deck surface soft lg hud">
          <DeckChrome />
          <Skeleton rows={6} />
        </section>
      );
    }

    // error (governed blocked vs generic failure)
    if (s.error) {
      if (denied) {
        return (
          <section className="an-deck surface soft lg hud">
            <DeckChrome />
            <div className="an-blocked" role="alert">
              <div className="an-blocked-glyph" aria-hidden="true">⛒</div>
              <div className="empty-title">{t('state.permissionDenied')}</div>
              <p className="muted" style={{ maxWidth: 460, margin: '4px auto 0' }}>
                {Lz('governedBlocked')}
              </p>
              <div style={{ marginTop: 12 }}>
                <Button small onClick={s.reload}>{t('action.retry')}</Button>
              </div>
            </div>
          </section>
        );
      }
      return <ErrorState message={s.error} onRetry={s.reload} retryLabel={t('action.retry')} />;
    }

    // empty (no data at all)
    if (metrics.length === 0) {
      return <EmptyState title={t('state.empty')} hint={t('state.emptyHint')} />;
    }

    // loaded — the Signal Deck + honest lower board
    return (
      <>
        {/* ── HERO · the Signal Deck: real distribution in the mockup framing ── */}
        <section className="an-deck surface soft lg hud reveal" style={iv(1)}>
          <DeckChrome />

          <div className="an-deck-top">
            <span className="eyebrow">{Lz('distByNode')}</span>
            {/* This branch only renders after a successful read, so the pill states what
                that read actually is: a one-shot all-time snapshot, not a live stream. */}
            <span className="pill info">{Lz('readSnapshot')}</span>
          </div>

          <AnPlot metrics={metrics} hidden={hidden} onToggle={toggle} tr={Lz} lang={lang} />

          {/* Only when there is something to cut. A slider with one position is a control
              that cannot be wrong and cannot be useful. */}
          {ranked.length > 1 && (
            <AnScrub value={shownCount} max={ranked.length} onChange={setCut} tr={Lz} />
          )}

          {/* Plain divider — `wire.live` animates a travelling pulse that reads as a
              running feed. There is no feed behind this deck, so the claim is dropped. */}
          <div className="wire" aria-hidden="true" />

          <div className="an-deck-foot">
            <span className="capsule">
              <b>{metrics.length}</b>
              <span>{Lz('nodes')}</span>
            </span>
            {/* When the cut is hiding nodes, say so. A count that silently means "some of
                them" is the same failure as a total that ignores the control above it. */}
            {shownCount < ranked.length && (
              <span className="micro muted">
                {`${Lz('scrubTop')} ${shownCount} ${Lz('scrubOf')} ${ranked.length}`}
              </span>
            )}
            <span className="an-foot-r">
              <span className="micro">{Lz('totalAcrossNodes')}</span>
              <b className="mono">{totalShown}</b>
            </span>
          </div>
        </section>

        {/* ── LOWER BOARD · honest empties for aggregates the engine lacks ───── */}
        <div className="an-lower">
          <AnHonest
            panelClass="an-districts"
            title={Lz('distByDistrict')}
            note={Lz('routedCalls')}
            glyph="◍"
            hint={Lz('districtHint')}
            tableHint={Lz('districtTableHint')}
            segLabel={Lz('district')}
            valLabel={Lz('value')}
            i={3}
            tr={Lz}
          />

          <aside className="an-side">
            <AnHonest
              panelClass="an-auto"
              title={Lz('autonomy')}
              glyph="◑"
              hint={Lz('autonomyHint')}
              tableHint={Lz('autonomyTableHint')}
              segLabel={Lz('segment')}
              valLabel={Lz('value')}
              i={4}
              tr={Lz}
            />
            <AnHonest
              panelClass="an-chan"
              title={Lz('channelSplit')}
              glyph="◈"
              hint={Lz('channelHint')}
              tableHint={Lz('channelTableHint')}
              segLabel={Lz('channel')}
              valLabel={Lz('value')}
              i={5}
              tr={Lz}
            />
          </aside>
        </div>
      </>
    );
  };

  return (
    <div className="v-analytics">
      <style>{ANALYTICS_CSS}</style>

      {/* ── HEADER ─────────────────────────────────────────────────────────── */}
      <header className="pageHead reveal" style={iv(0)}>
        <div>
          <span className="eyebrow">{Lz('intelCentre')}</span>
          <h1>{t('nav.analytics')}</h1>
          <p className="sub">{t('analytics.subtitle')}</p>
        </div>
        <div className="right">
          {/* Bound to the REAL `get_analytics` read. It used to render "STREAM · LIVE"
              green even while the read was in flight, had failed, or was refused at the
              governed wall — a live indicator that is always on is not telemetry. */}
          <span className={`pill ${readPill.tone}`}>{Lz(readPill.key)}</span>
          <Mark state={readPill.mark} size={30} />
        </div>
      </header>

      {/* aria-live status: announces the current data state */}
      <div className="an-sr" role="status" aria-live="polite">{liveMsg}</div>

      {renderBody()}
    </div>
  );
}

// Page-scoped styles — only the bits the shared aios.css / ui.css don't cover:
// the visually-hidden helper, the governed-wall block, and the honest-empty
// <details> data tables. Everything else resolves through the design tokens.
const ANALYTICS_CSS = `
.v-analytics .an-sr { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }

/* ── the rank scrubber ─────────────────────────────────────────────────────── */
.v-analytics .an-scrub { display: grid; grid-template-columns: auto 1fr auto; align-items: center;
  gap: var(--s3); margin-top: var(--s4); }
.v-analytics .an-scrub-label { color: var(--ink-muted); }
.v-analytics .an-scrub-rail { position: relative; height: 6px; border-radius: var(--r-pill);
  background: rgb(var(--line-rgb)/.9); cursor: pointer; }
/* The focus ring is NOT decoration here: the rail is the only focusable thing in this
   row, and a keyboard user who cannot see where focus landed cannot use the arrows. */
.v-analytics .an-scrub-rail:focus-visible { outline: 2px solid var(--azure); outline-offset: 4px; }
.v-analytics .an-scrub-fill { position: absolute; inset: 0 auto 0 0; border-radius: var(--r-pill);
  background: linear-gradient(90deg, rgb(var(--cyan-rgb)/.55), rgb(var(--azure-rgb)/.9)); }
.v-analytics .an-scrub-knob { position: absolute; top: 50%; width: 14px; height: 14px;
  margin: -7px 0 0 -7px; border-radius: 50%; background: var(--ink);
  box-shadow: 0 0 0 3px rgb(var(--azure-rgb)/.35); transition: left var(--fast); }
.v-analytics .an-scrub-value { white-space: nowrap; }
.v-analytics .an-scrub-hint { grid-column: 1 / -1; }
@media (prefers-reduced-motion: reduce) {
  .v-analytics .an-scrub-knob { transition: none; }
}

/* honest-empty data-table fallback (AnHonest panels) */
.v-analytics .an-table { font-size: 13px; margin-top: 10px; }
.v-analytics .an-table > summary { cursor: pointer; color: var(--cyan-soft); font-size: 12px; width: fit-content; }
.v-analytics .an-table > summary:focus-visible { outline: none; box-shadow: 0 0 0 2px var(--cyan); border-radius: 6px; }
.v-analytics .an-table table { width: 100%; border-collapse: collapse; margin-top: 10px; }
.v-analytics .an-table caption { text-align: left; }
.v-analytics .an-table th, .v-analytics .an-table td { text-align: left; padding: 6px 10px;
  border-bottom: 1px solid rgb(var(--line-rgb)/.8); font-variant-numeric: tabular-nums; }
.v-analytics .an-table thead th { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--ink-muted); }

/* governed-wall block (denied) */
.v-analytics .an-blocked { text-align: center; padding: 34px 18px; }
.v-analytics .an-blocked-glyph { font-size: 30px; color: var(--warning); }
`;
