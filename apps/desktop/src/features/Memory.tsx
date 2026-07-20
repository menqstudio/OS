import { useState } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, Badge, Async, Modal, FormRow, Input, Textarea, Select, ConfirmDialog,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { MEMORY_KINDS, statusTone } from '../domain/enums';

function NewEntryForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { t } = useApp();
  const [scope, setScope] = useState('global');
  const [kind, setKind] = useState('note');
  const [content, setContent] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = () => {
    if (!content.trim() || busy) return;
    setBusy(true);
    setError(null);
    desktop
      .createMemory({ scope: scope.trim() || 'global', kind, content: content.trim() })
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
    <Modal title={t('memory.newEntry')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <FormRow label={t('memory.content')}>
        <Textarea value={content} autoFocus onChange={(e) => setContent(e.target.value)} />
      </FormRow>
      <FormRow label={t('memory.kind')}>
        <Select value={kind} onChange={(e) => setKind(e.target.value)}>
          {MEMORY_KINDS.map((k) => (
            <option key={k} value={k}>{k}</option>
          ))}
        </Select>
      </FormRow>
      <FormRow label={t('memory.scope')}>
        <Input value={scope} onChange={(e) => setScope(e.target.value)} />
      </FormRow>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="primary" onClick={submit}>{t('action.create')}</Button>
      </div>
    </Modal>
  );
}

export function Memory() {
  const { t } = useApp();
  const [creating, setCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const s = useAsync(() => desktop.listMemory(), []);

  const togglePin = (id: string, pinned: boolean) => {
    desktop.setMemoryPinned(id, pinned).then(() => s.reload()).catch(() => s.reload());
  };
  const remove = (id: string) => {
    setPendingDelete(null);
    desktop.deleteMemory(id).then(() => s.reload()).catch(() => s.reload());
  };

  return (
    <>
      <PageHeader
        title={t('nav.memory')}
        subtitle={t('memory.subtitle')}
        actions={<Button variant="primary" onClick={() => setCreating(true)}>{t('action.new')}</Button>}
      />

      {creating && <NewEntryForm onClose={() => setCreating(false)} onCreated={() => s.reload()} />}

      {pendingDelete && (
        <ConfirmDialog
          title={t('confirm.deleteTitle')}
          message={t('confirm.deleteBody')}
          confirmLabel={t('action.delete')}
          cancelLabel={t('action.cancel')}
          onConfirm={() => remove(pendingDelete)}
          onCancel={() => setPendingDelete(null)}
        />
      )}

      <Panel>
        <Async state={s} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
          {(entries) => (
            <div className="stack">
              {entries.map((m) => (
                <div key={m.id} className="list-row">
                  <span className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                    <Badge tone={statusTone[m.kind] ?? 'accent'}>{m.kind}</Badge>
                    <span className="muted">{m.scope}</span>
                    <span>{m.content}</span>
                    {m.pinned && <Badge tone="warning">{t('memory.pinned')}</Badge>}
                  </span>
                  <span className="row" style={{ gap: 8 }}>
                    <Button small variant="ghost" onClick={() => togglePin(m.id, !m.pinned)}>
                      {m.pinned ? t('memory.unpin') : t('memory.pin')}
                    </Button>
                    <Button small variant="ghost" onClick={() => setPendingDelete(m.id)}>{t('action.delete')}</Button>
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
