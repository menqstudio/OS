import { useApp } from '../app/store';
import { PageHeader, StatusPill, Avatar, Async } from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { desktop } from '../services/desktop';

export function Agents() {
  const { t } = useApp();
  const state = useAsync(() => desktop.listAgents());

  return (
    <>
      <PageHeader title={t('nav.agents')} subtitle={t('agents.subtitle')} />

      <Async state={state} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
        {(data) => (
          <div className="grid grid-3">
            {data.map((a) => (
              <div key={a.id} className="card">
                <div className="panel">
                  <div className="between">
                    <span className="row" style={{ gap: 8 }}>
                      <Avatar name={a.displayName} />
                      <span>
                        <div className="panel-title">{a.displayName}</div>
                        <div className="muted">{a.role}</div>
                      </span>
                    </span>
                    <StatusPill status={a.status} />
                  </div>

                  <div className="muted" style={{ marginTop: 10 }}>{a.model ?? '—'}</div>
                  <div className="muted" style={{ marginTop: 4 }}>{a.slug}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </Async>
    </>
  );
}
