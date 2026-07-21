import { useApp } from '../app/store';
import { PageHeader, Card, Button, Badge, StatusPill, Field, Async } from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { useToast } from '../components/toast';
import { desktop } from '../services/desktop';

export function Approvals() {
  const { t } = useApp();
  const toast = useToast();
  const state = useAsync(() => desktop.listApprovals());

  // T-010: reject is the only decision the webview may make. Approve is not a
  // webview command — generic decide_approval is capability-denied to this window,
  // and an approve requires renderer-independent native confirmation (T-011).
  const reject = (id: string) => {
    desktop
      .rejectApproval(id)
      .then(() => state.reload())
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : String(e);
        toast(`${t('approvals.decideFailed')}: ${msg}`, 'error');
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

                  {a.status === 'pending' && (
                    <div className="stack">
                      <div className="row">
                        <Button variant="primary" disabled title={t('approvals.approveNativePending')}>
                          {t('action.approve')}
                        </Button>
                        <Button variant="danger" onClick={() => reject(a.id)}>
                          {t('action.reject')}
                        </Button>
                      </div>
                      <div className="muted" style={{ fontSize: 12 }}>
                        🔒 {t('approvals.approveNativePending')}
                      </div>
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
