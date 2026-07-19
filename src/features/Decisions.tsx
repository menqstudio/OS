import { useApp } from '../app/store';
import { PageHeader, Card, StatusPill, Field, Async } from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { desktop } from '../services/desktop';
import type { Decision } from '../domain/entities';

export function Decisions() {
  const { t } = useApp();
  const state = useAsync<Decision[]>(() => desktop.listDecisions());

  return (
    <>
      <PageHeader title={t('nav.decisions')} subtitle={t('decisions.subtitle')} />

      <Async state={state} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
        {(decisions) => (
          <div className="stack">
            {decisions.map((d) => (
              <Card key={d.id}>
                <div className="stack">
                  <div className="between row">
                    <span style={{ fontWeight: 600, fontSize: 15 }}>{d.title}</span>
                    <StatusPill status={d.status} />
                  </div>
                  <Field label={t('field.owner')}>{d.owner}</Field>
                  <div className="muted">{d.rationale}</div>
                  <div className="muted" style={{ fontSize: 12 }}>{d.updatedAt}</div>
                </div>
              </Card>
            ))}
          </div>
        )}
      </Async>
    </>
  );
}
