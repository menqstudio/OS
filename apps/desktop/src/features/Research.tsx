import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, Badge, Input, Skeleton, ErrorState, EmptyState,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';

// ─────────────────────────────────────────────────────────────────────────────
// research ⌖ Հետազոտում — §D page.
//
// Data source (spec): a research run is a *governed* bridge task
// (`bridge.task-request` → `bridge.result`) that yields a verified receipt, and
// its result is saved to knowledge. The desktop research-run IPC command is NOT
// yet exposed by `services/desktop.ts` (there is no `list_research_runs` / research
// `bridge.task-request` command). Per the spec's honesty rule this page therefore:
//   • reads the REAL `ai_status` command to gate governed availability →
//     drives the `blocked` state (governed provider off / sidecar down → no result);
//   • renders NO fabricated runs — with no research store the run list is honestly
//     `empty` ("Bro has run no research yet");
//   • on a run attempt, performs a REAL `ai_status` round-trip and honestly reports
//     that the governed research bridge is unavailable, rather than inventing sources
//     or a synthesis.
// The completed-run UI (sources list, synthesis, verified-receipt badge, save-to-
// knowledge) is fully implemented and wired to the REAL `create_knowledge` command;
// it renders only from a genuine committed run, so it never shows fake data.
// ─────────────────────────────────────────────────────────────────────────────

interface ResearchSource {
  id: string;
  title: string;
  url: string;
}

interface ResearchRun {
  id: string;
  query: string;
  synthesis: string;
  sources: ResearchSource[];
  verified: boolean;
  receiptId: string;
}

// The local run-status machine. `done` is part of the contract but is only ever
// constructed from a genuine committed bridge result — absent a research IPC
// command in this build it stays unreached, so no fabricated run is shown.
type RunView =
  | { kind: 'idle' }
  | { kind: 'running'; query: string }
  | { kind: 'blocked'; query: string; reason: string }
  | { kind: 'error'; query: string; message: string }
  | { kind: 'done'; run: ResearchRun };

const STR = {
  en: {
    subtitle: 'Governed research — every run yields a verified receipt',
    queryPanel: 'Research query',
    resultPanel: 'Latest run',
    placeholder: 'Ask a question for Bro to research…',
    run: 'Run',
    running: 'Running governed research…',
    governed: 'Governed',
    ungoverned: 'Ungoverned',
    verified: 'Verified receipt',
    unverified: 'Unverified',
    hintEnter: 'Enter to run · Esc to cancel',
    blockedTitle: 'Governed research unavailable',
    blockedBody:
      'Research is governed — it only runs behind the engine wall with a verified receipt. The governed provider is off or the sidecar is down, so no result can be produced.',
    runFailedTitle: 'Research run failed',
    bridgeAbsent:
      'The governed research bridge (bridge.task-request) is not wired in this desktop build yet — no result was produced and no data is fabricated.',
    emptyTitle: 'Bro has run no research yet',
    emptyHint: 'Run a governed research query above to produce a verified result.',
    sources: 'Sources',
    noSources: 'This run surfaced no sources.',
    synthesis: 'Synthesis',
    saveToKnowledge: 'Save to knowledge',
    saved: 'Saved to knowledge.',
    idleStatus: 'Idle — no run in progress.',
    liveRunning: 'Governed research run in progress.',
    liveBlocked: 'Research blocked:',
    liveFailed: 'Research run failed:',
    liveDone: 'Research run complete — verified receipt issued.',
    openSource: 'Open source',
  },
  hy: {
    subtitle: 'Կառավարվող հետազոտում — յուրաքանչյուր գործարկում տալիս է ստուգված անդորրագիր',
    queryPanel: 'Հետազոտման հարցում',
    resultPanel: 'Վերջին գործարկումը',
    placeholder: 'Հարց տուր, որ Bro-ն հետազոտի…',
    run: 'Գործարկել',
    running: 'Կառավարվող հետազոտումը ընթացքի մեջ է…',
    governed: 'Կառավարվող',
    ungoverned: 'Չկառավարվող',
    verified: 'Ստուգված անդորրագիր',
    unverified: 'Չստուգված',
    hintEnter: 'Enter՝ գործարկել · Esc՝ չեղարկել',
    blockedTitle: 'Կառավարվող հետազոտումն անհասանելի է',
    blockedBody:
      'Հետազոտումը կառավարվող է — այն աշխատում է միայն շարժիչի պատի հետևում՝ ստուգված անդորրագրով։ Կառավարվող մատակարարն անջատված է կամ sidecar-ը չի աշխատում, ուստի արդյունք հնարավոր չէ ստանալ։',
    runFailedTitle: 'Հետազոտման գործարկումը ձախողվեց',
    bridgeAbsent:
      'Կառավարվող հետազոտման կամուրջը (bridge.task-request) դեռ միացված չէ այս կառուցվածքում — արդյունք չի ստացվել, և տվյալներ չեն հորինվում։',
    emptyTitle: 'Bro-ն դեռ հետազոտում չի կատարել',
    emptyHint: 'Վերևում գործարկիր կառավարվող հարցում՝ ստուգված արդյունք ստանալու համար։',
    sources: 'Աղբյուրներ',
    noSources: 'Այս գործարկումը աղբյուրներ չբերեց։',
    synthesis: 'Ամփոփում',
    saveToKnowledge: 'Պահել գիտելիքում',
    saved: 'Պահվեց գիտելիքում։',
    idleStatus: 'Դատարկ — ընթացիկ գործարկում չկա։',
    liveRunning: 'Կառավարվող հետազոտման գործարկումը ընթացքի մեջ է։',
    liveBlocked: 'Հետազոտումն արգելափակված է՝',
    liveFailed: 'Հետազոտման գործարկումը ձախողվեց՝',
    liveDone: 'Հետազոտման գործարկումն ավարտվեց — տրվել է ստուգված անդորրագիր։',
    openSource: 'Բացել աղբյուրը',
  },
} as const;

