import { useState } from 'react';
import { useApp } from '../app/store';
import { PageHeader, Card, Button, Badge, StatusPill, Field, Async, ConfirmDialog } from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { useToast } from '../components/toast';
import { desktop } from '../services/desktop';

export function Approvals() {
  const { t } = useApp();
  const toast = useToast();
  const state = useAsync(() => desktop.listApprovals());
  // An A3 (destructive) approval awaiting the second, explicit confirmation.
  const [confirmA3, setConfirmA3] = useState<string | null>(null);

  const decide = (id: string, decision: 'approved' | 'rejected') => {
    desktop
      .decideApproval(id, decision)
      .then(() => state.reload())
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : String(e);
        toast(`${t('approvals.decideFailed')}: ${msg}`, 'error');
      });
  };

  // A3 approvals require a deliberate second confirmation before approving.
  const requestApprove = (id: string, level: string) => {
    if (level === 'A3') setConfirmA3(id);
    else decide(id, 'approved');
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
                      <Button variant="primary" onClick={() => requestApprove(a.id, a.level)}>
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

      {confirmA3 && (
        <ConfirmDialog
          title={t('approvals.a3ConfirmTitle')}
          message={t('approvals.a3ConfirmBody')}
          confirmLabel={t('action.approve')}
          cancelLabel={t('action.cancel')}
          onConfirm={() => { const id = confirmA3; setConfirmA3(null); decide(id, 'approved'); }}
          onCancel={() => setConfirmA3(null)}
        />
      )}
    </>
  );
}
