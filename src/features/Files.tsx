import { useState } from 'react';
import { useApp } from '../app/store';
import { PageHeader, Panel, Button, Badge, Skeleton, ErrorState, EmptyState } from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';

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

export function Files() {
  const { t } = useApp();
  // undefined path == home directory (resolved by the backend).
  const [path, setPath] = useState<string | undefined>(undefined);
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
                style={{ cursor: e.isDir ? 'pointer' : 'default' }}
                onClick={() => e.isDir && setPath(e.path)}
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
    </>
  );
}
