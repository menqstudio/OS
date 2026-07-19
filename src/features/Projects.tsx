import { useState } from 'react';
import { useApp } from '../app/store';
import { PageHeader, Panel, Button, Badge, StatusPill, Field, Async } from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { statusTone } from '../domain/enums';
import type { Project } from '../domain/entities';

function ProjectDetail({ project, onClose }: { project: Project; onClose: () => void }) {
  const { t } = useApp();
  const s = useAsync(() => desktop.listTasksByProject(project.id), [project.id]);

  return (
    <div style={{ marginTop: 16 }}>
      <Panel
        title={project.name}
        actions={<Button small variant="ghost" onClick={onClose}>{t('action.viewAll')}</Button>}
      >
        <div className="muted" style={{ marginBottom: 12 }}>{project.description}</div>
        <div className="grid grid-3" style={{ marginBottom: 12 }}>
          <Field label={t('field.status')}><StatusPill status={project.status} /></Field>
          <Field label={t('field.risk')}>
            <Badge tone={statusTone[project.priority] ?? 'neutral'}>{project.priority}</Badge>
          </Field>
        </div>
        <div className="panel-title" style={{ marginBottom: 8 }}>Linked tasks</div>
        <Async state={s} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
          {(items) => (
            <div className="stack">
              {items.map((x) => (
                <div key={x.id} className="list-row">
                  <span>{x.title}</span>
                  <StatusPill status={x.status} />
                </div>
              ))}
            </div>
          )}
        </Async>
      </Panel>
    </div>
  );
}

export function Projects() {
  const { t } = useApp();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const s = useAsync(() => desktop.listProjects(), []);

  return (
    <>
      <PageHeader
        title={t('nav.projects')}
        subtitle={t('projects.subtitle')}
        actions={<Button variant="primary">{t('action.new')}</Button>}
      />

      <Panel>
        <Async state={s} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
          {(projects) => {
            const selected = projects.find((p) => p.id === selectedId) ?? null;
            return (
              <>
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
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {selected && (
                  <ProjectDetail project={selected} onClose={() => setSelectedId(null)} />
                )}
              </>
            );
          }}
        </Async>
      </Panel>
    </>
  );
}
