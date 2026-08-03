import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useApp } from '../app/store';
import { useAsync } from '../hooks/useAsync';
import { desktop } from '../services/desktop';
import { ringPositions } from '../components/charts/Chart';
import { Mark } from '../components/Ambient';
import type { Agent } from '../domain/entities';

// ── `agents` ⬡ Կենդանի Ցանց — the live agent lattice, dressed as the AI-OS mockup ─
// The mockup (views/agents.js · «Կենդանի Ցանց») is a living roster network with a
// state-census instrument and a re-forging dossier rail. This React port keeps the
// mockup's chrome — `.lattice-panel .surface .cut .hud` (brackets/ticks/eyebrow/
// legend/census) + a `.dossier .surface .soft` rail — but drives EVERY node from the
// REAL `list_agents` Tauri command (services/desktop → domain Agent) laid out on the
// shared, deterministic `ringPositions` lattice geometry. No fabricated roster.
//
// HONEST DATA. The mockup's fuller dossier (per-guild SKILLS, guild MATES, a live
// telemetry sparkline, a current-task line) has NO backing in the real `Agent`
// entity, so those fields are OMITTED rather than invented; the telemetry block
// renders an explicit "governed telemetry pending" note. What the entity really
// carries — displayName, role, status, model, slug, id — is all that is shown.

// The five per-agent phases, derived from the real AgentStatus string.
type Phase = 'idle' | 'flowing' | 'throttled' | 'blocked' | 'completed';

function phaseOf(status: string): Phase {
  switch (status) {
    case 'observing':
    case 'thinking':
    case 'working':
      return 'flowing';
    case 'review':
      return 'throttled';
    case 'blocked':
    case 'failed':
      return 'blocked';
    case 'completed':
      return 'completed';
    default: // offline, idle, or anything unknown
      return 'idle';
  }
}

// Phase → shared aios state class (drives the `--st-rgb` colour token used by the
// legend swatch, census segment, node ring and governance link).
const PHASE_STATE: Record<Phase, string> = {
  idle: 'state-idle',
  flowing: 'state-working',
  throttled: 'state-waiting',
  blocked: 'state-blocked',
  completed: 'state-completed',
};
// Phase → foundation `.pill` tone (`.bad` is the v-agents-local danger pill).
const PHASE_PILL: Record<Phase, string> = {
  idle: 'off',
  flowing: 'info',
  throttled: 'warn',
  blocked: 'bad',
  completed: 'live',
};
// Phase → GLYPH power-mark state (mockup rule: mark reflects the real status).
const PHASE_MARK: Record<Phase, string> = {
  idle: 'idle',
  flowing: 'live',
  throttled: 'thinking',
  blocked: 'alert',
  completed: 'live',
};

const PHASE_ORDER: Phase[] = ['flowing', 'throttled', 'idle', 'completed', 'blocked'];

