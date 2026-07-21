import { useState } from 'react';
import { useApp } from '../app/store';
import { PageHeader, Panel, Button, StatusPill, Avatar, Badge, Async, Input } from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { Markdown } from '../components/markdown';
import { useToast } from '../components/toast';

export function Home() {
  const { t, setRoute } = useApp();
  const toast = useToast();
  const [q, setQ] = useState('');
  const [answer, setAnswer] = useState('');
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const ask = async () => {
    const prompt = q.trim();
    if (!prompt || asking) return;
    setAsking(true);
    setAnswer('');
    setAskError(null);
    try {
      await desktop.streamAsk(prompt, (ev) => {
        if (ev.type === 'delta') setAnswer((prev) => prev + ev.text);
        else if (ev.type === 'error') setAskError(ev.message);
      });
    } catch (e: unknown) {
      setAskError(e instanceof Error ? e.message : String(e));
    } finally {
      setAsking(false);
    }
  };

  // Persist a finished Ask-Bro answer as a new direct conversation, then jump to
  // the Chat screen. The question is captured before any await because the input
  // may change while the async work runs; the answer is read from state.
  const saveToChat = async () => {
    if (saving || asking || !answer || askError) return;
    const question = q.trim();
    const savedAnswer = answer;
    const title = question ? question.slice(0, 48) : 'Ask Bro';
    setSaving(true);
    try {
      // P1-6: agent messages are minted server-side only. Persist the reviewed
      // Ask-Bro pair via the scoped command instead of posting an 'agent' message
      // from the webview.
      await desktop.saveAskToChat(title, question || title, savedAnswer);
      toast(t('toast.savedToChat'), 'success');
      setRoute('chat');
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : String(e), 'error');
    } finally {
      setSaving(false);
    }
  };

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

      <Panel title={t('home.askBro')}>
        <form className="ask-form" onSubmit={(e) => { e.preventDefault(); ask(); }}>
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('command.placeholder')} />
          <Button type="submit" variant="primary" disabled={asking}>{t('action.ask')}</Button>
        </form>
        {(asking || answer || askError) && (
          <div className="ask-answer">
            {answer && (asking
              ? <div className="ask-stream">{answer}<span className="chat-cursor" /></div>
              : <Markdown text={answer} />)}
            {asking && !answer && (
              <span className="chat-typing"><span></span><span></span><span></span></span>
            )}
            {askError && <div className="chat-hint">⚠ {askError}</div>}
            {!asking && answer && !askError && (
              <div style={{ marginTop: 8 }}>
                <Button small variant="ghost" onClick={saveToChat} disabled={saving}>
                  {t('chat.saveToChat')}
                </Button>
              </div>
            )}
          </div>
        )}
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
