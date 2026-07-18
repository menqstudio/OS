import { useApp } from '../app/store';
import { PageHeader, Panel, Badge, StatusPill, EmptyState } from '../components/ui';
import { memory } from '../data/mock';

export function Memory() {
  const { t } = useApp();

  return (
    <>
      <PageHeader title={t('nav.memory')} subtitle={t('memory.subtitle')} />

      <div className="proto-banner">No hidden memory — every stored item is inspectable below.</div>

      {memory.length === 0 ? (
        <EmptyState title={t('state.empty')} hint={t('state.emptyHint')} />
      ) : (
        <div className="stack">
          {memory.map((m) => (
            <Panel key={m.id}>
              <div className="stack" style={{ gap: 8 }}>
                <div className="between row">
                  <div className="row">
                    <Badge tone="accent">{m.category}</Badge>
                    <span style={{ fontWeight: 600 }}>{m.subject}</span>
                  </div>
                  <StatusPill status={m.status} />
                </div>
                <span className="muted">{m.content}</span>
                <div className="row">
                  <span className="muted">Confidence {Math.round(m.confidence * 100)}%</span>
                  <Badge tone={m.sensitivity === 'normal' ? 'neutral' : 'warning'}>{m.sensitivity}</Badge>
                </div>
              </div>
            </Panel>
          ))}
        </div>
      )}
    </>
  );
}
