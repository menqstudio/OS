import { useState, type CSSProperties } from 'react';
import { useApp } from '../app/store';
import { PageHeader, Panel, Button, Avatar, StatusPill, EmptyState } from '../components/ui';
import { conversations, agents } from '../data/mock';
import type { Message } from '../domain/entities';

const inputStyle: CSSProperties = {
  flex: 1,
  background: 'var(--brops-surface)',
  color: 'var(--brops-text)',
  border: '1px solid var(--brops-border)',
  borderRadius: 'var(--menq-radius-md)',
  padding: '8px 12px',
  font: 'inherit',
  outline: 'none',
};

const bubbleStyle: CSSProperties = {
  maxWidth: '80%',
  padding: 'var(--menq-space-3) var(--menq-space-4)',
  borderRadius: 'var(--menq-radius-card)',
  border: '1px solid var(--brops-border)',
  background: 'var(--brops-surface)',
};

function memberName(id: string): string {
  const agent = agents.find((a) => a.slug === id);
  if (agent) return agent.name;
  if (id === 'gev') return 'You';
  return id.charAt(0).toUpperCase() + id.slice(1);
}

function senderLabel(m: Message): string {
  if (m.senderType === 'user') return 'You';
  return memberName(m.senderId);
}

export function GroupChat() {
  const { t } = useApp();
  const rooms = conversations.filter((c) => c.type === 'group' || c.type === 'direct');
  const [selectedId, setSelectedId] = useState(rooms[0]?.id ?? '');
  const [draft, setDraft] = useState('');

  const room = rooms.find((r) => r.id === selectedId) ?? rooms[0];

  return (
    <>
      <PageHeader title={t('nav.groupChat')} subtitle={t('groupChat.subtitle')} />

      <div className="grid" style={{ gridTemplateColumns: '260px 1fr' }}>
        <Panel title={t('nav.groupChat')}>
          <div className="stack">
            {rooms.map((r) => (
              <button
                key={r.id}
                className={`nav-item ${r.id === room.id ? 'active' : ''}`}
                onClick={() => setSelectedId(r.id)}
              >
                <span className="row" style={{ justifyContent: 'space-between', width: '100%' }}>
                  <span>{r.title}</span>
                  <span className="muted" style={{ fontSize: 11 }}>{r.members.length}</span>
                </span>
              </button>
            ))}
          </div>
        </Panel>

        <div className="stack">
          <Panel title={room.title}>
            {room.messages.length === 0 ? (
              <EmptyState title={t('state.empty')} hint={t('state.emptyHint')} />
            ) : (
              <div className="stack" style={{ gap: 'var(--menq-space-4)' }}>
                {room.messages.map((m) => (
                  <div key={m.id} className="row" style={{ alignItems: 'flex-start' }}>
                    <Avatar name={senderLabel(m)} />
                    <div style={bubbleStyle}>
                      <div className="row between" style={{ gap: 'var(--menq-space-3)', marginBottom: 4 }}>
                        <span style={{ fontWeight: 600, fontSize: 13 }}>{senderLabel(m)}</span>
                        <span className="muted" style={{ fontSize: 11 }}>{m.createdAt}</span>
                      </div>
                      <div>{m.content}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="row" style={{ marginTop: 'var(--menq-space-2)' }}>
              <input
                style={inputStyle}
                placeholder={t('chat.composer')}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
              />
              <Button variant="primary" onClick={() => setDraft('')}>{t('action.send')}</Button>
            </div>
          </Panel>

          <Panel title="Members">
            <div className="stack">
              {room.members.map((id) => {
                const agent = agents.find((a) => a.slug === id);
                return (
                  <div key={id} className="list-row">
                    <span className="row">
                      <Avatar name={memberName(id)} />
                      <span>{memberName(id)}</span>
                      {agent && <span className="muted">· {agent.role}</span>}
                    </span>
                    {agent && <StatusPill status={agent.status} />}
                  </div>
                );
              })}
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}
