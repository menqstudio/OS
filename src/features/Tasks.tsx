import { useState } from 'react';
import { useApp } from '../app/store';
import { PageHeader, Panel, Button, Badge, StatusPill, Avatar, EmptyState } from '../components/ui';
import { tasks } from '../data/mock';
import { statusTone, type TaskStatus } from '../domain/enums';

type Tab = { key: string; label: string; match: (s: TaskStatus) => boolean };

const TABS: Tab[] = [
  { key: 'inbox', label: 'Inbox', match: (s) => s === 'inbox' },
  { key: 'active', label: 'Active', match: (s) => s === 'active' || s === 'planned' },
  { key: 'blocked', label: 'Blocked', match: (s) => s === 'blocked' },
  { key: 'review', label: 'Review', match: (s) => s === 'review' },
  { key: 'done', label: 'Done', match: (s) => s === 'done' || s === 'cancelled' },
];

export function Tasks() {
  const { t } = useApp();
  const [tab, setTab] = useState<string>('inbox');
  const active = TABS.find((x) => x.key === tab) ?? TABS[0];
  const filtered = tasks.filter((x) => active.match(x.status));

  return (
    <>
      <PageHeader
        title={t('nav.tasks')}
        subtitle={t('tasks.subtitle')}
        actions={<Button variant="primary">{t('action.new')}</Button>}
      />

      <div className="row" style={{ gap: 8, marginBottom: 16 }}>
        {TABS.map((x) => (
          <Button key={x.key} small variant={x.key === tab ? 'primary' : 'ghost'} onClick={() => setTab(x.key)}>
            {x.label}
          </Button>
        ))}
      </div>

      <Panel title={active.label}>
        {filtered.length === 0 ? (
          <EmptyState title={t('state.empty')} hint={t('state.emptyHint')} />
        ) : (
          <div className="stack">
            {filtered.map((x) => (
              <div key={x.id} className="list-row">
                <span className="row" style={{ gap: 8 }}>
                  <Avatar name={x.assignee} />
                  <span>{x.title}</span>
                  {x.status === 'blocked' && x.blockedReason && (
                    <span className="muted">· {x.blockedReason}</span>
                  )}
                </span>
                <span className="row" style={{ gap: 8 }}>
                  <Badge tone={statusTone[x.priority] ?? 'neutral'}>{x.priority}</Badge>
                  {x.dueAt && <span className="muted">{x.dueAt}</span>}
                  <StatusPill status={x.status} />
                </span>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </>
  );
}
