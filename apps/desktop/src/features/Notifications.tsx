import {
  useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent,
} from 'react';
import { useApp } from '../app/store';
import {
  Button, Badge, EmptyState, Skeleton, ErrorState,
} from '../components/ui';
import { Mark } from '../components/Ambient';
import { useAsync } from '../hooks/useAsync';
import { desktop } from '../services/desktop';
import { hasRecords, recordCount, isUnauthenticatedMirror } from '../services/governance';
import type { Notification } from '../domain/entities';
import { statusTone } from '../domain/enums';
import { severityLabel } from '../domain/statusLabels';
import { STR } from './Notifications.strings';

// Fixed priority order for the severity filter chips (most severe first).
const SEVERITY_ORDER = ['critical', 'error', 'warning', 'success', 'info'];

// Semantic-token color for a signal's severity accent (left rail + focus).
function severityColor(sev: string): string {
  switch (sev) {
    case 'info': return 'var(--menq-color-info)';
    case 'success': return 'var(--menq-color-success)';
    case 'warning': return 'var(--menq-color-warning)';
    case 'error':
    case 'critical': return 'var(--menq-color-danger)';
    default: return 'var(--brops-border)';
  }
}

// Power-mark posture from real severity: warning/error/critical draws attention
// (`alert`); everything else sits `idle`. NEVER forced to a green/live "verified"
// state — the desktop mirrors signals, it does not certify them.
function markState(sev: string): string {
  return /warning|error|critical/.test(sev) ? 'alert' : 'idle';
}

// A chip either matches everything, unread only, or one severity value. Severity
// values never collide with the two reserved words, so a plain string is enough.
type Filter = 'all' | 'unread' | string;

