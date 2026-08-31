import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { useApp } from '../app/store';
import { Card, Button, Skeleton, ErrorState, EmptyState, ConfirmDialog } from '../components/ui';
import { Mark } from '../components/Ambient';
import { useAsync } from '../hooks/useAsync';
import { useToast } from '../components/toast';
import { desktop, hasBackend } from '../services/desktop';
import { riskLabel } from '../domain/statusLabels';
import { STR } from './Approvals.strings';

// ── §D `approvals` — Հաստատումներ (Approval gate) ────────────────────────────
// Mirror, never decide: the desktop READS the engine approval queue and can only
// *request* a verdict — grant (native-confirmed) / deny (fail-safe) — which the
// engine's Ed25519 system adjudicates. Escalate is a third, non-verdict action: it
// decides nothing and authorizes nothing, it routes the pending request to higher
// review (A3) via a real backend command and notifies the owner. Owner-not-authenticated
// → `blocked`; engine-unreachable → `error`.
//
// This view is re-skinned onto the design mockup's APPROVAL GATE (`.gate .surface`
// with `st-*` status tones), a real-derived approval-stats strip (`.astats-wrap`),
// and a press-and-hold grant key. Every count, tone and verdict is derived from the
// REAL `listApprovals()` / `readEngineApprovalQueue()` data — nothing is fabricated,
// and pending stays pending (amber, `idle` mark) until the backend confirms.
//
// Every visible/aria string lives in the co-located trilingual catalog
// `Approvals.strings.ts` (en/hy/ru); shared-i18n strings stay as `t('…')`.

type ActionKind = 'grant' | 'deny' | 'escalate';
interface Staged { id: string; kind: ActionKind; }

/** Trilingual lookup over the co-located catalog. */
type L = (k: keyof typeof STR) => string;

const CIRC = 2 * Math.PI * 92; // SLA ring circumference (r=92, matches the mockup)
const HOLD_MS = 1100;          // deliberate press-and-hold duration to grant

/** Presentation for a REAL approval status — gate tone, pill, power-mark state and
 *  label. Green/`live` is reachable ONLY from a real `approved` status; pending is
 *  always amber + `idle`, never forced green. */
