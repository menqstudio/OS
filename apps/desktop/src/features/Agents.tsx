import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Badge, StatusPill, Avatar, Skeleton, ErrorState, EmptyState, Button,
} from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { desktop } from '../services/desktop';
import { ringPositions } from '../components/charts/Chart';
import type { Agent } from '../domain/entities';

// ── Phase 6 · `agents` ⬡ Կենդանի Ցանց — the live agent lattice ─────────────────
// Faithful to MASTER_EXECUTION_ROADMAP.md §D (lines 920-926): lattice/latStage/
// latLinks + dossier, per-agent state (idle/flowing/throttled/blocked/completed),
// owner + role; states live/loading/empty/error/blocked; link stream/emit motion,
// suspend/interrupt on throttle/block; arrow-navigate + Enter/Esc; role=list
// fallback, each node labeled "agent · role · state", state announced on change.
//
// HONEST DATA. Nodes render REAL agents from the `list_agents` Tauri command
// (services/desktop → domain Agent). The spec's fuller "engine supervisor live
// pack state" (per-agent lease_id / receipt_id live subscription) has NO backing
// command in this build, so the dossier renders an explicit honest "telemetry
// pending" panel instead of fabricating lease/receipt values.

// The five per-agent phases the spec names, derived from the real AgentStatus.
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

// Bilingual strings inlined (the shared i18n files are not edited). Falls back to
// English for any non-Armenian UI language.
type Lang = 'hy' | 'en';
const STR: Record<Lang, Record<string, string>> = {
  en: {
    networkTitle: 'Live Network',
    dossierTitle: 'Dossier',
    building: 'Building lattice…',
    linkLost: 'Link to the engine supervisor was lost — the live pack state is unavailable.',
    emptyTitle: 'No active agents',
    emptyHint: 'When the conductor dispatches a governed pack, its builders appear here.',
    conductor: 'conductor',
    conductorHint: 'One conductor · the desktop observes, never holds a lease',
    pickTitle: 'Select an agent',
    pickHint: 'Choose a node in the lattice — or press Enter — to open its dossier.',
    close: 'Close',
    role: 'Role',
    owner: 'Owner',
    model: 'Model',
    slug: 'Slug',
    agentId: 'Agent ID',
    phase: 'State',
    governed: 'Governed telemetry',
    telemetryPending:
      'Live lease & receipt telemetry is issued by the engine supervisor. That subscription is not wired in this build, so no lease_id / receipt_id is shown — the desktop never holds a lease.',
    blockedTitle: 'Agent blocked',
    blockedBody:
      'A governed turn for this agent was halted by the wall. Its result is withheld until a verified receipt is produced.',
    legend: 'State legend',
    keysHint: 'Arrows move between agents · Enter opens the dossier · Esc closes it',
    latticeLabel: 'Agent lattice',
    activeOf: 'active',
  },
  hy: {
    networkTitle: 'Կենդանի Ցանց',
    dossierTitle: 'Անձնագիր',
    building: 'Ցանցը կառուցվում է…',
    linkLost: 'Կապը շարժիչի վերահսկիչի հետ կորավ — կենդանի փաթեթի վիճակն անհասանելի է։',
    emptyTitle: 'Ակտիվ գործակալներ չկան',
    emptyHint: 'Երբ դիրիժորը ուղարկի կառավարվող փաթեթ, նրա կառուցողները կհայտնվեն այստեղ։',
    conductor: 'դիրիժոր',
    conductorHint: 'Մեկ դիրիժոր · աշխատասեղանը դիտում է, երբեք չի պահում լիզինգ',
    pickTitle: 'Ընտրեք գործակալ',
    pickHint: 'Ընտրեք հանգույց ցանցում — կամ սեղմեք Enter — բացելու համար նրա անձնագիրը։',
    close: 'Փակել',
    role: 'Դեր',
    owner: 'Տեր',
    model: 'Մոդել',
    slug: 'Ծածկագիր',
    agentId: 'Գործակալի ID',
    phase: 'Վիճակ',
    governed: 'Կառավարվող տվյալներ',
    telemetryPending:
      'Կենդանի լիզինգի և ստացականի տվյալները տրամադրվում են շարժիչի վերահսկիչի կողմից։ Այդ բաժանորդագրությունը միացված չէ այս կառուցվածքում, ուստի lease_id / receipt_id չի ցուցադրվում — աշխատասեղանը երբեք չի պահում լիզինգ։',
    blockedTitle: 'Գործակալն արգելափակված է',
    blockedBody:
      'Այս գործակալի կառավարվող քայլը կանգնեցվեց պատի կողմից։ Արդյունքը պահվում է մինչև ստուգված ստացականի ստեղծումը։',
    legend: 'Վիճակների լեգենդ',
    keysHint: 'Սլաքները տեղաշարժում են · Enter-ը բացում է անձնագիրը · Esc-ը փակում է',
    latticeLabel: 'Գործակալների ցանց',
    activeOf: 'ակտիվ',
  },
};