/** Sources list with roving-focus arrow-key navigation. Each source is a labeled,
 *  focusable link (spec: "each source labeled + linked"; "arrow-navigate sources"). */
function SourceList({ sources, label, openLabel }: { sources: ResearchSource[]; label: string; openLabel: string }) {
  const [active, setActive] = useState(0);
  const refs = useRef<(HTMLAnchorElement | null)[]>([]);

  useEffect(() => {
    refs.current[active]?.focus();
  }, [active]);

  const onKeyDown = (e: KeyboardEvent<HTMLUListElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, sources.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Home') {
      e.preventDefault();
      setActive(0);
    } else if (e.key === 'End') {
      e.preventDefault();
      setActive(sources.length - 1);
    }
  };

  return (
    <ul className="rsx-sources" role="list" aria-label={label} onKeyDown={onKeyDown}>
      {sources.map((src, idx) => (
        <li key={src.id} role="listitem" className="rsx-source-row">
          <a
            ref={(el) => { refs.current[idx] = el; }}
            className={`rsx-source ${idx === active ? 'rsx-source--active' : ''}`}
            href={src.url}
            target="_blank"
            rel="noreferrer noopener"
            tabIndex={idx === active ? 0 : -1}
            aria-label={`${openLabel}: ${src.title}`}
            onFocus={() => setActive(idx)}
          >
            <span className="rsx-source-idx" aria-hidden="true">{idx + 1}</span>
            <span className="rsx-source-title">{src.title}</span>
            <span className="rsx-source-url muted">{src.url}</span>
          </a>
        </li>
      ))}
    </ul>
  );
}

