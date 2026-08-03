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

  const metrics = s.data ?? [];
  const total = metrics.reduce((sum, m) => sum + m.value, 0);
  const reduced = useReducedMotion();
  const totalShown = useCountUp(total, reduced);
  const denied = s.error ? /denied|not permitted|permission|blocked|forbidden/i.test(s.error) : false;

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
            <span className="pill live">{Lz('streamLive')}</span>
          </div>

          <AnPlot metrics={metrics} hidden={hidden} onToggle={toggle} tr={Lz} lang={lang} />

          <div className="wire live" aria-hidden="true" />

          <div className="an-deck-foot">
            <span className="capsule">
              <b>{metrics.length}</b>
              <span>{Lz('nodes')}</span>
            </span>
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
          <span className="pill live">{Lz('streamLive')}</span>
          <Mark state="live" size={30} />
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