const PHASE_LABELS: Record<Lang, Record<Phase, string>> = {
  en: { idle: 'idle', flowing: 'flowing', throttled: 'throttled', blocked: 'blocked', completed: 'completed' },
  hy: { idle: 'պարապ', flowing: 'հոսող', throttled: 'զսպված', blocked: 'արգելափակված', completed: 'ավարտված' },
};

const PHASE_ORDER: Phase[] = ['idle', 'flowing', 'throttled', 'blocked', 'completed'];

// Node ring geometry comes from the shared, deterministic `ringPositions`
// (components/charts/geometry): evenly spaced coordinates on a 0..100 ring so the
// absolutely-positioned nodes and the SVG links stay aligned. The lattice itself
// stays bespoke (see DESIGN_SYSTEM §3.1) — only the geometry is shared.

function Dossier({ agent, L, phaseLabels }: { agent: Agent; L: Record<string, string>; phaseLabels: Record<Phase, string> }) {
  const phase = phaseOf(agent.status);
  return (
    <div className="stack" style={{ gap: 14 }}>
      <div className="row" style={{ gap: 10 }}>
        <Avatar name={agent.displayName} />
        <span style={{ minWidth: 0 }}>
          <div className="panel-title">{agent.displayName}</div>
          <div className="muted">{agent.role}</div>
        </span>
        <span style={{ marginLeft: 'auto' }}>
          <StatusPill status={agent.status} />
        </span>
      </div>

      {phase === 'blocked' && (
        <div className="lat-blocked" role="note">
          <div className="lat-blocked-title">⚠ {L.blockedTitle}</div>
          <div className="muted" style={{ marginTop: 4 }}>{L.blockedBody}</div>
        </div>
      )}

      <div className="lat-facts">
        <div className="field">
          <span className="field-label">{L.phase}</span>
          <span><Badge tone="neutral">{phaseLabels[phase]}</Badge></span>
        </div>
        <div className="field">
          <span className="field-label">{L.role}</span>
          <span>{agent.role}</span>
        </div>
        <div className="field">
          <span className="field-label">{L.owner}</span>
          <span>Bro · {L.conductor}</span>
        </div>
        <div className="field">
          <span className="field-label">{L.model}</span>
          <span>{agent.model ?? '—'}</span>
        </div>
        <div className="field">
          <span className="field-label">{L.slug}</span>
          <span className="lat-mono">{agent.slug}</span>
        </div>
        <div className="field">
          <span className="field-label">{L.agentId}</span>
          <span className="lat-mono">{agent.id}</span>
        </div>
      </div>

      <div className="lat-telemetry">
        <div className="field-label">{L.governed}</div>
        <div className="muted" style={{ marginTop: 6 }}>{L.telemetryPending}</div>
      </div>
    </div>
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
  const nodeRefs = useRef<(HTMLButtonElement | null)[]>([]);

  // Keep the roving focus index inside the current agent set.
  useEffect(() => {
    if (focusedIndex > agents.length - 1) setFocusedIndex(agents.length > 0 ? agents.length - 1 : 0);
  }, [agents.length, focusedIndex]);

  const selected = agents.find((a) => a.id === selectedId) ?? null;
  const focused = agents[focusedIndex] ?? null;

  // aria-live: announce the currently focused node's "agent · role · state" so a
  // screen-reader user hears the lattice change as they arrow across it.
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
    <PageHeader
      title={t('nav.agents')}
      subtitle={t('agents.subtitle')}
      actions={agents.length > 0 ? <Badge tone="accent">{`${agents.length} ${L.activeOf}`}</Badge> : undefined}
    />
  );

  // ── States: loading(building) · error(link lost) · empty(no active agents) ──
  if (state.loading && state.data === null) {
    return (
      <>
        {header}
        <style>{LATTICE_CSS}</style>
        <Panel title={L.networkTitle}>
          <div className="muted" style={{ marginBottom: 12 }} aria-live="polite">{L.building}</div>
          <Skeleton rows={5} />
        </Panel>
      </>
    );
  }

  if (state.error) {
    return (
      <>
        {header}
        <Panel title={L.networkTitle}>
          <ErrorState message={`${L.linkLost} ${state.error}`} onRetry={state.reload} retryLabel={t('action.retry')} />
        </Panel>
      </>
    );
  }

  if (agents.length === 0) {
    return (
      <>
        {header}
        <Panel title={L.networkTitle}>
          <EmptyState glyph="⬡" title={L.emptyTitle} hint={L.emptyHint} />
        </Panel>
      </>
    );
  }

  // ── Default: the live lattice + dossier ─────────────────────────────────────
  return (
    <>
      {header}
      <style>{LATTICE_CSS}</style>

      <div className="lat-live-announce" aria-live="polite">{announcement}</div>

      <div className="lat-layout">
        <Panel title={L.networkTitle}>
          <div className="lattice">
            {/* Decorative governance links from the central conductor to each node. */}
            <svg className="latLinks" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              {positions.map((p, i) => {
                const phase = phaseOf(agents[i].status);
                return (
                  <line
                    key={agents[i].id}
                    className={`lat-link lat-link--${phase}`}
                    x1={50}
                    y1={50}
                    x2={p.x}
                    y2={p.y}
                    vectorEffect="non-scaling-stroke"
                  />
                );
              })}
            </svg>

            {/* Central conductor hub — structural anchor of the lattice, not agent
                data. The desktop observes the pack; it holds no lease. */}
            <div className="lat-hub" aria-hidden="true" title={L.conductorHint}>
              <span className="lat-hub-glyph">⬡</span>
              <span className="lat-hub-name">Bro</span>
              <span className="lat-hub-role">{L.conductor}</span>
            </div>

            {/* Node list fallback: role=list, each node a listitem with a labeled,
                roving-tabindex button — the lattice IS the accessible list. */}
            <ul
              className="latStage"
              role="list"
              aria-label={L.latticeLabel}
              onKeyDown={onStageKeyDown}
            >
              {agents.map((a, i) => {
                const phase = phaseOf(a.status);
                const pos = positions[i];
                const label = `${a.displayName} · ${a.role} · ${phaseLabels[phase]}`;
                return (
                  <li
                    key={a.id}
                    role="listitem"
                    className="lat-node-slot"
                    style={{ left: `${pos.x}%`, top: `${pos.y}%` }}
                  >
                    <button
                      type="button"
                      ref={(el) => { nodeRefs.current[i] = el; }}
                      className={`lat-node lat-node--${phase}${a.id === selectedId ? ' lat-node--sel' : ''}`}
                      aria-label={label}
                      aria-pressed={a.id === selectedId}
                      tabIndex={i === focusedIndex ? 0 : -1}
                      title={label}
                      onFocus={() => setFocusedIndex(i)}
                      onClick={() => { setFocusedIndex(i); setSelectedId(a.id); }}
                    >
                      <span className="lat-node-avatar" aria-hidden="true">{a.displayName.slice(0, 1).toUpperCase()}</span>
                      <span className="lat-node-name">{a.displayName}</span>
                      <span className="lat-node-role">{a.role}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>

          {/* Legend + keyboard hint */}
          <div className="lat-legend" aria-label={L.legend}>
            {PHASE_ORDER.map((p) => (
              <span key={p} className="lat-legend-item">
                <span className={`lat-dot lat-node--${p}`} aria-hidden="true" />
                <span className="muted">{phaseLabels[p]}</span>
              </span>
            ))}
          </div>
          <div className="lat-keys muted">{L.keysHint}</div>
        </Panel>

        <Panel title={L.dossierTitle}>
          {selected ? (
            <>
              <div className="lat-dossier-head">
                <Button small variant="ghost" onClick={() => setSelectedId(null)} title={L.close}>✕</Button>
              </div>
              <Dossier agent={selected} L={L} phaseLabels={phaseLabels} />
            </>
          ) : (
            <EmptyState glyph="◍" title={L.pickTitle} hint={L.pickHint} />
          )}
        </Panel>
      </div>
    </>
  );
}

// Lattice-only styling, scoped by `lat-`/`lattice` class names so it never
// collides with the shared kit. All colors resolve through design tokens; every
// animation is disabled under prefers-reduced-motion.
const LATTICE_CSS = `
.lat-layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, 380px); gap: var(--menq-space-4); align-items: start; }
@media (max-width: 900px) { .lat-layout { grid-template-columns: 1fr; } }

.lat-live-announce { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }

.lattice { position: relative; width: 100%; min-height: 420px; }
.latLinks { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.lat-link { stroke: var(--brops-border); stroke-width: 1.5; fill: none; }
.lat-link--flowing { stroke: var(--brops-accent); stroke-dasharray: 4 5; animation: lat-stream 900ms linear infinite; }
.lat-link--completed { stroke: var(--menq-color-success); }
.lat-link--throttled { stroke: var(--menq-color-warning); stroke-dasharray: 3 6; }
.lat-link--blocked { stroke: var(--menq-color-danger); stroke-dasharray: 2 4; }
@keyframes lat-stream { to { stroke-dashoffset: -18; } }

.lat-hub { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  width: 92px; height: 92px; justify-content: center; border-radius: 50%;
  background: var(--brops-elevated); border: 1.5px solid var(--brops-accent);
  box-shadow: var(--menq-shadow-1); pointer-events: none; z-index: 1; }
.lat-hub-glyph { font-size: 20px; color: var(--brops-accent); line-height: 1; }
.lat-hub-name { font-weight: 700; font-size: 13px; }
.lat-hub-role { font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--brops-muted); }

.latStage { position: absolute; inset: 0; list-style: none; margin: 0; padding: 0; z-index: 2; }
.lat-node-slot { position: absolute; transform: translate(-50%, -50%); }

.lat-node { display: flex; flex-direction: column; align-items: center; gap: 3px;
  width: 104px; padding: 10px 8px; cursor: pointer; font: inherit; text-align: center;
  background: var(--brops-surface); color: var(--brops-text);
  border: 1.5px solid var(--brops-border); border-radius: var(--menq-radius-card);
  box-shadow: var(--menq-shadow-1);
  transition: border-color var(--menq-motion-fast), background var(--menq-motion-fast), transform var(--menq-motion-fast); }
.lat-node:hover { transform: translateY(-2px); }
.lat-node:focus-visible { outline: 2px solid var(--menq-color-focus); outline-offset: 2px; }
.lat-node--sel { border-color: var(--brops-accent); background: var(--menq-color-selected); }
.lat-node-avatar { width: 30px; height: 30px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center;
  background: var(--menq-color-selected); color: var(--brops-accent); font-weight: 700; font-size: 13px; }
.lat-node-name { font-weight: 600; font-size: 13px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lat-node-role { font-size: 11px; color: var(--brops-muted); max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* node state color, from semantic tokens (ring + avatar tint) */
.lat-node--idle .lat-node-avatar { background: var(--menq-color-hover); color: var(--brops-muted); }
.lat-node--flowing { border-color: color-mix(in srgb, var(--brops-accent) 60%, var(--brops-border)); }
.lat-node--flowing .lat-node-avatar { background: var(--menq-color-selected); color: var(--brops-accent); }
.lat-node--completed { border-color: color-mix(in srgb, var(--menq-color-success) 55%, var(--brops-border)); }
.lat-node--completed .lat-node-avatar { background: color-mix(in srgb, var(--menq-color-success) 18%, transparent); color: var(--menq-color-success); }
.lat-node--throttled { border-color: color-mix(in srgb, var(--menq-color-warning) 60%, var(--brops-border)); animation: lat-suspend 1.8s ease-in-out infinite; }
.lat-node--throttled .lat-node-avatar { background: color-mix(in srgb, var(--menq-color-warning) 18%, transparent); color: var(--menq-color-warning); }
.lat-node--blocked { border-color: var(--menq-color-danger); animation: lat-interrupt 1.1s ease-in-out infinite; }
.lat-node--blocked .lat-node-avatar { background: color-mix(in srgb, var(--menq-color-danger) 18%, transparent); color: var(--menq-color-danger); }

/* suspend = gentle breathing on a throttled node; interrupt = urgent pulse on block */
@keyframes lat-suspend { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }
@keyframes lat-interrupt { 0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--menq-color-danger) 45%, transparent); } 50% { box-shadow: 0 0 0 5px color-mix(in srgb, var(--menq-color-danger) 0%, transparent); } }

.lat-legend { display: flex; flex-wrap: wrap; gap: var(--menq-space-4); margin-top: var(--menq-space-4); padding-top: var(--menq-space-3); border-top: 1px solid var(--brops-border); }
.lat-legend-item { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; }
.lat-dot { width: 10px; height: 10px; border-radius: 50%; border: 1.5px solid var(--brops-border); background: var(--brops-surface); }
.lat-dot.lat-node--flowing { border-color: var(--brops-accent); background: var(--brops-accent); }
.lat-dot.lat-node--completed { border-color: var(--menq-color-success); background: var(--menq-color-success); }
.lat-dot.lat-node--throttled { border-color: var(--menq-color-warning); background: var(--menq-color-warning); animation: none; }
.lat-dot.lat-node--blocked { border-color: var(--menq-color-danger); background: var(--menq-color-danger); animation: none; }
.lat-dot.lat-node--idle { border-color: var(--brops-muted); background: transparent; }
.lat-keys { margin-top: var(--menq-space-3); font-size: 12px; }

.lat-dossier-head { display: flex; justify-content: flex-end; margin-bottom: -6px; }
.lat-facts { display: grid; grid-template-columns: 1fr 1fr; gap: var(--menq-space-3) var(--menq-space-4); }
.lat-mono { font-family: var(--menq-font-mono); font-size: 12px; word-break: break-all; }
.lat-telemetry { padding: var(--menq-space-3); background: var(--menq-color-hover); border: 1px dashed var(--brops-border); border-radius: var(--menq-radius-md); }
.lat-blocked { padding: var(--menq-space-3); border: 1px solid var(--menq-color-danger); border-radius: var(--menq-radius-md);
  background: color-mix(in srgb, var(--menq-color-danger) 10%, transparent); }
.lat-blocked-title { font-weight: 700; color: var(--menq-color-danger); }

@media (prefers-reduced-motion: reduce) {
  .lat-link--flowing, .lat-node--throttled, .lat-node--blocked, .lat-node:hover { animation: none; transition: none; }
  .lat-node:hover { transform: none; }
}
`;
