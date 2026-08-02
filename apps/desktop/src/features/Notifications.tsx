import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, StatusPill, EmptyState, Skeleton, ErrorState,
} from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { desktop } from '../services/desktop';
import type { Notification } from '../domain/entities';

// ── page-local strings ──────────────────────────────────────────────────────
// The shared i18n dictionaries are not edited here (per task scope); the thin
// pages inline literals, so this page carries its own HY + EN copy and falls
// back to EN for any other language.
type Str = { en: string; hy: string };
const STRINGS = {
  filterAll: { en: 'All', hy: 'Բոլորը' },
  filterUnread: { en: 'Unread', hy: 'Չկարդացված' },
  clearTitle: { en: 'All clear', hy: 'Ամեն ինչ մաքուր է' },
  clearHint: { en: 'No signals right now.', hy: 'Այս պահին ազդանշաններ չկան։' },
  open: { en: 'Open', hy: 'Բացել' },
  collapse: { en: 'Collapse', hy: 'Փակել' },
  dismiss: { en: 'Dismiss', hy: 'Անտեսել' },
  unread: { en: 'unread', hy: 'չկարդացված' },
  keyboardHint: {
    en: '↑/↓ navigate · Enter open · x dismiss',
    hy: '↑/↓ նավարկել · Enter բացել · x անտեսել',
  },
  feedLabel: { en: 'Signal feed', hy: 'Ազդանշանների հոսք' },
  filtersLabel: { en: 'Filter signals', hy: 'Զտել ազդանշանները' },
  liveCount: { en: 'signals shown', hy: 'ազդանշան ցուցադրված է' },
  gateHeading: { en: 'Engine governance signals', hy: 'Շարժիչի կառավարման ազդանշաններ' },
  gateTitle: { en: 'Governance stream sealed', hy: 'Կառավարման հոսքը կնքված է' },
  gateBody: {
    en: 'The engine governance-event stream is not connected to this desktop yet. Signals '
      + 'from the engine ledger appear here once the read bridge lands — the desktop mirrors, '
      + 'it never decides.',
    hy: 'Շարժիչի կառավարման իրադարձությունների հոսքը դեռ միացված չէ այս աշխատասեղանին։ '
      + 'Շարժիչի մատյանի ազդանշանները կհայտնվեն այստեղ, երբ ընթերցման կամուրջը պատրաստ լինի — '
      + 'աշխատասեղանը արտացոլում է, երբեք չի որոշում։',
  },
} as const;

