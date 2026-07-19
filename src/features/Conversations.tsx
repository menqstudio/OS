import { useState } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, Async, EmptyState, Avatar, Modal, FormRow, Input,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import type { Conversation } from '../domain/entities';

type Kind = 'direct' | 'group';

function MessageThread({ conversation, onActivity }: { conversation: Conversation; onActivity: () => void }) {
  const { t } = useApp();
  const s = useAsync(() => desktop.listMessages(conversation.id), [conversation.id]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = () => {
    const body = draft.trim();
    if (!body || busy) return;
    setBusy(true);
    setError(null);
    desktop
      .postMessage({ conversationId: conversation.id, role: 'user', author: t('chat.you'), body })
      .then(() => {
        setDraft('');
        setBusy(false);
        s.reload();
        onActivity();
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
        setBusy(false);
      });
  };

  return (
    <Panel title={conversation.title}>
      <div className="chat-thread">
        <Async state={s} emptyTitle={t('chat.noMessages')} emptyHint={t('chat.noMessagesHint')}>
          {(messages) => (
            <div className="stack">
              {messages.map((m) => (
                <div key={m.id} className={`chat-msg chat-msg--${m.role === 'user' ? 'mine' : 'other'}`}>
                  <Avatar name={m.author} />
                  <div className="chat-bubble">
                    <div className="chat-author">{m.author}</div>
                    <div>{m.body}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Async>
      </div>
      {error && <div className="form-error">{error}</div>}
      <form
        className="chat-composer"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={t('chat.composer')}
          autoFocus
        />
        <Button type="submit" variant="primary">{t('action.send')}</Button>
      </form>
    </Panel>
  );
}

function NewRoomForm({ onClose, onCreated }: { onClose: () => void; onCreated: (c: Conversation) => void }) {
  const { t } = useApp();
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    desktop
      .createConversation('group', name.trim())
      .then((c) => {
        onCreated(c);
        onClose();
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
        setBusy(false);
      });
  };

  return (
    <Modal title={t('chat.newConversation')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <FormRow label={t('chat.roomName')}>
        <Input value={name} autoFocus onChange={(e) => setName(e.target.value)} />
      </FormRow>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="primary" onClick={submit}>{t('action.create')}</Button>
      </div>
    </Modal>
  );
}

/** Two-pane conversation workspace shared by the Chat (direct) and Group Chat
 *  (group) screens. Both are backed by the same conversations/messages tables. */
export function Conversations({ kind }: { kind: Kind }) {
  const { t } = useApp();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const s = useAsync(() => desktop.listConversations(kind), [kind]);

  const titleKey = kind === 'group' ? 'nav.groupChat' : 'nav.chat';
  const subtitleKey = kind === 'group' ? 'groupChat.subtitle' : 'chat.subtitle';

  const startNew = () => {
    if (kind === 'group') {
      setCreating(true);
    } else {
      desktop.createConversation('direct', 'Bro').then((c) => {
        setSelectedId(c.id);
        s.reload();
      });
    }
  };

  return (
    <>
      <PageHeader
        title={t(titleKey)}
        subtitle={t(subtitleKey)}
        actions={<Button variant="primary" onClick={startNew}>{t('action.new')}</Button>}
      />

      {creating && (
        <NewRoomForm
          onClose={() => setCreating(false)}
          onCreated={(c) => {
            setSelectedId(c.id);
            s.reload();
          }}
        />
      )}

      <div className="chat-layout">
        <Panel title={t('chat.conversations')}>
          <Async state={s} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
            {(conversations) => {
              const active = selectedId ?? conversations[0]?.id ?? null;
              return (
                <div className="stack">
                  {conversations.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      className={`chat-item ${c.id === active ? 'chat-item--active' : ''}`}
                      onClick={() => setSelectedId(c.id)}
                    >
                      <span className="chat-item-title">{c.title}</span>
                      <span className="muted">{c.messageCount}</span>
                    </button>
                  ))}
                </div>
              );
            }}
          </Async>
        </Panel>

        <div>
          {(() => {
            const conversations = s.data ?? [];
            const active = conversations.find((c) => c.id === (selectedId ?? conversations[0]?.id)) ?? null;
            if (!active) {
              return (
                <Panel>
                  <EmptyState glyph={kind === 'group' ? '👥' : '💬'} title={t('chat.pickHint')} />
                </Panel>
              );
            }
            return <MessageThread conversation={active} onActivity={() => s.reload()} />;
          })()}
        </div>
      </div>
    </>
  );
}
