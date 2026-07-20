import { useApp } from '../app/store';
import { PageHeader, Panel, Badge, Avatar, Async } from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { desktop } from '../services/desktop';
import type { ActivityEvent } from '../domain/entities';

export function Activity() {
  const { t } = useApp();
  const state = useAsync<ActivityEvent[]>(() => desktop.listActivity());

  return (
    <>
      <PageHeader title={t('nav.activity')} subtitle={t('activity.subtitle')} />

      <Async state={state} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
        {(events) => (
          <Panel>
            <div className="stack" style={{ gap: 0 }}>
              {events.map((e) => {
                const actor = e.actorId ?? 'system';
                const target = e.entityId ?? e.entityType;
                return (
                  <div key={e.id} className="list-row">
                    <span className="row">
                      <Badge tone="info">{e.eventType}</Badge>
                      {target && <span>{target}</span>}
                      <span className="row muted">
                        <Avatar name={actor} />
                        {actor}
                      </span>
                    </span>
                    <span className="muted">{e.createdAt}</span>
                  </div>
                );
              })}
            </div>
          </Panel>
        )}
      </Async>
    </>
  );
}
