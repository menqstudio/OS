import { useState } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, StatusPill, Async, Modal, FormRow, Input, Textarea, Select,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { RUN_STATUSES } from '../domain/enums';
import type { Run } from '../domain/entities';

function NewRunForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { t } = useApp();
  const [intent, setIntent] = useState('');
  const [plan, setPlan] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = () => {
    if (!intent.trim() || busy) return;
    setBusy(true);
    setError(null);
    desktop
      .createRun(intent.trim(), plan.trim())
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
    <Modal title={t('command.newRun')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <FormRow label={t('field.intent')}>
        <Input value={intent} autoFocus onChange={(e) => setIntent(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.plan')}>
        <Textarea value={plan} onChange={(e) => setPlan(e.target.value)} />
      </FormRow>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="primary" onClick={submit}>{t('action.create')}</Button>
      </div>
    </Modal>
  );
}

function RunDetail({ run, onChanged }: { run: Run; onChanged: () => void }) {
  const { t } = useApp();
  const steps = useAsync(() => desktop.listRunSteps(run.id), [run.id]);
  const [title, setTitle] = useState('');

  const advance = () => {
    desktop.advanceRun(run.id).then(() => { steps.reload(); onChanged(); }).catch(() => steps.reload());
  };
  const addStep = () => {
    const trimmed = title.trim();
    if (!trimmed) return;
    desktop.addRunStep(run.id, trimmed, '').then(() => { setTitle(''); steps.reload(); }).catch(() => steps.reload());
  };

  return (
    <div style={{ marginTop: 16 }}>
      <Panel
        title={run.intent}
        actions={<Button small variant="primary" onClick={advance}>{t('command.advance')}</Button>}
      >
        <div className="row" style={{ gap: 8, marginBottom: 12 }}>
          <StatusPill status={run.status} />
        </div>
        <div className="panel-title" style={{ marginBottom: 8 }}>{t('command.steps')}</div>
        <Async state={steps} emptyTitle={t('command.noSteps')}>
          {(items) => (
            <div className="stack">
              {items.map((s) => (
                <div key={s.id} className="list-row">
                  <span className="row" style={{ gap: 8 }}>
                    <span className="muted">{s.position}.</span>
                    <span>{s.title}</span>
                    {s.detail && <span className="muted">{s.detail}</span>}
                  </span>
                  <StatusPill status={s.status} />
                </div>
              ))}
            </div>
          )}
        </Async>
        <form
          className="chat-composer"
          style={{ marginTop: 12 }}
          onSubmit={(e) => { e.preventDefault(); addStep(); }}
        >
          <Input value={title} placeholder={t('command.addStep')} onChange={(e) => setTitle(e.target.value)} />
          <Button type="submit" variant="ghost">{t('command.addStep')}</Button>
        </form>
      </Panel>
    </div>
  );
}

export function Command() {
  const { t } = useApp();
  const [creating, setCreating] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const s = useAsync(() => desktop.listRuns(), []);

  const changeStatus = (id: string, status: string) => {
    desktop.setRunStatus(id, status).then(() => s.reload()).catch(() => s.reload());
  };

  return (
    <>
      <PageHeader
        title={t('nav.command')}
        subtitle={t('command.subtitle')}
        actions={<Button variant="primary" onClick={() => setCreating(true)}>{t('action.new')}</Button>}
      />

      {creating && <NewRunForm onClose={() => setCreating(false)} onCreated={() => s.reload()} />}

      <Panel title={t('command.runs')}>
        <Async state={s} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
          {(runs) => {
            const selected = runs.find((r) => r.id === selectedId) ?? null;
            return (
              <>
                <div className="stack">
                  {runs.map((r) => (
                    <div
                      key={r.id}
                      className="list-row"
                      style={{ cursor: 'pointer', outline: selectedId === r.id ? '2px solid var(--brops-accent)' : 'none' }}
                      onClick={() => setSelectedId(r.id)}
                    >
                      <span className="row" style={{ gap: 8 }}>
                        <StatusPill status={r.status} />
                        <span>{r.intent}</span>
                      </span>
                      <Select
                        value={r.status}
                        onClick={(e) => e.stopPropagation()}
                        onChange={(e) => changeStatus(r.id, e.target.value)}
                        style={{ width: 'auto', padding: '4px 8px' }}
                        title={t('field.status')}
                      >
                        {RUN_STATUSES.map((st) => (
                          <option key={st} value={st}>{st}</option>
                        ))}
                      </Select>
                    </div>
                  ))}
                </div>
                {selected && <RunDetail run={selected} onChanged={() => s.reload()} />}
              </>
            );
          }}
        </Async>
      </Panel>
    </>
  );
}
