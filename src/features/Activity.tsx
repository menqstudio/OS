import { useApp } from '../app/store';
import { PageHeader, Panel, Badge, Avatar, EmptyState } from '../components/ui';
import { activity } from '../data/mock';

export function Activity() {
  const { t } = useApp();

  return (
    <>
      <PageHeader title={t('nav.activity')} subtitle={t('activity.subtitle')} />

      {activity.length === 0 ? (
        <EmptyState title={t('state.empty')} hint={t('state.emptyHint')} />
      ) : (
        <Panel>
          <div className="stack" style={{ gap: 0 }}>
            {activity.map((e) => (
              <div key={e.id} className="list-row">
                <span className="row">
                  <Badge tone="info">{e.eventType}</Badge>
                  <span>{e.entity}</span>
                  <span className="row muted">
                    <Avatar name={e.actor} />
                    {e.actor}
                  </span>
                </span>
                <span className="muted">{e.createdAt}</span>
              </div>
            ))}
          </div>
        </Panel>
      )}
    </>
  );
}
