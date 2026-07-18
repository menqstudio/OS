import { useState } from 'react';
import { useApp } from '../app/store';
import { PageHeader, Card, Button, Badge, StatusPill, Field, EmptyState } from '../components/ui';
import { approvals } from '../data/mock';
import type { ApprovalStatus } from '../domain/enums';

export function Approvals() {
  const { t } = useApp();
  const [overrides, setOverrides] = useState<Record<string, ApprovalStatus>>({});

  const decide = (id: string, status: ApprovalStatus) =>
    setOverrides((prev) => ({ ...prev, [id]: status }));

  const items = approvals.map((a) => ({ ...a, status: overrides[a.id] ?? a.status }));
  const pending = items.filter((a) => a.status === 'pending');

  return (
    <>
      <PageHeader title={t('nav.approvals')} subtitle={t('approvals.subtitle')} />

      {pending.length === 0 ? (
        <EmptyState title={t('state.empty')} hint={t('state.emptyHint')} glyph="✓" />
      ) : (
        <div className="stack">
          {pending.map((a) => (
            <Card key={a.id}>
              <div className="stack">
                <div className="between row">
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 15 }}>{a.action}</div>
                    <div className="muted">{a.target}</div>
                  </div>
                  <StatusPill status={a.status} />
                </div>

                <div className="grid grid-2">
                  <Field label={t('field.level')}>
                    <Badge tone="accent">{a.level}</Badge>
                  </Field>
                  <Field label={t('field.risk')}>
                    <StatusPill status={a.risk} />
                  </Field>
                  <Field label={t('field.reversible')}>
                    {a.reversible ? t('value.yes') : t('value.no')}
                  </Field>
                  <Field label="Requested by">{a.requestedBy}</Field>
                  <Field label="Expires">{a.expiresAt}</Field>
                </div>

                {a.level === 'A3' && (
                  <div className="muted" style={{ fontSize: 12 }}>
                    ⚠ A3 — dual confirmation required for this destructive action.
                  </div>
                )}

                <div className="row">
                  <Button variant="primary" onClick={() => decide(a.id, 'approved')}>
                    {t('action.approve')}
                  </Button>
                  <Button variant="danger" onClick={() => decide(a.id, 'rejected')}>
                    {t('action.reject')}
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
