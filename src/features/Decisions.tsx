import { useApp } from '../app/store';
import { PageHeader, Card, Badge, Field } from '../components/ui';
import { decisions } from '../data/mock';
import { statusTone } from '../domain/enums';

export function Decisions() {
  const { t } = useApp();

  return (
    <>
      <PageHeader title={t('nav.decisions')} subtitle={t('decisions.subtitle')} />

      <div className="stack">
        {decisions.map((d) => (
          <Card key={d.id}>
            <div className="stack">
              <div className="between row">
                <span style={{ fontWeight: 600, fontSize: 15 }}>{d.title}</span>
                <Badge tone={statusTone[d.status] ?? 'neutral'}>{d.status.replace(/_/g, ' ')}</Badge>
              </div>
              <Field label={t('field.owner')}>{d.owner}</Field>
              <div className="muted">{d.rationale}</div>
              <div className="muted" style={{ fontSize: 12 }}>{d.updatedAt}</div>
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}