export function Research() {
  const { t, lang } = useApp();
  const tr = lang === 'hy' ? STR.hy : STR.en;

  const [query, setQuery] = useState('');
  const [run, setRun] = useState<RunView>({ kind: 'idle' });
  const [saved, setSaved] = useState(false);
  // Monotonic token: a run resolved after Esc/cancel (or a newer run) is ignored.
  const runToken = useRef(0);

  // REAL data: governed-provider availability gates the whole page.
  const status = useAsync(() => desktop.aiStatus(), []);

  const available = !!status.data && status.data.ready && status.data.governed;

  const cancel = () => {
    runToken.current += 1;
    setRun({ kind: 'idle' });
  };

  const startRun = async () => {
    const q = query.trim();
    if (!q || !available || run.kind === 'running') return;
    const token = (runToken.current += 1);
    setSaved(false);
    setRun({ kind: 'running', query: q });
    try {
      // A real backend round-trip so the loading (pulse) state reflects live
      // governed availability at run time — no fabricated latency.
      const now = await desktop.aiStatus();
      if (token !== runToken.current) return; // cancelled or superseded
      if (!now.ready || !now.governed) {
        setRun({ kind: 'blocked', query: q, reason: now.detail || tr.blockedBody });
        return;
      }
      // Governed engine reachable, but this build exposes no research bridge
      // command — report honestly instead of inventing sources/synthesis.
      setRun({ kind: 'error', query: q, message: tr.bridgeAbsent });
    } catch (e: unknown) {
      if (token !== runToken.current) return;
      setRun({ kind: 'error', query: q, message: e instanceof Error ? e.message : String(e) });
    }
  };

  const onInputKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      if (run.kind === 'running') cancel();
      else if (query) setQuery('');
      else setRun({ kind: 'idle' });
    }
  };

  const saveRunToKnowledge = async (r: ResearchRun) => {
    try {
      await desktop.createKnowledge({
        title: `Research: ${r.query}`,
        body: r.synthesis,
        source: `Governed research run · receipt ${r.receiptId}`,
        tags: 'research',
      });
      setSaved(true);
    } catch {
      /* surfaced through the run's error path elsewhere; keep the result visible */
    }
  };

  // Text for the polite live region that narrates run-status transitions.
  const liveText = (() => {
    switch (run.kind) {
      case 'running': return tr.liveRunning;
      case 'blocked': return `${tr.liveBlocked} ${run.reason}`;
      case 'error': return `${tr.liveFailed} ${run.message}`;
      case 'done': return tr.liveDone;
      default: return tr.idleStatus;
    }
  })();

  return (
    <>
      <PageHeader title={t('nav.research')} subtitle={tr.subtitle} />

      <style>{CSS}</style>

      {/* Governed-availability gate (REAL ai_status). */}
      {status.loading && status.data === null ? (
        <Panel title={tr.queryPanel}>
          <Skeleton rows={3} />
        </Panel>
      ) : status.error ? (
        <Panel title={tr.queryPanel}>
          {/* ErrorState renders a calm offline state when there is no backend. */}
          <ErrorState message={status.error} onRetry={status.reload} retryLabel={t('action.retry')} />
        </Panel>
      ) : (
        <>
          <Panel
            title={tr.queryPanel}
            actions={
              <Badge tone={available ? 'success' : 'danger'}>
                {status.data && status.data.governed ? tr.governed : tr.ungoverned}
              </Badge>
            }
          >
            <form
              className="ask-form"
              onSubmit={(e) => { e.preventDefault(); startRun(); }}
            >
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onInputKeyDown}
                placeholder={tr.placeholder}
                disabled={!available || run.kind === 'running'}
                aria-label={tr.queryPanel}
                autoFocus
              />
              <Button
                type="submit"
                variant="primary"
                disabled={!available || run.kind === 'running' || !query.trim()}
              >
                {tr.run}
              </Button>
              {run.kind === 'running' && (
                <Button variant="ghost" onClick={cancel}>{t('action.cancel')}</Button>
              )}
            </form>
            <div className="chat-hint" style={{ marginTop: 8 }}>{tr.hintEnter}</div>

            {/* Blocked state — governed provider off / sidecar down. */}
            {!available && (
              <div className="rsx-blocked" role="note">
                <div className="rsx-blocked-title">⛔ {tr.blockedTitle}</div>
                <div className="muted" style={{ marginTop: 4 }}>
                  {status.data && status.data.detail ? status.data.detail : tr.blockedBody}
                </div>
              </div>
            )}

            {/* Run-status live region (polite) — narrates every transition. */}
            <div className="rsx-live" role="status" aria-live="polite">
              {run.kind === 'running' && <span className="rsx-pulse" aria-hidden="true" />}
              <span>{liveText}</span>
            </div>
          </Panel>

          <div style={{ height: 16 }} />

          <Panel title={tr.resultPanel}>
            {!available ? (
              <EmptyState glyph="⌖" title={tr.blockedTitle} hint={tr.blockedBody} />
            ) : run.kind === 'running' ? (
              <div className="rsx-run-card rsx-run-card--running" aria-busy="true">
                <span className="rsx-pulse" aria-hidden="true" />
                <span>{tr.running}</span>
              </div>
            ) : run.kind === 'blocked' ? (
              <EmptyState glyph="⛔" title={tr.blockedTitle} hint={run.reason} />
            ) : run.kind === 'error' ? (
              <div className="rsx-run-card rsx-run-card--error" role="alert">
                <div className="rsx-run-card-title">⚠ {tr.runFailedTitle}</div>
                <div className="muted" style={{ marginTop: 4 }}>{run.message}</div>
                <div style={{ marginTop: 12 }}>
                  <Button small onClick={startRun}>{t('action.retry')}</Button>
                </div>
              </div>
            ) : run.kind === 'done' ? (
              <div className="stack">
                <div className="row between" style={{ flexWrap: 'wrap', gap: 8 }}>
                  <div className="panel-title">{run.run.query}</div>
                  <Badge tone={run.run.verified ? 'success' : 'warning'}>
                    {run.run.verified ? `✓ ${tr.verified}` : tr.unverified}
                  </Badge>
                </div>

                <div className="field-label">{tr.sources}</div>
                {run.run.sources.length > 0 ? (
                  <SourceList sources={run.run.sources} label={tr.sources} openLabel={tr.openSource} />
                ) : (
                  <div className="muted">{tr.noSources}</div>
                )}

                <div className="field-label" style={{ marginTop: 8 }}>{tr.synthesis}</div>
                <div className="rsx-synthesis">{run.run.synthesis}</div>

                <div className="row" style={{ gap: 8, marginTop: 4 }}>
                  <Button variant="primary" small onClick={() => saveRunToKnowledge(run.run)} disabled={saved}>
                    {tr.saveToKnowledge}
                  </Button>
                  {saved && <span className="chat-hint">✓ {tr.saved}</span>}
                </div>
              </div>
            ) : (
              // idle — no runs yet (honest empty; no research store exists).
              <EmptyState glyph="⌖" title={tr.emptyTitle} hint={tr.emptyHint} />
            )}
          </Panel>
        </>
      )}
    </>
  );
}