function statusMeta(status: string, L: L) {
  const s = (status || '').toLowerCase();
  if (s === 'approved' || s === 'granted' || s === 'confirmed')
    return { gate: 'st-approved', pill: 'live', mark: 'live', face: 'completed', lbl: L('approved') };
  if (s === 'rejected' || s === 'denied')
    return { gate: 'st-denied', pill: 'off', mark: 'alert', face: 'blocked', lbl: L('denied') };
  if (s === 'escalated')
    return { gate: 'st-escalated', pill: 'info', mark: 'thinking', face: 'collaborating', lbl: L('escalatedA3') };
  if (s === 'expired')
    return { gate: 'st-expired', pill: 'off', mark: 'idle', face: 'blocked', lbl: L('expiredHeld') };
  if (s === 'reviewing')
    return { gate: 'st-reviewing', pill: 'info', mark: 'thinking', face: 'thinking', lbl: L('broReviewing') };
  // pending / unknown → awaiting a human decision. Amber, idle — never green.
  return { gate: 'st-waiting', pill: 'warn', mark: 'idle', face: 'waiting', lbl: L('awaitingDecision') };
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

  /** Trilingual lookup from the co-located catalog, keyed off the shared `lang`. */
  const L = useCallback<L>((k) => STR[k][lang] ?? STR[k].en, [lang]);

  const [selected, setSelected] = useState(0);
  const [staged, setStaged] = useState<Staged | null>(null);
  const [holding, setHolding] = useState(false);
  const [verdict, setVerdict] = useState('');
  const [now, setNow] = useState(() => Date.now());
  const [reduced, setReduced] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  );
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

  // Honor the OS reduced-motion setting: the hold ring fill (and the shared
  // grant-bar fill) become instant rather than sweeping across HOLD_MS — the
  // deliberate press is still required, only the continuous animation is dropped.
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const on = () => setReduced(mq.matches);
    mq.addEventListener?.('change', on);
    return () => mq.removeEventListener?.('change', on);
  }, []);

  const onError = (e: unknown) => {
    const msg = e instanceof Error ? e.message : String(e);
    toast(`${t('approvals.decideFailed')}: ${msg}`, 'error');
  };

  // The single real action path. grant/deny/escalate each go through a real backend
  // command the desktop cannot forge — there is no local-only, made-up outcome.
  const runAction = useCallback((id: string, kind: ActionKind) => {
    const item = (data ?? []).find((a) => a.id === id);
    if (!item || item.status !== 'pending') return; // only pending items are actionable
    const label = item.target;
    if (kind === 'grant') {
      // T-011: real commit is adjudicated behind a Rust-driven native dialog the
      // webview cannot forge; the press-and-hold here is only the in-app pre-commit gate.
      desktop.confirmApproval(id)
        .then(() => { setVerdict(`${L('grantedPrefix')}${label}`); reload(); })
        .catch(onError);
    } else if (kind === 'deny') {
      // T-010: dedicated fail-safe reject path.
      desktop.rejectApproval(id)
        .then(() => { setVerdict(`${L('deniedPrefix')}${label}`); reload(); })
        .catch(onError);
    } else {
      // Non-verdict routing: escalate to higher review (A3). Decides nothing, authorizes
      // nothing — the backend re-tiers the pending approval and notifies the owner.
      desktop.escalateApproval(id)
        .then(() => { setVerdict(`${L('escalatedPrefix')}${label}`); reload(); })
        .catch(onError);
    }
  }, [data, L, reload]); // eslint-disable-line react-hooks/exhaustive-deps

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
      // A MODIFIED KEY IS SOMEBODY ELSE'S SHORTCUT. `e.key.toLowerCase() === 'g'` matched
      // Ctrl+G / Cmd+G, so find-next staged a grant dialog and preventDefault swallowed the
      // browser's own binding (A-11, fifth audit). Pre-existing for `d`/`e`; this round widened
      // it to the grant path, which is the one where a mistaken keystroke matters most.
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const list = data ?? [];
      if (list.length === 0) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); setSelected((i) => Math.min(i + 1, list.length - 1)); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); setSelected((i) => Math.max(i - 1, 0)); return; }
      const cur = list[Math.min(selected, list.length - 1)];
      if (!cur || cur.status !== 'pending') return;
      const k = e.key.toLowerCase();
      // §D binds `g` to grant. It was missing: grant was reachable only as the pointer
      // press-and-hold (or Space/Enter ON that button), so a keyboard owner driving the
      // queue with ↑/↓ could deny and escalate by keystroke and not grant. `g` stages the
      // SAME confirm dialog `d` and `e` stage — §D's own "all actions confirm before
      // committing" — rather than committing on one keypress, which would have made the
      // deliberate hold gesture bypassable by the very binding meant to complete it. The
      // real gate is unchanged either way: `desktop.confirmApproval` is adjudicated behind
      // the Rust-driven native dialog (T-011) that the webview cannot forge.
      if (k === 'g') { e.preventDefault(); setStaged({ id: cur.id, kind: 'grant' }); }
      else if (k === 'd') { e.preventDefault(); setStaged({ id: cur.id, kind: 'deny' }); }
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
        <span className="eyebrow">{L('eyebrowHitl')}</span>
        <h1>{t('nav.approvals')}</h1>
        <p className="sub">{t('approvals.subtitle')}</p>
      </div>
      <div className="right">
        <span className={`pill ${pendingCount > 0 ? 'warn' : 'live'}`}>
          <b className="mono">{pendingCount}</b>&nbsp;{L('pending')}
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
      return frame(<Card><ErrorState message={L('engineUnreachable')} /></Card>);
    }
    if (isAuthError(error)) {
      // `blocked` — owner not authenticated: gate locked, all actions disabled.
      return frame(
        <Card>
          <div className="ap-blocked" role="alert">
            <div className="ap-blocked-glyph" aria-hidden="true">🔒</div>
            <div className="empty-title">{L('ownerNotAuthenticated')}</div>
            <div className="muted ap-blocked-body">
              {L('gateLockedBody')}
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
    const msg = denied ? `${t('state.permissionDenied')}: ${error}` : `${L('engineUnreachable')} ${error}`;
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
          title={L('gateClear')}
          hint={L('newRequestsHint')}
        />
      </section>,
    );
  }

  // ── default: the seated gate + queue + real-derived stats strip ────────────
  const stagedItem = staged ? items.find((a) => a.id === staged.id) ?? null : null;
  const meta = seated ? statusMeta(seated.status, L) : statusMeta('pending', L);
  const when = seated ? parseWhen(seated.requestedAt) : null;
  const isPending = !!seated && seated.status === 'pending';
  const opened = !!seated && /^(approved|granted|confirmed)$/i.test(seated.status);
  const pushed = !!seated && /^(rejected|denied|expired)$/i.test(seated.status);

  // Hold-fill ring (decorative, aria-hidden with the whole seal): a pending gate
  // shows an empty track that a deliberate press-and-hold sweeps full over HOLD_MS,
  // reinforcing the grant bar; approved/active gates show the tone ring resolved,
  // denied/expired empty it. Never anticipates the verdict — the ring only fills
  // while a real hold is in progress, and the seal/stamp still wait on real data.
  const ringOffset = opened ? 0 : pushed ? CIRC : isPending ? (holding ? 0 : CIRC) : 0;

  const tiles: Array<[number, string, string]> = [
    [items.length, L('inQueue'), 'as-info'],
    [pendingCount, L('pendingNow'), 'as-warn'],
    [approvedCount, L('approvedLower'), 'as-mint'],
    [deniedCount, L('deniedHeld'), ''],
  ];

  return frame(
    <>
      {/* ── HERO · the authorization gate (seats the selected real approval) ── */}
      <section
        className={`gate surface soft lg hud reveal ${meta.gate}`}
        style={{ '--i': 1 } as CSSProperties}
        aria-live="polite"
        aria-label={seated ? `${L('approvalGatePrefix')}${seated.actionType}, ${meta.lbl}` : undefined}
      >
        <span className="bracket tl" aria-hidden="true" /><span className="bracket tr" aria-hidden="true" />
        <span className="bracket bl" aria-hidden="true" /><span className="bracket br" aria-hidden="true" />
        <span className="ticks" aria-hidden="true"><i /><i /><i /><i /><i /><i /><i /><i /><i /></span>

        <div className="g-head">
          <div className="gh-title">
            <span className="eyebrow">{L('controlGate')}</span>
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
            <span className="micro">{L('requestingAgent')}</span>
            <div className="gr-id">
              <span aria-hidden="true"><Mark state={meta.mark} size={40} /></span>
              <div className="gr-who">
                <b>{seated?.requestedBy || '—'}</b>
                <span>{L('requester')}</span>
              </div>
            </div>
            <p className="gr-reason">{seated?.target}</p>
          </div>

          <div className="g-seal">
            <span className="s-cap micro">{L('actionHeld')}</span>
            <div className="seal-lock" aria-hidden="true">
              <svg className="sla-ring" viewBox="0 0 200 200">
                <circle className="sr-track" cx="100" cy="100" r="92" />
                <circle className="sr-val" cx="100" cy="100" r="92"
                  style={{
                    strokeDasharray: CIRC,
                    strokeDashoffset: ringOffset,
                    // Reduced motion → instant; a live hold sweeps over HOLD_MS; otherwise a quick settle.
                    transition: reduced ? 'none' : `stroke-dashoffset ${holding ? HOLD_MS : 380}ms linear, stroke .5s ease`,
                  } as CSSProperties} />
              </svg>
              <div className="seal-body">
                <span className="through" />
                <span className="half l" /><span className="half r" />
                <span className="seam" />
                <span className="keyhole" />
              </div>
              <span className="held" />
              <span className="tier-ring">{seated?.level}</span>
              {opened && <span className="stamp">{L('approvedStamp')}</span>}
            </div>
            <div className="sla-read">
              <b className="mono sla-time" aria-hidden="true">
                {isPending && when ? fmtElapsed(now - when.getTime()) : (opened ? '✓' : pushed ? '—' : '·')}
              </b>
              <span className="micro">
                {isPending ? L('waiting') : meta.lbl}
              </span>
            </div>
          </div>

          <div className="g-impact">
            <span className="micro">{L('impactScope')}</span>
            <div className="im-scope"><span className="dot" aria-hidden="true" />{seated?.target}</div>
            <div className="im-grid">
              <div className="im-row">
                <span className="micro">{t('field.level')}</span>
                <span className="im-v"><b className="mono">{seated?.level}</b></span>
              </div>
              <div className="im-row">
                <span className="micro">{t('field.risk')}</span>
                <span className="im-v"><b className="mono">{riskLabel((seated?.riskLevel ?? '').toLowerCase(), lang)}</b></span>
              </div>
              <div className="im-row">
                <span className="micro">{L('requestedByLabel')}</span>
                <span className="im-v"><b className="mono">{seated?.requestedBy}</b></span>
              </div>
              <div className="im-row">
                <span className="micro">{L('requestedAtLabel')}</span>
                <span className="im-v"><b className="mono">{when ? dateFmt.format(when) : (seated?.requestedAt || '—')}</b></span>
              </div>
            </div>
          </div>

        </div>

        {/* ── AUTHORIZATION BAR — the owner is the key ── */}
        <div className="g-authbar">
          <span className="ab-meta micro">
            {`${L('requestedWord')} ${when ? dateFmt.format(when) : (seated?.requestedAt || '—')} · `}
            <b>{seated?.level}</b>{L('levelSuffix')}
          </span>
          <div className="ab-actions">
            <button
              type="button" className="ab-btn deny" disabled={!isPending}
              onClick={() => seated && setStaged({ id: seated.id, kind: 'deny' })}
              aria-label={L('denyAria')}
            >✕ {L('deny')}</button>
            <button
              type="button" className="ab-btn escalate" disabled={!isPending}
              onClick={() => seated && setStaged({ id: seated.id, kind: 'escalate' })}
              aria-label={L('escalateForReview')}
            >↑ {L('escalateA3')}</button>
            <button
              type="button" className={`ab-btn grant${holding ? ' holding' : ''}`} disabled={!isPending}
              onPointerDown={(e) => { e.preventDefault(); startHold(); }}
              onPointerUp={cancelHold}
              onPointerLeave={cancelHold}
              onPointerCancel={cancelHold}
              onKeyDown={(e) => { if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) { e.preventDefault(); startHold(); } }}
              onKeyUp={(e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); cancelHold(); } }}
              onBlur={cancelHold}
              aria-label={opened ? L('approved') : L('pressHoldAria')}
            >
              <span className="grant-fill" aria-hidden="true" />
              <span className="grant-lbl">
                {opened ? `✓ ${L('approved')}` : L('pressHoldGrant')}
              </span>
            </button>
          </div>
        </div>
      </section>

      <div className="ap-hint muted" aria-hidden="true">
        {`↑/↓ ${L('select')} · ${L('holdGrantConfirm')} · g ${L('grant').toLowerCase()} · d ${L('denyLower')} · e ${L('escalateLower')}`}
      </div>

      {/* Engine approval-QUEUE mirror (read-only). Until the engine queue read answers,
          this reads honestly as blocked/unreachable — the list is the local mirror;
          the desktop never fabricates an engine queue and never decides on its own. */}
      {engineQueue.data && engineQueue.data.state !== 'ok' && (
        <div className="ap-blocked" role="note" style={{ padding: 'var(--s3) var(--s4)', textAlign: 'left' }}>
          <span className="muted">
            {engineQueue.data.state === 'unreachable'
              ? L('queueUnreachable')
              : L('queueSealed')}
            {engineQueue.data.reason ? ` (${engineQueue.data.reason})` : ''}
          </span>
        </div>
      )}

      {/* ── PENDING QUEUE ── */}
      <div className="sec-head" style={{ marginTop: 26 }}>
        <h2>{L('approvalQueue')}</h2>
        <span className="note">
          {L('selectRowHint')}
          <b className="mono">{items.length}</b>{L('inQueueSuffix')}
        </span>
      </div>
      {/* `listbox`/`option`, not `list`/`listitem` — found by the real-browser axe sweep
          (`aria-allowed-attr`, critical). These rows are a single-select list: clicking one
          decides which approval the panel above shows. That was expressed as a `<button>`
          re-roled to `listitem` carrying `aria-pressed`, and `aria-pressed` is not an allowed
          attribute on `listitem` — so a screen reader was handed a list item claiming a
          pressed state, which is neither a control nor a selection. The pattern that means
          what this UI does is listbox/option with `aria-selected`, and it keeps the buttons
          individually focusable. */}
      <div className="queue" role="listbox" aria-label={L('approvalQueueAria')}>
        {items.map((a, i) => {
          const m = statusMeta(a.status, L);
          const rw = parseWhen(a.requestedAt);
          const isSel = i === sel;
          const rowPending = a.status === 'pending';
          return (
            <button
              type="button" role="option"
              key={a.id}
              className={`q-row surface soft rise state-${m.face}${isSel ? ' on' : ''}`}
              style={{ '--i': i + 2 } as CSSProperties}
              aria-selected={isSel}
              aria-label={`${a.actionType}, ${a.target}, ${m.lbl}`}
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
                <span className="micro">{L('target')}</span>
                <b className="mono">{a.target}</b>
                <span className="q-rev ok">{riskLabel((a.riskLevel ?? '').toLowerCase(), lang)}</span>
              </span>
              <span className="q-sla">
                <span className="micro">{L('waitingLabel')}</span>
                <b className="mono">{rowPending && rw ? fmtElapsed(now - rw.getTime()) : '—'}</b>
              </span>
              <span className={`pill ${m.pill}`}>{m.lbl}</span>
            </button>
          );
        })}
      </div>

      {/* ── approval-stats strip (real-derived counts) ── */}
      <section className="surface soft astats-wrap rise" style={{ '--i': 2 } as CSSProperties} aria-label={L('approvalStats')}>
        <div className="astats">
          {tiles.map(([n, label, cls], i) => (
            <div className={`astat rise${cls ? ' ' + cls : ''}`} style={{ '--i': i + 2 } as CSSProperties} key={label}>
              <b className="mono">{n}</b>
              <span className="micro">{label}</span>
            </div>
          ))}
        </div>
        {/* The travelling `live` pulse is earned only while something is genuinely
            waiting on a human. An empty queue is a still divider, not a running feed. */}
        <div className={`wire${pendingCount > 0 ? ' live' : ''}`} aria-hidden="true" />
      </section>

      {/* All three actions confirm before committing (§D). `g`/`d`/`e` stage this dialog;
          the pointer press-and-hold on the grant key is the mouse-driven equivalent, not a
          second authority — both end at the same `confirm_approval`, which is adjudicated
          behind the Rust-driven native dialog the webview cannot forge (T-011). */}
      {staged && stagedItem && (
        <ConfirmDialog
          title={
            staged.kind === 'grant' ? L('confirmGrant')
              : staged.kind === 'deny' ? L('confirmDenial')
                : L('escalateForReview')
          }
          message={
            staged.kind === 'grant'
              ? `${L('grantDialogA')}${stagedItem.actionType}${L('grantDialogB')}${stagedItem.target}${L('grantDialogC')}`
              : staged.kind === 'deny'
                ? `${L('denyDialogA')}${stagedItem.actionType}${L('denyDialogB')}${stagedItem.target}${L('denyDialogC')}`
                : `${L('escalateDialogA')}${stagedItem.actionType}${L('escalateDialogB')}${stagedItem.target}${L('escalateDialogC')}`
          }
          confirmLabel={
            staged.kind === 'grant' ? L('grant')
              : staged.kind === 'deny' ? t('action.reject')
                : L('escalate')
          }
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

      /* The grant key is a real hold gesture. Under reduced motion the shared
         aios.css already collapses the grant-fill and SLA-ring transitions to ~0ms,
         so the fill is instant with no continuous sweep — the deliberate ~${HOLD_MS}ms
         press is still required; only the animation is removed. Nothing here re-adds it. */
      .v-approvals .ab-btn.grant .grant-fill { will-change: transform; }
    `}</style>
  );
}
