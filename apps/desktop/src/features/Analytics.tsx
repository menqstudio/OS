import { useApp } from '../app/store';
import {
  PageHeader, Panel, Async,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import type { Metric } from '../domain/entities';

/** Horizontal bar chart over the metrics already returned by getAnalytics().
 *  Bar length is proportional to value / max(values); when every value is 0
 *  (max === 0) all bars render zero-length instead of dividing by zero. */
function MetricBars({ metrics }: { metrics: Metric[] }) {
  const max = Math.max(0, ...metrics.map((m) => m.value));
  return (
    <div className="bar-chart">
      {metrics.map((m) => {
        const pct = max > 0 ? (m.value / max) * 100 : 0;
        return (
          <div className="bar-row" key={m.key}>
            <div className="bar-label" title={m.label}>{m.label}</div>
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${pct}%` }} />
            </div>
            <div className="bar-value">{m.value}</div>
          </div>
        );
      })}
    </div>
  );
}

export function Analytics() {
  const { t } = useApp();
  const s = useAsync(() => desktop.getAnalytics(), []);

  return (
    <>
      <PageHeader
        title={t('nav.analytics')}
        subtitle={t('analytics.subtitle')}
      />

      <Async state={s} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
        {(metrics) => (
          <div className="stack">
            <div className="grid grid-3">
              {metrics.map((m) => (
                <div className="card" key={m.key}>
                  <div className="panel">
                    <div style={{ fontSize: 30, fontWeight: 700 }}>{m.value}</div>
                    <div className="muted" style={{ marginTop: 4 }}>{m.label}</div>
                  </div>
                </div>
              ))}
            </div>

            <Panel title={t('analytics.chart')}>
              <MetricBars metrics={metrics} />
            </Panel>
          </div>
        )}
      </Async>
    </>
  );
}
