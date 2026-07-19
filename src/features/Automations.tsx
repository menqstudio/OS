import { useState } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, Badge, Async, Modal, FormRow, Input,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';

function NewRuleForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { t } = useApp();
  const [name, setName] = useState('');
  const [trigger, setTrigger] = useState('');
  const [action, setAction] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    desktop
      .createAutomation({ name: name.trim(), trigger: trigger.trim(), action: action.trim() })
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
    <Modal title={t('automations.newRule')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <FormRow label={t('field.name')}>
        <Input value={name} autoFocus onChange={(e) => setName(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.trigger')}>
        <Input value={trigger} onChange={(e) => setTrigger(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.action')}>
        <Input value={action} onChange={(e) => setAction(e.target.value)} />
      </FormRow>
      <div className="form-actions">
        <Button type="button" variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button type="button" variant="primary" onClick={submit}>{t('action.create')}</Button>
      </div>
    </Modal>
  );
}

export function Automations() {
  const { t } = useApp();
  const [creating, setCreating] = useState(false);
  const s = useAsync(() => desktop.listAutomations(), []);

  const toggle = (id: string, enabled: boolean) => {
    desktop.setAutomationEnabled(id, enabled).then(() => s.reload()).catch(() => s.reload());
  };

  const remove = (id: string) => {
    desktop.deleteAutomation(id).then(() => s.reload()).catch(() => s.reload());
  };

  return (
    <>
      <PageHeader
        title={t('nav.automations')}
        subtitle={t('automations.subtitle')}
        actions={<Button type="button" variant="primary" onClick={() => setCreating(true)}>{t('action.new')}</Button>}
      />

      {creating && <NewRuleForm onClose={() => setCreating(false)} onCreated={() => s.reload()} />}

      <Panel title={t('nav.automations')}>
        <Async state={s} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
          {(items) => (
            <div className="stack">
              {items.map((a) => (
                <div key={a.id} className="list-row">
                  <span className="row" style={{ gap: 8 }}>
                    <Badge tone={a.enabled ? 'success' : 'neutral'}>{a.enabled ? t('automations.enabled') : '—'}</Badge>
                    <span>{a.name}</span>
                    <span className="muted">{a.trigger} → {a.action}</span>
                  </span>
                  <span className="row" style={{ gap: 8 }}>
                    <Button type="button" variant="ghost" onClick={() => toggle(a.id, !a.enabled)}>
                      {t(a.enabled ? 'automations.disable' : 'automations.enable')}
                    </Button>
                    <Button type="button" variant="ghost" onClick={() => remove(a.id)}>
                      {t('action.delete')}
                    </Button>
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
