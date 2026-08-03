import { useState } from 'react';
import { useApp } from '../app/store';
import { PageHeader, Panel, Button, StatusPill, Avatar, Badge, Async, Input, TileGroup, StatTile } from '../components/ui';
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
  // A governed Ask-Bro turn that the desktop receipt wall Blocked: no answer was
  // produced, so this holds the machine verdict and the page shows a calm notice
  // instead of a (non-existent) reply. Distinct from askError (a real failure).
  const [blocked, setBlocked] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Opaque one-time id for the server-held answer (P1-6). The streamed `answer`
  // above is for display only; saving uses this id, never the local text.
  const [resultId, setResultId] = useState<string | null>(null);

  const ask = async () => {
    const prompt = q.trim();
    if (!prompt || asking) return;
    setAsking(true);
    setAnswer('');
    setAskError(null);
    setBlocked(null);
    setResultId(null);
    try {
      await desktop.streamAsk(prompt, (ev) => {
        if (ev.type === 'delta') setAnswer((prev) => prev + ev.text);
        else if (ev.type === 'ready') setResultId(ev.resultId);
        // Wave 3a Blocks every governed turn at the receipt wall — surface the
        // verdict; no reply exists and none may be saved.
        else if (ev.type === 'blocked') setBlocked(ev.reason);
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
    if (saving || asking || !answer || askError || blocked || !resultId) return;
    const question = q.trim();
    const title = question ? question.slice(0, 48) : t('home.askTitle');
    setSaving(true);
    try {
      // P1-6: agent messages are minted server-side only. Pass just the one-time
      // resultId + a display title — the server persists the held question+answer
      // pair. The webview never carries the agent body.
      await desktop.saveAskToChat(resultId, title);
      setResultId(null);
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

  const showAnswerBlock = asking || answer || askError || blocked;

  return (
    <>
      <PageHeader title={t('nav.home')} subtitle={t('home.subtitle')} />

      <Panel title={t('home.askBro')}>
        <form className="ask-form" onSubmit={(e) => { e.preventDefault(); ask(); }}>
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t('command.placeholder')}
            aria-label={t('action.ask')}
          />
          <Button type="submit" variant="primary" disabled={asking || !q.trim()}>{t('action.ask')}</Button>
        </form>
        {showAnswerBlock && (
          <div className="ask-answer">
            {/* Live region: the streamed answer and the typing indicator are
                announced to assistive tech as text arrives. */}
            <div aria-live="polite" aria-atomic="false" aria-busy={asking}>
              {answer && (asking
                ? <div className="ask-stream">{answer}<span className="chat-cursor" aria-hidden="true" /></div>
                : <Markdown text={answer} />)}
              {asking && !answer && (
                <span className="chat-typing" role="status" aria-label={t('state.loading')}>
                  <span aria-hidden="true"></span><span aria-hidden="true"></span><span aria-hidden="true"></span>
                </span>
              )}
            </div>

            {blocked && !asking && (
              <div className="chat-hint" role="status">
                <span aria-hidden="true">⚠ </span>
                {t('chat.governedBlocked')}{blocked ? ` — ${blocked}` : ''}
              </div>
            )}

            {askError && (
              <div role="alert">
                <div className="chat-hint"><span aria-hidden="true">⚠ </span>{askError}</div>
                <div style={{ marginTop: 8 }}>
                  <Button small variant="ghost" onClick={ask} disabled={asking || !q.trim()}>
                    {t('action.retry')}
                  </Button>
                </div>
              </div>
            )}

            {!asking && answer && !askError && !blocked && (
              <div style={{ marginTop: 8 }}>
                <Button small variant="ghost" onClick={saveToChat} disabled={saving || !resultId}>
                  {t('chat.saveToChat')}
                </Button>
              </div>
            )}
          </div>
        )}
      </Panel>

      {/* At-a-glance overview — the four workspace counts as keyboard-operable
          StatTiles (roving arrows inside the group); each opens its full screen. */}
      <div style={{ marginTop: 16 }}>
        <TileGroup label={t('home.subtitle')}>
          <StatTile glyph="◆" value={active.data?.length ?? 0} label={t('home.priorities')} countUp onActivate={() => setRoute('tasks')} />
          <StatTile glyph="⚑" value={approvals.data?.length ?? 0} label={t('home.approvals')} countUp onActivate={() => setRoute('approvals')} />
          <StatTile glyph="⬡" value={agents.data?.length ?? 0} label={t('home.agents')} countUp onActivate={() => setRoute('agents')} />
          <StatTile glyph="▤" value={projects.data?.length ?? 0} label={t('nav.projects')} countUp onActivate={() => setRoute('projects')} />
        </TileGroup>
      </div>

      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <Panel
          title={t('home.priorities')}
          actions={(
            <Button small variant="ghost" title={`${t('action.viewAll')} — ${t('home.priorities')}`} onClick={() => setRoute('tasks')}>
              {t('action.viewAll')}
            </Button>
          )}
        >
          <Async state={active} emptyTitle={t('home.emptyPriorities')} emptyHint={t('home.emptyPrioritiesHint')}>
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

        <Panel
          title={t('home.approvals')}
          actions={(
            <Button small variant="ghost" title={`${t('action.viewAll')} — ${t('home.approvals')}`} onClick={() => setRoute('approvals')}>
              {t('action.viewAll')}
            </Button>
          )}
        >
          <Async state={approvals} emptyTitle={t('home.emptyApprovals')} emptyHint={t('home.emptyApprovalsHint')}>
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

        <Panel
          title={t('home.agents')}
          actions={(
            <Button small variant="ghost" title={`${t('action.viewAll')} — ${t('home.agents')}`} onClick={() => setRoute('agents')}>
              {t('action.viewAll')}
            </Button>
          )}
        >
          <Async state={agents} emptyTitle={t('home.emptyAgents')} emptyHint={t('home.emptyAgentsHint')}>
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

        <Panel
          title={t('nav.projects')}
          actions={(
            <Button small variant="ghost" title={`${t('action.viewAll')} — ${t('nav.projects')}`} onClick={() => setRoute('projects')}>
              {t('action.viewAll')}
            </Button>
          )}
        >
          <Async state={projects} emptyTitle={t('home.emptyProjects')} emptyHint={t('home.emptyProjectsHint')}>
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
