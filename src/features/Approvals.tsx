import { useApp } from '../app/store';
import { PageHeader, Card, Button, Badge, StatusPill, Field, Async } from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { desktop } from '../services/desktop';

export function Approvals() {
  const { t } = useApp();
  const state = useAsync(() => desktop.listApprovals());

  const decide = (id: string, decision: 'approved' | 'rejected') => {
    desktop
      .decideApproval(id, decision)
      .then(() => state.reload())
      .catch(() => {
        /* keep simple: surface nothing, the list simply stays as-is */
      });
  };

  return (
    <>
      <PageHeader title={t('nav.approvals')} subtitle={t('approvals.subtitle')} />

      <Async state={state} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
        {(data) => (
          <div className="stack">
            {data.map((a) => (
              <Card key={a.id}>
                <div className="stack">
                  <div className="between row">
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 15 }}>{a.actionType}</div>
                      <div className="muted">{a.target}</div>
                    </div>
                    <StatusPill status={a.status} />
                  </div>

                  <div className="grid grid-2">
                    <Field label={t('field.level')}>
                      <Badge tone="accent">{a.level}</Badge>
                    </Field>
                    <Field label={t('field.risk')}>
                      <StatusPill status={a.riskLevel} />
                    </Field>
                    <Field label="Requested by">{a.requestedBy}</Field>
                    <Field label="Requested at">{a.requestedAt}</Field>
                    <Field label={t('field.status')}>
                      <StatusPill status={a.status} />
                    </Field>
                  </div>

                  {a.level === 'A3' && (
                    <div className="muted" style={{ fontSize: 12 }}>
                      ⚠ A3 — dual confirmation required for this destructive action.
                    </div>
                  )}

                  {a.status === 'pending' && (
                    <div className="row">
                      <Button variant="primary" onClick={() => decide(a.id, 'approved')}>
                        {t('action.approve')}
                      </Button>
                      <Button variant="danger" onClick={() => decide(a.id, 'rejected')}>
                        {t('action.reject')}
                      </Button>
                    </div>
                  )}
                </div>
              </Card>
            ))}
          </div>
        )}
      </Async>
    </>
  );
}
