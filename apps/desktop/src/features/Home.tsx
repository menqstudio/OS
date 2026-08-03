import { useMemo, useState, type CSSProperties } from 'react';
import { useApp } from '../app/store';
import { Button, Async, Input, TileGroup, StatTile, EmptyState, Skeleton } from '../components/ui';
import { Mark } from '../components/Ambient';
import { statusTone } from '../domain/enums';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { Beatline, BarChart } from '../components/charts/Chart';
import { Markdown } from '../components/markdown';
import { useToast } from '../components/toast';
import { STR, taskSummary, activitySummary } from './Home.strings';

// Real status → aios `.pill` modifier. The pill only re-skins a status that the
// backend actually returned — it never invents a "verified"/"live" state.
function pillTone(status: string): string {
  switch (statusTone[status] ?? 'neutral') {
    case 'success': return 'live';
    case 'accent':
    case 'info': return 'info';
    case 'warning':
    case 'danger': return 'warn';
    default: return '';
  }
}

const label = (s: string) => s.replace(/_/g, ' ');

// Ring geometry (r=60) mirrored from the aios ring gauge — --len/--off drive the
// same dash sweep. Pure constants; carry no data.
const RING_R = 60;
const RING_LEN = 2 * Math.PI * RING_R;
// Equal time-buckets for the activity throughput sparkline.
const FLOW_BUCKETS = 12;

// Parse an event timestamp (ISO or epoch string) to ms, or null if unparseable.
// Same honest derivation Activity.tsx uses for its beat timeline.
function parseTime(raw: string): number | null {
  const n = Number(raw);
  const d = new Date(Number.isNaN(n) ? raw : n);
  const ms = d.getTime();
  return Number.isNaN(ms) ? null : ms;
}

