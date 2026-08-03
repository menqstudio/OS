import { useMemo, useState, type CSSProperties, type KeyboardEvent } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, Skeleton, ErrorState, EmptyState,
} from '../components/ui';
import { BarChart } from '../components/charts/Chart';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import type { Metric } from '../domain/entities';

// ---------------------------------------------------------------------------
// analytics ◈ Վերլուծություն — §D page.
//
// Real data source: the `get_analytics` Tauri command (desktop.getAnalytics()),
// which returns all-time aggregate `Metric[]` (key/label/value). That backs the
// live deck (anLive/anDeck) and the distribution-by-node plot (anPlot/anCap/anTotal).
//
// The engine does NOT (yet) expose a time-bucketed series, an autonomy-split
// aggregate, or a channel-split aggregate. So per the spec's honesty rule we do
// not fabricate any of them:
//   • the scrubber (anScrub) narrows the window, but only "All time" resolves —
//     any narrower window renders the spec's `empty (no data range)` state,
//     because all we hold are all-time aggregates;
//   • the autonomy split and channel split render their honest `empty` state,
//     naming the missing engine aggregate rather than inventing numbers.
// ---------------------------------------------------------------------------

type L = (en: string, hy: string) => string;

/** Custom-property inline style (React.CSSProperties has no string index sig). */
function vars(v: Record<string, string | number>): CSSProperties {
  return v as unknown as CSSProperties;
}

interface RangePreset { id: string; en: string; hy: string; }

// Widest → narrowest. Index 0 ("All time") is the only window the all-time
// aggregates can honestly answer; the rest exercise the `empty (no data range)`
// state through a real, keyboard-driven control.
const RANGES: RangePreset[] = [
  { id: 'all', en: 'All time', hy: 'Ամբողջ ընթացքը' },
  { id: '90d', en: 'Last 90 days', hy: 'Վերջին 90 օր' },
  { id: '30d', en: 'Last 30 days', hy: 'Վերջին 30 օր' },
  { id: '7d', en: 'Last 7 days', hy: 'Վերջին 7 օր' },
  { id: '24h', en: 'Last 24 hours', hy: 'Վերջին 24 ժ' },
];

// --- anScrub: the time-range scrubber (role=slider, arrow-driven) -----------
function AnScrub(
  { index, onIndex, rangeText, L }:
  { index: number; onIndex: (i: number) => void; rangeText: string; L: L },
) {
  const max = RANGES.length - 1;
  const pct = max > 0 ? (index / max) * 100 : 0;

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    let next = index;
    if (e.key === 'ArrowRight' || e.key === 'ArrowUp') next = Math.min(max, index + 1);
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') next = Math.max(0, index - 1);
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = max;
    else if (e.key === 'PageUp') next = Math.min(max, index + 2);
    else if (e.key === 'PageDown') next = Math.max(0, index - 2);
    else return;
    e.preventDefault();
    if (next !== index) onIndex(next);
  };

  return (
    <div className="an-scrub">
      <div className="an-scrub-cap">{L('Range', 'Ժամանակահատված')}</div>
      <div
        className="an-scrub-track"
        role="slider"
        tabIndex={0}
        aria-label={L('Analytics time range', 'Վերլուծության ժամանակահատված')}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={index}
        aria-valuetext={rangeText}
        onKeyDown={onKey}
      >
        <div className="an-scrub-rail" />
        <div className="an-scrub-fill" style={{ width: `${pct}%` }} />
        {RANGES.map((r, i) => (
          <button
            key={r.id}
            type="button"
            className={`an-scrub-tick ${i === index ? 'an-scrub-tick--on' : ''}`}
            style={{ left: `${max > 0 ? (i / max) * 100 : 0}%` }}
            aria-label={L(r.en, r.hy)}
            aria-current={i === index ? 'true' : undefined}
            tabIndex={-1}
            onClick={() => onIndex(i)}
          />
        ))}
        <div className="an-scrub-thumb" style={{ left: `${pct}%` }} aria-hidden="true" />
      </div>
      <div className="an-scrub-now" aria-hidden="true">{rangeText}</div>
    </div>
  );
}

