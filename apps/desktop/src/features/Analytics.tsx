import { useMemo, useState } from 'react';
import { useApp } from '../app/store';
import { Button, Skeleton, ErrorState, EmptyState } from '../components/ui';
import { BarChart } from '../components/charts/Chart';
import { Mark } from '../components/Ambient';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import type { Metric } from '../domain/entities';

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

type L = (en: string, hy: string) => string;

// --- the distribution plot: the shared accessible BarChart over real metrics --
// Delegates to the library `BarChart` (horizontal bars + focusable legend + share%
// + accessible one-line summary + <details> table fallback). This page only maps
// the real `Metric[]` to the primitive's data shape and supplies bilingual labels.
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

// --- honest empty panel: the engine exposes no such split aggregate yet -------
// Names what's missing (with a keyboard-reachable <details> table) instead of
// fabricating a breakdown. Reused for the districts, autonomy and channel panels.
function AnHonest(
  { panelClass, title, note, glyph, hint, tableHint, segLabel, valLabel, L }:
  {
    panelClass: string; title: string; note?: string; glyph: string; hint: string;
    tableHint: string; segLabel: string; valLabel: string; L: L;
  },
) {
  return (
    <section className={`surface soft ${panelClass} rise`}>
      <div className="sec-head">
        <h2>{title}</h2>
        {note ? <span className="note">{note}</span> : null}
      </div>
      <EmptyState glyph={glyph} title={L('No breakdown available', 'Բաժանում առկա չէ')} hint={hint} />
      <details className="an-table">
        <summary>{L('Show data table', 'Ցուցադրել աղյուսակը')}</summary>
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
  const L: L = (en, hy) => (lang === 'hy' ? hy : en);
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
  const denied = s.error ? /denied|not permitted|permission|blocked|forbidden/i.test(s.error) : false;

  // aria-live announcement: current data state (node count from real metrics).
  const liveMsg = useMemo(() => {
    if (s.loading && s.data === null) return L('Loading analytics…', 'Վերլուծությունը բեռնվում է…');
    if (s.error) return L('Analytics unavailable.', 'Վերլուծությունն անհասանելի է։');
    if (metrics.length === 0) return L('No analytics data.', 'Վերլուծության տվյալներ չկան։');
    return L(`${metrics.length} nodes.`, `${metrics.length} հանգույց։`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.loading, s.error, s.data, metrics.length, lang]);

  const renderBody = () => {
    // loading
    if (s.loading && s.data === null) {
      return (
        <section className="an-deck surface soft lg hud">
          <span className="bracket tl" aria-hidden="true" />
          <span className="bracket tr" aria-hidden="true" />
          <span className="bracket bl" aria-hidden="true" />
          <span className="bracket br" aria-hidden="true" />
          <Skeleton rows={6} />
        </section>
      );
    }

    // error (governed blocked vs generic failure)
    if (s.error) {
      if (denied) {
        return (
          <section className="an-deck surface soft lg hud">
            <span className="bracket tl" aria-hidden="true" />
            <span className="bracket tr" aria-hidden="true" />
            <span className="bracket bl" aria-hidden="true" />
            <span className="bracket br" aria-hidden="true" />
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
        <section className="an-deck surface soft lg hud reveal">
          <span className="bracket tl" aria-hidden="true" />
          <span className="bracket tr" aria-hidden="true" />
          <span className="bracket bl" aria-hidden="true" />
          <span className="bracket br" aria-hidden="true" />

          <div className="an-deck-top">
            <span className="eyebrow">{L('Distribution by node', 'Բաշխում ըստ հանգույցի')}</span>
            <span className="pill live">{L('STREAM · LIVE', 'ՀՈՍՔ · ԿԵՆԴԱՆԻ')}</span>
          </div>

          <AnPlot metrics={metrics} hidden={hidden} onToggle={toggle} L={L} />

          <div className="wire live" aria-hidden="true" />

          <div className="an-deck-foot">
            <span className="capsule">
              <b>{metrics.length}</b>
              <span>{L('nodes', 'հանգույց')}</span>
            </span>
            <span className="an-foot-r">
              <span className="micro">{L('Total across nodes', 'Ընդամենը հանգույցներով')}</span>
              <b className="mono">{total}</b>
            </span>
          </div>
        </section>

        {/* ── LOWER BOARD · honest empties for aggregates the engine lacks ───── */}
        <div className="an-lower">
          <AnHonest
            panelClass="an-districts"
            title={L('Distribution by district', 'Բաշխում ըստ շրջանների')}
            note={L('routed calls', 'ուղղորդված կանչ')}
            glyph="◍"
            hint={L(
              'The engine does not expose a per-district aggregate yet, so no breakdown is shown.',
              'Շարժիչը դեռ չի տրամադրում ըստ շրջանի ագրեգատ, ուստի բաժանում ցուցադրված չէ։',
            )}
            tableHint={L('No district aggregate from the engine.', 'Շարժիչից շրջանի ագրեգատ չկա։')}
            segLabel={L('District', 'Շրջան')}
            valLabel={L('Value', 'Արժեք')}
            L={L}
          />

          <aside className="an-side">
            <AnHonest
              panelClass="an-auto"
              title={L('Autonomy', 'Ինքնավարություն')}
              glyph="◑"
              hint={L(
                'The engine does not expose an autonomy-level aggregate yet, so no split is shown.',
                'Շարժիչը դեռ չի տրամադրում ինքնավարության մակարդակի ագրեգատ, ուստի բաժանում ցուցադրված չէ։',
              )}
              tableHint={L('No autonomy aggregate from the engine.', 'Շարժիչից ինքնավարության ագրեգատ չկա։')}
              segLabel={L('Segment', 'Հատված')}
              valLabel={L('Value', 'Արժեք')}
              L={L}
            />
            <AnHonest
              panelClass="an-chan"
              title={L('Channel split', 'Ալիքների բաժանում')}
              glyph="◈"
              hint={L(
                'The engine does not expose a per-channel aggregate yet, so no split is shown.',
                'Շարժիչը դեռ չի տրամադրում ըստ ալիքի ագրեգատ, ուստի բաժանում ցուցադրված չէ։',
              )}
              tableHint={L('No channel aggregate from the engine.', 'Շարժիչից ալիքի ագրեգատ չկա։')}
              segLabel={L('Channel', 'Ալիք')}
              valLabel={L('Value', 'Արժեք')}
              L={L}
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
      <header className="pageHead reveal">
        <div>
          <span className="eyebrow">{L('INTELLIGENCE CENTRE · ANALYTICS', 'ԻՆՏԵԼԵԿՏԻ ԿԵՆՏՐՈՆ · ANALYTICS')}</span>
          <h1>{t('nav.analytics')}</h1>
          <p className="sub">{t('analytics.subtitle')}</p>
        </div>
        <div className="right">
          <span className="pill live">{L('STREAM · LIVE', 'ՀՈՍՔ · ԿԵՆԴԱՆԻ')}</span>
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