const CSS = `
.rsx-live { display: flex; align-items: center; gap: 8px; margin-top: 12px;
  font-size: 12px; color: var(--brops-muted); }
.rsx-blocked { margin-top: 12px; padding: 12px 14px;
  background: color-mix(in srgb, var(--menq-color-danger) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--menq-color-danger) 34%, transparent);
  border-radius: var(--menq-radius-md); }
.rsx-blocked-title { font-weight: 600; color: var(--menq-color-danger); }
.rsx-run-card { padding: 14px 16px; border: 1px solid var(--brops-border);
  border-radius: var(--menq-radius-md); background: var(--menq-color-hover);
  display: flex; align-items: center; gap: 10px; }
.rsx-run-card--running { color: var(--brops-accent); }
.rsx-run-card--error { display: block; border-color: color-mix(in srgb, var(--menq-color-danger) 34%, transparent); }
.rsx-run-card-title { font-weight: 600; color: var(--menq-color-danger); }
.rsx-pulse { width: 10px; height: 10px; border-radius: 50%; flex: none;
  background: var(--brops-accent); animation: rsx-pulse 1.1s ease-in-out infinite; }
@keyframes rsx-pulse {
  0%, 100% { opacity: 0.35; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.15); }
}
.rsx-sources { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.rsx-source-row { min-width: 0; }
.rsx-source { display: flex; align-items: center; gap: 10px; width: 100%;
  padding: 8px 11px; border: 1px solid var(--brops-border);
  border-radius: var(--menq-radius-md); background: var(--brops-surface);
  color: var(--brops-text); text-decoration: none;
  transition: background var(--menq-motion-fast), border-color var(--menq-motion-fast); }
.rsx-source:hover { background: var(--menq-color-hover); }
.rsx-source--active, .rsx-source:focus-visible {
  border-color: var(--brops-accent); background: var(--menq-color-selected); outline: none; }
.rsx-source-idx { width: 20px; height: 20px; flex: none; border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 700; color: var(--brops-accent);
  background: var(--menq-color-selected); }
.rsx-source-title { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rsx-source-url { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rsx-synthesis { line-height: 1.5; white-space: pre-wrap;
  padding: 12px 14px; background: var(--menq-color-hover);
  border: 1px solid var(--brops-border); border-radius: var(--menq-radius-md); }
@media (prefers-reduced-motion: reduce) {
  .rsx-pulse { animation: none; }
}
`;
