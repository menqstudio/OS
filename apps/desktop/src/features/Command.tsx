import { useState, useEffect, type CSSProperties } from 'react';
import { useApp } from '../app/store';
import {
  Badge, StatusPill, Async, Modal, FormRow, Input, Textarea, Select, Button, EmptyState,
} from '../components/ui';
import { Mark } from '../components/Ambient';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { Markdown } from '../components/markdown';
import { RUN_STATUSES } from '../domain/enums';
import type { Run, RunStep } from '../domain/entities';

// Scoped supplements to the global `aios.css` command-reactor design. The page is
// re-skinned to the "COMMAND REACTOR" mockup, but every value it shows is REAL —
// the run ledger (`list_runs`), the run's step chain (`list_run_steps`), streamed
// execution (`stream_run_step`), and the governed advance/add handlers. The
// mockup's fabricated instruments — the named ISP agent mesh, the assigned-team
// card, confidence/recall %, and the core-load sparkline — have NO backing in the
// `Run`/`RunStep` entities and are therefore OMITTED, never faked. The reactor
// orbit visual is kept purely decorative (aria-hidden); the HUD readouts show only
// honestly-countable step facts. Motion is disabled under prefers-reduced-motion.
const styles = `
.v-command .cmd-console{display:grid;gap:16px;min-width:0}
.v-command .reactor-panel .reactor{width:min(100%,360px)}
.v-command .cmd-step-form{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.v-command .cmd-step-form .cmd-approve{display:inline-flex;align-items:center;gap:5px;white-space:nowrap;
  font-family:var(--f-mono);font-size:9.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-muted)}
.v-command .cmd-actions{display:flex;gap:8px}
.v-command .cmd-live{margin:0;font-size:var(--t-small,13px);line-height:1.5}
.v-command .cmd-runs{display:grid;gap:8px;max-height:58vh;overflow-y:auto;padding-right:2px}
.v-command .cmd-runs .led{grid-template-columns:1fr auto;align-items:center;gap:10px;padding:11px 13px}
.v-command .cmd-runs .led-pick{display:grid;gap:5px;text-align:left;background:none;border:0;padding:0;
  cursor:pointer;color:inherit;min-width:0;font:inherit}
.v-command .cmd-runs .led-pick:focus-visible{outline:2px solid rgb(var(--cyan-rgb)/.6);outline-offset:3px;border-radius:8px}
.v-command .cmd-runs .led.on{border-color:rgb(var(--cyan-rgb)/.55);background:rgb(var(--cyan-rgb)/.06)}
.v-command .cmd-runs .led-ti{font-family:var(--f-display);font-size:13.5px;line-height:1.25;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.v-command .cmd-trace .node .cmd-detail{display:block;font-size:11px;color:var(--ink-muted);margin-top:2px}
.v-command .cmd-trace .node .run-step-result{margin-top:6px}
/* LIVE traveling pulse — a light dot riding down the dispatch rail while a step
   streams. Purely decorative (aria-hidden) and only rendered while executing; the
   REAL active step is marked by the shared .node.now::before pulse from aios.css. */
.v-command .cmd-trace .cmd-pulse{position:absolute;left:5px;top:0;width:7px;height:7px;
  transform:translate(-50%,-50%);border-radius:50%;background:var(--cyan-soft);pointer-events:none;z-index:2;
  box-shadow:0 0 12px rgb(var(--cyan-rgb)/.95),0 0 22px rgb(var(--cyan-rgb)/.5);
  animation:cmd-trace-travel 2.4s ease-in-out infinite}
@keyframes cmd-trace-travel{0%{top:0;opacity:0}14%{opacity:1}86%{opacity:1}100%{top:100%;opacity:0}}
@media (prefers-reduced-motion:reduce){.v-command .cmd-trace .cmd-pulse{display:none;animation:none}}
`;

// Ported from the mockup's `init()` motion gate: the reactor orbit/sweep and the
// trace pulse are decorative continuous motion, so they must go static under
// prefers-reduced-motion. The shared aios.css already freezes the orbit/sweep;
// this hook lets React drop the traveling pulse + dispatch beat entirely so
// nothing keeps animating for motion-sensitive operators.
function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState<boolean>(() =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
      : false);
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const sync = () => setReduced(mq.matches);
    sync();
    mq.addEventListener('change', sync);
    return () => mq.removeEventListener('change', sync);
  }, []);
  return reduced;
}

// Honest RunStep status → trace presentation. Colour/word mirror the real step
// status; nothing is shown as done/now unless the data says so.
function stepMeta(status: string): { node: string; rs: string; word: string } {
  switch ((status || '').toLowerCase()) {
    case 'done': return { node: 'done', rs: 'done', word: 'Ավարտ' };
    case 'active': return { node: 'now', rs: 'now', word: 'Ընթացքում' };
    case 'failed': return { node: '', rs: 'wait', word: 'Ձախողում' };
    case 'skipped': return { node: '', rs: 'wait', word: 'Բաց թողնված' };
    default: return { node: '', rs: 'wait', word: 'Սպասում' };
  }
}

