import { useState } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, Badge, StatusPill, Field, Async, Modal, FormRow, Input, Textarea, Select,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { useToast } from '../components/toast';
import { statusTone, PRIORITIES } from '../domain/enums';
import type { Project } from '../domain/entities';

function NewProjectForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { t } = useApp();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState('normal');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    desktop
      .createProject({ name: name.trim(), description: description.trim(), priority, workspaceId: null })
      .then(() => {
        onCreated();
        onClose();
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
        setBusy(false);
      });
  };

  return (
    <Modal title={t('form.newProject')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <FormRow label={t('field.name')}>
        <Input value={name} autoFocus onChange={(e) => setName(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.description')}>
        <Textarea value={description} onChange={(e) => setDescription(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.priority')}>
        <Select value={priority} onChange={(e) => setPriority(e.target.value)}>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </Select>
      </FormRow>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="primary" onClick={submit}>{t('action.create')}</Button>
      </div>
    </Modal>
  );
}

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
          <Field label={t('field.priority')}>
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
  const toast = useToast();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const s = useAsync(() => desktop.listProjects(), []);

  return (
    <>
      <PageHeader
        title={t('nav.projects')}
        subtitle={t('projects.subtitle')}
        actions={<Button variant="primary" onClick={() => setCreating(true)}>{t('action.new')}</Button>}
      />

      {creating && (
        <NewProjectForm
          onClose={() => setCreating(false)}
          onCreated={() => { s.reload(); toast(t('toast.created'), 'success'); }}
        />
      )}

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
