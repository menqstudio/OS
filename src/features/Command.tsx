import { useState } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, StatusPill, Async, Modal, FormRow, Input, Textarea, Select,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { RUN_STATUSES } from '../domain/enums';

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

export function Command() {
  const { t } = useApp();
  const [creating, setCreating] = useState(false);
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
          {(runs) => (
            <div className="stack">
              {runs.map((r) => (
                <div key={r.id} className="list-row">
                  <span className="row" style={{ gap: 8 }}>
                    <StatusPill status={r.status} />
                    <span>{r.intent}</span>
                  </span>
                  <Select
                    value={r.status}
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
          )}
        </Async>
      </Panel>
    </>
  );
}
