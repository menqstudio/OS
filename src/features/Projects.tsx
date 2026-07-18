import { useState } from 'react';
import { useApp } from '../app/store';
import { PageHeader, Panel, Button, Badge, StatusPill, Field } from '../components/ui';
import { projects, tasks } from '../data/mock';
import { statusTone } from '../domain/enums';

export function Projects() {
  const { t } = useApp();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = projects.find((p) => p.id === selectedId) ?? null;
  const linked = selected ? tasks.filter((x) => x.projectId === selected.id) : [];

  return (
    <>
      <PageHeader
        title={t('nav.projects')}
        subtitle={t('projects.subtitle')}
        actions={<Button variant="primary">{t('action.new')}</Button>}
      />

      <div className="grid grid-3">
        {projects.map((p) => (
          <div
            key={p.id}
            className="card"
            style={{ cursor: 'pointer', outline: selectedId === p.id ? '2px solid var(--brops-accent)' : 'none' }}
            onClick={() => setSelectedId(p.id)}
          >
            <div className="panel">
              <div className="between">
                <div className="panel-title">{p.name}</div>
                <StatusPill status={p.status} />
              </div>
              <div className="muted" style={{ marginTop: 6 }}>{p.description}</div>
              <div className="row" style={{ marginTop: 12, gap: 8 }}>
                <Badge tone={statusTone[p.priority] ?? 'neutral'}>{p.priority}</Badge>
                <span className="muted">{p.taskCount} tasks</span>
                <span className="muted">{p.openApprovals} approvals</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {selected && (
        <div style={{ marginTop: 16 }}>
          <Panel
            title={selected.name}
            actions={<Button small variant="ghost" onClick={() => setSelectedId(null)}>{t('action.viewAll')}</Button>}
          >
            <div className="muted" style={{ marginBottom: 12 }}>{selected.description}</div>
            <div className="grid grid-3" style={{ marginBottom: 12 }}>
              <Field label={t('field.status')}><StatusPill status={selected.status} /></Field>
              <Field label={t('field.risk')}><Badge tone={statusTone[selected.priority] ?? 'neutral'}>{selected.priority}</Badge></Field>
              <Field label={t('action.open')}>{selected.openApprovals} approvals</Field>
            </div>
            <div className="panel-title" style={{ marginBottom: 8 }}>Linked tasks</div>
            <div className="stack">
              {linked.map((x) => (
                <div key={x.id} className="list-row">
                  <span>{x.title}</span>
                  <StatusPill status={x.status} />
                </div>
              ))}
            </div>
          </Panel>
        </div>
      )}
    </>
  );
}
