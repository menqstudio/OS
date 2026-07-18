import { useApp } from '../app/store';
import { PageHeader, Panel, Button, StatusPill, Avatar, Badge } from '../components/ui';
import { tasks, commandRuns, approvals, agents } from '../data/mock';

export function Home() {
  const { t, setRoute } = useApp();
  const priorities = tasks.filter((x) => x.status !== 'done' && x.status !== 'cancelled').slice(0, 4);
  const runs = commandRuns;
  const pending = approvals.filter((a) => a.status === 'pending');
  const active = agents.filter((a) => a.activeRuns > 0 || a.status === 'working' || a.status === 'thinking');

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
          <div className="stack">
            {priorities.map((x) => (
              <div key={x.id} className="list-row">
                <span>{x.title}</span>
                <StatusPill status={x.status} />
              </div>
            ))}
          </div>
        </Panel>

        <Panel title={t('home.approvals')} actions={<Button small variant="ghost" onClick={() => setRoute('approvals')}>{t('action.viewAll')}</Button>}>
          <div className="stack">
            {pending.map((a) => (
              <div key={a.id} className="list-row">
                <span>{a.action}</span>
                <Badge tone="warning">{a.level}</Badge>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title={t('home.activeRuns')} actions={<Button small variant="ghost" onClick={() => setRoute('command')}>{t('action.viewAll')}</Button>}>
          <div className="stack">
            {runs.map((r) => (
              <div key={r.id} className="list-row">
                <span>{r.commandText}</span>
                <StatusPill status={r.status} />
              </div>
            ))}
          </div>
        </Panel>

        <Panel title={t('home.agents')} actions={<Button small variant="ghost" onClick={() => setRoute('agents')}>{t('action.viewAll')}</Button>}>
          <div className="stack">
            {active.map((a) => (
              <div key={a.id} className="list-row">
                <span className="row"><Avatar name={a.name} />{a.name} · <span className="muted">{a.role}</span></span>
                <StatusPill status={a.status} />
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </>
  );
}
