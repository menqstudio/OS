import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, Badge, Async,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { statusTone } from '../domain/enums';

export function Integrations() {
  const { t } = useApp();
  const s = useAsync(() => desktop.listIntegrations(), []);

  const changeStatus = (id: string, status: string) => {
    desktop.setIntegrationStatus(id, status).then(() => s.reload()).catch(() => s.reload());
  };

  return (
    <>
      <PageHeader
        title={t('nav.integrations')}
        subtitle={t('integrations.subtitle')}
      />

      <Panel>
        <Async state={s} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
          {(items) => (
            <div className="stack">
              {items.map((i) => (
                <div key={i.id} className="list-row">
                  <span className="row" style={{ gap: 8 }}>
                    <span className="panel-title">{i.name}</span>
                    <span className="muted">{i.provider}</span>
                  </span>
                  <span className="row" style={{ gap: 8 }}>
                    <Badge tone={statusTone[i.status] ?? 'neutral'}>{i.status}</Badge>
                    {i.status === 'connected' ? (
                      <Button
                        type="button"
                        variant="ghost"
                        onClick={() => changeStatus(i.id, 'disconnected')}
                      >
                        {t('integrations.disconnect')}
                      </Button>
                    ) : (
                      <Button
                        type="button"
                        variant="primary"
                        onClick={() => changeStatus(i.id, 'connected')}
                      >
                        {t('integrations.connect')}
                      </Button>
                    )}
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