// --- anDeck / anLive: the live KPI deck over real metrics -------------------
function AnDeck({ metrics, L }: { metrics: Metric[]; L: L }) {
  return (
    <div className="an-deck grid grid-3" role="list" aria-label={L('Live metrics', 'Կենդանի ցուցանիշներ')}>
      {metrics.map((m, i) => (
        <div className="card an-live" role="listitem" key={m.key} style={vars({ '--enter': `${i * 45}ms` })}>
          <div className="panel">
            <div className="an-live-head">
              <span className="an-live-dot" aria-hidden="true" />
              <span className="an-live-tag">{L('Live', 'Կենդանի')}</span>
            </div>
            <div className="an-live-value" style={{ fontSize: 30, fontWeight: 700 }}>{m.value}</div>
            <div className="muted" style={{ marginTop: 4 }}>{m.label}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

// --- distribution-by-node: the BarChart primitive -------------------------
// Delegates to the library `BarChart` (horizontal bars + focusable legend + share%
// + accessible summary + <details> table fallback). This page only maps the real
// `Metric[]` to the primitive's data shape and supplies bilingual labels + the
// honest one-line summary. Color is one flat accent — meaning is carried by the
// text label + value on every row, never by hue.
function AnPlot(
  { metrics, hidden, onToggle, L }:
  { metrics: Metric[]; hidden: ReadonlySet<string>; onToggle: (key: string) => void; L: L },
) {
  const visible = metrics.filter((m) => !hidden.has(m.key));
  const total = visible.reduce((sum, m) => sum + m.value, 0);
  const top = visible.reduce<Metric | null>((best, m) => (best && best.value >= m.value ? best : m), null);

  const summary = visible.length === 0
    ? L('No nodes selected.', 'Ընտրված հանգույց չկա։')
    : L(
      `${visible.length} nodes, total ${total}.${top ? ` Highest: ${top.label} (${top.value}).` : ''}`,
      `${visible.length} հանգույց, ընդամենը ${total}։${top ? ` Ամենաբարձրը՝ ${top.label} (${top.value})։` : ''}`,
    );

  return (
    <BarChart
      data={metrics.map((m) => ({ key: m.key, label: m.label, value: m.value }))}
      caption={L('Distribution by node', 'Բաշխում ըստ հանգույցի')}
      summary={summary}
      hidden={hidden}
      onToggle={onToggle}
      legendLabel={L('Toggle nodes', 'Փոխարկել հանգույցները')}
      showLabel={L('Show node', 'Ցուցադրել հանգույցը')}
      hideLabel={L('Hide node', 'Թաքցնել հանգույցը')}
      hiddenWord={L('hidden', 'թաքցված')}
      allHiddenNote={L('All nodes hidden — enable one in the legend.', 'Բոլոր հանգույցները թաքցված են․ միացրեք որևէ մեկը լեգենդից։')}
      totalLabel={L('Total across nodes', 'Ընդամենը հանգույցներով')}
      nodeHeader={L('Node', 'Հանգույց')}
      valueHeader={L('Value', 'Արժեք')}
      shareHeader={L('Share', 'Բաժին')}
      tableToggle={L('Show data table', 'Ցուցադրել աղյուսակը')}
    />
  );
}

// --- autonomy split / channel split: honest empty --------------------------
// The engine exposes no split aggregate yet; we name what's missing instead of
// fabricating a breakdown (spec forbids invented data).
function AnSplit(
  { title, glyph, note, tableHint, L }:
  { title: string; glyph: string; note: string; tableHint: string; L: L },
) {
  return (
    <Panel title={title}>
      <EmptyState glyph={glyph} title={L('No breakdown available', 'Բաժանում առկա չէ')} hint={note} />
      <details className="an-table">
        <summary>{L('Show data table', 'Ցուցադրել աղյուսակը')}</summary>
        <table>
          <caption className="an-sr">{title}</caption>
          <thead>
            <tr>
              <th scope="col">{L('Segment', 'Հատված')}</th>
              <th scope="col">{L('Value', 'Արժեք')}</th>
            </tr>
          </thead>
          <tbody>
            <tr><td colSpan={2} className="muted">{tableHint}</td></tr>
          </tbody>
        </table>
      </details>
    </Panel>
  );
}

export function Analytics() {
  const { t, lang } = useApp();
  const L: L = (en, hy) => (lang === 'hy' ? hy : en);
  const s = useAsync(() => desktop.getAnalytics(), []);

  const [rangeIdx, setRangeIdx] = useState(0);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(() => new Set());

  const range = RANGES[rangeIdx];
  const rangeText = L(range.en, range.hy);
  // Only the all-time window (index 0) can be honestly answered by all-time aggregates.
  const windowed = rangeIdx !== 0;

  const toggle = (key: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const metrics = s.data ?? [];
  const denied = s.error ? /denied|not permitted|permission|blocked|forbidden/i.test(s.error) : false;

  // aria-live announcement: current range + whether it resolves to data.
  const liveMsg = useMemo(() => {
    if (s.loading && s.data === null) return L('Loading analytics…', 'Վերլուծությունը բեռնվում է…');
    if (s.error) return L('Analytics unavailable.', 'Վերլուծությունն անհասանելի է։');
    if (metrics.length === 0) return L('No analytics data.', 'Վերլուծության տվյալներ չկան։');
    if (windowed) return L(`${rangeText}: no data in this range.`, `${rangeText}՝ այս ընդգրկույթում տվյալ չկա։`);
    return L(`${rangeText}: ${metrics.length} nodes.`, `${rangeText}՝ ${metrics.length} հանգույց։`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.loading, s.error, s.data, metrics.length, windowed, rangeText, lang]);

  const renderBody = () => {
    // loading
    if (s.loading && s.data === null) {
      return (
        <div className="stack">
          <Panel title={t('nav.analytics')}>
            <Skeleton rows={3} />
          </Panel>
          <Panel title={t('analytics.chart')}>
            <Skeleton rows={5} />
          </Panel>
        </div>
      );
    }

    // error (governed blocked vs generic failure)
    if (s.error) {
      if (denied) {
        return (
          <Panel title={t('nav.analytics')}>
            <div className="an-blocked" role="alert">
              <div className="an-blocked-glyph" aria-hidden="true">⛒</div>
              <div className="empty-title">{t('state.permissionDenied')}</div>
              <p className="muted" style={{ maxWidth: 460, margin: '4px auto 0' }}>
                {L(
                  'This analytics aggregate is governed. The request was blocked at the wall; nothing was read.',
                  'Այս վերլուծական ագրեգատը կառավարվող է։ Հարցումը արգելափակվեց պատի մոտ․ ոչինչ չկարդացվեց։',
                )}
              </p>
              <div style={{ marginTop: 12 }}>
                <Button small onClick={s.reload}>{t('action.retry')}</Button>
              </div>
            </div>
          </Panel>
        );
      }
      return <ErrorState message={s.error} onRetry={s.reload} retryLabel={t('action.retry')} />;
    }

    // empty (no data at all)
    if (metrics.length === 0) {
      return <EmptyState title={t('state.empty')} hint={t('state.emptyHint')} />;
    }

    // scrubber is always present once data loads so the user can return to "All time"
    return (
      <div className="stack">
        <Panel title={t('analytics.subtitle')}>
          <AnScrub index={rangeIdx} onIndex={setRangeIdx} rangeText={rangeText} L={L} />
          <p className="an-cap muted">
            {L(
              'Engine analytics are all-time aggregates. Narrower windows are not available yet.',
              'Շարժիչի վերլուծությունը ամբողջ ընթացքի ագրեգատներ են։ Ավելի նեղ պատուհանները դեռ հասանելի չեն։',
            )}
          </p>
        </Panel>

        {windowed ? (
          // empty (no data range) — the spec's named empty state, reached via the scrubber
          <Panel title={rangeText}>
            <EmptyState
              glyph="◷"
              title={L('No data in this range', 'Այս ընդգրկույթում տվյալ չկա')}
              hint={L(
                'The engine only returns all-time aggregates. Scrub back to “All time” to see the data.',
                'Շարժիչը վերադարձնում է միայն ամբողջ ընթացքի ագրեգատներ։ Վերադարձեք «Ամբողջ ընթացքը»՝ տվյալները տեսնելու համար։',
              )}
            />
          </Panel>
        ) : (
          <>
            <AnDeck metrics={metrics} L={L} />

            <Panel title={t('analytics.chart')}>
              <AnPlot metrics={metrics} hidden={hidden} onToggle={toggle} L={L} />
            </Panel>

            <div className="grid grid-2">
              <AnSplit
                title={L('Autonomy split', 'Ինքնավարության բաժանում')}
                glyph="◑"
                note={L(
                  'The engine does not expose an autonomy-level aggregate yet, so no split is shown.',
                  'Շարժիչը դեռ չի տրամադրում ինքնավարության մակարդակի ագրեգատ, ուստի բաժանում ցուցադրված չէ։',
                )}
                tableHint={L('No autonomy aggregate from the engine.', 'Շարժիչից ինքնավարության ագրեգատ չկա։')}
                L={L}
              />
              <AnSplit
                title={L('Channel split', 'Ալիքների բաժանում')}
                glyph="◈"
                note={L(
                  'The engine does not expose a per-channel aggregate yet, so no split is shown.',
                  'Շարժիչը դեռ չի տրամադրում ըստ ալիքի ագրեգատ, ուստի բաժանում ցուցադրված չէ։',
                )}
                tableHint={L('No channel aggregate from the engine.', 'Շարժիչից ալիքի ագրեգատ չկա։')}
                L={L}
              />
            </div>
          </>
        )}
      </div>
    );
  };

  return (
    <>
      <style>{ANALYTICS_CSS}</style>
      <PageHeader title={t('nav.analytics')} subtitle={t('analytics.subtitle')} />

      {/* aria-live status: announces range + whether it resolves to data */}
      <div className="an-sr" role="status" aria-live="polite">{liveMsg}</div>

      {renderBody()}
    </>
  );
}

// Page-scoped styles — all resolve through design tokens, no hard-coded colors.
// Chart series use `--enter` (staggered entrance) and the scrubber `--fast`
// motion; every animation is disabled under prefers-reduced-motion.
const ANALYTICS_CSS = `
.an-sr { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }

/* anScrub */
.an-scrub { display: flex; align-items: center; gap: var(--menq-space-4); flex-wrap: wrap; }
.an-scrub-cap { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--brops-muted); }
.an-scrub-track { position: relative; flex: 1; min-width: 220px; height: 26px; display: flex; align-items: center;
  cursor: pointer; outline: none; }
.an-scrub-track:focus-visible { box-shadow: 0 0 0 2px var(--menq-color-focus); border-radius: var(--menq-radius-pill); }
.an-scrub-rail { position: absolute; left: 0; right: 0; height: 4px; border-radius: var(--menq-radius-pill);
  background: var(--menq-color-hover); }
.an-scrub-fill { position: absolute; left: 0; height: 4px; border-radius: var(--menq-radius-pill);
  background: var(--brops-accent); transition: width var(--menq-motion-fast) ease; }
.an-scrub-tick { position: absolute; top: 50%; width: 11px; height: 11px; padding: 0; transform: translate(-50%, -50%);
  border-radius: 50%; border: 2px solid var(--brops-border); background: var(--brops-surface); cursor: pointer;
  transition: border-color var(--menq-motion-fast), background var(--menq-motion-fast); }
.an-scrub-tick:hover { border-color: var(--brops-accent); }
.an-scrub-tick--on { border-color: var(--brops-accent); background: var(--brops-accent); }
.an-scrub-thumb { position: absolute; top: 50%; width: 16px; height: 16px; transform: translate(-50%, -50%);
  border-radius: 50%; background: var(--brops-accent); border: 2px solid var(--brops-surface);
  box-shadow: var(--menq-shadow-1); pointer-events: none; transition: left var(--menq-motion-fast) ease; }
.an-scrub-now { font-size: 13px; font-weight: 600; color: var(--brops-text); min-width: 92px; text-align: right; }

/* anDeck / anLive */
.an-deck { margin-bottom: 0; }
.an-live { animation: an-rise var(--menq-motion-med) ease-out both; animation-delay: var(--enter, 0ms); }
.an-live-head { display: inline-flex; align-items: center; gap: 6px; }
.an-live-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--menq-color-success);
  box-shadow: 0 0 0 0 color-mix(in srgb, var(--menq-color-success) 60%, transparent);
  animation: an-pulse 2s ease-out infinite; }
.an-live-tag { font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--brops-muted); font-weight: 700; }
.an-live-value { font-variant-numeric: tabular-nums; }

/* anCap — the scrubber's honest note (the distribution plot itself is the shared
   BarChart primitive, styled in ui.css). */
.an-cap { font-size: 13px; color: var(--brops-muted); margin: 0; }

/* data-table fallback (AnSplit honest-empty tables) */
.an-table { font-size: 13px; }
.an-table > summary { cursor: pointer; color: var(--brops-accent); font-size: 12px; width: fit-content; }
.an-table > summary:focus-visible { outline: none; box-shadow: 0 0 0 2px var(--menq-color-focus); border-radius: var(--menq-radius-sm); }
.an-table table { width: 100%; border-collapse: collapse; margin-top: var(--menq-space-3); }
.an-table caption { text-align: left; }
.an-table th, .an-table td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--brops-border);
  font-variant-numeric: tabular-nums; }
.an-table thead th { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--brops-muted); }
.an-table tbody th { font-weight: 500; color: var(--brops-text); }

/* blocked (governed wall) */
.an-blocked { text-align: center; padding: var(--menq-space-6) var(--menq-space-4); }
.an-blocked-glyph { font-size: 30px; color: var(--menq-color-warning); }

@keyframes an-rise { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes an-pulse {
  0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--menq-color-success) 55%, transparent); }
  70% { box-shadow: 0 0 0 6px color-mix(in srgb, var(--menq-color-success) 0%, transparent); }
  100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--menq-color-success) 0%, transparent); }
}
@media (prefers-reduced-motion: reduce) {
  .an-live { animation: none; }
  .an-live-dot { animation: none; }
  .an-scrub-fill, .an-scrub-thumb, .an-scrub-tick { transition: none; }
}
`;
