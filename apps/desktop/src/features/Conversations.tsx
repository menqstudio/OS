import { useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Rail, Button, Async, EmptyState, Modal, FormRow, Input, Select, Skeleton,
  ErrorState, ConfirmDialog, Badge,
} from '../components/ui';
import { desktop, hasBackend } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { Markdown } from '../components/markdown';
import { Mark } from '../components/Ambient';
import type { Conversation, Message } from '../domain/entities';
import type { Tone } from '../domain/enums';
import { STR } from './Conversations.strings';

/** Map a message's server-derived receipt outcome to its trust badge, or `null` for
 *  no badge. `development_untrusted` → amber dev badge; `trusted_verified` → green
 *  "Verified" (Wave 3b only); anything else → no badge. A blocked governed turn
 *  produces no message, so it never reaches here. Pure — unit-tested. */
export function receiptBadge(
  receipt: Message['receipt'],
): { tone: Tone; key: 'chat.receiptVerified' | 'chat.receiptDev' } | null {
  if (receipt === 'trusted_verified') return { tone: 'success', key: 'chat.receiptVerified' };
  if (receipt === 'development_untrusted') return { tone: 'warning', key: 'chat.receiptDev' };
  return null;
}

type Kind = 'direct' | 'group';

/** The `@mention` token being typed immediately before the caret, if any. A
 *  mention runs from an `@` at the start of input or after whitespace up to the
 *  caret, and contains no whitespace. Returns its start offset and the query
 *  text typed so far (empty right after the `@`). */
function activeMention(text: string, caret: number): { start: number; query: string } | null {
  let i = caret - 1;
  while (i >= 0 && !/\s/.test(text[i]) && text[i] !== '@') i -= 1;
  if (i < 0 || text[i] !== '@') return null;
  if (i > 0 && !/\s/.test(text[i - 1])) return null;
  return { start: i, query: text.slice(i + 1, caret) };
}

/** Per-view CSS. The chat canvas + context rail are dressed by the global aios
 *  theme (`.v-chat …`); only the app-plumbing bits the mockup has no design for
 *  (the conversation-list column, reply-as control, honest error strips and the
 *  honest rate readout) get their tweaks here, all scoped under `.v-chat`. */
const VIEW_CSS = `
.v-chat .chat-workspace{display:grid;grid-template-columns:minmax(198px,238px) minmax(0,1fr);gap:18px;align-items:start}
.v-chat .chat-main{min-width:0}
.v-chat .th-actions{display:flex;align-items:center;gap:10px;flex:0 0 auto}
.v-chat .th-actions .select{width:auto;padding:4px 8px}
.v-chat .t-meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.v-chat .turn.me .t-meta{flex-direction:row-reverse}
.v-chat .t-who{font-family:var(--f-mono);font-size:11px;letter-spacing:.05em;color:var(--ink-muted)}
.v-chat .chat-alert{margin:0 18px 8px;font-size:12px;line-height:1.5;color:var(--warning);display:flex;gap:6px;align-items:flex-start}
.v-chat .attn-mark{display:flex;justify-content:center;margin:4px 0 14px}
.v-chat .rate-stat{display:flex;align-items:baseline;gap:9px;margin-top:6px}
.v-chat .rate-stat b{font-size:27px;font-family:var(--f-mono);color:var(--ink)}
.v-chat .rate-note{margin:9px 0 0;font-size:11.5px;color:var(--ink-muted);line-height:1.5}
@media (max-width:1100px){.v-chat .chat-workspace{grid-template-columns:1fr}}
`;

/** Monogram avatar in the aios `.sigil` idiom, with a live-state dot. Purely
 *  decorative (identity is carried by the adjacent author text), so aria-hidden. */
