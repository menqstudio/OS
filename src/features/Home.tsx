import { useApp } from '../app/store';
import { PageHeader, Panel, Button, StatusPill, Avatar, Badge, Async } from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';

export function Home() {
  const { t, setRoute } = useApp();
  const active = useAsync(() => desktop.listTasksByStatus('active'), []);
  const approvals = useAsync(
    () => desktop.listApprovals().then((rows) => rows.filter((a) => a.status === 'pending')),
    [],
  );
  const agents = useAsync(() => desktop.listAgents(), []);
  const projects = useAsync(() => desktop.listProjects(), []);

  return (
    <>
      <PageHeader title={t('nav.home')} subtitle={t('home.subtitle')} />

      <Panel title={t('home.askBro')} actions={<Button variant="primary" onClick={() => setRoute('command')}>{t('action.ask')}</Button>}>
        <div className="searchbtn" style={{ maxWidth: 'none', cursor: 'text' }} onClick={() => setRoute('command')}>
          <span>⌘</span><span>{t('command.placeholder')}</span>
        </div>
      </Panel>

      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <Panel title={t('home.priorities')} actions={<Button small variant="ghost" onClick={() => setRoute('tasks')}>{t('action.viewAll')}</Button>}>
          <Async state={active} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
            {(items) => (
              <div className="stack">
                {items.map((x) => (
                  <div key={x.id} className="list-row">
                    <span>{x.title}</span>
                    <StatusPill status={x.status} />
                  </div>
                ))}
              </div>
            )}
          </Async>
        </Panel>

        <Panel title={t('home.approvals')} actions={<Button small variant="ghost" onClick={() => setRoute('approvals')}>{t('action.viewAll')}</Button>}>
          <Async state={approvals} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
            {(items) => (
              <div className="stack">
                {items.map((a) => (
                  <div key={a.id} className="list-row">
                    <span>{a.actionType}</span>
                    <Badge tone="warning">{a.level}</Badge>
                  </div>
                ))}
              </div>
            )}
          </Async>
        </Panel>

        <Panel title={t('home.agents')} actions={<Button small variant="ghost" onClick={() => setRoute('agents')}>{t('action.viewAll')}</Button>}>
          <Async state={agents} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
            {(items) => (
              <div className="stack">
                {items.map((a) => (
                  <div key={a.id} className="list-row">
                    <span className="row"><Avatar name={a.displayName} />{a.displayName} · <span className="muted">{a.role}</span></span>
                    <StatusPill status={a.status} />
                  </div>
                ))}
              </div>
            )}
          </Async>
        </Panel>

        <Panel title={t('nav.projects')} actions={<Button small variant="ghost" onClick={() => setRoute('projects')}>{t('action.viewAll')}</Button>}>
          <Async state={projects} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
            {(items) => (
              <div className="stack">
                {items.map((p) => (
                  <div key={p.id} className="list-row">
                    <span>{p.name}</span>
                    <StatusPill status={p.status} />
                  </div>
                ))}
              </div>
            )}
          </Async>
        </Panel>
      </div>
    </>
  );
}
