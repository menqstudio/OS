import { useApp } from '../app/store';
import { PageHeader, Panel, Badge, EmptyState } from '../components/ui';
import { knowledge } from '../data/mock';

export function Knowledge() {
  const { t } = useApp();

  return (
    <>
      <PageHeader title={t('nav.knowledge')} subtitle={t('knowledge.subtitle')} />

      <input
        className="searchbtn"
        style={{ maxWidth: 'none', marginBottom: 16 }}
        placeholder={t('top.search')}
        readOnly
      />

      {knowledge.length === 0 ? (
        <EmptyState title={t('state.empty')} hint={t('state.emptyHint')} />
      ) : (
        <div className="stack">
          {knowledge.map((k) => (
            <Panel key={k.id}>
              <div className="between row">
                <div className="stack" style={{ gap: 4 }}>
                  <div className="row">
                    <Badge tone="accent">{k.type}</Badge>
                    <span style={{ fontWeight: 600 }}>{k.title}</span>
                  </div>
                  <span className="muted">{k.source}</span>
                </div>
                <span className="muted">{k.updatedAt}</span>
              </div>
            </Panel>
          ))}
        </div>
      )}
    </>
  );
}
