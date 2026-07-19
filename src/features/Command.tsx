import { useState } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, StatusPill, Async, Modal, FormRow, Input, Textarea, Select,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { Markdown } from '../components/markdown';
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
  const [executing, setExecuting] = useState(false);
  const [stepStream, setStepStream] = useState('');
  const [execError, setExecError] = useState<string | null>(null);

  const advance = () => {
    desktop.advanceRun(run.id).then(() => { steps.reload(); onChanged(); }).catch(() => steps.reload());
  };
  const addStep = () => {
    const trimmed = title.trim();
    if (!trimmed) return;
    desktop.addRunStep(run.id, trimmed, '').then(() => { setTitle(''); steps.reload(); }).catch(() => steps.reload());
  };
  const execute = async () => {
    if (executing) return;
    setExecuting(true);
    setStepStream('');
    setExecError(null);
    try {
      await desktop.streamRunStep(run.id, (ev) => {
        if (ev.type === 'delta') setStepStream((prev) => prev + ev.text);
        else if (ev.type === 'error') setExecError(ev.message);
      });
    } catch (e: unknown) {
      setExecError(e instanceof Error ? e.message : String(e));
    } finally {
      setExecuting(false);
      setStepStream('');
      steps.reload();
      onChanged();
    }
  };

  const terminal = run.status === 'succeeded' || run.status === 'failed' || run.status === 'cancelled';

  return (
    <div style={{ marginTop: 16 }}>
      <Panel
        title={run.intent}
        actions={
          <span className="row" style={{ gap: 8 }}>
            <Button small variant="ghost" onClick={advance} disabled={executing || terminal}>{t('command.advance')}</Button>
            <Button small variant="primary" onClick={execute} disabled={executing || terminal}>{t('command.execute')}</Button>
          </span>
        }
      >
        <div className="row" style={{ gap: 8, marginBottom: 12 }}>
          <StatusPill status={run.status} />
        </div>
        {executing && (
          <div className="run-step-result" style={{ marginBottom: 12 }}>
            {stepStream
              ? <span>{stepStream}<span className="chat-cursor" /></span>
              : <span className="chat-typing"><span></span><span></span><span></span></span>}
          </div>
        )}
        <div className="panel-title" style={{ marginBottom: 8 }}>{t('command.steps')}</div>
        <Async state={steps} emptyTitle={t('command.noSteps')}>
          {(items) => (
            <div className="stack">
              {items.map((s) => (
                <div key={s.id} className="run-step">
                  <div className="list-row">
                    <span className="row" style={{ gap: 8 }}>
                      <span className="muted">{s.position}.</span>
                      <span>{s.title}</span>
                      {s.detail && <span className="muted">{s.detail}</span>}
                    </span>
                    <StatusPill status={s.status} />
                  </div>
                  {s.result && (
                    <div className="run-step-result"><Markdown text={s.result} /></div>
                  )}
                </div>
              ))}
            </div>
          )}
        </Async>
        {execError && <div className="chat-hint" style={{ marginTop: 8 }}>⚠ {execError}</div>}
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
                {selected && <RunDetail key={selected.id} run={selected} onChanged={() => s.reload()} />}
              </>
            );
          }}
        </Async>
      </Panel>
    </>
  );
}
