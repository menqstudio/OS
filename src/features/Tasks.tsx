import { useState } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Button, Badge, Async, Modal, FormRow, Input, Textarea, Select,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { useToast } from '../components/toast';
import { statusTone, PRIORITIES } from '../domain/enums';
import type { Task } from '../domain/entities';

// Board columns, left to right — the full task status vocabulary so no task is
// ever invisible. Moving a card between columns sets its status.
const COLUMNS = ['inbox', 'planned', 'active', 'blocked', 'review', 'done', 'cancelled'];

function NewTaskForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { t } = useApp();
  const projects = useAsync(() => desktop.listProjects(), []);
  const [title, setTitle] = useState('');
  const [priority, setPriority] = useState('normal');
  const [projectId, setProjectId] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = () => {
    if (!title.trim() || busy) return;
    setBusy(true);
    setError(null);
    desktop
      .createTask({ title: title.trim(), description: '', priority, projectId: projectId || null, assignedAgentId: null })
      .then(() => { onCreated(); onClose(); })
      .catch((e: unknown) => { setError(e instanceof Error ? e.message : String(e)); setBusy(false); });
  };

  return (
    <Modal title={t('form.newTask')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <FormRow label={t('field.title')}>
        <Input value={title} autoFocus onChange={(e) => setTitle(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.priority')}>
        <Select value={priority} onChange={(e) => setPriority(e.target.value)}>
          {PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
        </Select>
      </FormRow>
      <FormRow label={t('field.project')}>
        <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
          <option value="">{t('field.none')}</option>
          {(projects.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </Select>
      </FormRow>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="primary" onClick={submit}>{t('action.create')}</Button>
      </div>
    </Modal>
  );
}

function TaskDetail({ task, onClose, onSaved }: { task: Task; onClose: () => void; onSaved: () => void }) {
  const { t } = useApp();
  const toast = useToast();
  const [title, setTitle] = useState(task.title);
  const [description, setDescription] = useState(task.description);
  const [priority, setPriority] = useState(task.priority);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const save = () => {
    if (!title.trim() || busy) return;
    setBusy(true);
    setError(null);
    desktop
      .updateTask(task.id, title.trim(), description, priority)
      .then(() => { toast(t('toast.saved'), 'success'); onSaved(); onClose(); })
      .catch((e: unknown) => { setError(e instanceof Error ? e.message : String(e)); setBusy(false); });
  };

  return (
    <Modal title={t('form.editTask')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <div className="row" style={{ gap: 8, marginBottom: 12 }}>
        <Badge tone={statusTone[task.status] ?? 'neutral'}>{task.status.replace(/_/g, ' ')}</Badge>
      </div>
      <FormRow label={t('field.title')}>
        <Input value={title} autoFocus onChange={(e) => setTitle(e.target.value)} />
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

export function Tasks() {
  const { t } = useApp();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [detail, setDetail] = useState<Task | null>(null);
  const [dragId, setDragId] = useState<string | null>(null);
  const [dragStatus, setDragStatus] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState<string | null>(null);
  const s = useAsync(() => desktop.listTasks(), []);

  const moveTo = (id: string, status: string) => {
    desktop.setTaskStatus(id, status).then(() => s.reload()).catch(() => s.reload());
  };
  const onDrop = (status: string) => {
    setDragOver(null);
    // Skip a drop onto the card's own column — no status change, no spurious write.
    if (dragId && dragStatus !== status) {
      moveTo(dragId, status);
    }
    setDragId(null);
    setDragStatus(null);
  };

  return (
    <>
      <PageHeader
        title={t('nav.tasks')}
        subtitle={t('tasks.subtitle')}
        actions={<Button variant="primary" onClick={() => setCreating(true)}>{t('action.new')}</Button>}
      />

      {creating && (
        <NewTaskForm
          onClose={() => setCreating(false)}
          onCreated={() => { s.reload(); toast(t('toast.created'), 'success'); }}
        />
      )}
      {detail && <TaskDetail task={detail} onClose={() => setDetail(null)} onSaved={() => s.reload()} />}

      <Async state={s} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
        {(tasks) => (
          <div className="board">
            {COLUMNS.map((col) => {
              const items = tasks.filter((x) => x.status === col);
              return (
                <div
                  key={col}
                  className={`board-col ${dragOver === col ? 'board-col--over' : ''}`}
                  onDragOver={(e) => { e.preventDefault(); setDragOver(col); }}
                  onDragLeave={() => setDragOver((c) => (c === col ? null : c))}
                  onDrop={() => onDrop(col)}
                >
                  <div className="board-col-head">
                    <span className="board-col-title">{col.replace(/_/g, ' ')}</span>
                    <span className="muted">{items.length}</span>
                  </div>
                  <div className="board-col-body">
                    {items.map((x) => (
                      <div
                        key={x.id}
                        className="board-card"
                        draggable
                        onDragStart={() => { setDragId(x.id); setDragStatus(x.status); }}
                        onDragEnd={() => { setDragId(null); setDragStatus(null); setDragOver(null); }}
                        onClick={() => setDetail(x)}
                      >
                        <div className="board-card-title">{x.title}</div>
                        <div className="row" style={{ gap: 6, marginTop: 6 }}>
                          <Badge tone={statusTone[x.priority] ?? 'neutral'}>{x.priority}</Badge>
                          {x.assignedAgentId && <span className="muted">{x.assignedAgentId}</span>}
                        </div>
                      </div>
                    ))}
                    {items.length === 0 && <div className="board-empty muted">—</div>}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Async>
    </>
  );
}