const SEVERITY_HY: Record<string, string> = {
  info: 'Տեղեկություն',
  success: 'Հաջողություն',
  warning: 'Զգուշացում',
  error: 'Սխալ',
  critical: 'Կրիտիկական',
};

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

  const tr = (k: keyof typeof STRINGS): string => (lang === 'hy' ? STRINGS[k].hy : STRINGS[k].en);
  const severityLabel = (sev: string): string =>
    lang === 'hy' ? (SEVERITY_HY[sev] ?? sev) : sev.charAt(0).toUpperCase() + sev.slice(1);

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

  const chip = (value: Filter, label: string, count: number) => {
    const active = filter === value;
    return (
      <button
        key={value}
        type="button"
        className={`btn btn--sm ${active ? 'btn--primary' : 'btn--ghost'} nsig-chip`}
        aria-pressed={active}
        onClick={() => setFilter(value)}
      >
        {label}
        <span className="nsig-chip-count">{count}</span>
      </button>
    );
  };

  return (
    <>
      <style>{CSS}</style>

      <PageHeader title={t('nav.notifications')} subtitle={t('notifications.subtitle')} />

      <Panel title={tr('feedLabel')}>
        <div className="nsig-chips" role="group" aria-label={tr('filtersLabel')}>
          {chip('unread', tr('filterUnread'), unreadCount)}
          {chip('all', tr('filterAll'), items.length)}
          {severities.map((sev) =>
            chip(sev, severityLabel(sev), items.filter((n) => n.severity === sev).length))}
        </div>
        <div className="nsig-hint muted">{tr('keyboardHint')}</div>

        {/* Live region: new/changed signals are announced politely. */}
        <p className="nsig-sr" aria-live="polite">
          {`${visible.length} ${tr('liveCount')}`}
        </p>

        {state.loading && state.data === null ? (
          <Skeleton rows={4} />
        ) : state.error ? (
          <ErrorState message={state.error} onRetry={state.reload} />
        ) : visible.length === 0 ? (
          <EmptyState title={tr('clearTitle')} hint={tr('clearHint')} glyph="✓" />
        ) : (
          <div
            className="nsig-feed"
            role="feed"
            aria-label={tr('feedLabel')}
            aria-busy={state.loading}
            onKeyDown={onFeedKeyDown}
          >
            {visible.map((n, i) => {
              const isSelected = n.id === currentId;
              const isExpanded = n.id === expandedId;
              const isUnread = n.readAt === null;
              const accent = severityColor(n.severity);
              const label = `${severityLabel(n.severity)}: ${n.title}${isUnread ? ` — ${tr('unread')}` : ''}`;
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
                  className={`nsig-item${isSelected ? ' nsig-item--selected' : ''}${isUnread ? ' nsig-item--unread' : ''}`}
                  style={{ borderLeftColor: accent }}
                  onClick={() => setSelectedId(n.id)}
                >
                  <div className="nsig-item-main">
                    <div className="nsig-head">
                      <div className="row" style={{ gap: 8, minWidth: 0 }}>
                        {isUnread && <span className="nsig-dot" style={{ background: accent }} aria-hidden="true" />}
                        <StatusPill status={n.severity} />
                        <span className="nsig-title">{n.title}</span>
                      </div>
                      <div className="nsig-actions">
                        <Button small variant="ghost" onClick={() => toggleExpand(n.id)}>
                          {isExpanded ? tr('collapse') : tr('open')}
                        </Button>
                        {isUnread && (
                          <Button small variant="ghost" onClick={() => markRead(n.id)}>
                            {tr('dismiss')}
                          </Button>
                        )}
                      </div>
                    </div>
                    <div className="nsig-meta muted">{fmtDate(n.createdAt)}</div>
                    {isExpanded && (
                      <div className="nsig-body">
                        <div className="muted">{n.body}</div>
                        {(n.entityType || n.kind) && (
                          <div className="nsig-meta muted" style={{ marginTop: 6 }}>
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
      </Panel>

      {/* Governance stream (§D). Driven by the real READ-ONLY engine governance IPC
          (`read_evidence_chain`). Until the engine read endpoint answers, the honest
          state is blocked/unreachable — rendered as such from the actual result, never
          fabricating events. The desktop mirrors; it never decides. */}
      <div style={{ marginTop: 16 }}>
        <Panel title={tr('gateHeading')}>
          <div className="nsig-gate" role="status" aria-label={tr('gateTitle')}>
            <div className="nsig-gate-glyph" aria-hidden="true">⛨</div>
            <div>
              <div className="nsig-gate-title">
                {gov.data?.state === 'ok'
                  ? (lang === 'hy' ? 'Կառավարման հոսքն արտացոլված է' : 'Governance stream mirrored')
                  : tr('gateTitle')}
              </div>
              <div className="muted" style={{ marginTop: 4, maxWidth: 560 }}>
                {gov.data === null
                  ? (lang === 'hy' ? 'Կարդում ենք շարժիչի կառավարման հոսքը…' : 'Reading the engine governance stream…')
                  : gov.data.state === 'ok'
                    ? (lang === 'hy'
                      ? `${gov.data.records?.length ?? 0} իրադարձություն արտացոլված է շարժիչի շղթայից։`
                      : `${gov.data.records?.length ?? 0} event(s) mirrored from the engine chain.`)
                    : tr('gateBody')}
              </div>
              {gov.data && gov.data.state !== 'ok' && gov.data.reason ? (
                <div className="muted" style={{ marginTop: 6, fontSize: 12 }}>
                  {(lang === 'hy' ? 'Պատճառ՝ ' : 'Reason: ')}{gov.data.reason}
                </div>
              ) : null}
            </div>
          </div>
        </Panel>
      </div>
    </>
  );
}

const CSS = `
.nsig-chips { display: flex; flex-wrap: wrap; gap: var(--menq-space-2); }
.nsig-chip { display: inline-flex; align-items: center; gap: 6px; }
.nsig-chip-count {
  font-variant-numeric: tabular-nums; font-size: 11px; font-weight: 700;
  padding: 0 6px; border-radius: var(--menq-radius-pill);
  background: color-mix(in srgb, currentColor 16%, transparent);
}
.nsig-hint { font-size: 12px; margin-top: 2px; }
.nsig-sr {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
.nsig-feed { display: flex; flex-direction: column; gap: var(--menq-space-3); }
.nsig-item {
  display: flex; gap: var(--menq-space-3);
  background: var(--brops-surface);
  border: 1px solid var(--brops-border);
  border-left: 3px solid var(--brops-border);
  border-radius: var(--menq-radius-md);
  padding: 10px 12px; cursor: default;
  transition: border-color var(--menq-motion-fast), background var(--menq-motion-fast);
  animation: nsig-reveal var(--menq-motion-med) ease-out;
}
.nsig-item:hover { background: var(--menq-color-hover); }
.nsig-item--selected { border-color: var(--brops-accent); background: var(--menq-color-selected); }
.nsig-item:focus-visible { outline: 2px solid var(--menq-color-focus); outline-offset: 2px; }
.nsig-item--unread .nsig-title { font-weight: 700; }
.nsig-item-main { flex: 1; min-width: 0; }
.nsig-head { display: flex; align-items: center; justify-content: space-between; gap: var(--menq-space-3); }
.nsig-dot { width: 7px; height: 7px; border-radius: 50%; flex: none; }
.nsig-title { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nsig-actions { display: flex; gap: 4px; flex: none; }
.nsig-meta { font-size: 12px; margin-top: 4px; }
.nsig-body { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--brops-border); }
.nsig-gate { display: flex; gap: var(--menq-space-4); align-items: flex-start; padding: var(--menq-space-2) 0; }
.nsig-gate-glyph {
  font-size: 26px; line-height: 1; color: var(--menq-color-warning);
  width: 44px; height: 44px; flex: none; display: grid; place-items: center;
  border-radius: var(--menq-radius-md);
  background: color-mix(in srgb, var(--menq-color-warning) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--menq-color-warning) 30%, transparent);
}
.nsig-gate-title { font-weight: 700; }
@keyframes nsig-reveal { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) { .nsig-item { animation: none; } }
@media (max-width: 620px) {
  .nsig-head { flex-direction: column; align-items: flex-start; }
  .nsig-actions { align-self: flex-end; }
}
`;