function Sigil({ name, state = 'idle' }: { name: string; state?: string }) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const mono = parts.length === 0 ? '·'
    : parts.length === 1 ? parts[0].slice(0, 2).toUpperCase()
    : (parts[0][0] + parts[1][0]).toUpperCase();
  return (
    <span className={`sigil st-${state}`} aria-hidden="true">
      <span className="st-dot" />{mono}
    </span>
  );
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function MessageThread({ conversation, onActivity }: { conversation: Conversation; onActivity: () => void }) {
  const { t, lang } = useApp();
  const L = (k: keyof typeof STR) => STR[k][lang] ?? STR[k].en;
  const s = useAsync(() => desktop.listMessages(conversation.id), [conversation.id]);
  const ai = useAsync(() => desktop.aiStatus(), []);
  const agents = useAsync(() => desktop.listAgents(), []);
  const isGroup = conversation.kind === 'group';
  const agentList = agents.data ?? [];
  const agentNames = agentList.map((a) => a.displayName);
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
  // Stop button: a ref the responder loop checks so it can break out immediately.
  const cancelledRef = useRef(false);
  // Messages sent while a turn is running are queued and fire automatically when it
  // finishes — the user never waits to keep talking. A ref (not state) so the drain in
  // send's `finally` reads the latest queue without a stale closure.
  const queueRef = useRef<string[]>([]);
  const [queuedCount, setQueuedCount] = useState(0);
  // @mention autocomplete over agent display names.
  const inputRef = useRef<HTMLInputElement | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const [mention, setMention] = useState<{ start: number; query: string } | null>(null);
  const [mentionIndex, setMentionIndex] = useState(0);
  const mentionMatches = mention
    ? agentNames.filter((n) => n.toLowerCase().includes(mention.query.toLowerCase()))
    : [];
  const showMentions = mention !== null && mentionMatches.length > 0;
  const mentionActive = Math.min(mentionIndex, mentionMatches.length - 1);

  const syncMention = (value: string, caret: number) => {
    const found = activeMention(value, caret);
    setMention(found);
    setMentionIndex(0);
  };

  const onDraftChange = (e: ChangeEvent<HTMLInputElement>) => {
    setDraft(e.target.value);
    syncMention(e.target.value, e.target.selectionStart ?? e.target.value.length);
  };

  const insertMention = (name: string) => {
    if (!mention) return;
    const before = draft.slice(0, mention.start);
    const after = draft.slice(mention.start + 1 + mention.query.length);
    const inserted = `@${name} `;
    const caret = before.length + inserted.length;
    setDraft(before + inserted + after);
    setMention(null);
    // Restore focus and place the caret after the inserted mention.
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (el) {
        el.focus();
        el.setSelectionRange(caret, caret);
      }
    });
  };

  // The composer "@" affordance: drop an `@` at the caret and open the picker,
  // reusing the exact same mention pipeline typing `@` triggers.
  const onAtClick = () => {
    const base = draft && !/\s$/.test(draft) ? `${draft} ` : draft;
    const next = `${base}@`;
    setDraft(next);
    syncMention(next, next.length);
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (el) { el.focus(); el.setSelectionRange(next.length, next.length); }
    });
  };

  const onDraftKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (!showMentions) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setMentionIndex((i) => (Math.min(i, mentionMatches.length - 1) + 1) % mentionMatches.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setMentionIndex((i) => {
        const cur = Math.min(i, mentionMatches.length - 1);
        return (cur - 1 + mentionMatches.length) % mentionMatches.length;
      });
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault();
      insertMention(mentionMatches[mentionActive]);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setMention(null);
    }
  };

  const send = async (override?: string) => {
    const body = (override ?? draft).trim();
    if (!body) return;
    // A turn is already running: don't block the user — queue this message and it
    // fires automatically when the current turn finishes (see the drain in `finally`).
    if (!override && (busy || thinking)) {
      queueRef.current.push(body);
      setQueuedCount(queueRef.current.length);
      setDraft('');
      requestAnimationFrame(() => inputRef.current?.focus());
      return;
    }
    cancelledRef.current = false;
    setBusy(true);
    setError(null);
    setReplyError(null);
    try {
      const userMsg = await desktop.postMessage({ conversationId: conversation.id, role: 'user', author: t('chat.you'), body });
      setExtra((prev) => [...prev, userMsg]);
      if (!override) setDraft('');
      // Focus management on send: return the caret to the composer for the next turn.
      requestAnimationFrame(() => inputRef.current?.focus());
      onActivity();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
      return;
    }
    setBusy(false);
    // Stream real agent replies. In a direct chat the selected agent answers;
    // in a group room the first couple of specialists answer in turn. A provider
    // failure is shown honestly and never loses the user's message. The Stop button
    // sets cancelledRef so this loop breaks and the backend turn is cancelled.
    setThinking(true);
    setStreamingText('');
    try {
      const responders = isGroup
        ? (agentNames.slice(0, 2).length ? agentNames.slice(0, 2) : ['Bro'])
        : [selectedAgent];
      for (const who of responders) {
        if (cancelledRef.current) break;
        setStreamingAuthor(who);
        setStreamingText('');
        let failed = false;
        await desktop.streamReply(conversation.id, (ev) => {
          if (ev.type === 'delta') setStreamingText((prev) => prev + ev.text);
          else if (ev.type === 'done') setExtra((prev) => [...prev, ev.message]);
          else if (ev.type === 'error') { setReplyError(ev.message); failed = true; }
          // Governed turn Blocked by desktop receipt verification: a transient
          // turn-level notice, NO persisted agent message (Wave 3a Blocks every turn).
          else if (ev.type === 'blocked') { setReplyError(`${t('chat.governedBlocked')}: ${ev.reason}`); failed = true; }
        }, who);
        if (failed || cancelledRef.current) break; // stop the chain on error or Stop
      }
    } catch (e: unknown) {
      setReplyError(e instanceof Error ? e.message : String(e));
    } finally {
      setThinking(false);
      setStreamingText('');
      onActivity();
      // Fire the next queued message, if any and the user didn't Stop.
      if (!cancelledRef.current && queueRef.current.length > 0) {
        const next = queueRef.current.shift()!;
        setQueuedCount(queueRef.current.length);
        void send(next);
      }
    }
  };

  // Stop the in-flight turn: break the responder loop, cancel the backend stream
  // (keeping whatever streamed so far), and drop any queued follow-ups.
  const stopTurn = () => {
    cancelledRef.current = true;
    queueRef.current = [];
    setQueuedCount(0);
    void desktop.cancelReply(conversation.id).catch(() => {});
  };

  const history = s.data ?? [];
  const allMessages = [...history, ...extra];

  // Keep the newest turn in view as history loads and the reply streams in.
  useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [allMessages.length, streamingText, thinking]);

  // Assistant power-mark state: thinking while a reply streams, live when a
  // backend is present, idle when there is none.
  const markState = thinking ? 'thinking' : (hasBackend() ? 'live' : 'idle');
  const liveWord = thinking ? L('typing') : L('ready');
  const attnPill = thinking ? 'live' : (ai.data && !ai.data.ready ? 'warn' : 'info');
  const attnWord = thinking ? L('thinkingCap') : (ai.data && !ai.data.ready ? L('unavailable') : L('readyCap'));
  const participantCount = agentList.length + 1; // agents + Bro

  return (
    <div className="chat-shell">

      {/* ── MAIN · the conversation stream ─────────────────────────────────── */}
      <section className="chat-canvas surface soft lg" aria-label={conversation.title}>

        <header className="thread-head">
          <div className="th-topic">
            <span className="eyebrow">{isGroup ? L('groupChatEyebrow') : L('liveChatEyebrow')}</span>
            <h2>{conversation.title}</h2>
          </div>
          <div className="th-actions">
            {!isGroup && agentNames.length > 0 && (
              <Select
                value={selectedAgent}
                onChange={(e) => setSelectedAgent(e.target.value)}
                title={t('chat.replyAs')}
                aria-label={t('chat.replyAs')}
              >
                <option value="Bro">Bro</option>
                {agentNames.map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
            )}
            <span className={`th-live${thinking ? '' : ' idle'}`}>
              <span className="th-live-dot" aria-hidden="true" />
              <span className="micro">{liveWord}</span>
            </span>
          </div>
        </header>

        {/* the message log — a labelled polite live region */}
        <div
          className={`thread${thinking ? ' streaming' : ''}`}
          id="thread"
          ref={threadRef}
          role="log"
          aria-label={t('chat.conversations')}
          aria-live="polite"
          aria-busy={thinking}
        >
          {s.loading && s.data === null && <Skeleton rows={4} />}
          {s.error && <ErrorState message={s.error} onRetry={s.reload} />}
          {s.data !== null && !s.error && allMessages.length === 0 && !thinking && (
            <EmptyState title={t('chat.noMessages')} hint={t('chat.noMessagesHint')} />
          )}

          {allMessages.map((m) => {
            const mine = m.role === 'user';
            const badge = m.role === 'agent' ? receiptBadge(m.receipt) : null;
            const time = fmtTime(m.createdAt);
            return (
              <article key={m.id} className={`turn ${mine ? 'me' : 'bro'}`}>
                <span className="t-av"><Sigil name={m.author} /></span>
                <div className="t-body">
                  <div className={`bubble ${mine ? 'me' : 'bro'}`}>
                    <div className="btext">
                      {mine ? m.body : <Markdown text={m.body} />}
                    </div>
                  </div>
                  <div className="t-meta">
                    <span className="t-who">{m.author}</span>
                    {badge && <Badge tone={badge.tone}>{t(badge.key)}</Badge>}
                    {time && <span className="t-time mono">{time}</span>}
                  </div>
                </div>
              </article>
            );
          })}

          {thinking && (
            <article className="turn bro now">
              <span className="tbeam" aria-hidden="true"><span className="tbeam-run" /></span>
              <span className="t-av"><Sigil name={streamingAuthor} state="thinking" /></span>
              <div className="t-body">
                <div className="bubble bro">
                  <div className="btext">
                    {streamingText
                      ? <><Markdown text={streamingText} /><span className="caret" aria-hidden="true" /></>
                      : <span className="typing" aria-hidden="true"><i /><i /><i /></span>}
                  </div>
                </div>
                <div className="t-meta"><span className="t-who">{streamingAuthor}</span></div>
              </div>
            </article>
          )}
        </div>

        {/* honest error / status strips — never lose the user's posted message */}
        {error && <p className="chat-alert" role="alert">⚠ {error}</p>}
        {replyError && <p className="chat-alert" role="status">⚠ {t('chat.replyFailed')}: {replyError}</p>}
        {ai.data && !ai.data.ready && !replyError && <p className="chat-alert" role="status">⚠ {ai.data.detail}</p>}

        {/* composer — @mention picker over REAL agents + keyboard submit */}
        <form
          className="composer"
          autoComplete="off"
          onSubmit={(e) => { e.preventDefault(); send(); }}
        >
          {showMentions && (
            <ul className="mention-popup mention-pop open" role="listbox" aria-label={t('chat.composer')}>
              {mentionMatches.map((n, idx) => (
                <li key={n} role="option" aria-selected={idx === mentionActive}>
                  <button
                    type="button"
                    className={`mention-item ${idx === mentionActive ? 'mention-item--active' : ''}`}
                    // onMouseDown (not onClick) so the input keeps focus for caret restore.
                    onMouseDown={(e) => { e.preventDefault(); insertMention(n); }}
                  >
                    <Sigil name={n} />
                    <span>{n}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {queuedCount > 0 && (
            <div className="comp-queued" aria-live="polite">
              {queuedCount === 1 ? L('queuedOne') : `${queuedCount} ${L('queuedMany')}`}
            </div>
          )}
          <div className="comp-bar">
            <button
              type="button"
              className={`comp-at${showMentions ? ' on' : ''}`}
              aria-label={t('chat.replyAs')}
              aria-expanded={showMentions}
              onClick={onAtClick}
            >@</button>
            <Input
              ref={inputRef}
              className="comp-input"
              value={draft}
              onChange={onDraftChange}
              onKeyDown={onDraftKeyDown}
              onBlur={() => setMention(null)}
              placeholder={t('chat.composer')}
              aria-label={t('chat.composer')}
              autoFocus
            />
            {thinking ? (
              // While a turn streams, the primary action is Stop; Enter still queues a
              // follow-up so the user can keep talking without waiting.
              <button
                type="button"
                className="comp-send comp-stop"
                aria-label={L('stop')}
                title={L('stop')}
                onClick={stopTurn}
              >
                <span className="cs-glyph" aria-hidden="true">■</span>
              </button>
            ) : (
              <button type="submit" className="comp-send" aria-label={t('action.send')} disabled={busy}>
                <span className="cs-glyph" aria-hidden="true">➤</span>
              </button>
            )}
          </div>
        </form>

      </section>

      {/* ── RAIL · live context, all derived from real data ────────────────── */}
      <aside className="ctx-rail">

        {/* Attention field — the assistant's live state, honestly sourced from
            aiStatus + the streaming flag (no fabricated confidence telemetry). */}
        <section className="surface cut hud ctx-attn" aria-label={L('attnFieldAria')}>
          <i className="bracket tl" /><i className="bracket tr" />
          <i className="bracket bl" /><i className="bracket br" />
          <div className="ctx-head">
            <span className="eyebrow">{L('attnFieldEyebrow')}</span>
            <span className={`pill ${attnPill}`}>{attnWord}</span>
          </div>
          <p className="ctx-note">{L('liveState')}</p>
          <div className="attn-mark"><Mark state={markState} size={72} /></div>
          <div className="ctx-recalls">
            <span className="micro rc-lbl">{L('contextLabel')}</span>
            <ul className="recall-list">
              <li className="recall"><span className="rk" /><b className="mono">{allMessages.length}</b>&nbsp;{L('messagesUnit')}</li>
              <li className="recall"><span className="rk" /><b className="mono">{agentList.length}</b>&nbsp;{L('agentsUnit')}</li>
              {ai.data && !ai.data.ready && <li className="recall"><span className="rk" />{ai.data.detail}</li>}
            </ul>
          </div>
        </section>

        {/* In the room — REAL participants: Bro + the agents from listAgents. */}
        <section className="surface soft ctx-room">
          <div className="cr-head">
            <span className="eyebrow">{L('inRoomEyebrow')}</span>
            <span className="micro">{participantCount}&nbsp;·&nbsp;{L('participantsUnit')}</span>
          </div>
          <div className="room-list">
            <div className="rm">
              <span className="rm-av"><Sigil name="Bro" state={thinking ? 'working' : 'idle'} /></span>
              <span className="rm-who"><b>Bro</b><span>{L('broRole')}</span></span>
              <i className={`rm-st st-${thinking ? 'working' : 'idle'}`}>{thinking ? L('statusWorking') : L('statusIdle')}</i>
            </div>
            <Async state={agents} emptyTitle={t('state.empty')}>
              {(list) => (
                <>
                  {list.map((a) => {
                    const active = thinking && streamingAuthor === a.displayName;
                    return (
                      <div key={a.id} className="rm">
                        <span className="rm-av"><Sigil name={a.displayName} state={active ? 'working' : 'idle'} /></span>
                        <span className="rm-who"><b>{a.displayName}</b><span>{a.role}</span></span>
                        <i className={`rm-st st-${active ? 'working' : 'idle'}`}>{active ? L('statusWorking') : L('statusIdle')}</i>
                      </div>
                    );
                  })}
                </>
              )}
            </Async>
          </div>
        </section>

        {/* Response — the mockup's writing-tempo sparkline has no real source, so
            we show an honest real readout (this conversation's message count)
            instead of fabricated telemetry. */}
        <section className="surface soft ctx-rate">
          <div className="cr-head"><span className="eyebrow">{L('responseEyebrow')}</span></div>
          <div className="rate-stat">
            <b>{conversation.messageCount}</b>
            <span className="micro">{L('messagesUnit')}</span>
          </div>
          <p className="rate-note">{L('tempoNote')}</p>
        </section>

      </aside>
    </div>
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

function RenameConversationForm({ conversation, onClose, onRenamed }:
  { conversation: Conversation; onClose: () => void; onRenamed: () => void }) {
  const { t } = useApp();
  const [name, setName] = useState(conversation.title);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    desktop
      .renameConversation(conversation.id, name.trim())
      .then(() => {
        onRenamed();
        onClose();
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
        setBusy(false);
      });
  };

  return (
    <Modal title={t('chat.renameTitle')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <FormRow label={t('chat.roomName')}>
        <Input value={name} autoFocus onChange={(e) => setName(e.target.value)} />
      </FormRow>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="primary" onClick={submit}>{t('chat.rename')}</Button>
      </div>
    </Modal>
  );
}

/** Two-pane conversation workspace shared by the Chat (direct) and Group Chat
 *  (group) screens. Both are backed by the same conversations/messages tables. */
export function Conversations({ kind }: { kind: Kind }) {
  const { t, focus, clearFocus } = useApp();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<Conversation | null>(null);
  const [deleting, setDeleting] = useState<Conversation | null>(null);
  const s = useAsync(() => desktop.listConversations(kind), [kind]);

  // Consume a command-palette deep-link. The palette already routed to the
  // Conversations instance matching the picked conversation's kind, so only the
  // instance that actually owns the id selects it and clears the pending focus;
  // if the id is absent from this fully-loaded list it belongs to the other
  // kind — leave focus set so the correctly-routed instance handles it.
  useEffect(() => {
    if (focus?.kind !== 'conversation' || s.loading || s.data === null) return;
    if (s.data.some((c) => c.id === focus.id)) {
      setSelectedId(focus.id);
      clearFocus();
    }
  }, [focus, s.data, s.loading, clearFocus]);

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

  const confirmDelete = () => {
    const target = deleting;
    if (!target) return;
    desktop
      .deleteConversation(target.id)
      .then(() => {
        if (selectedId === target.id) setSelectedId(null);
        setDeleting(null);
        s.reload();
      })
      .catch(() => setDeleting(null));
  };

  return (
    <div className="v-chat">
      <style>{VIEW_CSS}</style>

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

      {renaming && (
        <RenameConversationForm
          conversation={renaming}
          onClose={() => setRenaming(null)}
          onRenamed={() => s.reload()}
        />
      )}

      {deleting && (
        <ConfirmDialog
          title={t('chat.deleteConversation')}
          message={t('chat.deleteConfirm')}
          confirmLabel={t('action.delete')}
          cancelLabel={t('action.cancel')}
          onConfirm={confirmDelete}
          onCancel={() => setDeleting(null)}
        />
      )}

      <div className="chat-workspace">
        {/* Conversation rail — the Rail primitive's plain-panel variant, so it
            adopts the rail model without adding a second complementary landmark
            or changing the panel padding. */}
        <Rail variant="panel" label={t('chat.conversations')}>
          <Async state={s} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
            {(conversations) => {
              const active = selectedId ?? conversations[0]?.id ?? null;
              return (
                <div className="stack">
                  {conversations.map((c) => (
                    <div key={c.id} className="chat-item-row">
                      <button
                        type="button"
                        className={`chat-item ${c.id === active ? 'chat-item--active' : ''}`}
                        onClick={() => setSelectedId(c.id)}
                      >
                        <span className="chat-item-title">{c.title}</span>
                        <span className="muted">{c.messageCount}</span>
                      </button>
                      <div className="chat-item-actions">
                        <button
                          type="button"
                          className="chat-item-action"
                          title={t('chat.rename')}
                          aria-label={t('chat.rename')}
                          onClick={() => setRenaming(c)}
                        >✎</button>
                        <button
                          type="button"
                          className="chat-item-action chat-item-action--danger"
                          disabled
                          title={t('action.deleteDisabledSafety')}
                          aria-label={t('action.deleteDisabledSafety')}
                          onClick={() => setDeleting(c)}
                        >🗑</button>
                      </div>
                    </div>
                  ))}
                </div>
              );
            }}
          </Async>
        </Rail>

        <div className="chat-main">
          {(() => {
            const conversations = s.data ?? [];
            const active = conversations.find((c) => c.id === (selectedId ?? conversations[0]?.id)) ?? null;
            if (!active) {
              return (
                <section className="chat-canvas surface soft lg" aria-label={t('chat.pickHint')}>
                  <EmptyState glyph={kind === 'group' ? '👥' : '💬'} title={t('chat.pickHint')} />
                </section>
              );
            }
            // key on the conversation id so switching remounts the thread —
            // its streaming/error state never bleeds across conversations.
            return <MessageThread key={active.id} conversation={active} onActivity={() => s.reload()} />;
          })()}
        </div>
      </div>
    </div>
  );
}
