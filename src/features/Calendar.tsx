import { useState } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, Badge, Async, Modal, FormRow, Input,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { statusTone } from '../domain/enums';

function NewEventForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { t } = useApp();
  const [title, setTitle] = useState('');
  const [kind, setKind] = useState('event');
  const [location, setLocation] = useState('');
  const [when, setWhen] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = () => {
    if (!title.trim() || busy) return;
    setBusy(true);
    setError(null);
    desktop
      .createEvent({
        title: title.trim(),
        kind: kind.trim() || 'event',
        location: location.trim(),
        startsAt: when.trim(),
        endsAt: null,
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
    <Modal title={t('calendar.newEvent')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <FormRow label={t('field.title')}>
        <Input value={title} autoFocus onChange={(e) => setTitle(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.kind')}>
        <Input value={kind} onChange={(e) => setKind(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.location')}>
        <Input value={location} onChange={(e) => setLocation(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.when')}>
        <Input value={when} onChange={(e) => setWhen(e.target.value)} />
      </FormRow>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="primary" onClick={submit}>{t('action.create')}</Button>
      </div>
    </Modal>
  );
}

export function Calendar() {
  const { t } = useApp();
  const [creating, setCreating] = useState(false);
  const s = useAsync(() => desktop.listEvents(), []);

  const remove = (id: string) => {
    desktop.deleteEvent(id).then(() => s.reload()).catch(() => s.reload());
  };

  return (
    <>
      <PageHeader
        title={t('nav.calendar')}
        subtitle={t('calendar.subtitle')}
        actions={<Button variant="primary" onClick={() => setCreating(true)}>{t('action.new')}</Button>}
      />

      {creating && <NewEventForm onClose={() => setCreating(false)} onCreated={() => s.reload()} />}

      <Panel title={t('nav.calendar')}>
        <Async state={s} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
          {(items) => (
            <div className="stack">
              {items.map((e) => (
                <div key={e.id} className="list-row">
                  <span className="row" style={{ gap: 8 }}>
                    <Badge tone={statusTone[e.kind] ?? 'accent'}>{e.kind}</Badge>
                    <span>{e.title}</span>
                  </span>
                  <span className="row" style={{ gap: 8 }}>
                    <span className="muted">{e.location || '—'}</span>
                    <span className="muted">{e.startsAt}</span>
                    <Button variant="ghost" onClick={() => remove(e.id)}>{t('action.delete')}</Button>
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
