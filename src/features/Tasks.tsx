import { useState } from 'react';
import { useApp } from '../app/store';
import { PageHeader, Panel, Button, Badge, StatusPill, Avatar, Async } from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { statusTone } from '../domain/enums';

type Tab = { key: string; label: string; status: string };

const TABS: Tab[] = [
  { key: 'inbox', label: 'Inbox', status: 'inbox' },
  { key: 'active', label: 'Active', status: 'active' },
  { key: 'blocked', label: 'Blocked', status: 'blocked' },
  { key: 'review', label: 'Review', status: 'review' },
  { key: 'done', label: 'Done', status: 'done' },
];

export function Tasks() {
  const { t } = useApp();
  const [tab, setTab] = useState<string>('inbox');
  const active = TABS.find((x) => x.key === tab) ?? TABS[0];
  const s = useAsync(() => desktop.listTasksByStatus(active.status), [active.status]);

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
        <Async state={s} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
          {(items) => (
            <div className="stack">
              {items.map((x) => (
                <div key={x.id} className="list-row">
                  <span className="row" style={{ gap: 8 }}>
                    <Avatar name={x.assignedAgentId ?? '—'} />
                    <span>{x.title}</span>
                    <span className="muted">{x.assignedAgentId ?? '—'}</span>
                  </span>
                  <span className="row" style={{ gap: 8 }}>
                    <Badge tone={statusTone[x.priority] ?? 'neutral'}>{x.priority}</Badge>
                    <span className="muted">{x.dueAt ?? '—'}</span>
                    <StatusPill status={x.status} />
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
