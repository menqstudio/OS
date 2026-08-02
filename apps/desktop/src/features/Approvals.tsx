import { useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Card, Button, Badge, StatusPill, Field, Skeleton, ErrorState, EmptyState, ConfirmDialog,
} from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { useToast } from '../components/toast';
import { desktop, hasBackend } from '../services/desktop';

// ── §D `approvals` — Հաստատումներ (Approval gate) ────────────────────────────
// Mirror, never decide: the desktop READS the engine approval queue and can only
// *request* a verdict — grant (native-confirmed) / deny (fail-safe) — which the
// engine's Ed25519 system adjudicates. Escalate has no engine command in this
// build, so its request path renders honestly as unavailable rather than faking a
// result. Owner-not-authenticated → `blocked`; engine-unreachable → `error`.

type ActionKind = 'grant' | 'deny' | 'escalate';
interface Staged { id: string; kind: ActionKind; }

/** Parse a `requestedAt` that may be an epoch-millis string or an ISO instant. */
function parseWhen(raw: string): Date | null {
  const s = (raw ?? '').trim();
  if (!s) return null;
  const d = new Date(isNaN(Number(s)) ? s : Number(s));
  return isNaN(d.getTime()) ? null : d;
}

/** Human elapsed span for the live countdown/age clock (`apClock`). */
function fmtElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const s = total % 60;
  const m = Math.floor(total / 60) % 60;
  const h = Math.floor(total / 3600);
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m`;
  if (m > 0) return `${m}m ${String(s).padStart(2, '0')}s`;
  return `${s}s`;
}

/** A real backend error that names an auth/permission failure is the honest
 *  signal for `blocked` (owner not authenticated); anything else is `error`
 *  (engine unreachable). */
function isAuthError(msg: string): boolean {
  return /denied|not permitted|permission|unauthor|authenticat|not signed|sign in|login|forbidden|owner/i.test(msg);
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function Approvals() {
  const { t, lang } = useApp();
  const toast = useToast();
  const state = useAsync(() => desktop.listApprovals());
  const { data, error, reload } = state;

  /** Inline HY/EN the way the thin pages do (shared i18n stays untouched). */
  const bi = useCallback((en: string, hy: string) => (lang === 'hy' ? hy : en), [lang]);

  const [selected, setSelected] = useState(0);
  const [staged, setStaged] = useState<Staged | null>(null);
  const [flash, setFlash] = useState<{ id: string; kind: 'stamp' | 'strike' } | null>(null);
  const [verdict, setVerdict] = useState('');
  const [now, setNow] = useState(() => Date.now());

  const items = useMemo(() => data ?? [], [data]);
  const sel = items.length ? Math.min(selected, items.length - 1) : 0;

  const dateFmt = useMemo(
    () => new Intl.DateTimeFormat(lang, { dateStyle: 'medium', timeStyle: 'short' }),
    [lang],
  );

  // Live clock for `apClock` — re-render every second so each pending item's
  // waiting time stays current.
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const onError = (e: unknown) => {
    const msg = e instanceof Error ? e.message : String(e);
    toast(`${t('approvals.decideFailed')}: ${msg}`, 'error');
  };

  const flashThenReload = useCallback((id: string, kind: 'stamp' | 'strike') => {
    if (prefersReducedMotion()) { reload(); return; }
    setFlash({ id, kind });
    window.setTimeout(() => { setFlash(null); reload(); }, 540);
  }, [reload]);

  // Commit the staged action. grant/deny go through the real engine-request
  // commands; escalate has no command, so it reports honestly and sends nothing.
  const commit = useCallback(() => {
    if (!staged) return;
    const { id, kind } = staged;
    const item = (data ?? []).find((a) => a.id === id);
    const label = item ? item.target : id;
    setStaged(null);
    if (kind === 'grant') {
      // T-011: real commit is adjudicated behind a Rust-driven native dialog the
      // webview cannot forge; confirm here is only the in-app pre-commit gate.
      desktop.confirmApproval(id)
        .then(() => { setVerdict(bi(`Granted: ${label}`, `Հաստատվեց՝ ${label}`)); flashThenReload(id, 'stamp'); })
        .catch(onError);
    } else if (kind === 'deny') {
      // T-010: dedicated fail-safe reject path.
      desktop.rejectApproval(id)
        .then(() => { setVerdict(bi(`Denied: ${label}`, `Մերժվեց՝ ${label}`)); flashThenReload(id, 'strike'); })
        .catch(onError);
    } else {
      // Honest empty request path: no engine escalate command exists in this build.
      setVerdict(bi(`Escalation unavailable for ${label}`, `Բարձրացումն անհասանելի է՝ ${label}`));
      toast(bi('Escalation isn’t wired to the engine yet — no request was sent.',
        'Բարձրացումը դեռ միացված չէ շարժիչին — հարցում չուղարկվեց։'), 'info');
    }
  }, [staged, data, bi, flashThenReload]);

  // Keyboard: ↑/↓ select, g/d/e stage an action (queue is live only when there
  // is no open confirm — the confirm owns Enter/Esc).
  useEffect(() => {
    if (staged) return;
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      const list = data ?? [];
      if (list.length === 0) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); setSelected((i) => Math.min(i + 1, list.length - 1)); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); setSelected((i) => Math.max(i - 1, 0)); return; }
      const cur = list[Math.min(selected, list.length - 1)];
      if (!cur || cur.status !== 'pending') return;
      const k = e.key.toLowerCase();
      if (k === 'g') { e.preventDefault(); setStaged({ id: cur.id, kind: 'grant' }); }
      else if (k === 'd') { e.preventDefault(); setStaged({ id: cur.id, kind: 'deny' }); }
      else if (k === 'e') { e.preventDefault(); setStaged({ id: cur.id, kind: 'escalate' }); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [staged, data, selected]);

  // While a confirm is open: Enter commits, Esc cancels.
  useEffect(() => {
    if (!staged) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Enter') { e.preventDefault(); commit(); }
      else if (e.key === 'Escape') { e.preventDefault(); setStaged(null); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [staged, commit]);

  const pendingCount = items.filter((a) => a.status === 'pending').length;

  const header = <PageHeader title={t('nav.approvals')} subtitle={t('approvals.subtitle')} />;

  // Verdict announcer — always mounted so grant/deny/escalate results are read out.
  const liveRegion = (
    <div className="ap-sr" role="status" aria-live="assertive" aria-atomic="true">{verdict}</div>
  );

  const style = <ApprovalsStyle />;

  // ── loading: skeleton rows ────────────────────────────────────────────────
  if (state.loading && data === null) {
    return (
      <>
        {style}{header}{liveRegion}
        <Card><Skeleton rows={5} /></Card>
      </>
    );
  }

  // ── error / blocked ───────────────────────────────────────────────────────
  if (error) {
    // No backend at all (browser preview) → honest engine-unreachable, calm.
    if (!hasBackend()) {
      return (
        <>
          {style}{header}{liveRegion}
          <Card><ErrorState message={bi('Engine unreachable.', 'Շարժիչն անհասանելի է։')} /></Card>
        </>
      );
    }
    if (isAuthError(error)) {
      // `blocked` — owner not authenticated: gate locked, all actions disabled.
      return (
        <>
          {style}{header}{liveRegion}
          <Card>
            <div className="ap-blocked" role="alert">
              <div className="ap-blocked-glyph">🔒</div>
              <div className="empty-title">{bi('Owner not authenticated', 'Տերը նույնականացված չէ')}</div>
              <div className="muted ap-blocked-body">
                {bi('The approval gate is locked until the owner authenticates with the engine. Grant, deny and escalate stay disabled — the desktop never decides on its own.',
                  'Հաստատման դարպասը կողպված է, մինչև տերը նույնականացվի շարժիչի հետ։ Հաստատել, մերժել և բարձրացնել գործողություններն անջատված են — desktop-ը երբեք ինքնուրույն որոշում չի կայացնում։')}
              </div>
              <div style={{ marginTop: 12 }}>
                <Button small onClick={reload}>{t('action.retry')}</Button>
              </div>
            </div>
          </Card>
        </>
      );
    }
    // `error` — engine unreachable.
    const denied = /denied|not permitted|permission/i.test(error);
    const msg = denied ? `${t('state.permissionDenied')}: ${error}` : `${bi('Engine unreachable.', 'Շարժիչն անհասանելի է։')} ${error}`;
    return (
      <>
        {style}{header}{liveRegion}
        <Card><ErrorState message={msg} onRetry={reload} retryLabel={t('action.retry')} /></Card>
      </>
    );
  }

  // ── empty ─────────────────────────────────────────────────────────────────
  if (items.length === 0) {
    return (
      <>
        {style}{header}{liveRegion}
        <Card>
          <div className="ap-gate ap-gate--clear" role="status">
            <span className="ap-gate-dot" aria-hidden="true" />
            {bi('Gate clear — nothing awaiting your authority', 'Դարպասը մաքուր է — ոչինչ չի սպասում ձեր հաստատմանը')}
          </div>
          <EmptyState
            glyph="✅"
            title={bi('No pending approvals', 'Չկան սպասող հաստատումներ')}
            hint={bi('New engine requests will appear here as they arrive.',
              'Շարժիչի նոր հարցումները կհայտնվեն այստեղ, երբ ստացվեն։')}
          />
        </Card>
      </>
    );
  }

  // ── default: queue ────────────────────────────────────────────────────────
  const stagedItem = staged ? items.find((a) => a.id === staged.id) ?? null : null;

  return (
    <>
      {style}{header}{liveRegion}

      {/* live gate state (apGate) */}
      <div className={`ap-gate ${pendingCount > 0 ? 'ap-gate--active' : 'ap-gate--clear'}`} role="status" aria-live="polite">
        <span className="ap-gate-dot" aria-hidden="true" />
        {pendingCount > 0
          ? bi(`Gate active — ${pendingCount} awaiting your authority`, `Դարպասը ակտիվ է — ${pendingCount} սպասում է ձեր հաստատմանը`)
          : bi('Gate clear — nothing pending', 'Դարպասը մաքուր է — ոչինչ չի սպասում')}
      </div>

      <div className="ap-hint muted" aria-hidden="true">
        {`↑/↓ ${bi('select', 'ընտրել')} · g ${bi('grant', 'հաստատել')} · d ${bi('deny', 'մերժել')} · e ${bi('escalate', 'բարձրացնել')} · Enter ${bi('confirm', 'հաստատել')} · Esc ${bi('cancel', 'չեղարկել')}`}
      </div>

      {/* approval queue (apQueue) */}
      <ul className="ap-queue stack" role="list" aria-label={bi('Approval queue', 'Հաստատումների հերթ')}>
        {items.map((a, i) => {
          const when = parseWhen(a.requestedAt);
          const isSelected = i === sel;
          const isPending = a.status === 'pending';
          const flashCls = flash?.id === a.id ? ` ap-item--${flash.kind}` : '';
          return (
            <li
              key={a.id}
              role="listitem"
              className={`card ap-item${isSelected ? ' ap-item--selected' : ''}${flashCls}`}
              style={{ '--i': i } as CSSProperties}
              aria-current={isSelected ? 'true' : undefined}
              onClick={() => setSelected(i)}
            >
              <div className="stack">
                <div className="between row">
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 15 }}>{a.actionType}</div>
                    <div className="muted">{a.target}</div>
                  </div>
                  {/* decision pill (apPill) */}
                  <StatusPill status={a.status} />
                </div>

                <div className="grid grid-2">
                  <Field label={t('field.level')}>
                    <Badge tone="accent">{a.level}</Badge>
                  </Field>
                  <Field label={t('field.risk')}>
                    <StatusPill status={a.riskLevel} />
                  </Field>
                  <Field label={bi('Requested by', 'Հայցող')}>{a.requestedBy}</Field>
                  <Field label={bi('Requested at', 'Հայցվել է')}>
                    {when ? dateFmt.format(when) : (a.requestedAt || '—')}
                  </Field>
                  <Field label={t('field.status')}>
                    <StatusPill status={a.status} />
                  </Field>
                  {/* countdown clock (apClock) — live waiting time for pending items */}
                  {isPending && when && (
                    <Field label={bi('Waiting', 'Սպասում է')}>
                      <span className="ap-clock" aria-label={bi(`Waiting ${fmtElapsed(now - when.getTime())}`, `Սպասում է ${fmtElapsed(now - when.getTime())}`)}>
                        ⏱ {fmtElapsed(now - when.getTime())}
                      </span>
                    </Field>
                  )}
                </div>

                {isPending && (
                  <div className="stack">
                    <div className="row">
                      {/* grant / deny / escalate (apGrant / apDeny / apEsc) */}
                      <Button
                        variant="primary"
                        onClick={() => { setSelected(i); setStaged({ id: a.id, kind: 'grant' }); }}
                        title={bi('Grant — request the engine approve this action', 'Հաստատել — խնդրել շարժիչին հաստատել')}
                      >
                        {bi('Grant', 'Հաստատել')}
                      </Button>
                      <Button
                        variant="danger"
                        onClick={() => { setSelected(i); setStaged({ id: a.id, kind: 'deny' }); }}
                        title={bi('Deny — reject this action', 'Մերժել — մերժել գործողությունը')}
                      >
                        {bi('Deny', 'Մերժել')}
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => { setSelected(i); setStaged({ id: a.id, kind: 'escalate' }); }}
                        title={bi('Escalate for higher review', 'Բարձրացնել՝ ավելի բարձր վերանայման')}
                      >
                        {bi('Escalate', 'Բարձրացնել')}
                      </Button>
                    </div>
                    <div className="muted" style={{ fontSize: 12 }}>
                      🔒 {t('approvals.approveNativeHint')}
                    </div>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      {staged && stagedItem && (
        <ConfirmDialog
          title={
            staged.kind === 'grant'
              ? (stagedItem.level === 'A3' ? t('approvals.a3ConfirmTitle') : bi('Confirm grant', 'Հաստատե՞լ'))
              : staged.kind === 'deny'
                ? bi('Confirm denial', 'Մերժե՞լ')
                : bi('Escalate for higher review', 'Բարձրացնե՞լ')
          }
          message={
            staged.kind === 'grant'
              ? (stagedItem.level === 'A3'
                ? t('approvals.a3ConfirmBody')
                : bi(`Request the engine to grant “${stagedItem.actionType}” on ${stagedItem.target}? A native confirmation follows; the engine adjudicates the final verdict.`,
                  `Խնդրե՞լ շարժիչին հաստատել «${stagedItem.actionType}»՝ ${stagedItem.target}-ի վրա։ Կհետևի native հաստատում. վերջնական վճիռը կայացնում է շարժիչը։`))
              : staged.kind === 'deny'
                ? bi(`Deny “${stagedItem.actionType}” on ${stagedItem.target}? This is the fail-safe reject path.`,
                  `Մերժե՞լ «${stagedItem.actionType}»՝ ${stagedItem.target}-ի վրա։ Սա fail-safe մերժման ուղին է։`)
                : bi('Escalation is not wired to the engine in this build — confirming sends no request.',
                  'Բարձրացումը այս տարբերակում միացված չէ շարժիչին — հաստատումը հարցում չի ուղարկում։')
          }
          confirmLabel={
            staged.kind === 'grant' ? t('action.approve')
              : staged.kind === 'deny' ? t('action.reject')
                : bi('Escalate', 'Բարձրացնել')
          }
          cancelLabel={t('action.cancel')}
          onConfirm={commit}
          onCancel={() => setStaged(null)}
        />
      )}
    </>
  );
}

/** Page-local styles — all colors/spacing/motion resolve through design tokens.
 *  Reduced motion is honored (global rule already neutralizes animations; the
 *  explicit blocks keep intent clear). */
function ApprovalsStyle() {
  return (
    <style>{`
      .ap-sr { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
        overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }

      .ap-gate { display: flex; align-items: center; gap: var(--menq-space-3);
        padding: 10px var(--menq-space-4); border-radius: var(--menq-radius-md);
        font-weight: 600; font-size: 13px; margin-bottom: var(--menq-space-3);
        border: 1px solid var(--brops-border); }
      .ap-gate-dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; flex: none; }
      .ap-gate--active { color: var(--menq-color-warning);
        background: color-mix(in srgb, var(--menq-color-warning) 12%, transparent);
        border-color: color-mix(in srgb, var(--menq-color-warning) 30%, transparent); }
      .ap-gate--active .ap-gate-dot { animation: ap-pulse 1.8s ease-in-out infinite; }
      .ap-gate--clear { color: var(--menq-color-success);
        background: color-mix(in srgb, var(--menq-color-success) 12%, transparent);
        border-color: color-mix(in srgb, var(--menq-color-success) 30%, transparent); }
      @keyframes ap-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }

      .ap-hint { font-size: 12px; margin-bottom: var(--menq-space-3); font-variant-numeric: tabular-nums; }

      .ap-queue { list-style: none; margin: 0; padding: 0; }
      .ap-item { cursor: pointer;
        transition: border-color var(--menq-motion-fast), background var(--menq-motion-fast);
        animation: ap-reveal var(--menq-motion-med) ease-out backwards;
        animation-delay: calc(var(--i, 0) * 45ms); }
      .ap-item:hover { border-color: var(--brops-accent); }
      .ap-item--selected { border-color: var(--brops-accent);
        box-shadow: 0 0 0 1px var(--brops-accent) inset; }
      @keyframes ap-reveal { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }

      /* grant → mint stamp */
      .ap-item--stamp { border-color: var(--menq-color-success) !important;
        animation: ap-stamp var(--menq-motion-med) ease-out; }
      @keyframes ap-stamp {
        0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--menq-color-success) 55%, transparent); }
        30% { box-shadow: 0 0 0 3px color-mix(in srgb, var(--menq-color-success) 55%, transparent); transform: scale(1.01); }
        100% { box-shadow: 0 0 0 0 transparent; transform: scale(1); } }

      /* deny → danger strike */
      .ap-item--strike { border-color: var(--menq-color-danger) !important;
        animation: ap-strike var(--menq-motion-fast) ease-in-out; }
      @keyframes ap-strike {
        0%, 100% { transform: translateX(0); }
        25% { transform: translateX(-5px); }
        75% { transform: translateX(5px); } }

      .ap-clock { font-variant-numeric: tabular-nums; color: var(--brops-text); }

      .ap-blocked { text-align: center; padding: var(--menq-space-6) var(--menq-space-4); color: var(--brops-muted); }
      .ap-blocked-glyph { font-size: 30px; }
      .ap-blocked .empty-title { margin-top: var(--menq-space-3); }
      .ap-blocked-body { max-width: 480px; margin: 6px auto 0; }

      @media (prefers-reduced-motion: reduce) {
        .ap-item, .ap-item--stamp, .ap-item--strike, .ap-gate--active .ap-gate-dot { animation: none !important; }
        .ap-item { opacity: 1; transform: none; }
      }
    `}</style>
  );
}
