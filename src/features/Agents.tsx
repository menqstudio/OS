import { useState } from 'react';
import { useApp } from '../app/store';
import { PageHeader, Button, Badge, StatusPill, Avatar } from '../components/ui';
import { agents } from '../data/mock';

export function Agents() {
  const { t } = useApp();
  const [paused, setPaused] = useState<Record<string, boolean>>({});

  return (
    <>
      <PageHeader title={t('nav.agents')} subtitle={t('agents.subtitle')} />

      <div className="grid grid-3">
        {agents.map((a) => {
          const isPaused = paused[a.id] ?? false;
          return (
            <div key={a.id} className="card">
              <div className="panel">
                <div className="between">
                  <span className="row" style={{ gap: 8 }}>
                    <Avatar name={a.name} />
                    <span>
                      <div className="panel-title">{a.name}</div>
                      <div className="muted">{a.role}</div>
                    </span>
                  </span>
                  <StatusPill status={isPaused ? 'paused' : a.status} />
                </div>

                <div className="muted" style={{ marginTop: 10 }}>{a.model}</div>

                <div className="row" style={{ marginTop: 10, gap: 6, flexWrap: 'wrap' }}>
                  {a.capabilities.map((c) => (
                    <Badge key={c} tone="info">{c}</Badge>
                  ))}
                </div>

                <div className="between" style={{ marginTop: 12 }}>
                  <span className="muted">{a.activeRuns} active runs</span>
                  <Button
                    small
                    variant={isPaused ? 'primary' : 'ghost'}
                    onClick={() => setPaused((prev) => ({ ...prev, [a.id]: !isPaused }))}
                  >
                    {isPaused ? 'Resume' : 'Pause'}
                  </Button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}