// Bilingual strings inlined (the shared i18n files are not edited). Armenian reuses
// the mockup's own strings; English is the fallback for any non-Armenian UI.
type Lang = 'hy' | 'en';
const STR: Record<Lang, Record<string, string>> = {
  en: {
    eyebrow: 'Roster · Live Network',
    activeWord: 'active',
    agentWord: 'agents',
    censusLabel: 'State distribution',
    latticeLabel: 'Agent lattice',
    footHint: 'Pick a node to open its dossier',
    keysHint: 'Arrows move · Enter opens · Esc closes',
    building: 'Building lattice…',
    linkLost: 'Link to the engine supervisor was lost — the live pack state is unavailable.',
    emptyTitle: 'No active agents',
    emptyHint: 'When the conductor dispatches a governed pack, its builders appear here.',
    conductor: 'conductor',
    pickTitle: 'Select an agent',
    pickHint: 'Choose a node in the lattice — or press Enter — to open its dossier.',
    details: 'Details',
    owner: 'Owner',
    model: 'Model',
    slug: 'Slug',
    agentId: 'Agent ID',
    state: 'State',
    governed: 'Governed telemetry',
    telemetryPending:
      'Live lease & receipt telemetry is issued by the engine supervisor. That subscription is not wired in this build — no lease_id / receipt_id is shown, and the desktop never holds a lease.',
    blockedTitle: 'Agent blocked',
    blockedBody:
      'A governed turn for this agent was halted by the wall. Its result is withheld until a verified receipt is produced.',
    retry: 'Retry',
  },
  hy: {
    eyebrow: 'ՌՈՍՏԵՐ · ԿԵՆԴԱՆԻ ՑԱՆՑ',
    activeWord: 'ԱԿՏԻՎ',
    agentWord: 'ԳՈՐԾԱԿԱԼ',
    censusLabel: 'Վիճակների բաշխում',
    latticeLabel: 'Գործակալների ցանց',
    footHint: 'Ընտրի՛ր հանգույց՝ անձնագիրը բացելու համար',
    keysHint: 'Սլաքներ՝ տեղաշարժ · Enter՝ բացել · Esc՝ փակել',
    building: 'Ցանցը կառուցվում է…',
    linkLost: 'Կապը շարժիչի վերահսկիչի հետ կորավ — կենդանի փաթեթի վիճակն անհասանելի է։',
    emptyTitle: 'Ակտիվ գործակալներ չկան',
    emptyHint: 'Երբ դիրիժորը ուղարկի կառավարվող փաթեթ, նրա կառուցողները կհայտնվեն այստեղ։',
    conductor: 'դիրիժոր',
    pickTitle: 'Ընտրեք գործակալ',
    pickHint: 'Ընտրեք հանգույց ցանցում — կամ սեղմեք Enter — բացելու համար նրա անձնագիրը։',
    details: 'ՄԱՆՐԱՄԱՍՆԵՐ',
    owner: 'ՏԵՐ',
    model: 'ՄՈԴԵԼ',
    slug: 'ԾԱԾԿԱԳԻՐ',
    agentId: 'ԳՈՐԾԱԿԱԼԻ ID',
    state: 'ՎԻՃԱԿ',
    governed: 'ՀԵՌԱՉԱՓՈՒԹՅՈՒՆ',
    telemetryPending:
      'Կենդանի լիզինգի և ստացականի տվյալները տրամադրվում են շարժիչի վերահսկիչի կողմից։ Այդ բաժանորդագրությունը միացված չէ այս կառուցվածքում — lease_id / receipt_id չի ցուցադրվում, և աշխատասեղանը երբեք չի պահում լիզինգ։',
    blockedTitle: 'Գործակալն արգելափակված է',
    blockedBody:
      'Այս գործակալի կառավարվող քայլը կանգնեցվեց պատի կողմից։ Արդյունքը պահվում է մինչև ստուգված ստացականի ստեղծումը։',
    retry: 'Կրկնել',
  },
};

const PHASE_LABELS: Record<Lang, Record<Phase, string>> = {
  en: { idle: 'idle', flowing: 'flowing', throttled: 'throttled', blocked: 'blocked', completed: 'completed' },
  hy: { idle: 'պարապ', flowing: 'հոսող', throttled: 'զսպված', blocked: 'արգելափակված', completed: 'ավարտ' },
};

// ── The re-forging dossier rail — fills for the selected node ─────────────────
function Dossier({
  agent,
  L,
  phaseLabels,
}: {
  agent: Agent;
  L: Record<string, string>;
  phaseLabels: Record<Phase, string>;
}) {
  const phase = phaseOf(agent.status);
  return (
    <>
      <div className="dos-hd">
        <span className="dos-face"><Mark state={PHASE_MARK[phase]} size={54} /></span>
        <div className="dos-id">
          <b>{agent.displayName}</b>
          <span className="micro">{agent.role}</span>
        </div>
        <span className={`pill ${PHASE_PILL[phase]} dos-pill`}>{phaseLabels[phase]}</span>
      </div>

      <p className="dos-role">Bro · {L.conductor}</p>

      {phase === 'blocked' && (
        <div className="ag-blocked" role="note">
          <span className="micro">⚠ {L.blockedTitle}</span>
          <p>{L.blockedBody}</p>
        </div>
      )}

      <div className="dos-block">
        <span className="micro">{L.details}</span>
        <div className="ag-facts">
          <div className="ag-fact"><span className="ag-fk">{L.state}</span><span className={`pill ${PHASE_PILL[phase]}`}>{phaseLabels[phase]}</span></div>
          <div className="ag-fact"><span className="ag-fk">{L.owner}</span><span>Bro · {L.conductor}</span></div>
          <div className="ag-fact"><span className="ag-fk">{L.model}</span><span>{agent.model ?? '—'}</span></div>
          <div className="ag-fact"><span className="ag-fk">{L.slug}</span><span className="ag-mono">{agent.slug}</span></div>
          <div className="ag-fact ag-fact--wide"><span className="ag-fk">{L.agentId}</span><span className="ag-mono">{agent.id}</span></div>
        </div>
      </div>

      {/* Honest omission: the real Agent entity carries no live telemetry / skills /
          guild-mates, so the mockup's sparkline + skill grades + mate stack are not
          fabricated — this block states the governed telemetry is pending instead. */}
      <div className="dos-block">
        <span className="micro">{L.governed}</span>
        <p className="muted ag-telemetry">{L.telemetryPending}</p>
      </div>
    </>
  );
}