function NewRunForm({ onClose, onCreated }: { onClose: () => void; onCreated: (run: Run) => void }) {
  const { t } = useApp();
  const [intent, setIntent] = useState('');
  const [plan, setPlan] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = () => {
    if (!intent.trim() || busy) return;
    setBusy(true);
    setError(null);
    desktop
      .createRun(intent.trim(), plan.trim())
      .then((run) => {
        onCreated(run);
        onClose();
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
        setBusy(false);
      });
  };

  return (
    <Modal title={t('command.newRun')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <FormRow label={t('field.intent')}>
        <Input value={intent} autoFocus onChange={(e) => setIntent(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.plan')}>
        <Textarea value={plan} onChange={(e) => setPlan(e.target.value)} />
      </FormRow>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="primary" onClick={submit}>{t('action.create')}</Button>
      </div>
    </Modal>
  );
}

// The reactor console for the SELECTED run: the hero reactor-panel (decorative
// orbit + real HUD counts + status readout), the governed step composer + advance/
// execute actions, streamed output, and the dispatch-trace timeline of real steps.
function RunConsole({ run, onChanged }: { run: Run; onChanged: () => void }) {
  const { t, setRoute } = useApp();
  const reduced = usePrefersReducedMotion();
  const steps = useAsync(() => desktop.listRunSteps(run.id), [run.id]);
  const [title, setTitle] = useState('');
  const [reqApproval, setReqApproval] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [stepStream, setStepStream] = useState('');
  const [execError, setExecError] = useState<string | null>(null);
  const [approvalNeeded, setApprovalNeeded] = useState(false);

  const advance = () => {
    desktop.advanceRun(run.id).then(() => { steps.reload(); onChanged(); }).catch(() => steps.reload());
  };
  const addStep = () => {
    const trimmed = title.trim();
    if (!trimmed) return;
    // The requires-approval flag rides straight into the real step: a step marked
    // here is created human-in-the-loop and will NOT auto-run.
    desktop.addRunStep(run.id, trimmed, '', reqApproval)
      .then(() => { setTitle(''); setReqApproval(false); steps.reload(); })
      .catch(() => steps.reload());
  };
  const execute = async () => {
    if (executing) return;
    setExecuting(true);
    setStepStream('');
    setExecError(null);
    setApprovalNeeded(false);
    try {
      await desktop.streamRunStep(run.id, (ev) => {
        if (ev.type === 'delta') setStepStream((prev) => prev + ev.text);
        // Governance stays intact: an approval-gated step halts the stream here
        // instead of auto-executing; the operator is routed to Approvals.
        else if (ev.type === 'approvalRequired') setApprovalNeeded(true);
        else if (ev.type === 'error') setExecError(ev.message);
      });
    } catch (e: unknown) {
      setExecError(e instanceof Error ? e.message : String(e));
    } finally {
      setExecuting(false);
      setStepStream('');
      steps.reload();
      onChanged();
    }
  };

  const terminal = run.status === 'succeeded' || run.status === 'failed' || run.status === 'cancelled';
  const items: RunStep[] = steps.data ?? [];
  const anyFailed = run.status === 'failed' || items.some((s) => s.status === 'failed');
  // Power mark from REAL state: thinking while streaming, alert on failure, idle
  // otherwise (never forced green/verified).
  const markState = executing ? 'thinking' : anyFailed ? 'alert' : 'idle';

  // HUD readouts — derived ENTIRELY from the real step chain. No fabricated
  // confidence/recall/linked-agent counts.
  const doneN = items.filter((s) => s.status === 'done').length;
  const activeN = items.filter((s) => s.status === 'active').length;
  const gatedN = items.filter((s) => s.requiresApproval).length;
  const hud = [
    { pos: 'tl', k: 'ՔԱՅԼԵՐ', v: items.length },
    { pos: 'tr', k: 'ԱՎԱՐՏ', v: doneN },
    { pos: 'bl', k: 'ԸՆԹԱՑՔ', v: activeN },
    { pos: 'br', k: 'ՀԱՍՏԱՏՈՒՄ', v: gatedN },
  ];

  return (
    <div className="cmd-console">
      {/* THE REACTOR — hero centerpiece for the selected run */}
      <section className="reactor-panel surface cut hud reveal" style={{ ['--i' as string]: 1 } as CSSProperties} aria-label={t('nav.command')}>
        <i className="bracket tl" aria-hidden="true" /><i className="bracket tr" aria-hidden="true" />
        <i className="bracket bl" aria-hidden="true" /><i className="bracket br" aria-hidden="true" />
        <div className="ticks" aria-hidden="true">{Array.from({ length: 12 }, (_, i) => <i key={i} />)}</div>

        <div className={`reactor${executing && !reduced ? ' dispatching' : ''}`}>
          <span className="reactor-sweep" aria-hidden="true" />
          <span className="orbit orbit-1" aria-hidden="true" />
          <span className="orbit orbit-2" aria-hidden="true" />
          <div className="reactor-core" aria-hidden="true">
            <div className="core" style={{ ['--core-size' as string]: '100%' } as CSSProperties}>
              <span className="halo" /><span className="halo inner" /><span className="disc" />
              <span className="glyphwrap"><Mark state={markState} style={{ width: '100%', height: '100%' }} /></span>
            </div>
            <span className="core-name">BRO · ՄԻՋՈՒԿ</span>
          </div>

          {/* live HUD readouts — real step counts, readable by AT */}
          {hud.map((h) => (
            <div key={h.pos} className={`r-hud ${h.pos}`}>
              <span className="rh-k">{h.k}</span>
              <span className="rh-v"><b>{h.v}</b></span>
            </div>
          ))}
        </div>

        <div className="reactor-foot">
          <StatusPill status={run.status} />
          <h2 className="cmd-active">{run.intent}</h2>
        </div>
      </section>

      {/* governed step composer + actions */}
      <div className="surface soft rail-card reveal" style={{ ['--i' as string]: 2 } as CSSProperties}>
        <div className="cmd-actions">
          <Button small variant="ghost" onClick={advance} disabled={executing || terminal}>{t('command.advance')}</Button>
          <Button small variant="primary" onClick={execute} disabled={executing || terminal}>{t('command.execute')}</Button>
        </div>
        <form
          className="cmd-step-form"
          onSubmit={(e) => { e.preventDefault(); addStep(); }}
        >
          <Input
            value={title}
            placeholder={t('command.addStep')}
            aria-label={t('command.addStep')}
            onChange={(e) => setTitle(e.target.value)}
            style={{ flex: 1, minWidth: 160 }}
          />
          <label className="cmd-approve" title={t('command.requiresApproval')}>
            <input type="checkbox" checked={reqApproval} onChange={(e) => setReqApproval(e.target.checked)} />
            <span>{t('command.requiresApproval')}</span>
          </label>
          <Button type="submit" variant="ghost">{t('command.addStep')}</Button>
        </form>

        {/* streamed execution + governance notices — visible and announced politely */}
        <div role="status" aria-live="polite">
          {executing && (
            <div className="run-step-result" style={{ marginTop: 4 }}>
              {stepStream
                ? <span>{stepStream}<span className="chat-cursor" /></span>
                : <span className="chat-typing"><span /><span /><span /></span>}
            </div>
          )}
          {approvalNeeded && (
            <p className="cmd-live" style={{ marginTop: 8 }}>
              <span className="pill warn">⚠ {t('command.approvalRequired')}</span>{' '}
              <Button small variant="ghost" onClick={() => setRoute('approvals')}>{t('command.goToApprovals')}</Button>
            </p>
          )}
          {execError && <p className="cmd-live" style={{ marginTop: 8 }}><span className="pill warn">⚠ {execError}</span></p>}
        </div>
      </div>

      {/* dispatch trace — the real step chain, announced as it progresses */}
      <div className="surface soft rail-card reveal" style={{ ['--i' as string]: 3 } as CSSProperties}>
        <div className="rail-head">
          <span className="eyebrow">ԱՌԱՔՄԱՆ ՀԵՏՔ</span>
          {executing && <span className="pill info">LIVE</span>}
        </div>
        <div className="timeline cmd-trace" aria-live="polite" aria-label={t('command.steps')}>
          {/* decorative LIVE pulse riding the rail — only while a step streams and
              only when motion is allowed; the real progress is the .now node below */}
          {executing && !reduced && <span className="cmd-pulse" aria-hidden="true" />}
          <Async state={steps} emptyTitle={t('command.noSteps')}>
            {(list) => (
              <>
                {[...list].sort((a, b) => a.position - b.position).map((s, i) => {
                  const m = stepMeta(s.status);
                  return (
                    <div key={s.id} className={`node ${m.node} reveal`.trim()} style={{ ['--i' as string]: i } as CSSProperties}>
                      <b>
                        <span className="mono" aria-hidden="true">{s.position}. </span>{s.title}
                        {s.requiresApproval && <> <Badge tone="warning">{t('command.requiresApproval')}</Badge></>}
                      </b>
                      {s.detail && <span className="cmd-detail">{s.detail}</span>}
                      <span className="route">
                        <em>{run.intent}</em>
                        <i className={`rs rs-${m.rs}`}>{m.word}</i>
                      </span>
                      {s.result && <div className="run-step-result"><Markdown text={s.result} /></div>}
                    </div>
                  );
                })}
              </>
            )}
          </Async>
        </div>
      </div>
    </div>
  );
}

export function Command() {
  const { t } = useApp();
  const [creating, setCreating] = useState(false);
  const [dockIntent, setDockIntent] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const s = useAsync(() => desktop.listRuns(), []);

  const changeStatus = (id: string, status: string) => {
    desktop.setRunStatus(id, status).then(() => s.reload()).catch(() => s.reload());
  };
  // Command-first quick create: the dock issues a run from a one-line intent.
  const dockCreate = () => {
    const intent = dockIntent.trim();
    if (!intent) return;
    desktop.createRun(intent, '').then((run) => {
      setDockIntent('');
      setSelectedId(run.id);
      s.reload();
    }).catch(() => s.reload());
  };

  return (
    <div className="v-command">
      <style>{styles}</style>

      <header className="pageHead">
        <div>
          <span className="eyebrow">ՀՐԱՄԱՆԻ ՄԻՋՈՒԿ · COMMAND REACTOR</span>
          <h1>{t('nav.command')}</h1>
          <p className="sub">{t('command.subtitle')}</p>
        </div>
        <div className="right">
          <Button variant="primary" onClick={() => setCreating(true)}>{t('action.new')}</Button>
        </div>
      </header>

      {creating && <NewRunForm onClose={() => setCreating(false)} onCreated={(run) => { setSelectedId(run.id); s.reload(); }} />}

      <div className="cmd-grid">
        <div className="cmd-main">
          {/* the floating command dock — quick-issue a run (command-first) */}
          <form
            className="cmd-dock reveal"
            style={{ ['--i' as string]: 0 } as CSSProperties}
            autoComplete="off"
            onSubmit={(e) => { e.preventDefault(); dockCreate(); }}
          >
            <div className="dock">
              <Mark state="live" className="dock-mark" style={{ width: 26, height: 26 }} />
              <input
                className="dock-input"
                value={dockIntent}
                aria-label={t('command.newRun')}
                placeholder={t('command.placeholder')}
                onChange={(e) => setDockIntent(e.target.value)}
              />
              <button type="submit" className="dock-run">Կատարել</button>
            </div>
            <div className="cmd-chips">
              <span className="micro chips-lbl">ԱՐԱԳ ՀՐԱՄԱՆ</span>
              <button type="button" className="chip" onClick={() => setCreating(true)}>＋ {t('command.newRun')}</button>
            </div>
          </form>

          <Async state={s} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
            {(runs) => {
              const selected = runs.find((r) => r.id === selectedId) ?? null;
              if (!selected) {
                return (
                  <section className="reactor-panel surface cut hud" aria-label={t('nav.command')}>
                    <i className="bracket tl" aria-hidden="true" /><i className="bracket tr" aria-hidden="true" />
                    <i className="bracket bl" aria-hidden="true" /><i className="bracket br" aria-hidden="true" />
                    <EmptyState
                      glyph="❖"
                      title={t('command.runs')}
                      hint={t('command.subtitle')}
                    />
                  </section>
                );
              }
              return <RunConsole key={selected.id} run={selected} onChanged={() => s.reload()} />;
            }}
          </Async>
        </div>

        {/* RAIL: the run ledger — selectable, keyboard-navigable */}
        <aside className="cmd-rail">
          <div className="surface soft rail-card reveal" style={{ ['--i' as string]: 2 } as CSSProperties}>
            <div className="rail-head">
              <h2 className="eyebrow" style={{ margin: 0 }}>{t('command.runs')}</h2>
            </div>
            <Async state={s} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
              {(runs) => (
                <div className="cmd-runs">
                  {runs.map((r, i) => (
                    <div
                      key={r.id}
                      className={`led surface soft rise state-idle${selectedId === r.id ? ' on' : ''}`}
                      style={{ ['--i' as string]: i + 2 } as CSSProperties}
                    >
                      <button
                        type="button"
                        className="led-pick"
                        aria-pressed={selectedId === r.id}
                        aria-label={`${r.intent} — ${r.status.replace(/_/g, ' ')}`}
                        onClick={() => setSelectedId(r.id)}
                      >
                        <span className="led-ti">{r.intent}</span>
                        <StatusPill status={r.status} />
                      </button>
                      <Select
                        value={r.status}
                        onChange={(e) => changeStatus(r.id, e.target.value)}
                        style={{ width: 'auto', padding: '4px 8px' }}
                        title={t('field.status')}
                        aria-label={t('field.status')}
                      >
                        {RUN_STATUSES.map((st) => (
                          <option key={st} value={st}>{st}</option>
                        ))}
                      </Select>
                    </div>
                  ))}
                </div>
              )}
            </Async>
          </div>
        </aside>
      </div>
    </div>
  );
}
