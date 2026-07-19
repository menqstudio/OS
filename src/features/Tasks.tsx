import { useState } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, Badge, StatusPill, Avatar, Async, Modal, FormRow, Input, Select,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { useToast } from '../components/toast';
import { statusTone, TASK_STATUSES, PRIORITIES } from '../domain/enums';

type Tab = { key: string; label: string; status: string };

const TABS: Tab[] = [
  { key: 'inbox', label: 'Inbox', status: 'inbox' },
  { key: 'active', label: 'Active', status: 'active' },
  { key: 'blocked', label: 'Blocked', status: 'blocked' },
  { key: 'review', label: 'Review', status: 'review' },
  { key: 'done', label: 'Done', status: 'done' },
];

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
      .createTask({
        title: title.trim(),
        description: '',
        priority,
        projectId: projectId || null,
        assignedAgentId: null,
      })
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
    <Modal title={t('form.newTask')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <FormRow label={t('field.title')}>
        <Input value={title} autoFocus onChange={(e) => setTitle(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.priority')}>
        <Select value={priority} onChange={(e) => setPriority(e.target.value)}>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </Select>
      </FormRow>
      <FormRow label={t('field.project')}>
        <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
          <option value="">{t('field.none')}</option>
          {(projects.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
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

export function Tasks() {
  const { t } = useApp();
  const toast = useToast();
  const [tab, setTab] = useState<string>('inbox');
  const [creating, setCreating] = useState(false);
  const activeTab = TABS.find((x) => x.key === tab) ?? TABS[0];
  const s = useAsync(() => desktop.listTasksByStatus(activeTab.status), [activeTab.status]);

  const changeStatus = (id: string, status: string) => {
    desktop.setTaskStatus(id, status).then(() => s.reload()).catch(() => s.reload());
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

      <div className="row" style={{ gap: 8, marginBottom: 16 }}>
        {TABS.map((x) => (
          <Button key={x.key} small variant={x.key === tab ? 'primary' : 'ghost'} onClick={() => setTab(x.key)}>
            {x.label}
          </Button>
        ))}
      </div>

      <Panel title={activeTab.label}>
        <Async state={s} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
          {(items) => (
            <div className="stack">
              {items.map((x) => (
                <div key={x.id} className="list-row">
                  <span className="row" style={{ gap: 8 }}>
                    <Avatar name={x.assignedAgentId ?? '—'} />
                    <span>{x.title}</span>
                    <span className="muted">{x.assignedAgentId ?? '—'}</span>
                  </span>
                  <span className="row" style={{ gap: 8 }}>
                    <Badge tone={statusTone[x.priority] ?? 'neutral'}>{x.priority}</Badge>
                    <span className="muted">{x.dueAt ?? '—'}</span>
                    <Select
                      value={x.status}
                      onChange={(e) => changeStatus(x.id, e.target.value)}
                      style={{ width: 'auto', padding: '4px 8px' }}
                      title={t('field.status')}
                    >
                      {TASK_STATUSES.map((st) => (
                        <option key={st} value={st}>{st}</option>
                      ))}
                    </Select>
                  </span>
                </div>
              ))}
            </div>
          )}
        </Async>
      </Panel>
    </>
  );
}
