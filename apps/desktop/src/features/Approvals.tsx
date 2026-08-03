import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { useApp } from '../app/store';
import { Card, Button, Skeleton, ErrorState, EmptyState, ConfirmDialog } from '../components/ui';
import { Mark } from '../components/Ambient';
import { useAsync } from '../hooks/useAsync';
import { useToast } from '../components/toast';
import { desktop, hasBackend } from '../services/desktop';

// ── §D `approvals` — Հաստատումներ (Approval gate) ────────────────────────────
// Mirror, never decide: the desktop READS the engine approval queue and can only
// *request* a verdict — grant (native-confirmed) / deny (fail-safe) — which the
// engine's Ed25519 system adjudicates. Escalate has no engine command in this
// build, so its request path renders honestly as unavailable rather than faking a
// result. Owner-not-authenticated → `blocked`; engine-unreachable → `error`.
//
// This view is re-skinned onto the design mockup's APPROVAL GATE (`.gate .surface`
// with `st-*` status tones), a real-derived approval-stats strip (`.astats-wrap`),
// and a press-and-hold grant key. Every count, tone and verdict is derived from the
// REAL `listApprovals()` / `readEngineApprovalQueue()` data — nothing is fabricated,
// and pending stays pending (amber, `idle` mark) until the backend confirms.

type ActionKind = 'grant' | 'deny' | 'escalate';
interface Staged { id: string; kind: ActionKind; }

const CIRC = 2 * Math.PI * 92; // SLA ring circumference (r=92, matches the mockup)
const HOLD_MS = 1100;          // deliberate press-and-hold duration to grant

/** Presentation for a REAL approval status — gate tone, pill, power-mark state and
 *  label. Green/`live` is reachable ONLY from a real `approved` status; pending is
 *  always amber + `idle`, never forced green. */
function statusMeta(status: string, bi: (en: string, hy: string) => string) {
  const s = (status || '').toLowerCase();
  if (s === 'approved' || s === 'granted' || s === 'confirmed')
    return { gate: 'st-approved', pill: 'live', mark: 'live', face: 'completed', lbl: bi('Approved', 'Հաստատված') };
  if (s === 'rejected' || s === 'denied')
    return { gate: 'st-denied', pill: 'off', mark: 'alert', face: 'blocked', lbl: bi('Denied', 'Մերժված') };
  if (s === 'escalated')
    return { gate: 'st-escalated', pill: 'info', mark: 'thinking', face: 'collaborating', lbl: bi('Escalated · A3', 'Փոխանցված · A3') };
  if (s === 'expired')
    return { gate: 'st-expired', pill: 'off', mark: 'idle', face: 'blocked', lbl: bi('Expired · held', 'Ժամկետանց · պահված') };
  if (s === 'reviewing')
    return { gate: 'st-reviewing', pill: 'info', mark: 'thinking', face: 'thinking', lbl: bi('Bro reviewing', 'Bro վերլուծում է') };
  // pending / unknown → awaiting a human decision. Amber, idle — never green.
  return { gate: 'st-waiting', pill: 'warn', mark: 'idle', face: 'waiting', lbl: bi('Awaiting decision', 'Սպասում է որոշման') };
}

/** Parse a `requestedAt` that may be an epoch-millis string or an ISO instant. */
function parseWhen(raw: string): Date | null {
  const s = (raw ?? '').trim();
  if (!s) return null;
  const d = new Date(isNaN(Number(s)) ? s : Number(s));
  return isNaN(d.getTime()) ? null : d;
}

/** Human elapsed span for the live waiting clock. */
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
 *  signal for `blocked` (owner not authenticated); anything else is `error`. */
function isAuthError(msg: string): boolean {
  return /denied|not permitted|permission|unauthor|authenticat|not signed|sign in|login|forbidden|owner/i.test(msg);
}