export function Agents() {
  const { t, lang } = useApp();
  const L = STR[lang === 'hy' ? 'hy' : 'en'];
  const phaseLabels = PHASE_LABELS[lang === 'hy' ? 'hy' : 'en'];
  const state = useAsync(() => desktop.listAgents(), []);

  const agents = useMemo(() => state.data ?? [], [state.data]);
  const positions = useMemo(() => ringPositions(agents.length), [agents.length]);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusedIndex, setFocusedIndex] = useState(0);
  const [filter, setFilter] = useState<Phase | null>(null);
  const nodeRefs = useRef<(HTMLButtonElement | null)[]>([]);

  // Roster state census — a real, live count per phase over the actual agents.
  const counts = useMemo(() => {
    const c: Record<Phase, number> = { idle: 0, flowing: 0, throttled: 0, blocked: 0, completed: 0 };
    for (const a of agents) c[phaseOf(a.status)] += 1;
    return c;
  }, [agents]);
  const active = counts.flowing + counts.throttled;

  // Keep the roving focus index inside the current agent set; open the first node
  // by default so the dossier rail is populated (mockup init select(0)).
  useEffect(() => {
    if (focusedIndex > agents.length - 1) setFocusedIndex(agents.length > 0 ? agents.length - 1 : 0);
  }, [agents.length, focusedIndex]);
  useEffect(() => {
    if (selectedId === null && agents.length > 0) setSelectedId(agents[0].id);
  }, [agents, selectedId]);

  const selected = agents.find((a) => a.id === selectedId) ?? null;
  const focused = agents[focusedIndex] ?? null;

  // aria-live: announce the focused node's "agent · role · state".
  const announcement = focused
    ? `${focused.displayName} · ${focused.role} · ${phaseLabels[phaseOf(focused.status)]}`
    : '';

  const moveFocus = (delta: number) => {
    const n = agents.length;
    if (n === 0) return;
    const next = (focusedIndex + delta + n) % n;
    setFocusedIndex(next);
    nodeRefs.current[next]?.focus();
  };

  const onStageKeyDown = (e: KeyboardEvent<HTMLUListElement>) => {
    if (agents.length === 0) return;
    switch (e.key) {
      case 'ArrowRight':
      case 'ArrowDown':
        e.preventDefault();
        moveFocus(1);
        break;
      case 'ArrowLeft':
      case 'ArrowUp':
        e.preventDefault();
        moveFocus(-1);
        break;
      case 'Enter':
      case ' ':
        e.preventDefault();
        setSelectedId(agents[focusedIndex]?.id ?? null);
        break;
      case 'Escape':
        if (selectedId) {
          e.preventDefault();
          setSelectedId(null);
        }
        break;
      default:
        break;
    }
  };

  const header = (
    <div className="pageHead">
      <div>
        <span className="eyebrow">{L.eyebrow}</span>
        <h1>{t('nav.agents')}</h1>
        <p className="sub">{t('agents.subtitle')}</p>
      </div>
      {agents.length > 0 && (
        <div className="right">
          <span className="pill live">{active} {L.activeWord}</span>
          <span className="pill info">{agents.length} {L.agentWord}</span>
        </div>
      )}
    </div>
  );

  // ── States: loading · error(link lost) · empty(no active agents) ────────────
  if (state.loading && state.data === null) {
    return (
      <div className="v-agents">
        <style>{AG_CSS}</style>
        {header}
        <section className="lattice-panel surface cut hud" aria-label={L.latticeLabel}>
          <i className="bracket tl" /><i className="bracket tr" /><i className="bracket bl" /><i className="bracket br" />
          <div className="muted" style={{ marginBottom: 14 }} aria-live="polite">{L.building}</div>
          <div className="ag-skel" aria-hidden="true"><i /><i /><i /><i /></div>
        </section>
      </div>
    );
  }

  if (state.error) {
    return (
      <div className="v-agents">
        <style>{AG_CSS}</style>
        {header}
        <section className="surface soft" role="alert" style={{ padding: 'var(--s6)' }}>
          <span className="eyebrow">{L.eyebrow}</span>
          <p className="muted" style={{ margin: '10px 0 14px', maxWidth: '60ch' }}>{`${L.linkLost} ${state.error}`}</p>
          <button type="button" className="ag-btn" onClick={state.reload}>{L.retry}</button>
        </section>
      </div>
    );
  }

  if (agents.length === 0) {
    return (
      <div className="v-agents">
        <style>{AG_CSS}</style>
        {header}
        <section className="surface soft ag-empty" role="status">
          <span className="ag-empty-glyph" aria-hidden="true">⬡</span>
          <div className="ag-empty-title">{L.emptyTitle}</div>
          <p className="muted">{L.emptyHint}</p>
        </section>
      </div>
    );
  }

  // ── Default: the live lattice + dossier ─────────────────────────────────────
  return (
    <div className="v-agents">
      <style>{AG_CSS}</style>
      {header}

      <span className="ag-sr" aria-live="polite">{announcement}</span>

      <div className="ros-wrap">
        {/* ── HERO · the roster lattice ─────────────────────────────────────── */}
        <section className="lattice-panel surface cut hud reveal" aria-label={L.latticeLabel}>
          <i className="bracket tl" /><i className="bracket tr" /><i className="bracket bl" /><i className="bracket br" />
          <div className="ticks" aria-hidden="true">
            {Array.from({ length: 12 }).map((_, i) => <i key={i} />)}
          </div>

          <div className="lat-top">
            <span className="eyebrow">{L.eyebrow}</span>
            <div className="lat-legend" aria-hidden="true">
              {PHASE_ORDER.map((p) => (
                <span key={p} className={`lg-key ${PHASE_STATE[p]}`}><i />{phaseLabels[p]}</span>
              ))}
            </div>
          </div>

          {/* the one live instrument — state census (click a segment to isolate) */}
          <div className="census" role="group" aria-label={L.censusLabel}>
            {PHASE_ORDER.map((p) => {
              const n = counts[p];
              const pressed = filter === p;
              return (
                <button
                  key={p}
                  type="button"
                  className={`cseg ${PHASE_STATE[p]}`}
                  style={{ flex: `${Math.max(n, 0.35)} 1 0` }}
                  aria-pressed={pressed}
                  aria-label={`${phaseLabels[p]} · ${n}`}
                  onClick={() => setFilter((f) => (f === p ? null : p))}
                >
                  <b>{n}</b>
                  <span className="cseg-k">{phaseLabels[p]}</span>
                </button>
              );
            })}
          </div>

          {/* the lattice: real agents on the shared ringPositions geometry */}
          <div className={`ag-stage${filter ? ' filtering' : ''}`}>
            <svg className="ag-links" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              {positions.map((pt, i) => {
                const ph = phaseOf(agents[i].status);
                const dim = filter !== null && ph !== filter;
                return (
                  <line
                    key={agents[i].id}
                    className={`ag-link ${PHASE_STATE[ph]}${dim ? ' dim' : ''}`}
                    x1={50}
                    y1={50}
                    x2={pt.x}
                    y2={pt.y}
                    vectorEffect="non-scaling-stroke"
                  />
                );
              })}
            </svg>

            {/* central conductor anchor — structural, not agent data. The desktop
                observes the pack and holds no lease. */}
            <div className="ag-hub" aria-hidden="true">
              <Mark state="live" size={30} />
              <span className="ag-hub-name">Bro</span>
              <span className="ag-hub-role">{L.conductor}</span>
            </div>

            <ul className="ag-nodes" role="list" aria-label={L.latticeLabel} onKeyDown={onStageKeyDown}>
              {agents.map((a, i) => {
                const phase = phaseOf(a.status);
                const pos = positions[i];
                const dim = filter !== null && phase !== filter;
                const label = `${a.displayName} · ${a.role} · ${phaseLabels[phase]}`;
                return (
                  <li
                    key={a.id}
                    role="listitem"
                    className="ag-slot"
                    style={{ left: `${pos.x}%`, top: `${pos.y}%` }}
                  >
                    <button
                      type="button"
                      ref={(el) => { nodeRefs.current[i] = el; }}
                      className={`ag-node ${PHASE_STATE[phase]}${a.id === selectedId ? ' sel' : ''}${dim ? ' dim' : ''}`}
                      aria-label={label}
                      aria-pressed={a.id === selectedId}
                      tabIndex={i === focusedIndex ? 0 : -1}
                      title={label}
                      onFocus={() => setFocusedIndex(i)}
                      onClick={() => { setFocusedIndex(i); setSelectedId(a.id); }}
                    >
                      <span className="ag-node-face"><Mark state={PHASE_MARK[phase]} size={26} /></span>
                      <span className="ag-node-name">{a.displayName}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>

          <div className="lat-foot">
            <span className="micro">{L.footHint}</span>
            <span className="lat-scan-lbl micro">◎ {L.keysHint}</span>
          </div>
        </section>

        {/* ── DOSSIER rail ──────────────────────────────────────────────────── */}
        <aside className="dossier surface soft reveal" aria-live="polite" aria-label={L.details}>
          {selected ? (
            <Dossier agent={selected} L={L} phaseLabels={phaseLabels} />
          ) : (
            <div className="ag-pick">
              <Mark state="idle" size={44} />
              <div className="ag-empty-title">{L.pickTitle}</div>
              <p className="muted">{L.pickHint}</p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

// Lattice-internal styling (scoped under `.v-agents`, prefixed `ag-`) for the radial
// stage, nodes, governance links, dossier facts and the state branches. The panel
// chrome (surface/cut/hud/bracket/ticks/eyebrow/lat-top/lat-legend/lg-key/census/
// cseg/lat-foot/dossier/dos-*/pill/micro/eyebrow) is the shared aios.css. Colours
// resolve through the `--st-rgb` phase token; motion honours prefers-reduced-motion.
const AG_CSS = `
.v-agents .ag-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}

.v-agents .ag-stage{position:relative;width:100%;min-height:440px;margin:var(--s4) 0 var(--s5)}
.v-agents .ag-links{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:1}
.v-agents .ag-link{stroke:rgb(var(--st-rgb)/.42);stroke-width:1.4;fill:none;transition:opacity var(--slow)}
.v-agents .ag-link.state-working{stroke-dasharray:4 5;animation:ag-stream 900ms linear infinite}
.v-agents .ag-link.dim{opacity:.12}
@keyframes ag-stream{to{stroke-dashoffset:-18}}

.v-agents .ag-hub{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:2;
  display:flex;flex-direction:column;align-items:center;gap:2px;width:96px;height:96px;justify-content:center;
  border-radius:50%;background:linear-gradient(158deg,rgb(var(--raised-rgb)/.97),rgb(var(--surface-rgb)/.9));
  border:1.5px solid rgb(var(--cyan-rgb)/.5);box-shadow:0 0 26px -6px rgb(var(--cyan-rgb)/.5);pointer-events:none}
.v-agents .ag-hub .mark{width:30px;height:30px}
.v-agents .ag-hub-name{font-family:var(--f-display);font-weight:700;font-size:13px;letter-spacing:-.01em}
.v-agents .ag-hub-role{font-family:var(--f-mono);font-size:8.5px;font-weight:700;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink-muted)}

.v-agents .ag-nodes{position:absolute;inset:0;list-style:none;margin:0;padding:0;z-index:3}
.v-agents .ag-slot{position:absolute;transform:translate(-50%,-50%)}
.v-agents .ag-node{display:flex;flex-direction:column;align-items:center;gap:4px;width:104px;padding:9px 8px;
  cursor:pointer;font:inherit;text-align:center;color:var(--ink);
  background:linear-gradient(158deg,rgb(var(--raised-rgb)/.96),rgb(var(--surface-rgb)/.9));
  border:1.5px solid rgb(var(--st-rgb)/.4);border-radius:14px;
  box-shadow:0 0 0 0 rgb(var(--st-rgb)/0),var(--shadow-1);
  transition:transform var(--slow),border-color var(--slow),box-shadow var(--slow),opacity var(--slow)}
.v-agents .ag-node .mark{width:26px;height:26px}
.v-agents .ag-node-name{font-family:var(--f-mono);font-size:10px;font-weight:600;letter-spacing:.02em;
  max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink-muted)}
.v-agents .ag-node:hover{transform:translateY(-2px);border-color:rgb(var(--st-rgb)/.65)}
.v-agents .ag-node:hover .ag-node-name{color:var(--ink)}
.v-agents .ag-node:focus-visible{outline:2px solid var(--cyan-soft);outline-offset:3px}
.v-agents .ag-node.sel{transform:translateY(-2px) scale(1.05);border-color:rgb(var(--st-rgb)/.9);
  box-shadow:0 0 22px -4px rgb(var(--st-rgb)/.6),var(--shadow-2)}
.v-agents .ag-node.sel .ag-node-name{color:var(--ink)}
.v-agents .ag-node.dim{opacity:.22;filter:grayscale(.4)}
.v-agents .ag-node.dim:hover{opacity:.55}
.v-agents .ag-node.state-working{animation:ag-glow 2.8s cubic-bezier(.4,0,.2,1) infinite}
.v-agents .ag-node.state-waiting{animation:ag-suspend 1.9s ease-in-out infinite}
.v-agents .ag-node.state-blocked{animation:ag-interrupt 1.2s ease-in-out infinite}
@keyframes ag-glow{0%,100%{box-shadow:0 0 8px -3px rgb(var(--st-rgb)/.3),var(--shadow-1)}
  50%{box-shadow:0 0 18px -2px rgb(var(--st-rgb)/.55),var(--shadow-1)}}
@keyframes ag-suspend{0%,100%{opacity:1}50%{opacity:.62}}
@keyframes ag-interrupt{0%,100%{box-shadow:0 0 0 0 rgb(var(--st-rgb)/.45),var(--shadow-1)}
  50%{box-shadow:0 0 0 5px rgb(var(--st-rgb)/0),var(--shadow-1)}}

/* dossier facts + honest telemetry */
.v-agents .ag-facts{display:grid;grid-template-columns:1fr 1fr;gap:var(--s3) var(--s4)}
.v-agents .ag-fact{display:flex;flex-direction:column;gap:4px;min-width:0}
.v-agents .ag-fact--wide{grid-column:1 / -1}
.v-agents .ag-fk{font-family:var(--f-mono);font-size:8.5px;font-weight:700;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink-muted)}
.v-agents .ag-mono{font-family:var(--f-mono);font-size:11px;word-break:break-all;color:var(--ink)}
.v-agents .ag-telemetry{font-size:12px;line-height:1.5;margin:0}
.v-agents .ag-blocked{padding:var(--s3) var(--s4);border-radius:12px;
  border:1px solid rgb(var(--danger-rgb)/.35);background:rgb(var(--danger-rgb)/.08)}
.v-agents .ag-blocked .micro{color:var(--danger)}
.v-agents .ag-blocked p{margin:5px 0 0;font-size:12px;line-height:1.5;color:var(--ink-muted)}

/* state branches: loading skeleton · error · empty · pick */
.v-agents .ag-skel{display:grid;gap:10px}
.v-agents .ag-skel i{height:16px;border-radius:8px;
  background:linear-gradient(90deg,transparent,rgb(var(--cyan-rgb)/.14) 40%,rgb(var(--line-rgb)/.9) 50%,rgb(var(--cyan-rgb)/.14) 60%,transparent);
  background-size:200% 100%;animation:ag-shimmer 1.4s linear infinite}
.v-agents .ag-skel i:nth-child(2){width:82%}.v-agents .ag-skel i:nth-child(3){width:64%}.v-agents .ag-skel i:nth-child(4){width:73%}
@keyframes ag-shimmer{from{background-position:200% 0}to{background-position:-200% 0}}
.v-agents .ag-btn{font:inherit;font-size:13px;font-weight:600;height:32px;padding:0 16px;cursor:pointer;
  color:var(--cyan);border:1px solid rgb(var(--cyan-rgb)/.4);background:rgb(var(--cyan-rgb)/.08);border-radius:var(--r-pill)}
.v-agents .ag-btn:hover{background:rgb(var(--cyan-rgb)/.14)}
.v-agents .ag-btn:focus-visible{outline:2px solid var(--cyan-soft);outline-offset:2px}
.v-agents .ag-empty,.v-agents .ag-pick{text-align:center;padding:var(--s7) var(--s5);display:grid;gap:8px;place-items:center}
.v-agents .ag-empty-glyph{font-size:34px;color:var(--cyan-soft)}
.v-agents .ag-empty-title{font-family:var(--f-display);font-weight:700;font-size:17px}
.v-agents .ag-pick .muted,.v-agents .ag-empty .muted{max-width:34ch;font-size:13px;line-height:1.5}

@media (max-width:560px){.v-agents .ag-node{width:88px}}
@media (prefers-reduced-motion:reduce){
  .v-agents .ag-link.state-working,.v-agents .ag-node.state-working,
  .v-agents .ag-node.state-waiting,.v-agents .ag-node.state-blocked,
  .v-agents .ag-skel i{animation:none}
  .v-agents .ag-node{transition:none}
}
`;