export function Notifications() {
  const { t, lang } = useApp();
  const state = useAsync<Notification[]>(() => desktop.listNotifications());
  // Real, READ-ONLY engine governance-event stream (mirrored via the evidence chain).
  // Steady state in Phase-2 is blocked/unreachable — the gate panel below renders that
  // honestly from the actual IPC result, never a fabricated stream.
  const gov = useAsync(() => desktop.readEvidenceChain());
  const [filter, setFilter] = useState<Filter>('unread');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const itemRefs = useRef(new Map<string, HTMLDivElement>());

  const L = (k: keyof typeof STR): string => STR[k][lang] ?? STR[k].en;

  const dateFmt = useMemo(
    () => new Intl.DateTimeFormat(lang, { dateStyle: 'medium', timeStyle: 'short' }),
    [lang],
  );
  // `createdAt` may be an epoch-millis string or an ISO instant; parse defensively.
  const fmtDate = (raw: string): string => {
    const s = raw.trim();
    if (!s) return '';
    const d = new Date(isNaN(Number(s)) ? s : Number(s));
    return isNaN(d.getTime()) ? raw : dateFmt.format(d);
  };

  const items = useMemo(() => state.data ?? [], [state.data]);

  // Severities actually present, in fixed priority order, for the filter chips.
  const severities = useMemo(() => {
    const present = new Set(items.map((n) => n.severity));
    return SEVERITY_ORDER.filter((s) => present.has(s));
  }, [items]);

  const unreadCount = useMemo(() => items.filter((n) => n.readAt === null).length, [items]);

  const visible = useMemo(() => items.filter((n) => {
    if (filter === 'all') return true;
    if (filter === 'unread') return n.readAt === null;
    return n.severity === filter;
  }), [items, filter]);

  // The "current triage" readout in the hero is a REAL signal, not a fabricated
  // verdict: the top unread signal by severity, else the most-severe signal. The
  // mockup's confidence %, signals/min, auto-resolve %, response-time HUD, the
  // dispersion-prism animation and synthetic source avatars have NO backing in the
  // Notification entity and are OMITTED, never faked.
  const lead = useMemo(() => {
    if (items.length === 0) return null;
    return [...items].sort((a, b) => {
      const ua = a.readAt === null ? 0 : 1;
      const ub = b.readAt === null ? 0 : 1;
      if (ua !== ub) return ua - ub;
      return SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity);
    })[0];
  }, [items]);

  // Roving selection: the explicitly selected row if still visible, else the top
  // of the current view. Drives the roving tabindex and keyboard actions.
  const currentId = (selectedId && visible.some((n) => n.id === selectedId))
    ? selectedId
    : (visible[0]?.id ?? null);

  // Move DOM focus to the selected row so keyboard + screen-reader stay in sync.
  useEffect(() => {
    if (!selectedId) return;
    itemRefs.current.get(selectedId)?.focus();
  }, [selectedId]);

  const markRead = (id: string) => {
    desktop.markNotificationRead(id).then(() => state.reload()).catch(() => state.reload());
  };

  const toggleExpand = (id: string) => setExpandedId((prev) => (prev === id ? null : id));

  const onFeedKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (visible.length === 0) return;
    const idx = visible.findIndex((n) => n.id === currentId);
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const ni = idx < 0 ? 0 : Math.min(idx + 1, visible.length - 1);
      setSelectedId(visible[ni].id);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const ni = idx <= 0 ? 0 : idx - 1;
      setSelectedId(visible[ni].id);
    } else if (e.key === 'Enter') {
      if (idx >= 0) {
        e.preventDefault();
        toggleExpand(visible[idx].id);
      }
    } else if (e.key === 'x' || e.key === 'X') {
      if (idx >= 0 && visible[idx].readAt === null) {
        e.preventDefault();
        markRead(visible[idx].id);
      }
    }
  };

  // A severity "band plate" doubling as a priority filter. Count is derived from the
  // real array; the accent is the severity's semantic token. Pressed state and the
  // count are both exposed to assistive tech via aria-label + aria-pressed.
  const band = (value: Filter, label: string, count: number, tone: string) => {
    const active = filter === value;
    return (
      <button
        key={value}
        type="button"
        className={`nsig-band${active ? ' is-sel' : ''}`}
        aria-pressed={active}
        aria-label={`${label} · ${count} ${L('statTotal')}`}
        onClick={() => setFilter(value)}
        style={{ ['--tone' as string]: tone } as CSSProperties}
      >
        <span className="nsig-band-edge" aria-hidden="true" />
        <span className="nsig-band-body">
          <span className="nsig-band-lbl">{label}</span>
          <span className="nsig-band-n num">
            <b className="count">{count}</b>
            <i aria-hidden="true">{L('unitSignal')}</i>
          </span>
        </span>
      </button>
    );
  };

  const loading = state.loading && state.data === null;
  const flowLive = unreadCount > 0;

  return (
    <div className="v-notifications">
      <style>{CSS}</style>

      {/* ── header ─────────────────────────────────────────────────────────── */}
      <header className="pageHead reveal">
        <div>
          <span className="eyebrow">{L('eyebrowPrism')}</span>
          <h1>{t('nav.notifications')}</h1>
          <p className="sub">{t('notifications.subtitle')}</p>
        </div>
        <div className="right">
          {/* Honest flow state: "active" only means there are unread signals to work. */}
          <span className={`pill ${flowLive ? 'live' : 'off'}`}>
            {flowLive ? L('flowActive') : L('flowIdle')}
          </span>
          <span className="pill info">{L('readOnlyMirror')}</span>
        </div>
      </header>

      {/* ── hero · current triage (real lead signal + real derived counts) ───── */}
      <section className="nsig-hero surface soft lg hud reveal" aria-label={L('triageNow')}>
        <span className="bracket tl" aria-hidden="true" /><span className="bracket tr" aria-hidden="true" />
        <span className="bracket bl" aria-hidden="true" /><span className="bracket br" aria-hidden="true" />

        <div className="nsig-now">
          <span className="eyebrow">{L('triageNow')}</span>
          {loading ? (
            <Skeleton rows={2} />
          ) : lead ? (
            <div className="nsig-now-body">
              {/* Power mark leans by REAL severity — never forced green/live. */}
              <Mark state={markState(lead.severity)} size={44} />
              <div className="nsig-now-txt">
                <p className="nsig-now-title">{lead.title}</p>
                <div className="row" style={{ gap: 8 }}>
                  <Badge tone={statusTone[lead.severity] ?? 'neutral'}>
                    {severityLabel(lead.severity, lang)}
                  </Badge>
                  {lead.readAt === null && (
                    <span className="micro nsig-now-unread">{L('unread')}</span>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <p className="nsig-now-title muted">{L('triageEmpty')}</p>
          )}
        </div>

        {/* HUD — every capsule is a fact countable from the real array. */}
        <div className="nsig-hud">
          <div className="capsule">
            <b className="num">{items.length}</b>
            <span>{L('statTotal')}</span>
          </div>
          <div className="capsule nsig-hud-warn">
            <b className="num">{unreadCount}</b>
            <span>{L('statUnread')}</span>
          </div>
          <div className="capsule">
            <b className="num">{visible.length}</b>
            <span>{L('statShown')}</span>
          </div>
        </div>
      </section>

      {/* ── ranked intake ────────────────────────────────────────────────────── */}
      <div className="sec-head" style={{ marginTop: 26 }}>
        <h2>{L('inboxHeading')}</h2>
        <span className="note">{L('inboxNote')}</span>
      </div>

      <div className="nsig-bands" role="group" aria-label={L('filtersLabel')}>
        {band('unread', L('filterUnread'), unreadCount, 'var(--menq-color-warning)')}
        {band('all', L('filterAll'), items.length, 'var(--brops-accent)')}
        {severities.map((sev) =>
          band(sev, severityLabel(sev, lang), items.filter((n) => n.severity === sev).length, severityColor(sev)))}
      </div>
      <div className="nsig-hint micro">{L('keyboardHint')}</div>

      {/* Live region: new/changed signals are announced politely. */}
      <p className="nsig-sr" aria-live="polite">
        {`${visible.length} ${L('liveCount')}`}
      </p>

      {loading ? (
        <Skeleton rows={4} />
      ) : state.error ? (
        <ErrorState message={state.error} onRetry={state.reload} />
      ) : visible.length === 0 ? (
        <EmptyState title={L('clearTitle')} hint={L('clearHint')} glyph="✓" />
      ) : (
        <div
          className="nsig-feed"
          role="feed"
          aria-label={L('feedLabel')}
          aria-busy={state.loading}
          onKeyDown={onFeedKeyDown}
        >
          {visible.map((n, i) => {
            const isSelected = n.id === currentId;
            const isExpanded = n.id === expandedId;
            const isUnread = n.readAt === null;
            const accent = severityColor(n.severity);
            const label = `${severityLabel(n.severity, lang)}: ${n.title}${isUnread ? ` — ${L('unread')}` : ''}`;
            return (
              <div
                key={n.id}
                ref={(el) => {
                  if (el) itemRefs.current.set(n.id, el);
                  else itemRefs.current.delete(n.id);
                }}
                role="article"
                aria-label={label}
                aria-posinset={i + 1}
                aria-setsize={visible.length}
                aria-expanded={isExpanded}
                tabIndex={isSelected ? 0 : -1}
                className={`nsig-srow rise${isSelected ? ' is-sel' : ''}${isUnread ? ' is-unread' : ''}`}
                style={{ ['--tone' as string]: accent, ['--i' as string]: i + 2 } as CSSProperties}
                onClick={() => setSelectedId(n.id)}
              >
                <span className="nsig-srow-rail" aria-hidden="true" />
                {isUnread && <span className="nsig-srow-unread" aria-hidden="true" />}
                <div className="nsig-srow-main">
                  <div className="nsig-srow-top">
                    <Badge tone={statusTone[n.severity] ?? 'neutral'}>
                      {severityLabel(n.severity, lang)}
                    </Badge>
                    {n.kind && <span className="micro nsig-srow-kind">{n.kind}</span>}
                    <time className="mono nsig-srow-time">{fmtDate(n.createdAt)}</time>
                  </div>
                  <div className="nsig-srow-title">{n.title}</div>
                  <div className="nsig-srow-foot">
                    <Button small variant="ghost" onClick={() => toggleExpand(n.id)}>
                      {isExpanded ? L('collapse') : L('open')}
                    </Button>
                    {isUnread && (
                      <Button
                        small
                        variant="ghost"
                        title={`${L('dismiss')}: ${n.title}`}
                        onClick={() => markRead(n.id)}
                      >
                        {L('dismiss')}
                      </Button>
                    )}
                  </div>
                  {isExpanded && (
                    <div className="nsig-body">
                      <div className="muted">{n.body}</div>
                      {(n.entityType || n.kind) && (
                        <div className="micro nsig-srow-meta">
                          {[n.kind, n.entityType].filter(Boolean).join(' · ')}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── governance stream (§D) ────────────────────────────────────────────
          Driven by the real READ-ONLY engine governance IPC (`read_evidence_chain`).
          Until the engine read endpoint answers, the honest state is blocked/
          unreachable — rendered as such from the ACTUAL GovernanceRead, never a
          fabricated stream. The desktop mirrors; it never decides. */}
      <div className="sec-head" style={{ marginTop: 30 }}>
        <h2>{L('gateHeading')}</h2>
        <span className="note">{L('readOnlyMirror')}</span>
      </div>

      <section className="nsig-gate surface soft cut" role="status" aria-label={L('gateTitle')}>
        {/* Mark posture: idle while reading/mirrored, alert when the chain is
            sealed/unreachable — an honest "not connected" cue, never a green seal. */}
        <Mark
          state={gov.data && gov.data.state !== 'ok' ? 'alert' : 'idle'}
          size={40}
          className="nsig-gate-mark"
        />
        <div className="nsig-gate-txt">
          <div className="nsig-gate-title">
            {/* "mirrored" is claimed only when events ACTUALLY arrived. An `ok` read
                carrying zero records is the absence of a stream, not a mirrored one. */}
            {gov.data && hasRecords(gov.data) ? L('gateTitleOk') : L('gateTitle')}
          </div>
          <div className="muted nsig-gate-body">
            {gov.data === null
              ? L('gateReading')
              : gov.data.state !== 'ok'
                ? L('gateBody')
                : hasRecords(gov.data)
                  ? `${recordCount(gov.data)} ${L('gateMirrored')}`
                  : L('gateEmpty')}
          </div>
          {/* Records shown here are schema-checked only, from a source the desktop does
              not authenticate — never let the panel imply verified engine truth. */}
          {gov.data && hasRecords(gov.data) && isUnauthenticatedMirror(gov.data) ? (
            <div className="micro nsig-gate-reason">{L('gateUnauthenticated')}</div>
          ) : null}
          {gov.data && gov.data.state !== 'ok' && gov.data.reason ? (
            <div className="micro nsig-gate-reason">
              {L('gateReasonLabel')}{gov.data.reason}
            </div>
          ) : null}
          {/* Honest read-path chain: engine → mirror. The middle node lights only when
              events genuinely arrived; an empty or sealed read leaves it un-lit. */}
          <div className="chain nsig-gate-chain" aria-hidden="true">
            <b className="done">{L('gateChainEngine')}</b>
            <b className={gov.data && hasRecords(gov.data) ? 'now' : ''}>{L('gateChainMirror')}</b>
            <b>{gov.data === null ? L('gateChainReading') : L('gateChainMirror')}</b>
          </div>
        </div>
      </section>
    </div>
  );
}

// Scoped supplement to the global `aios.css`. Structural dressing only — colour,
// motion and surfaces all come from the shared design tokens; the per-view CSS
// just lays out the prism-inspired triage hero, band-plate filters and the ranked
// signal rows. Motion is disabled under prefers-reduced-motion.
const CSS = `
.v-notifications { display: flex; flex-direction: column; }

.nsig-hero { display: flex; align-items: center; gap: var(--s6, 22px); flex-wrap: wrap; padding: var(--s6, 22px); }
.nsig-now { flex: 1 1 320px; min-width: 0; display: flex; flex-direction: column; gap: var(--s3, 10px); }
.nsig-now-body { display: flex; align-items: center; gap: var(--s4, 14px); min-width: 0; }
.nsig-now-txt { min-width: 0; display: flex; flex-direction: column; gap: 6px; }
.nsig-now-title { margin: 0; font-family: var(--f-display); font-size: clamp(15px, 1.7vw, 19px); font-weight: 700; line-height: 1.25; }
.nsig-now-unread { color: var(--menq-color-warning); }
.nsig-hud { display: flex; gap: var(--s3, 10px); flex-wrap: wrap; }
.nsig-hud .capsule b { font-size: 18px; }
.nsig-hud-warn { border-color: color-mix(in srgb, var(--menq-color-warning) 34%, transparent); }
.nsig-hud-warn b { color: var(--menq-color-warning); }

.nsig-bands { display: flex; flex-wrap: wrap; gap: var(--s3, 10px); }
.nsig-band {
  position: relative; display: flex; align-items: stretch; gap: 0;
  min-width: 118px; padding: 0; cursor: pointer; text-align: left;
  border: 1px solid var(--brops-border); border-radius: var(--r-md, 12px);
  background: var(--brops-surface); overflow: hidden;
  transition: border-color var(--fast, .18s), transform var(--fast, .18s), background var(--fast, .18s);
}
.nsig-band:hover { transform: translateY(-2px); border-color: color-mix(in srgb, var(--tone) 45%, var(--brops-border)); }
.nsig-band:focus-visible { outline: 2px solid var(--menq-color-focus); outline-offset: 2px; }
.nsig-band.is-sel { border-color: var(--tone); background: color-mix(in srgb, var(--tone) 9%, var(--brops-surface)); }
.nsig-band-edge { width: 4px; flex: none; background: var(--tone); opacity: .6; }
.nsig-band.is-sel .nsig-band-edge { opacity: 1; box-shadow: 0 0 12px var(--tone); }
.nsig-band-body { display: flex; flex-direction: column; gap: 3px; padding: 9px 13px; }
.nsig-band-lbl { font-size: 12px; font-weight: 600; }
.nsig-band-n { display: inline-flex; align-items: baseline; gap: 4px; }
.nsig-band-n b { font-family: var(--f-display); font-size: 18px; font-weight: 800; color: var(--tone); }
.nsig-band-n i { font-family: var(--f-mono); font-size: 10px; font-style: normal; text-transform: uppercase; letter-spacing: .1em; color: var(--ink-muted); }

.nsig-hint { margin: 12px 0 4px; letter-spacing: .1em; }
.nsig-sr { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }

.nsig-feed { display: flex; flex-direction: column; gap: var(--s3, 10px); }
.nsig-srow {
  position: relative; display: flex; gap: var(--s3, 10px);
  padding: 11px 14px 11px 16px; cursor: default;
  border: 1px solid var(--brops-border); border-radius: var(--r-md, 12px);
  background: var(--brops-surface);
  transition: border-color var(--fast, .18s), background var(--fast, .18s), transform var(--fast, .18s);
}
.nsig-srow:hover { transform: translateY(-2px); border-color: color-mix(in srgb, var(--tone) 40%, var(--brops-border)); }
.nsig-srow:focus-visible { outline: 2px solid var(--menq-color-focus); outline-offset: 2px; }
.nsig-srow.is-sel { border-color: var(--brops-accent); background: var(--menq-color-selected); }
.nsig-srow-rail { position: absolute; left: 0; top: 8px; bottom: 8px; width: 3px; border-radius: 99px; background: var(--tone); opacity: .55; }
.nsig-srow.is-unread .nsig-srow-rail { opacity: 1; box-shadow: 0 0 10px var(--tone); }
.nsig-srow-unread { width: 7px; height: 7px; border-radius: 50%; flex: none; margin-top: 6px; background: var(--tone); box-shadow: 0 0 8px var(--tone); }
.nsig-srow-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 5px; }
.nsig-srow-top { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
.nsig-srow-kind { letter-spacing: .1em; }
.nsig-srow-time { margin-left: auto; font-size: 11px; color: var(--ink-muted); }
.nsig-srow-title { font-family: var(--f-display); font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nsig-srow.is-unread .nsig-srow-title { font-weight: 800; }
.nsig-srow-foot { display: flex; gap: 6px; }
.nsig-body { margin-top: 6px; padding-top: 9px; border-top: 1px solid var(--brops-border); display: flex; flex-direction: column; gap: 6px; }
.nsig-srow-meta { letter-spacing: .08em; }

.nsig-gate { display: flex; gap: var(--s4, 14px); align-items: flex-start; padding: var(--s5, 18px); }
.nsig-gate-mark { flex: none; }
.nsig-gate-txt { min-width: 0; display: flex; flex-direction: column; gap: 5px; }
.nsig-gate-title { font-family: var(--f-display); font-weight: 700; }
.nsig-gate-body { max-width: 62ch; font-size: 13px; }
.nsig-gate-reason { letter-spacing: .06em; color: var(--ink-muted); }
.nsig-gate-chain { margin-top: 8px; }

@media (max-width: 640px) {
  .nsig-hero { align-items: flex-start; }
  .nsig-srow-time { margin-left: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .nsig-band, .nsig-srow { transition: none; }
  .nsig-band:hover, .nsig-srow:hover { transform: none; }
}
`;
