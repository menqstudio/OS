import { useState, type CSSProperties } from 'react';
import { useApp } from '../app/store';
import { PageHeader, Panel, Button, Avatar } from '../components/ui';
import { conversations } from '../data/mock';
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
  maxWidth: '72%',
  padding: 'var(--menq-space-3) var(--menq-space-4)',
  borderRadius: 'var(--menq-radius-card)',
  border: '1px solid var(--brops-border)',
};

function senderLabel(m: Message): string {
  if (m.senderType === 'user') return 'You';
  if (m.senderId === 'bro') return 'Bro';
  return m.senderId.charAt(0).toUpperCase() + m.senderId.slice(1);
}

export function Chat() {
  const { t } = useApp();
  const direct = conversations.find((c) => c.type === 'direct') ?? conversations[0];
  const [messages, setMessages] = useState<Message[]>(direct.messages);
  const [draft, setDraft] = useState('');

  function send() {
    const text = draft.trim();
    if (!text) return;
    const now = new Date();
    const stamp = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
    setMessages((prev) => [
      ...prev,
      { id: `local-${prev.length}`, senderType: 'user', senderId: 'gev', role: 'user', content: text, createdAt: stamp },
    ]);
    setDraft('');
  }

  return (
    <>
      <PageHeader title={t('nav.chat')} subtitle={t('chat.subtitle')} />

      <Panel title={direct.title}>
        <div className="stack" style={{ gap: 'var(--menq-space-4)' }}>
          {messages.map((m) => {
            const mine = m.senderType === 'user';
            return (
              <div
                key={m.id}
                className="row"
                style={{ alignItems: 'flex-start', flexDirection: mine ? 'row-reverse' : 'row' }}
              >
                <Avatar name={senderLabel(m)} />
                <div style={{ ...bubbleStyle, background: mine ? 'var(--menq-color-selected)' : 'var(--brops-surface)' }}>
                  <div className="row between" style={{ gap: 'var(--menq-space-3)', marginBottom: 4 }}>
                    <span style={{ fontWeight: 600, fontSize: 13 }}>{senderLabel(m)}</span>
                    <span className="muted" style={{ fontSize: 11 }}>{m.createdAt}</span>
                  </div>
                  <div>{m.content}</div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="row" style={{ marginTop: 'var(--menq-space-2)' }}>
          <input
            style={inputStyle}
            placeholder={t('chat.composer')}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') send(); }}
          />
          <Button variant="primary" onClick={send}>{t('action.send')}</Button>
        </div>
      </Panel>
    </>
  );
}
