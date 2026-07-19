import { useApp } from '../app/store';
import {
  PageHeader, Async,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';

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
        )}
      </Async>
    </>
  );
}
