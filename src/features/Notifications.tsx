import { useState } from 'react';
import { useApp } from '../app/store';
import { PageHeader, Card, Button, StatusPill, EmptyState, Async } from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { desktop } from '../services/desktop';
import type { Notification } from '../domain/entities';

type TabId = 'unread' | 'all';

export function Notifications() {
  const { t } = useApp();
  const [tab, setTab] = useState<TabId>('unread');
  const state = useAsync<Notification[]>(() => desktop.listNotifications());

  const markRead = (id: string) => {
    desktop.markNotificationRead(id).then(() => state.reload()).catch(() => state.reload());
  };

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

      <Async state={state} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
        {(items) => {
          const visible = tab === 'unread' ? items.filter((n) => n.readAt === null) : items;

          if (visible.length === 0) {
            return <EmptyState title={t('state.empty')} hint={t('state.emptyHint')} glyph="✓" />;
          }

          return (
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
                    {n.readAt === null && (
                      <Button small variant="ghost" onClick={() => markRead(n.id)}>
                        Mark read
                      </Button>
                    )}
                  </div>
                </Card>
              ))}
            </div>
          );
        }}
      </Async>
    </>
  );
}
