import { useEffect, useState } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, Badge, StatusPill, Field, Async, Modal, FormRow, Input, Textarea, Select,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { useToast } from '../components/toast';
import { statusTone, PRIORITIES, PROJECT_STATUSES } from '../domain/enums';
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

function EditProjectForm({ project, onClose, onSaved }: { project: Project; onClose: () => void; onSaved: () => void }) {
  const { t } = useApp();
  const toast = useToast();
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description);
  const [priority, setPriority] = useState(project.priority);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const save = () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    desktop
      .updateProject(project.id, name.trim(), description, priority)
      .then(() => { toast(t('toast.saved'), 'success'); onSaved(); onClose(); })
      .catch((e: unknown) => { setError(e instanceof Error ? e.message : String(e)); setBusy(false); });
  };

  return (
    <Modal title={t('form.editProject')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <FormRow label={t('field.name')}>
        <Input value={name} autoFocus onChange={(e) => setName(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.description')}>
        <Textarea value={description} onChange={(e) => setDescription(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.priority')}>
        <Select value={priority} onChange={(e) => setPriority(e.target.value)}>
          {PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
        </Select>
      </FormRow>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="primary" onClick={save}>{t('action.save')}</Button>
      </div>
    </Modal>
  );
}

function ProjectDetail({ project, onClose, onSaved }: { project: Project; onClose: () => void; onSaved: () => void }) {
  const { t } = useApp();
  const s = useAsync(() => desktop.listTasksByProject(project.id), [project.id]);
  const [tab, setTab] = useState<'overview' | 'tasks'>('overview');
  const [editing, setEditing] = useState(false);

  const changeStatus = (status: string) => {
    desktop.setProjectStatus(project.id, status).then(() => onSaved()).catch(() => onSaved());
  };

  return (
    <div style={{ marginTop: 16 }}>
      {editing && <EditProjectForm project={project} onClose={() => setEditing(false)} onSaved={onSaved} />}
      <Panel
        title={project.name}
        actions={<Button small variant="ghost" onClick={onClose}>{t('action.viewAll')}</Button>}
      >
        <div className="row" style={{ gap: 8, marginBottom: 12 }}>
          <Button small variant={tab === 'overview' ? 'primary' : 'ghost'} onClick={() => setTab('overview')}>
            {t('projects.tab.overview')}
          </Button>
          <Button small variant={tab === 'tasks' ? 'primary' : 'ghost'} onClick={() => setTab('tasks')}>
            {t('projects.tab.tasks')}
          </Button>
        </div>

        {tab === 'overview' ? (
          <>
            <div className="muted" style={{ marginBottom: 12 }}>{project.description}</div>
            <div className="grid grid-3" style={{ marginBottom: 12 }}>
              <Field label={t('field.status')}>
                <div className="row" style={{ gap: 8 }}>
                  <StatusPill status={project.status} />
                  <Select value={project.status} onChange={(e) => changeStatus(e.target.value)}>
                    {PROJECT_STATUSES.map((st) => <option key={st} value={st}>{st}</option>)}
                  </Select>
                </div>
              </Field>
              <Field label={t('field.priority')}>
                <Badge tone={statusTone[project.priority] ?? 'neutral'}>{project.priority}</Badge>
              </Field>
            </div>
            <Button small variant="primary" onClick={() => setEditing(true)}>{t('action.edit')}</Button>
          </>
        ) : (
          <>
            <div className="panel-title" style={{ marginBottom: 8 }}>{t('projects.linkedTasks')}</div>
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
          </>
        )}
      </Panel>
    </div>
  );
}

export function Projects() {
  const { t, focus, clearFocus } = useApp();
  const toast = useToast();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const s = useAsync(() => desktop.listProjects(), []);

  // Command-palette deep-link: when a project focus target arrives, open its
  // detail and consume the target so a later manual visit isn't hijacked.
  useEffect(() => {
    if (focus?.kind === 'project') {
      setSelectedId(focus.id);
      clearFocus();
    }
  }, [focus]);

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
                  <ProjectDetail
                    project={selected}
                    onClose={() => setSelectedId(null)}
                    onSaved={() => s.reload()}
                  />
                )}
              </>
            );
          }}
        </Async>
      </Panel>
    </>
  );
}
