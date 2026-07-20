import { useApp } from '../app/store';
import { PageHeader, Panel, Badge, Skeleton, ErrorState, EmptyState } from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';

export function Security() {
  const { t } = useApp();
  const s = useAsync(() => desktop.getSecuritySummary(), []);

  return (
    <>
      <PageHeader title={t('nav.security')} subtitle={t('security.subtitle')} />

      {s.loading && s.data === null && <Skeleton rows={4} />}
      {s.error && <ErrorState message={s.error} onRetry={s.reload} />}
      {s.data && (
        <>
          <div className="grid grid-3">
            <div className="card">
              <div className="panel">
                <div style={{ fontSize: 30, fontWeight: 700 }}>{s.data.pendingApprovals}</div>
                <div className="muted">{t('security.pending')}</div>
              </div>
            </div>
            <div className="card">
              <div className="panel">
                <div style={{ fontSize: 30, fontWeight: 700 }}>{s.data.decidedApprovals}</div>
                <div className="muted">{t('security.decided')}</div>
              </div>
            </div>
            <div className="card">
              <div className="panel">
                <div style={{ fontSize: 30, fontWeight: 700 }}>{s.data.auditEvents}</div>
                <div className="muted">{t('security.audit')}</div>
              </div>
            </div>
          </div>

          <div style={{ marginTop: 16 }}>
            <Panel title={t('security.sensitive')}>
              {s.data.sensitiveEvents.length === 0 ? (
                <EmptyState title={t('state.empty')} />
              ) : (
                <div className="stack">
                  {s.data.sensitiveEvents.map((ev) => (
                    <div key={ev.id} className="list-row">
                      <span className="row" style={{ gap: 8 }}>
                        <Badge tone="neutral">{ev.eventType}</Badge>
                        <span className="muted">
                          {ev.entityType ?? '—'}{ev.entityId ? ` · ${ev.entityId}` : ''}
                        </span>
                      </span>
                      <span className="muted">{ev.createdAt}</span>
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          </div>
        </>
      )}
    </>
  );
}
