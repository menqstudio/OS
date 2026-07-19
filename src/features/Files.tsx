import { useEffect, useState } from 'react';
import { useApp } from '../app/store';
import { PageHeader, Panel, Button, Badge, Skeleton, ErrorState, EmptyState, Modal, Textarea } from '../components/ui';
import { useToast } from '../components/toast';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import type { DirEntry } from '../domain/entities';

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let n = bytes / 1024;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(n < 10 ? 1 : 0)} ${units[i]}`;
}

/** View / edit a single text file. Mounts only while a file is selected, so
 *  the read happens on open and unmounts (discarding edits) on close. */
function FileViewer({ entry, onClose }: { entry: DirEntry; onClose: () => void }) {
  const { t } = useApp();
  const toast = useToast();
  const s = useAsync(() => desktop.readFile(entry.path), [entry.path]);
  const [content, setContent] = useState('');
  const [original, setOriginal] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (s.data) {
      setContent(s.data.content);
      setOriginal(s.data.content);
    }
  }, [s.data]);

  const editable = s.data != null && !s.data.readonly;
  const dirty = content !== original;

  async function save() {
    setSaving(true);
    setSaveError(null);
    try {
      await desktop.writeFile(entry.path, content);
      setOriginal(content);
      toast(t('files.saved'), 'success');
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={entry.name} onClose={onClose}>
      {s.loading && s.data === null && <Skeleton rows={6} />}
      {s.error && <ErrorState message={s.error} onRetry={s.reload} />}
      {s.data && !editable && (
        <div className="muted" style={{ marginBottom: 16 }}>{t('files.cantPreview')}</div>
      )}
      {editable && (
        <>
          <Textarea value={content} onChange={(ev) => setContent(ev.target.value)} rows={16} />
          {saveError && <div className="muted" style={{ marginTop: 8 }}>{saveError}</div>}
        </>
      )}
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('files.close')}</Button>
        {editable && (
          <Button onClick={save} disabled={saving || !dirty}>{t('files.save')}</Button>
        )}
      </div>
    </Modal>
  );
}

export function Files() {
  const { t } = useApp();
  // undefined path == home directory (resolved by the backend).
  const [path, setPath] = useState<string | undefined>(undefined);
  const [selected, setSelected] = useState<DirEntry | null>(null);
  const s = useAsync(() => desktop.listDir(path), [path]);

  return (
    <>
      <PageHeader title={t('nav.files')} subtitle={t('files.subtitle')} />

      <Panel
        title={s.data?.path ?? t('state.loading')}
        actions={
          <Button
            small
            variant="ghost"
            onClick={() => s.data?.parent && setPath(s.data.parent)}
            title={t('files.up')}
          >
            {t('files.up')}
          </Button>
        }
      >
        {s.loading && s.data === null && <Skeleton rows={6} />}
        {s.error && <ErrorState message={s.error} onRetry={s.reload} />}
        {s.data && s.data.entries.length === 0 && <EmptyState glyph="📁" title={t('files.empty')} />}
        {s.data && s.data.entries.length > 0 && (
          <div className="stack">
            {s.data.entries.map((e) => (
              <div
                key={e.path}
                className={`list-row ${e.isDir ? 'file-row--dir' : ''}`}
                style={{ cursor: 'pointer' }}
                onClick={() => (e.isDir ? setPath(e.path) : setSelected(e))}
              >
                <span className="row" style={{ gap: 8 }}>
                  <span>{e.isDir ? '📁' : '📄'}</span>
                  <span>{e.name}</span>
                </span>
                <span className="row" style={{ gap: 8 }}>
                  {e.isDir ? (
                    <Badge tone="neutral">{t('files.folder')}</Badge>
                  ) : (
                    <span className="muted">{formatSize(e.sizeBytes)}</span>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}
      </Panel>

      {selected && <FileViewer entry={selected} onClose={() => setSelected(null)} />}
    </>
  );
}