export function Approvals() {
  const { t, lang } = useApp();
  const toast = useToast();
  const state = useAsync(() => desktop.listApprovals());
  const { data, error, reload } = state;
  // Real, READ-ONLY engine approval-QUEUE read (mirror, never decide; queue read only —
  // NO approval-request POST, which is a separate gated engine task). Steady state in
  // Phase-2 is blocked/unreachable — surfaced honestly below the gate, never fabricated.
  const engineQueue = useAsync(() => desktop.readEngineApprovalQueue());

  /** Inline HY/EN the way the thin pages do (shared i18n stays untouched). */
  const bi = useCallback((en: string, hy: string) => (lang === 'hy' ? hy : en), [lang]);

  const [selected, setSelected] = useState(0);
  const [staged, setStaged] = useState<Staged | null>(null);
  const [holding, setHolding] = useState(false);
  const [verdict, setVerdict] = useState('');
  const [now, setNow] = useState(() => Date.now());
  const holdTimer = useRef<number | null>(null);

  const items = useMemo(() => data ?? [], [data]);
  const sel = items.length ? Math.min(selected, items.length - 1) : 0;
  const seated = items.length ? items[sel] : null;

  const dateFmt = useMemo(
    () => new Intl.DateTimeFormat(lang, { dateStyle: 'medium', timeStyle: 'short' }),
    [lang],
  );

  // Live clock — re-render every second so the seated pending item's waiting time
  // stays current. Only the (aria-hidden) clock text changes, so the aria-live gate
  // does not re-announce every tick.
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const onError = (e: unknown) => {
    const msg = e instanceof Error ? e.message : String(e);
    toast(`${t('approvals.decideFailed')}: ${msg}`, 'error');
  };

  // The single real action path. grant/deny go through the real engine-request
  // commands; escalate has no command, so it reports honestly and sends nothing.
  const runAction = useCallback((id: string, kind: ActionKind) => {
    const item = (data ?? []).find((a) => a.id === id);
    if (!item || item.status !== 'pending') return; // only pending items are actionable
    const label = item.target;
    if (kind === 'grant') {
      // T-011: real commit is adjudicated behind a Rust-driven native dialog the
      // webview cannot forge; the press-and-hold here is only the in-app pre-commit gate.
      desktop.confirmApproval(id)
        .then(() => { setVerdict(bi(`Granted: ${label}`, `Հաստատվեց՝ ${label}`)); reload(); })
        .catch(onError);
    } else if (kind === 'deny') {
      // T-010: dedicated fail-safe reject path.
      desktop.rejectApproval(id)
        .then(() => { setVerdict(bi(`Denied: ${label}`, `Մերժվեց՝ ${label}`)); reload(); })
        .catch(onError);
    } else {
      // Honest empty request path: no engine escalate command exists in this build.
      setVerdict(bi(`Escalation unavailable for ${label}`, `Բարձրացումն անհասանելի է՝ ${label}`));
      toast(bi('Escalation isn’t wired to the engine yet — no request was sent.',
        'Բարձրացումը դեռ միացված չէ շարժիչին — հարցում չուղարկվեց։'), 'info');
    }
  }, [data, bi, reload]); // eslint-disable-line react-hooks/exhaustive-deps

  // Commit the staged (dialog-confirmed) deny/escalate.
  const commit = useCallback(() => {
    if (!staged) return;
    const { id, kind } = staged;
    setStaged(null);
    runAction(id, kind);
  }, [staged, runAction]);

  // ── press-and-hold to grant ────────────────────────────────────────────────
  // A deliberate ~1.1s hold on the seated pending item. Release early cancels. This
  // is a re-dressing of the confirm gesture — it still calls the real confirmApproval.
  const cancelHold = useCallback(() => {
    if (holdTimer.current) { window.clearTimeout(holdTimer.current); holdTimer.current = null; }
    setHolding(false);
  }, []);

  const startHold = useCallback(() => {
    if (!seated || seated.status !== 'pending' || holdTimer.current) return;
    const id = seated.id;
    setHolding(true);
    holdTimer.current = window.setTimeout(() => {
      holdTimer.current = null;
      setHolding(false);
      runAction(id, 'grant');
    }, HOLD_MS);
  }, [seated, runAction]);

  useEffect(() => cancelHold, [sel, cancelHold]); // seating a new row cancels any in-flight hold

  // Keyboard: ↑/↓ select; d stages a deny, e stages an escalate (both open the
  // confirm dialog). Grant is the deliberate press-and-hold on its button.
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
      if (k === 'd') { e.preventDefault(); setStaged({ id: cur.id, kind: 'deny' }); }
      else if (k === 'e') { e.preventDefault(); setStaged({ id: cur.id, kind: 'escalate' }); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [staged, data, selected]);

  // While a confirm dialog is open: Enter commits, Esc cancels.
  useEffect(() => {
    if (!staged) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Enter') { e.preventDefault(); commit(); }
      else if (e.key === 'Escape') { e.preventDefault(); setStaged(null); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [staged, commit]);

  // ── real-derived counts (no fabricated numbers) ────────────────────────────
  const pendingCount = items.filter((a) => a.status === 'pending').length;
  const approvedCount = items.filter((a) => /^(approved|granted|confirmed)$/i.test(a.status)).length;
  const deniedCount = items.filter((a) => /^(rejected|denied|expired)$/i.test(a.status)).length;

  const style = <ApprovalsStyle />;

  // The mockup page header (eyebrow + h1 + sub + live pending pill), heading order
  // preserved (h1 here, h2 on the gate and the queue section head).
  const header = (
    <header className="pageHead reveal" style={{ '--i': 0 } as CSSProperties}>
      <div>
        <span className="eyebrow">{bi('HUMAN-IN-THE-LOOP · CONTROL GATE', 'ՄԱՐԴ-ՀԱՆԳՈՒՅՑ ՀՍԿԻՉ · HUMAN-IN-THE-LOOP')}</span>
        <h1>{t('nav.approvals')}</h1>
        <p className="sub">{t('approvals.subtitle')}</p>
      </div>
      <div className="right">
        <span className={`pill ${pendingCount > 0 ? 'warn' : 'live'}`}>
          <b className="mono">{pendingCount}</b>&nbsp;{bi('pending', 'սպասում է')}
        </span>
      </div>
    </header>
  );

  // Verdict announcer — always mounted so grant/deny/escalate results are read out.
  const liveRegion = (
    <div className="ap-sr" role="status" aria-live="assertive" aria-atomic="true">{verdict}</div>
  );

  const frame = (children: ReactNode) => (
    <div className="v-approvals">{style}{header}{liveRegion}{children}</div>
  );

  // ── loading: skeleton ──────────────────────────────────────────────────────
  if (state.loading && data === null) {
    return frame(<Card><Skeleton rows={5} /></Card>);
  }

  // ── error / blocked ────────────────────────────────────────────────────────
  if (error) {
    if (!hasBackend()) {
      return frame(<Card><ErrorState message={bi('Engine unreachable.', 'Շարժիչն անհասանելի է։')} /></Card>);
    }
    if (isAuthError(error)) {
      // `blocked` — owner not authenticated: gate locked, all actions disabled.
      return frame(
        <Card>
          <div className="ap-blocked" role="alert">
            <div className="ap-blocked-glyph" aria-hidden="true">🔒</div>
            <div className="empty-title">{bi('Owner not authenticated', 'Տերը նույնականացված չէ')}</div>
            <div className="muted ap-blocked-body">
              {bi('The approval gate is locked until the owner authenticates with the engine. Grant, deny and escalate stay disabled — the desktop never decides on its own.',
                'Հաստատման դարպասը կողպված է, մինչև տերը նույնականացվի շարժիչի հետ։ Հաստատել, մերժել և բարձրացնել գործողություններն անջատված են — desktop-ը երբեք ինքնուրույն որոշում չի կայացնում։')}
            </div>
            <div style={{ marginTop: 12 }}>
              <Button small onClick={reload}>{t('action.retry')}</Button>
            </div>
          </div>
        </Card>,
      );
    }
    // `error` — engine unreachable.
    const denied = /denied|not permitted|permission/i.test(error);
    const msg = denied ? `${t('state.permissionDenied')}: ${error}` : `${bi('Engine unreachable.', 'Շարժիչն անհասանելի է։')} ${error}`;
    return frame(<Card><ErrorState message={msg} onRetry={reload} retryLabel={t('action.retry')} /></Card>);
  }

  // ── empty — gate clear, nothing awaiting authority ─────────────────────────
  if (items.length === 0) {
    return frame(
      <section className="gate surface soft lg hud reveal st-approved" style={{ '--i': 1 } as CSSProperties} role="status" aria-live="polite">
        <span className="bracket tl" aria-hidden="true" /><span className="bracket tr" aria-hidden="true" />
        <span className="bracket bl" aria-hidden="true" /><span className="bracket br" aria-hidden="true" />
        <EmptyState
          glyph="✅"
          title={bi('Gate clear — no pending approvals', 'Դարպասը մաքուր է — չկան սպասող հաստատումներ')}
          hint={bi('New engine requests will appear here as they arrive.',
            'Շարժիչի նոր հարցումները կհայտնվեն այստեղ, երբ ստացվեն։')}
        />
      </section>,
    );
  }

  // ── default: the seated gate + queue + real-derived stats strip ────────────
  const stagedItem = staged ? items.find((a) => a.id === staged.id) ?? null : null;
  const meta = seated ? statusMeta(seated.status, bi) : statusMeta('pending', bi);
  const when = seated ? parseWhen(seated.requestedAt) : null;
  const isPending = !!seated && seated.status === 'pending';
  const opened = !!seated && /^(approved|granted|confirmed)$/i.test(seated.status);
  const pushed = !!seated && /^(rejected|denied|expired)$/i.test(seated.status);

  const tiles: Array<[number, string, string]> = [
    [items.length, bi('in queue', 'հերթում'), 'as-info'],
    [pendingCount, bi('pending now', 'սպասում է հիմա'), 'as-warn'],
    [approvedCount, bi('approved', 'հաստատված'), 'as-mint'],
    [deniedCount, bi('denied · held', 'մերժված'), ''],
  ];

  return frame(
    <>
      {/* ── HERO · the authorization gate (seats the selected real approval) ── */}
      <section
        className={`gate surface soft lg hud reveal ${meta.gate}`}
        style={{ '--i': 1 } as CSSProperties}
        aria-live="polite"
        aria-label={seated ? bi(`Approval gate — ${seated.actionType}, ${meta.lbl}`, `Հաստատման դարպաս — ${seated.actionType}, ${meta.lbl}`) : undefined}
      >
        <span className="bracket tl" aria-hidden="true" /><span className="bracket tr" aria-hidden="true" />
        <span className="bracket bl" aria-hidden="true" /><span className="bracket br" aria-hidden="true" />

        <div className="g-head">
          <div className="gh-title">
            <span className="eyebrow">{bi('CONTROL GATE', 'ՀԱՍՏԱՏՄԱՆ ԴԱՐՊԱՍ · CONTROL GATE')}</span>
            <h2>{seated?.actionType}</h2>
          </div>
          <div className="gh-tags">
            <span className={`tier tier-${seated?.level}`}>{seated?.level}</span>
            <span className={`pill ${meta.pill}`}>{meta.lbl}</span>
          </div>
        </div>

        {/* ── THE THRESHOLD — requester · seal · impact (all from real fields) ── */}
        <div className={`g-stage${opened ? ' opened' : ''}${pushed ? ' pushed' : ''}`}>

          <div className="g-req">
            <span className="micro">{bi('REQUESTING AGENT', 'ՊԱՀԱՆՋՈՂ ԳՈՐԾԱԿԱԼ')}</span>
            <div className="gr-id">
              <span aria-hidden="true"><Mark state={meta.mark} size={40} /></span>
              <div className="gr-who">
                <b>{seated?.requestedBy || '—'}</b>
                <span>{bi('requester', 'հայցող')}</span>
              </div>
            </div>
            <p className="gr-reason">{seated?.target}</p>
          </div>

          <div className="g-seal">
            <span className="s-cap micro">{bi('ACTION HELD', 'ԳՈՐԾՈՂՈՒԹՅՈՒՆԸ ՊԱՀՎԱԾ Է')}</span>
            <div className="seal-lock" aria-hidden="true">
              <svg className="sla-ring" viewBox="0 0 200 200">
                <circle className="sr-track" cx="100" cy="100" r="92" />
                <circle className="sr-val" cx="100" cy="100" r="92"
                  style={{ strokeDasharray: CIRC, strokeDashoffset: opened ? CIRC : 0 } as CSSProperties} />
              </svg>
              <div className="seal-body">
                <span className="through" />
                <span className="half l" /><span className="half r" />
                <span className="seam" />
                <span className="keyhole" />
              </div>
              <span className="held" />
              <span className="tier-ring">{seated?.level}</span>
              {opened && <span className="stamp">{bi('APPROVED', 'ՀԱՍՏԱՏՎԱԾ')}</span>}
            </div>
            <div className="sla-read">
              <b className="mono sla-time" aria-hidden="true">
                {isPending && when ? fmtElapsed(now - when.getTime()) : (opened ? '✓' : pushed ? '—' : '·')}
              </b>
              <span className="micro">
                {isPending ? bi('waiting', 'սպասում է') : meta.lbl}
              </span>
            </div>
          </div>

          <div className="g-impact">
            <span className="micro">{bi('IMPACT SCOPE', 'ԱԶԴԵՑՈՒԹՅԱՆ ՇԱՌԱՎԻՂ')}</span>
            <div className="im-scope"><span className="dot" aria-hidden="true" />{seated?.target}</div>
            <div className="im-grid">
              <div className="im-row">
                <span className="micro">{t('field.level')}</span>
                <span className="im-v"><b className="mono">{seated?.level}</b></span>
              </div>
              <div className="im-row">
                <span className="micro">{t('field.risk')}</span>
                <span className="im-v"><b className="mono">{seated?.riskLevel}</b></span>
              </div>
              <div className="im-row">
                <span className="micro">{bi('Requested by', 'Հայցող')}</span>
                <span className="im-v"><b className="mono">{seated?.requestedBy}</b></span>
              </div>
              <div className="im-row">
                <span className="micro">{bi('Requested at', 'Հայցվել է')}</span>
                <span className="im-v"><b className="mono">{when ? dateFmt.format(when) : (seated?.requestedAt || '—')}</b></span>
              </div>
            </div>
          </div>

        </div>

        {/* ── AUTHORIZATION BAR — the owner is the key ── */}
        <div className="g-authbar">
          <span className="ab-meta micro">
            {bi(`Requested ${when ? dateFmt.format(when) : (seated?.requestedAt || '—')} · `, `Պահանջվել է ${when ? dateFmt.format(when) : (seated?.requestedAt || '—')} · `)}
            <b>{seated?.level}</b>{bi(' level', ' մակարդակ')}
          </span>
          <div className="ab-actions">
            <button
              type="button" className="ab-btn deny" disabled={!isPending}
              onClick={() => seated && setStaged({ id: seated.id, kind: 'deny' })}
              aria-label={bi('Deny — reject this action', 'Մերժել — մերժել գործողությունը')}
            >✕ {bi('Deny', 'Մերժել')}</button>
            <button
              type="button" className="ab-btn escalate" disabled={!isPending}
              onClick={() => seated && setStaged({ id: seated.id, kind: 'escalate' })}
              aria-label={bi('Escalate for higher review', 'Բարձրացնել՝ ավելի բարձր վերանայման')}
            >↑ {bi('Escalate A3', 'Փոխանցել A3')}</button>
            <button
              type="button" className={`ab-btn grant${holding ? ' holding' : ''}`} disabled={!isPending}
              onPointerDown={(e) => { e.preventDefault(); startHold(); }}
              onPointerUp={cancelHold}
              onPointerLeave={cancelHold}
              onPointerCancel={cancelHold}
              onKeyDown={(e) => { if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) { e.preventDefault(); startHold(); } }}
              onKeyUp={(e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); cancelHold(); } }}
              onBlur={cancelHold}
              aria-label={opened
                ? bi('Approved', 'Հաստատված')
                : bi('Press and hold to grant', 'Սեղմիր և պահիր՝ հաստատելու')}
            >
              <span className="grant-fill" aria-hidden="true" />
              <span className="grant-lbl">
                {opened ? `✓ ${bi('Approved', 'Հաստատված')}` : bi('Press & hold to grant', 'Սեղմիր և պահիր՝ հաստատելու')}
              </span>
            </button>
          </div>
        </div>
      </section>

      <div className="ap-hint muted" aria-hidden="true">
        {`↑/↓ ${bi('select', 'ընտրել')} · ${bi('hold Grant to confirm', 'պահիր՝ հաստատելու')} · d ${bi('deny', 'մերժել')} · e ${bi('escalate', 'բարձրացնել')}`}
      </div>

      {/* Engine approval-QUEUE mirror (read-only). Until the engine queue read answers,
          this reads honestly as blocked/unreachable — the list is the local mirror;
          the desktop never fabricates an engine queue and never decides on its own. */}
      {engineQueue.data && engineQueue.data.state !== 'ok' && (
        <div className="ap-blocked" role="note" style={{ padding: 'var(--s3) var(--s4)', textAlign: 'left' }}>
          <span className="muted">
            {engineQueue.data.state === 'unreachable'
              ? bi('Engine approval queue unreachable — showing the local mirror only.',
                'Շարժիչի հաստատումների հերթն անհասանելի է — ցուցադրվում է միայն տեղական արտացոլումը։')
              : bi('Engine approval queue is sealed — showing the local mirror only.',
                'Շարժիչի հաստատումների հերթը կնքված է — ցուցադրվում է միայն տեղական արտացոլումը։')}
            {engineQueue.data.reason ? ` (${engineQueue.data.reason})` : ''}
          </span>
        </div>
      )}

      {/* ── PENDING QUEUE ── */}
      <div className="sec-head" style={{ marginTop: 26 }}>
        <h2>{bi('Approval queue', 'Հաստատման հերթ')}</h2>
        <span className="note">
          {bi('Select a row to seat it at the gate · ', 'Ընտրիր տողը՝ դարպասին բերելու համար · ')}
          <b className="mono">{items.length}</b>{bi(' in queue', ' գործողություն հերթում')}
        </span>
      </div>
      <div className="queue" role="list" aria-label={bi('Approval queue', 'Հաստատումների հերթ')}>
        {items.map((a, i) => {
          const m = statusMeta(a.status, bi);
          const rw = parseWhen(a.requestedAt);
          const isSel = i === sel;
          const rowPending = a.status === 'pending';
          return (
            <button
              type="button" role="listitem"
              key={a.id}
              className={`q-row surface soft rise state-${m.face}${isSel ? ' on' : ''}`}
              style={{ '--i': i + 2 } as CSSProperties}
              aria-pressed={isSel}
              aria-label={bi(`${a.actionType}, ${a.target}, ${m.lbl}`, `${a.actionType}, ${a.target}, ${m.lbl}`)}
              onClick={() => setSelected(i)}
            >
              <span className={`q-tier tier-${a.level}`}>{a.level}</span>
              <span className="q-main">
                <b className="q-ti">{a.actionType}</b>
                <span className="q-agent">
                  <span aria-hidden="true"><Mark state={m.mark} size={26} /></span>
                  <span className="q-who">{a.requestedBy}</span>
                </span>
              </span>
              <span className="q-impact">
                <span className="micro">{bi('Target', 'Ազդեցություն')}</span>
                <b className="mono">{a.target}</b>
                <span className="q-rev ok">{a.riskLevel}</span>
              </span>
              <span className="q-sla">
                <span className="micro">{bi('Waiting', 'Ժամկետ')}</span>
                <b className="mono">{rowPending && rw ? fmtElapsed(now - rw.getTime()) : '—'}</b>
              </span>
              <span className={`pill ${m.pill}`}>{m.lbl}</span>
            </button>
          );
        })}
      </div>

      {/* ── approval-stats strip (real-derived counts) ── */}
      <section className="surface soft astats-wrap rise" style={{ '--i': 2 } as CSSProperties} aria-label={bi('Approval statistics', 'Հաստատումների վիճակագրություն')}>
        <div className="astats">
          {tiles.map(([n, label, cls], i) => (
            <div className={`astat rise${cls ? ' ' + cls : ''}`} style={{ '--i': i + 2 } as CSSProperties} key={label}>
              <b className="mono">{n}</b>
              <span className="micro">{label}</span>
            </div>
          ))}
        </div>
        <div className="wire live" aria-hidden="true" />
      </section>

      {/* deny / escalate go through a confirm dialog (grant uses press-and-hold). */}
      {staged && stagedItem && staged.kind !== 'grant' && (
        <ConfirmDialog
          title={
            staged.kind === 'deny'
              ? bi('Confirm denial', 'Մերժե՞լ')
              : bi('Escalate for higher review', 'Բարձրացնե՞լ')
          }
          message={
            staged.kind === 'deny'
              ? bi(`Deny “${stagedItem.actionType}” on ${stagedItem.target}? This is the fail-safe reject path.`,
                `Մերժե՞լ «${stagedItem.actionType}»՝ ${stagedItem.target}-ի վրա։ Սա fail-safe մերժման ուղին է։`)
              : bi('Escalation is not wired to the engine in this build — confirming sends no request.',
                'Բարձրացումը այս տարբերակում միացված չէ շարժիչին — հաստատումը հարցում չի ուղարկում։')
          }
          confirmLabel={staged.kind === 'deny' ? t('action.reject') : bi('Escalate', 'Բարձրացնել')}
          cancelLabel={t('action.cancel')}
          onConfirm={commit}
          onCancel={() => setStaged(null)}
        />
      )}
    </>,
  );
}

/** Page-local styles for the few classes the design CSS doesn't already provide
 *  (the sr-only verdict region, the keyboard hint, and the blocked/empty panel). */
function ApprovalsStyle() {
  return (
    <style>{`
      .v-approvals .ap-sr { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
        overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }

      .v-approvals .ap-hint { font-size: 12px; margin: 10px 0 4px; color: var(--ink-muted);
        font-variant-numeric: tabular-nums; }

      .v-approvals .ap-blocked { text-align: center; padding: var(--s6) var(--s4); color: var(--ink-muted); }
      .v-approvals .ap-blocked-glyph { font-size: 30px; }
      .v-approvals .ap-blocked .empty-title { margin-top: var(--s3); }
      .v-approvals .ap-blocked-body { max-width: 480px; margin: 6px auto 0; }

      /* the grant key is a real hold gesture; keep the fill legible with motion reduced */
      @media (prefers-reduced-motion: reduce) {
        .v-approvals .ab-btn.grant.holding .grant-fill { transition: transform ${HOLD_MS}ms linear; }
      }
    `}</style>
  );
}
