import { useEffect, useRef, useState } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, Badge, Async, Modal, FormRow, Input, Textarea, ConfirmDialog,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';

function NewNoteForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { t } = useApp();
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [source, setSource] = useState('');
  const [tags, setTags] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = () => {
    if (!title.trim() || busy) return;
    setBusy(true);
    setError(null);
    desktop
      .createKnowledge({ title: title.trim(), body: body.trim(), source: source.trim(), tags: tags.trim() })
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
    <Modal title={t('knowledge.newNote')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <FormRow label={t('field.title')}>
        <Input value={title} autoFocus onChange={(e) => setTitle(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.description')}>
        <Textarea value={body} onChange={(e) => setBody(e.target.value)} />
      </FormRow>
      <FormRow label={t('knowledge.source')}>
        <Input value={source} onChange={(e) => setSource(e.target.value)} />
      </FormRow>
      <FormRow label={t('knowledge.tags')}>
        <Input value={tags} placeholder="architecture, sqlite" onChange={(e) => setTags(e.target.value)} />
      </FormRow>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="primary" onClick={submit}>{t('action.create')}</Button>
      </div>
    </Modal>
  );
}

export function Knowledge() {
  const { t, focus, clearFocus } = useApp();
  const [query, setQuery] = useState('');
  const [creating, setCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const s = useAsync(() => desktop.searchKnowledge(query), [query]);

  // Deep-link consumer: when a `knowledge` focus is pending, select and scroll
  // to the matching note once the list has loaded. Clear focus only after we
  // resolve it — if the note is present we highlight it; if it is genuinely
  // absent from a fully-loaded list we still clear focus to avoid a stuck state.
  useEffect(() => {
    if (focus?.kind !== 'knowledge' || s.loading || !s.data) return;
    const target = s.data.find((n) => n.id === focus.id);
    if (target) {
      setSelectedId(target.id);
      rowRefs.current[target.id]?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
    clearFocus();
  }, [focus, s.data, s.loading, clearFocus]);

  const remove = (id: string) => {
    setPendingDelete(null);
    desktop.deleteKnowledge(id).then(() => s.reload()).catch(() => s.reload());
  };

  return (
    <>
      <PageHeader
        title={t('nav.knowledge')}
        subtitle={t('knowledge.subtitle')}
        actions={<Button variant="primary" onClick={() => setCreating(true)}>{t('action.new')}</Button>}
      />

      {creating && <NewNoteForm onClose={() => setCreating(false)} onCreated={() => s.reload()} />}

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

      <div style={{ marginBottom: 16 }}>
        <Input
          value={query}
          placeholder={t('knowledge.search')}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      <Panel>
        <Async state={s} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
          {(notes) => (
            <div className="stack">
              {notes.map((n) => (
                <div
                  key={n.id}
                  ref={(el) => { rowRefs.current[n.id] = el; }}
                  className={`card ${selectedId === n.id ? 'card--focused' : ''}`}
                  style={selectedId === n.id ? { outline: '2px solid var(--brops-accent)', borderRadius: 8 } : undefined}
                >
                  <div className="panel">
                    <div className="between">
                      <div className="panel-title">{n.title}</div>
                      <Button small variant="ghost" disabled title={t('action.deleteDisabledSafety')} onClick={() => setPendingDelete(n.id)}>{t('action.delete')}</Button>
                    </div>
                    {n.body && <div className="muted" style={{ marginTop: 6 }}>{n.body}</div>}
                    <div className="row" style={{ marginTop: 10, gap: 8, flexWrap: 'wrap' }}>
                      {n.source && <Badge tone="info">{n.source}</Badge>}
                      {n.tags
                        .split(',')
                        .map((x) => x.trim())
                        .filter(Boolean)
                        .map((tag) => (
                          <Badge key={tag} tone="neutral">#{tag}</Badge>
                        ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Async>
      </Panel>
    </>
  );
}
