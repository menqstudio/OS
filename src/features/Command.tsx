import { useState, type CSSProperties } from 'react';
import { useApp } from '../app/store';
import { PageHeader, Panel, Button, StatusPill, Badge } from '../components/ui';
import { commandRuns } from '../data/mock';

const inputStyle: CSSProperties = {
  width: '100%',
  resize: 'vertical',
  background: 'var(--brops-surface)',
  color: 'var(--brops-text)',
  border: '1px solid var(--brops-border)',
  borderRadius: 'var(--menq-radius-md)',
  padding: 'var(--menq-space-3)',
  font: 'inherit',
  outline: 'none',
};

export function Command() {
  const { t } = useApp();
  const [draft, setDraft] = useState('');
  const latest = commandRuns[0];

  return (
    <>
      <PageHeader title={t('nav.command')} subtitle={t('command.subtitle')} />

      <Panel
        title={t('home.askBro')}
        actions={<Button variant="primary" onClick={() => setDraft('')}>{t('action.ask')}</Button>}
      >
        <textarea
          style={inputStyle}
          rows={3}
          placeholder={t('command.placeholder')}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
      </Panel>

      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <Panel title={t('command.plan')}>
          <div className="stack">
            {latest.plan.map((step, i) => (
              <div key={i} className="list-row">
                <span className="row">
                  <span className="avatar">{i + 1}</span>
                  <span>{step}</span>
                </span>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title={t('home.activeRuns')}>
          <div className="stack">
            {commandRuns.map((r) => (
              <div key={r.id} className="list-row">
                <span className="row">
                  <span>{r.commandText}</span>
                  {r.status === 'awaiting_approval' && <Badge tone="warning">Approval gate</Badge>}
                </span>
                <StatusPill status={r.status} />
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </>
  );
}
