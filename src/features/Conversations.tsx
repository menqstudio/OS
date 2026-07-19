import { useState } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, Async, EmptyState, Avatar, Modal, FormRow, Input, Select, Skeleton, ErrorState,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { Markdown } from '../components/markdown';
import type { Conversation, Message } from '../domain/entities';

type Kind = 'direct' | 'group';

function MessageThread({ conversation, onActivity }: { conversation: Conversation; onActivity: () => void }) {
  const { t } = useApp();
  const s = useAsync(() => desktop.listMessages(conversation.id), [conversation.id]);
  const ai = useAsync(() => desktop.aiStatus(), []);
  const agents = useAsync(() => desktop.listAgents(), []);
  const isGroup = conversation.kind === 'group';
  const agentNames = (agents.data ?? []).map((a) => a.displayName);
  const [selectedAgent, setSelectedAgent] = useState('Bro');
  const [streamingAuthor, setStreamingAuthor] = useState('Bro');
  const [draft, setDraft] = useState('');
  // Messages posted during this mounted session, appended optimistically on top
  // of the loaded history so the reply appears with no reload flash. Reset when
  // the component remounts per conversation (keyed on conversation.id).
  const [extra, setExtra] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [streamingText, setStreamingText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [replyError, setReplyError] = useState<string | null>(null);

  const send = async () => {
    const body = draft.trim();
    if (!body || busy || thinking) return;
    setBusy(true);
    setError(null);
    setReplyError(null);
    try {
      const userMsg = await desktop.postMessage({ conversationId: conversation.id, role: 'user', author: t('chat.you'), body });
      setExtra((prev) => [...prev, userMsg]);
      setDraft('');
      onActivity();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
      return;
    }
    setBusy(false);
    // Stream real agent replies. In a direct chat the selected agent answers;
    // in a group room the first couple of specialists answer in turn. A provider
    // failure is shown honestly and never loses the user's message.
    setThinking(true);
    setStreamingText('');
    try {
      const responders = isGroup
        ? (agentNames.slice(0, 2).length ? agentNames.slice(0, 2) : ['Bro'])
        : [selectedAgent];
      for (const who of responders) {
        setStreamingAuthor(who);
        setStreamingText('');
        let failed = false;
        await desktop.streamReply(conversation.id, (ev) => {
          if (ev.type === 'delta') setStreamingText((prev) => prev + ev.text);
          else if (ev.type === 'done') setExtra((prev) => [...prev, ev.message]);
          else if (ev.type === 'error') { setReplyError(ev.message); failed = true; }
        }, who);
        if (failed) break; // don't replay the same provider error for every agent
      }
    } catch (e: unknown) {
      setReplyError(e instanceof Error ? e.message : String(e));
    } finally {
      setThinking(false);
      setStreamingText('');
      onActivity();
    }
  };

  const history = s.data ?? [];
  const allMessages = [...history, ...extra];

  return (
    <Panel
      title={conversation.title}
      actions={!isGroup && agentNames.length > 0 ? (
        <Select
          value={selectedAgent}
          onChange={(e) => setSelectedAgent(e.target.value)}
          style={{ width: 'auto', padding: '4px 8px' }}
          title={t('chat.replyAs')}
        >
          <option value="Bro">Bro</option>
          {agentNames.map((n) => <option key={n} value={n}>{n}</option>)}
        </Select>
      ) : undefined}
    >
      <div className="chat-thread">
        {s.loading && s.data === null && <Skeleton rows={4} />}
        {s.error && <ErrorState message={s.error} onRetry={s.reload} />}
        {s.data !== null && !s.error && allMessages.length === 0 && !thinking && (
          <EmptyState title={t('chat.noMessages')} hint={t('chat.noMessagesHint')} />
        )}
        {allMessages.length > 0 && (
          <div className="stack">
            {allMessages.map((m) => (
              <div key={m.id} className={`chat-msg chat-msg--${m.role === 'user' ? 'mine' : 'other'}`}>
                <Avatar name={m.author} />
                <div className="chat-bubble">
                  <div className="chat-author">{m.author}</div>
                  {m.role === 'user'
                    ? <div className="md-plain">{m.body}</div>
                    : <Markdown text={m.body} />}
                </div>
              </div>
            ))}
          </div>
        )}
        {thinking && (
          <div className="chat-msg chat-msg--other">
            <Avatar name={streamingAuthor} />
            <div className="chat-bubble">
              <div className="chat-author">{streamingAuthor}</div>
              {streamingText
                ? <span>{streamingText}<span className="chat-cursor" /></span>
                : <span className="chat-typing"><span></span><span></span><span></span></span>}
            </div>
          </div>
        )}
      </div>
      {error && <div className="form-error">{error}</div>}
      {replyError && (
        <div className="chat-hint" style={{ marginBottom: 8 }}>⚠ {t('chat.replyFailed')}: {replyError}</div>
      )}
      {ai.data && !ai.data.ready && !replyError && (
        <div className="chat-hint" style={{ marginBottom: 8 }}>⚠ {ai.data.detail}</div>
      )}
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
        <Button type="submit" variant="primary" disabled={busy || thinking}>{t('action.send')}</Button>
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
            // key on the conversation id so switching remounts the thread —
            // its streaming/error state never bleeds across conversations.
            return <MessageThread key={active.id} conversation={active} onActivity={() => s.reload()} />;
          })()}
        </div>
      </div>
    </>
  );
}
