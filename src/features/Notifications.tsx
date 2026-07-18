import { useState } from 'react';
import { useApp } from '../app/store';
import { PageHeader, Card, Button, StatusPill, EmptyState } from '../components/ui';
import { notifications } from '../data/mock';

type TabId = 'unread' | 'all';

export function Notifications() {
  const { t } = useApp();
  const [tab, setTab] = useState<TabId>('unread');
  const [readIds, setReadIds] = useState<Record<string, boolean>>({});

  const markRead = (id: string) => setReadIds((prev) => ({ ...prev, [id]: true }));

  const items = notifications.map((n) => ({ ...n, read: n.read || !!readIds[n.id] }));
  const visible = tab === 'unread' ? items.filter((n) => !n.read) : items;

  return (
    <>
      <PageHeader title={t('nav.notifications')} subtitle={t('notifications.subtitle')} />

      <div className="row" style={{ marginBottom: 16 }}>
        <Button variant={tab === 'unread' ? 'primary' : 'ghost'} small onClick={() => setTab('unread')}>
          Unread
        </Button>
        <Button variant={tab === 'all' ? 'primary' : 'ghost'} small onClick={() => setTab('all')}>
          All
        </Button>
      </div>

      {visible.length === 0 ? (
        <EmptyState title={t('state.empty')} hint={t('state.emptyHint')} glyph="✓" />
      ) : (
        <div className="stack">
          {visible.map((n) => (
            <Card key={n.id}>
              <div className="between row">
                <div className="stack" style={{ gap: 4 }}>
                  <div className="row">
                    <StatusPill status={n.severity} />
                    <span style={{ fontWeight: 600 }}>{n.title}</span>
                  </div>
                  <div className="muted">{n.body}</div>
                  <div className="muted" style={{ fontSize: 12 }}>{n.createdAt}</div>
                </div>
                {!n.read && (
                  <Button small variant="ghost" onClick={() => markRead(n.id)}>
                    Mark read
                  </Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