export function Home() {
  const { t, setRoute, lang } = useApp();
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

  // Additional REAL desktop reads that back the derived instruments below. Each is a
  // plain list command; nothing here fabricates a value the backend didn't return.
  const allTasks = useAsync(() => desktop.listTasks(), []);
  const activity = useAsync(() => desktop.listActivity(), []);
  const allApprovals = useAsync(() => desktop.listApprovals(), []);

  // Page-local trilingual labels for the new instruments, sourced from
  // Home.strings. `t()` still serves every shared dict key; L() resolves the
  // page-local copy for the active language, falling back to English.
  const L = (k: keyof typeof STR) => STR[k][lang] ?? STR[k].en;

  // Task completion + attention — counts of real task statuses from listTasks().
  const taskStats = useMemo(() => {
    const rows = allTasks.data ?? [];
    const total = rows.length;
    const by = (s: string) => rows.filter((x) => x.status === s).length;
    const done = by('done');
    const active = by('active');
    const blocked = by('blocked');
    return {
      total, done, active, blocked,
      donePct: total ? Math.round((done / total) * 100) : 0,
      blockedPct: total ? Math.round((blocked / total) * 100) : null,
    };
  }, [allTasks.data]);

  // Agent engagement + status distribution — grouped counts from listAgents().
  const agentStats = useMemo(() => {
    const rows = agents.data ?? [];
    const total = rows.length;
    const busySet = new Set(['working', 'thinking', 'observing', 'review']);
    const busy = rows.filter((a) => busySet.has(a.status)).length;
    const counts = new Map<string, number>();
    for (const a of rows) counts.set(a.status, (counts.get(a.status) ?? 0) + 1);
    const dist = [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([status, value]) => ({ key: status, label: label(status), value }));
    return { total, busyPct: total ? Math.round((busy / total) * 100) : null, dist };
  }, [agents.data]);

  // Approval backlog share — pending / all approvals from the unfiltered read.
  const approvalStats = useMemo(() => {
    const rows = allApprovals.data ?? [];
    const total = rows.length;
    const pending = rows.filter((a) => a.status === 'pending').length;
    return { total, pending, pendingPct: total ? Math.round((pending / total) * 100) : null };
  }, [allApprovals.data]);

  // Recent-activity throughput — real events bucketed into equal time windows across
  // their own span (same parseTime derivation as Activity's beatline).
  const flow = useMemo(() => {
    const rows = activity.data ?? [];
    const times = rows
      .map((e) => parseTime(e.createdAt))
      .filter((n): n is number => n != null)
      .sort((a, b) => a - b);
    if (times.length === 0) return { points: [] as { label: string; value: number }[], total: 0, peak: 0 };
    const min = times[0];
    const max = times[times.length - 1];
    const span = max - min || 1;
    const counts = new Array<number>(FLOW_BUCKETS).fill(0);
    for (const tn of times) {
      const idx = Math.min(FLOW_BUCKETS - 1, Math.floor(((tn - min) / span) * FLOW_BUCKETS));
      counts[idx] += 1;
    }
    const fmt = new Intl.DateTimeFormat(lang, { hour: '2-digit', minute: '2-digit' });
    const points = counts.map((value, i) => ({
      label: fmt.format(new Date(min + ((i + 0.5) / FLOW_BUCKETS) * span)),
      value,
    }));
    return { points, total: times.length, peak: Math.max(...counts) };
  }, [activity.data, lang]);

  const showAnswerBlock = asking || answer || askError || blocked;
  // The greeting power-mark tracks the real interaction state — nothing else.
  const markState = askError || blocked ? 'alert' : asking ? 'thinking' : 'live';

  return (
    <>
      <style>{HOME_STYLE}</style>
      <div className="v-home">
      {/* ── HERO · Ask Bro + at-a-glance counts ─────────────────────────── */}
      <section className="briefing surface soft lg hud reveal">
        <span className="bracket tl" aria-hidden="true" />
        <span className="bracket tr" aria-hidden="true" />
        <span className="bracket bl" aria-hidden="true" />
        <span className="bracket br" aria-hidden="true" />

        <div className="brief-top">
          <span className="eyebrow">{t('home.subtitle')}</span>
        </div>

        <div className="brief-hd">
          <div className="greet">
            <Mark state={markState} size={46} />
            <div className="greet-txt">
              <h1>{t('nav.home')}</h1>
              <p className="sub">{t('home.subtitle')}</p>
            </div>
          </div>
        </div>

        {/* Ask-Bro command box — unchanged streaming/receipt logic. */}
        <div>
          <div className="sec-head"><h2>{t('home.askBro')}</h2></div>
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
        </div>

        {/* At-a-glance overview — the four workspace counts as keyboard-operable
            StatTiles (roving arrows inside the group); each opens its full screen. */}
        <div className="ledger-wrap">
          <span className="micro since">{t('home.subtitle')}</span>
          <TileGroup label={t('home.subtitle')}>
            <StatTile glyph="◆" value={active.data?.length ?? 0} label={t('home.priorities')} countUp onActivate={() => setRoute('tasks')} />
            <StatTile glyph="⚑" value={approvals.data?.length ?? 0} label={t('home.approvals')} countUp onActivate={() => setRoute('approvals')} />
            <StatTile glyph="⬡" value={agents.data?.length ?? 0} label={t('home.agents')} countUp onActivate={() => setRoute('agents')} />
            <StatTile glyph="▤" value={projects.data?.length ?? 0} label={t('nav.projects')} countUp onActivate={() => setRoute('projects')} />
          </TileGroup>
        </div>
      </section>

      {/* ── INSTRUMENTS · honest read-outs derived from the real arrays ───── */}
      <div className="hx-instruments">
        {/* Derived ratios — each a plain quotient of two real counts. Shows "—"
            until its source has loaded (never a placeholder number). */}
        <div className="hx-ratios" role="group" aria-label={L('derivedRatios')}>
          <div className="hx-ratio">
            <b>{agentStats.busyPct ?? '—'}{agentStats.busyPct != null && <i>%</i>}</b>
            <span className="micro">{L('agentsBusy')}</span>
          </div>
          <div className="hx-ratio">
            <b>{taskStats.blockedPct ?? '—'}{taskStats.blockedPct != null && <i>%</i>}</b>
            <span className="micro">{L('tasksBlocked')}</span>
          </div>
          <div className="hx-ratio">
            <b>{approvalStats.pendingPct ?? '—'}{approvalStats.pendingPct != null && <i>%</i>}</b>
            <span className="micro">{L('approvalsPending')}</span>
          </div>
        </div>

        <div className="hx-board">
          {/* Task-progress ring — done / total from listTasks(). */}
          <section className="surface soft hx-resolve reveal">
            <div className="sec-head"><h2>{L('taskProgress')}</h2></div>
            {allTasks.loading && allTasks.data === null ? (
              <Skeleton rows={3} />
            ) : allTasks.error ? (
              <p className="hx-note note">{L('progressUnavailable')}</p>
            ) : taskStats.total === 0 ? (
              <EmptyState glyph="◇" title={t('home.emptyPriorities')} />
            ) : (
              <>
                <div
                  className="ring hx-ring"
                  style={{ ['--len']: RING_LEN.toFixed(1), ['--off']: (RING_LEN * (1 - taskStats.donePct / 100)).toFixed(1) } as CSSProperties}
                >
                  <svg viewBox="0 0 140 140" aria-hidden="true">
                    <circle className="track" cx="70" cy="70" r={RING_R} />
                    <circle className="value mint" cx="70" cy="70" r={RING_R} />
                  </svg>
                  <span className="read">
                    <b>{taskStats.donePct}<i>%</i></b>
                    <span>{L('done')}</span>
                  </span>
                </div>
                {/* Accessible text equivalent for the ring — the real counts behind it. */}
                <p className="hx-note note">
                  {taskSummary(lang, taskStats.done, taskStats.total, taskStats.active, taskStats.blocked)}
                </p>
              </>
            )}
          </section>

          {/* Agents-by-status distribution — grouped counts from listAgents(). The
              BarChart carries its own summary + data-table for a11y. */}
          <section className="surface soft reveal">
            <div className="sec-head"><h2>{L('agentsByStatus')}</h2></div>
            {agents.loading && agents.data === null ? (
              <Skeleton rows={4} />
            ) : agents.error ? (
              <p className="hx-note note">{L('distributionUnavailable')}</p>
            ) : agentStats.total === 0 ? (
              <EmptyState glyph="⬡" title={t('home.emptyAgents')} />
            ) : (
              <BarChart
                data={agentStats.dist}
                caption={L('agentsByStatus')}
                unit={L('agentsUnit')}
                totalLabel={L('total')}
                nodeHeader={L('statusHeader')}
                valueHeader={L('countHeader')}
                shareHeader={L('shareHeader')}
                tableToggle={L('showDataTable')}
              />
            )}
          </section>

          {/* Recent-activity throughput — real events time-bucketed from listActivity().
              Beatline carries its own summary + data-table for a11y. */}
          <section className="surface soft reveal">
            <div className="sec-head">
              <h2>{L('recentActivity')}</h2>
              <span className="note">{L('eventsPerInterval')}</span>
            </div>
            {activity.error ? (
              <p className="hx-note note">{L('activityUnavailable')}</p>
            ) : (
              <Beatline
                data={flow.points}
                loading={activity.loading && activity.data === null}
                caption={L('recentActivityCaption')}
                summary={activitySummary(lang, flow.total, FLOW_BUCKETS, flow.peak)}
                unit={L('eventsUnit')}
                valueHeader={L('eventsHeader')}
                labelHeader={L('timeHeader')}
                emptyTitle={L('noActivityYet')}
              />
            )}
          </section>
        </div>
      </div>

      {/* ── BOARD · the four real-data queues ───────────────────────────── */}
      <div className="grid wide">
        <section className="surface soft reveal">
          <div className="sec-head">
            <h2>{t('home.priorities')}</h2>
            <button type="button" className="chip" title={`${t('action.viewAll')} — ${t('home.priorities')}`} onClick={() => setRoute('tasks')}>
              {t('action.viewAll')}
            </button>
          </div>
          <Async state={active} emptyTitle={t('home.emptyPriorities')} emptyHint={t('home.emptyPrioritiesHint')}>
            {(items) => (
              <ul className="nba-list">
                {items.map((x) => (
                  <li key={x.id} className="nba-item">
                    <span className="nba-rank mono" aria-hidden="true">◆</span>
                    <div className="nba-txt"><b>{x.title}</b></div>
                    <span className={`pill ${pillTone(x.status)}`.trim()}>{label(x.status)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Async>
        </section>

        <section className="surface soft reveal">
          <div className="sec-head">
            <h2>{t('home.approvals')}</h2>
            <button type="button" className="chip" title={`${t('action.viewAll')} — ${t('home.approvals')}`} onClick={() => setRoute('approvals')}>
              {t('action.viewAll')}
            </button>
          </div>
          <Async state={approvals} emptyTitle={t('home.emptyApprovals')} emptyHint={t('home.emptyApprovalsHint')}>
            {(items) => (
              <ul className="nba-list">
                {items.map((a) => (
                  <li key={a.id} className="nba-item">
                    <span className="nba-rank mono" aria-hidden="true">⚑</span>
                    <div className="nba-txt"><b>{a.actionType}</b><span className="micro">{a.level}</span></div>
                    <span className="pill warn">{label(a.status)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Async>
        </section>

        <section className="surface soft reveal">
          <div className="sec-head">
            <h2>{t('home.agents')}</h2>
            <button type="button" className="chip" title={`${t('action.viewAll')} — ${t('home.agents')}`} onClick={() => setRoute('agents')}>
              {t('action.viewAll')}
            </button>
          </div>
          <Async state={agents} emptyTitle={t('home.emptyAgents')} emptyHint={t('home.emptyAgentsHint')}>
            {(items) => (
              <ul className="nba-list">
                {items.map((a) => (
                  <li key={a.id} className="nba-item">
                    <span className="nba-rank mono" aria-hidden="true">⬡</span>
                    <div className="nba-txt"><b>{a.displayName}</b><span className="micro">{a.role}</span></div>
                    <span className={`pill ${pillTone(a.status)}`.trim()}>{label(a.status)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Async>
        </section>

        <section className="surface soft reveal">
          <div className="sec-head">
            <h2>{t('nav.projects')}</h2>
            <button type="button" className="chip" title={`${t('action.viewAll')} — ${t('nav.projects')}`} onClick={() => setRoute('projects')}>
              {t('action.viewAll')}
            </button>
          </div>
          <Async state={projects} emptyTitle={t('home.emptyProjects')} emptyHint={t('home.emptyProjectsHint')}>
            {(items) => (
              <ul className="nba-list">
                {items.map((p) => (
                  <li key={p.id} className="nba-item">
                    <span className="nba-rank mono" aria-hidden="true">▤</span>
                    <div className="nba-txt"><b>{p.name}</b></div>
                    <span className={`pill ${pillTone(p.status)}`.trim()}>{label(p.status)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Async>
        </section>
      </div>
      </div>
    </>
  );
}

// Page-local chrome only: the derived-instruments strip, the three-up instrument
// board layout, and a reduced-motion guard for the ring sweep. Everything visual
// otherwise is shared aios classes (.ring/.surface/.sec-head/.chart/.barchart).
const HOME_STYLE = `
.v-home .hx-instruments{display:grid;gap:16px;margin-top:20px}
.v-home .hx-ratios{display:flex;flex-wrap:wrap;gap:12px}
.v-home .hx-ratio{flex:1 1 140px;display:grid;gap:3px;padding:12px 14px;border-radius:var(--r);
  border:1px solid rgb(var(--line-rgb)/.7);background:rgb(var(--raised-rgb)/.5)}
.v-home .hx-ratio b{font-family:var(--f-mono);font-size:24px;font-weight:700;line-height:1;letter-spacing:-.02em}
.v-home .hx-ratio b i{font-style:normal;font-size:13px;color:var(--ink-muted);font-weight:400;margin-left:1px}
.v-home .hx-ratio .micro{color:var(--ink-muted)}
.v-home .hx-board{display:grid;gap:20px;grid-template-columns:minmax(220px,.8fr) 1fr 1fr}
.v-home .hx-board>section{padding:20px}
.v-home .hx-resolve{display:grid;gap:14px;justify-items:center}
.v-home .hx-resolve .sec-head{width:100%}
.v-home .hx-note{color:var(--ink-muted);text-align:center;max-width:36ch;margin-inline:auto}
@media (max-width:1080px){
  .v-home .hx-board{grid-template-columns:1fr 1fr}
  .v-home .hx-resolve{grid-column:1 / -1}
}
@media (max-width:720px){ .v-home .hx-board{grid-template-columns:1fr} }
@media (prefers-reduced-motion:reduce){
  .v-home .hx-ring .value{animation:none;stroke-dashoffset:var(--off)}
}
`;
