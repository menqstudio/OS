import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { useApp } from '../app/store';
import { PageHeader, Panel, Button, Badge, Avatar, EmptyState, Skeleton, ErrorState } from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { desktop, hasBackend } from '../services/desktop';
import type { ActivityEvent } from '../domain/entities';

// ─────────────────────────────────────────────────────────────────────────────
// activity ♥ Զարկերակ — the "pulse" page.
//
// Data source per §D: engine runtime telemetry (live). The desktop backend
// exposes `list_activity` (the chronological event record) but NO runtime
// telemetry IPC yet (system pulse / avg response / network load / error rate).
// So the honest split is:
//   • Blip markers  → REAL `desktop.listActivity()` data (one blip per event).
//   • Vitals numbers → the telemetry command is absent, so they render the
//     honest "not connected" state — never fabricated numbers.
//   • The ECG waveform itself is deterministic geometry (presentation, like the
//     calendar grid), not data.
// ─────────────────────────────────────────────────────────────────────────────

/** Longest run of blips we plot before collapsing the tail into a "+N" note. */
const MAX_BLIPS = 48;
/** Number of ECG complexes drawn across the strip (visual cadence only). */
const ECG_BEATS = 8;
const STRIP_W = 1000;
const STRIP_H = 150;

/** Respect `prefers-reduced-motion` for JS-driven motion (CSS handles the rest). */
function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== 'undefined' && !!window.matchMedia
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  );
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const on = () => setReduced(mq.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  return reduced;
}

/** Integer count-up (§D motion "integer count-up on vitals"). Snaps instantly
 *  when `animate` is false so reduced-motion users get the final value at once. */
function useCountUp(target: number, animate: boolean): number {
  const [value, setValue] = useState(animate ? 0 : target);
  useEffect(() => {
    if (!animate) { setValue(target); return; }
    let raf = 0;
    const start = performance.now();
    const dur = 600;
    const step = (now: number) => {
      const p = Math.min(1, (now - start) / dur);
      setValue(Math.round(target * p));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, animate]);
  return value;
}

/** buildECG — synthesize an ECG (P-QRS-T) SVG path across `beats` complexes.
 *  Deterministic geometry; carries no telemetry meaning. */
function buildECG(width: number, height: number, beats: number): string {
  const mid = height / 2;
  const seg = width / beats;
  let d = `M 0 ${mid}`;
  for (let i = 0; i < beats; i++) {
    const x = i * seg;
    const p = x + seg * 0.14;
    const q = x + seg * 0.42;
    const r = x + seg * 0.48;
    const s = x + seg * 0.54;
    const tw = x + seg * 0.74;
    d += ` L ${p.toFixed(1)} ${mid.toFixed(1)}`;
    d += ` L ${(p + seg * 0.05).toFixed(1)} ${(mid - height * 0.09).toFixed(1)}`;  // P
    d += ` L ${(p + seg * 0.1).toFixed(1)} ${mid.toFixed(1)}`;
    d += ` L ${q.toFixed(1)} ${(mid + height * 0.07).toFixed(1)}`;                 // Q
    d += ` L ${r.toFixed(1)} ${(mid - height * 0.42).toFixed(1)}`;                 // R
    d += ` L ${s.toFixed(1)} ${(mid + height * 0.18).toFixed(1)}`;                 // S
    d += ` L ${(s + seg * 0.04).toFixed(1)} ${mid.toFixed(1)}`;
    d += ` L ${tw.toFixed(1)} ${(mid - height * 0.15).toFixed(1)}`;                // T
    d += ` L ${(tw + seg * 0.08).toFixed(1)} ${mid.toFixed(1)}`;
    d += ` L ${(x + seg).toFixed(1)} ${mid.toFixed(1)}`;
  }
  return d;
}

interface Bi { (en: string, hy: string): string }

// The four §D vitals. Values come from live engine runtime telemetry — a command
// the desktop backend does not expose yet — so each renders honestly unavailable.
interface Vital { key: string; label: string; unit: string }

function PaBeatline({
  events, sel, opened, plot, sweep, frozen, reduced, bi, onSelect, onOpen, onKeyDown, blipLabel, gridId,
}: {
  events: ActivityEvent[];
  sel: number;
  opened: number | null;
  plot: boolean;
  sweep: boolean;
  frozen: boolean;
  reduced: boolean;
  bi: Bi;
  onSelect: (i: number) => void;
  onOpen: (i: number) => void;
  onKeyDown: (e: KeyboardEvent<HTMLDivElement>) => void;
  blipLabel: (e: ActivityEvent, i: number) => string;
  gridId: string;
}) {
  const blipRefs = useRef<(HTMLButtonElement | null)[]>([]);
  blipRefs.current = [];

  // Keep the roving-tabindex focus in sync with the selected blip after the
  // wrapper handles an arrow key.
  useEffect(() => {
    const el = blipRefs.current[sel];
    if (el && document.activeElement && el.closest('.pa-strip')?.contains(document.activeElement)) {
      el.focus();
    }
  }, [sel]);

  const path = useMemo(() => buildECG(STRIP_W, STRIP_H, ECG_BEATS), []);
  const stripClass = [
    'pa-strip',
    plot ? 'pa-strip--plot' : '',
    sweep && !frozen && !reduced ? 'pa-strip--sweeping' : '',
    frozen ? 'pa-strip--frozen' : '',
  ].filter(Boolean).join(' ');

  return (
    <div
      className={stripClass}
      role="group"
      tabIndex={0}
      aria-label={bi('Activity beatline — arrow keys scrub beats, Enter opens a beat, Space freezes',
        'Ակտիվության զարկագիծ — սլաքներով անցեք զարկերով, Enter՝ բացել, Space՝ սառեցնել')}
      onKeyDown={onKeyDown}
    >
      <svg
        className="pa-beatline"
        viewBox={`0 0 ${STRIP_W} ${STRIP_H}`}
        preserveAspectRatio="none"
        role="img"
        aria-hidden="true"
        focusable="false"
      >
        <defs>
          <pattern id={gridId} width="40" height="30" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 30" fill="none" className="pa-grid-line" />
          </pattern>
        </defs>
        {plot && <rect x="0" y="0" width={STRIP_W} height={STRIP_H} fill={`url(#${gridId})`} />}
        <line x1="0" y1={STRIP_H / 2} x2={STRIP_W} y2={STRIP_H / 2} className="pa-baseline" />
        <path d={path} className="pa-trace" fill="none" />
        {sweep && !reduced && <rect className="pa-sweep" x="0" y="0" width="3" height={STRIP_H} />}
      </svg>

      <div className="pa-blips">
        {events.map((e, i) => {
          const pct = ((i + 0.5) / events.length) * 100;
          const isSel = i === sel;
          const isOpen = i === opened;
          const cls = ['pa-blip', isSel ? 'pa-blip--sel' : '', isOpen ? 'pa-blip--open' : ''].filter(Boolean).join(' ');
          return (
            <button
              key={e.id}
              type="button"
              ref={(el) => { blipRefs.current[i] = el; }}
              className={cls}
              style={{ left: `${pct}%`, animationDelay: reduced ? undefined : `${Math.min(i, 20) * 24}ms` }}
              tabIndex={isSel ? 0 : -1}
              aria-label={blipLabel(e, i)}
              aria-pressed={isOpen}
              title={blipLabel(e, i)}
              onClick={() => { onSelect(i); onOpen(i); }}
              onFocus={() => onSelect(i)}
            >
              <span className="pa-blip-dot" aria-hidden="true" />
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function Activity() {
  const { t, lang } = useApp();
  const reduced = usePrefersReducedMotion();
  const state = useAsync<ActivityEvent[]>(() => desktop.listActivity());

  const bi = useCallback<Bi>((en, hy) => (lang === 'hy' ? hy : en), [lang]);

  const [frozen, setFrozen] = useState(false);
  const [sweep, setSweep] = useState(true);
  const [plot, setPlot] = useState(false);
  const [sel, setSel] = useState(0);
  const [opened, setOpened] = useState<number | null>(null);
  const gridId = useRef(`pa-grid-${Math.random().toString(36).slice(2)}`).current;

  const events = state.data ?? [];
  const displayed = useMemo(() => events.slice(0, MAX_BLIPS), [events]);
  const hiddenCount = events.length - displayed.length;

  // Keep selection in range as data changes.
  useEffect(() => {
    setSel((s) => (displayed.length === 0 ? 0 : Math.min(s, displayed.length - 1)));
    setOpened((o) => (o !== null && o >= displayed.length ? null : o));
  }, [displayed.length]);

  const dateFmt = useMemo(
    () => new Intl.DateTimeFormat(lang, { dateStyle: 'medium', timeStyle: 'short' }),
    [lang],
  );
  const fmtWhen = useCallback((raw: string) => {
    const d = new Date(isNaN(Number(raw)) ? raw : Number(raw));
    return isNaN(d.getTime()) ? raw : dateFmt.format(d);
  }, [dateFmt]);

  const blipLabel = useCallback((e: ActivityEvent, i: number) => {
    const target = e.entityId ?? e.entityType ?? '';
    return bi(
      `Beat ${i + 1}: ${e.eventType}${target ? ` on ${target}` : ''}`,
      `Զարկ ${i + 1}․ ${e.eventType}${target ? ` · ${target}` : ''}`,
    );
  }, [bi]);

  const move = useCallback((delta: number) => {
    setSel((s) => Math.max(0, Math.min(displayed.length - 1, s + delta)));
  }, [displayed.length]);

  const onKeyDown = useCallback((e: KeyboardEvent<HTMLDivElement>) => {
    if (displayed.length === 0) return;
    switch (e.key) {
      case ' ':
      case 'Spacebar':
        e.preventDefault();                       // Space → freeze (not scroll / not blip click)
        setFrozen((f) => !f);
        break;
      case 'ArrowRight':
      case 'ArrowDown':
        e.preventDefault();
        move(1);
        break;
      case 'ArrowLeft':
      case 'ArrowUp':
        e.preventDefault();
        move(-1);
        break;
      case 'Home':
        e.preventDefault();
        setSel(0);
        break;
      case 'End':
        e.preventDefault();
        setSel(displayed.length - 1);
        break;
      case 'Enter':
        e.preventDefault();                       // Enter → open the focused beat's detail
        setOpened(sel);
        break;
      case 'Escape':
        if (opened !== null) { e.preventDefault(); setOpened(null); }
        break;
      default:
        break;
    }
  }, [displayed.length, move, sel, opened]);

  const beatCount = useCountUp(events.length, !reduced && !state.loading && !state.error);

  const vitals: Vital[] = [
    { key: 'pulse', label: bi('System pulse', 'Համակարգի զարկ'), unit: bi('/min', '/րոպե') },
    { key: 'response', label: bi('Avg response', 'Միջին արձագանք'), unit: 'ms' },
    { key: 'network', label: bi('Network load', 'Ցանցի բեռ'), unit: '%' },
    { key: 'error', label: bi('Error rate', 'Սխալի հաճախ.'), unit: '%' },
  ];

  const selEvent = displayed[sel];
  const openEvent = opened !== null ? displayed[opened] : null;

  // Text-equivalent live region (§D a11y). Describes the strip in words: pulse is
  // honestly reported unavailable; the focused beat and beat count are real.
  const liveText = state.loading
    ? bi('Loading activity beatline…', 'Բեռնվում է ակտիվության զարկագիծը…')
    : bi(
      `System pulse unavailable (telemetry not connected). ${events.length} activity beats.${selEvent ? ` Focused beat ${sel + 1} of ${displayed.length}: ${selEvent.eventType}.` : ''}`,
      `Համակարգի զարկն անհասանելի է (հեռաչափումը միացված չէ)։ ${events.length} ակտիվության զարկ։${selEvent ? ` Կիզակետում՝ զարկ ${sel + 1}/${displayed.length}՝ ${selEvent.eventType}։` : ''}`,
    );

  const controls = (
    <div className="pa-controls" role="group" aria-label={bi('Beatline controls', 'Զարկագծի կառավարում')}>
      <Button small onClick={() => setFrozen((f) => !f)} title={bi('Freeze (Space)', 'Սառեցնել (Space)')}>
        <span aria-hidden="true">{frozen ? '▷' : '⏸'}</span>
        <span>{frozen ? bi('Frozen', 'Սառեցված') : bi('Freeze', 'Սառեցնել')}</span>
      </Button>
      <Button small variant={plot ? 'primary' : 'default'} onClick={() => setPlot((p) => !p)} title={bi('Toggle plot grid', 'Ցանց')}>
        <span aria-hidden="true">▦</span>{bi('Plot', 'Գծապատկեր')}
      </Button>
      <Button small variant={sweep ? 'primary' : 'default'} onClick={() => setSweep((s) => !s)} title={bi('Toggle sweep', 'Մաքրում')}>
        <span aria-hidden="true">↻</span>{bi('Sweep', 'Անցում')}
      </Button>
    </div>
  );

  const liveMark = (
    <span className={`pa-now ${state.loading || state.error ? 'pa-now--off' : ''} ${reduced ? 'pa-now--still' : ''}`}>
      <span className="pa-now-dot" aria-hidden="true" />
      {state.loading
        ? bi('Connecting', 'Միանում է')
        : state.error ? bi('Offline', 'Անջատված') : bi('Live', 'Կենդանի')}
    </span>
  );

  // ── Body: resolve the §D state (loading / blocked / error / empty / default) ──
  let body: ReactNode;
  if (state.loading && state.data === null) {
    // loading → strip skeleton
    body = (
      <div className="stack" style={{ gap: 'var(--menq-space-5)' }}>
        <div className="pa-strip pa-strip--skeleton" aria-busy="true" aria-label={bi('Loading beatline', 'Բեռնվում է զարկագիծը')}>
          <div className="pa-skeleton-line" />
        </div>
        <div className="pa-vitals">
          {vitals.map((v) => (
            <div key={v.key} className="pa-vital"><Skeleton rows={1} /></div>
          ))}
        </div>
      </div>
    );
  } else if (state.error && !hasBackend()) {
    // no desktop backend (e.g. browser preview) → calm offline, not alarming red
    body = <EmptyState glyph="♥" title={t('state.offline')} hint={t('state.offlineHint')} />;
  } else if (state.error && /denied|not permitted|permission|blocked/i.test(state.error)) {
    // blocked → the telemetry stream is refused by the governance wall
    body = (
      <div className="pa-blocked" role="status">
        <div className="pa-blocked-glyph" aria-hidden="true">⧉</div>
        <div className="pa-blocked-title">{bi('Telemetry stream blocked', 'Հեռաչափման հոսքն արգելափակված է')}</div>
        <div className="muted" style={{ maxWidth: 460, marginInline: 'auto' }}>
          {bi('The runtime telemetry stream did not clear the governance wall. No live data crosses until it is approved.',
            'Հեռաչափման հոսքը չանցավ կառավարման պատը։ Կենդանի տվյալ չի փոխանցվում մինչ հաստատում։')}
        </div>
        <div className="muted pa-blocked-reason">{state.error}</div>
        <div style={{ marginTop: 12 }}><Button small onClick={state.reload}>{t('action.retry')}</Button></div>
      </div>
    );
  } else if (state.error) {
    // error → stream lost
    body = (
      <ErrorState
        message={bi(`Telemetry stream lost — ${state.error}`, `Հեռաչափման հոսքը կորավ — ${state.error}`)}
        onRetry={state.reload}
        retryLabel={t('action.retry')}
      />
    );
  } else if (displayed.length === 0) {
    // empty → no activity yet
    body = (
      <EmptyState
        glyph="♥"
        title={bi('No activity yet', 'Դեռ ակտիվություն չկա')}
        hint={bi('Beats will appear here as the engine records events.', 'Զարկերը կհայտնվեն այստեղ, երբ շարժիչը գրանցի իրադարձություններ։')}
      />
    );
  } else {
    // default (live)
    body = (
      <div className="stack" style={{ gap: 'var(--menq-space-5)' }}>
        <PaBeatline
          events={displayed}
          sel={sel}
          opened={opened}
          plot={plot}
          sweep={sweep}
          frozen={frozen}
          reduced={reduced}
          bi={bi}
          onSelect={setSel}
          onOpen={setOpened}
          onKeyDown={onKeyDown}
          blipLabel={blipLabel}
          gridId={gridId}
        />

        {hiddenCount > 0 && (
          <div className="muted pa-tail">{bi(`+${hiddenCount} earlier beats not plotted`, `+${hiddenCount} ավելի վաղ զարկ չեն գծագրված`)}</div>
        )}

        <div className="pa-vitals">
          {/* Real, live vital derived from the activity feed (backend data). */}
          <div className="pa-vital pa-vital--live">
            <span className="pa-vital-label">{bi('Live beats', 'Կենդանի զարկեր')}</span>
            <span className="pa-vital-value">{beatCount}</span>
            <span className="pa-vital-unit">{bi('events', 'իրադ.')}</span>
          </div>
          {/* Runtime-telemetry vitals: no backing command → honest "unavailable". */}
          {vitals.map((v) => (
            <div key={v.key} className="pa-vital pa-vital--na" aria-label={bi(`${v.label}: unavailable`, `${v.label}՝ անհասանելի`)}>
              <span className="pa-vital-label">{v.label}</span>
              <span className="pa-vital-value pa-vital-value--na" aria-hidden="true">—</span>
              <span className="pa-vital-unit">{v.unit}</span>
            </div>
          ))}
        </div>
        <div className="muted pa-vitals-note" role="note">
          {bi('Live telemetry not connected — the engine runtime telemetry stream is not wired to this build. Beats above are the real event record.',
            'Կենդանի հեռաչափումը միացված չէ — շարժիչի հեռաչափման հոսքը միացված չէ։ Վերևի զարկերը իրական գրառումն են։')}
        </div>

        {/* Enter opens a beat's detail (§D keyboard). */}
        {openEvent && (
          <div className="pa-detail" role="region" aria-label={bi('Beat detail', 'Զարկի մանրամասն')}>
            <div className="pa-detail-head">
              <div className="row" style={{ gap: 8 }}>
                <Badge tone="info">{openEvent.eventType}</Badge>
                <span className="pa-detail-title">{blipLabel(openEvent, opened ?? 0)}</span>
              </div>
              <Button small variant="ghost" onClick={() => setOpened(null)} title={bi('Close (Esc)', 'Փակել (Esc)')} aria-label={bi('Close beat detail', 'Փակել')}>✕</Button>
            </div>
            <div className="pa-detail-grid">
              <PaField label={bi('Actor', 'Դերակատար')}>
                <span className="row" style={{ gap: 6 }}><Avatar name={openEvent.actorId ?? 'system'} />{openEvent.actorId ?? bi('system', 'համակարգ')}</span>
              </PaField>
              <PaField label={bi('Entity', 'Օբյեկտ')}>{openEvent.entityType ?? '—'}</PaField>
              <PaField label={bi('Entity ID', 'Օբյեկտի ID')}><code className="pa-mono">{openEvent.entityId ?? '—'}</code></PaField>
              <PaField label={bi('When', 'Ե՞րբ')}>{fmtWhen(openEvent.createdAt)}</PaField>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <>
      <style>{PA_STYLE}</style>
      <PageHeader
        title={`${t('nav.activity')} ♥ Զարկերակ`}
        subtitle={t('activity.subtitle')}
        actions={liveMark}
      />

      {/* Text-equivalent live region for the strip (§D a11y). */}
      <span className="pa-sr" role="status" aria-live="polite" aria-atomic="true">{liveText}</span>

      <Panel
        title={bi('Beatline', 'Զարկագիծ')}
        actions={!state.loading && !state.error && displayed.length > 0 ? controls : undefined}
      >
        {body}
      </Panel>
    </>
  );
}

function PaField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="pa-field">
      <span className="pa-field-label">{label}</span>
      <span className="pa-field-value">{children}</span>
    </div>
  );
}

const PA_STYLE = `
.pa-sr { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }

/* live "now" heartbeat mark */
.pa-now { display: inline-flex; align-items: center; gap: 7px; font-size: 12px; font-weight: 600; color: var(--menq-color-success); }
.pa-now-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--menq-color-success); box-shadow: 0 0 0 0 color-mix(in srgb, var(--menq-color-success) 60%, transparent); animation: pa-nowPulse 1.4s ease-out infinite; }
.pa-now--off { color: var(--brops-muted); }
.pa-now--off .pa-now-dot { background: var(--brops-muted); animation: none; }
.pa-now--still .pa-now-dot { animation: none; }
@keyframes pa-nowPulse {
  0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--menq-color-success) 55%, transparent); transform: scale(1); }
  70% { box-shadow: 0 0 0 8px color-mix(in srgb, var(--menq-color-success) 0%, transparent); transform: scale(1.12); }
  100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--menq-color-success) 0%, transparent); transform: scale(1); }
}

/* the ECG strip / beatline */
.pa-strip { position: relative; width: 100%; height: 160px; background: var(--brops-bg);
  border: 1px solid var(--brops-border); border-radius: var(--menq-radius-card); overflow: hidden; outline: none; }
.pa-strip:focus-visible { border-color: var(--brops-accent); box-shadow: 0 0 0 2px color-mix(in srgb, var(--brops-accent) 40%, transparent); }
.pa-beatline { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
.pa-baseline { stroke: var(--brops-border); stroke-width: 1; }
.pa-grid-line { stroke: color-mix(in srgb, var(--brops-border) 70%, transparent); stroke-width: 1; }
.pa-trace { stroke: var(--menq-color-success); stroke-width: 2; vector-effect: non-scaling-stroke;
  filter: drop-shadow(0 0 3px color-mix(in srgb, var(--menq-color-success) 40%, transparent)); }
.pa-sweep { fill: color-mix(in srgb, var(--menq-color-success) 70%, transparent); opacity: 0; }
.pa-strip--sweeping .pa-sweep { opacity: 0.8; animation: pa-sweepMove 3.2s linear infinite; }
.pa-strip--frozen .pa-sweep { animation-play-state: paused; }
@keyframes pa-sweepMove { from { transform: translateX(0); } to { transform: translateX(1000px); } }

/* blip markers (buttons overlaid on the trace) */
.pa-blips { position: absolute; inset: 0; }
.pa-blip { position: absolute; top: 50%; transform: translate(-50%, -50%); width: 22px; height: 22px;
  display: grid; place-items: center; padding: 0; background: transparent; border: none; cursor: pointer;
  border-radius: 50%; animation: pa-blipReveal var(--menq-motion-med) ease-out both; }
.pa-blip-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--brops-accent);
  border: 2px solid var(--brops-bg); box-shadow: 0 0 0 1px var(--brops-accent);
  transition: transform var(--menq-motion-fast); }
.pa-blip:hover .pa-blip-dot { transform: scale(1.25); }
.pa-blip--sel .pa-blip-dot { background: var(--menq-color-warning); box-shadow: 0 0 0 1px var(--menq-color-warning), 0 0 8px color-mix(in srgb, var(--menq-color-warning) 60%, transparent); }
.pa-blip--open .pa-blip-dot { background: var(--menq-color-success); box-shadow: 0 0 0 1px var(--menq-color-success); }
.pa-blip:focus-visible { outline: none; }
.pa-blip:focus-visible .pa-blip-dot { transform: scale(1.3); box-shadow: 0 0 0 2px var(--brops-accent), 0 0 0 4px var(--brops-bg); }
@keyframes pa-blipReveal { from { opacity: 0; transform: translate(-50%, -50%) scale(0.4); } to { opacity: 1; transform: translate(-50%, -50%) scale(1); } }

.pa-controls { display: inline-flex; gap: var(--menq-space-2); }
.pa-tail { font-size: 12px; }

/* skeleton strip (loading) */
.pa-strip--skeleton { height: 160px; display: grid; place-items: center; }
.pa-skeleton-line { width: 92%; height: 3px; border-radius: 2px;
  background: linear-gradient(90deg, transparent, var(--menq-color-hover) 20%, var(--brops-border) 50%, var(--menq-color-hover) 80%, transparent);
  background-size: 200% 100%; animation: pa-shimmer 1.4s linear infinite; }
@keyframes pa-shimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }

/* vitals readout */
.pa-vitals { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: var(--menq-space-3); }
.pa-vital { display: flex; flex-direction: column; gap: 3px; padding: var(--menq-space-4);
  background: var(--brops-surface); border: 1px solid var(--brops-border); border-radius: var(--menq-radius-md); }
.pa-vital--live { border-color: color-mix(in srgb, var(--menq-color-success) 45%, var(--brops-border)); }
.pa-vital-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--brops-muted); }
.pa-vital-value { font-size: 26px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1.1; }
.pa-vital--live .pa-vital-value { color: var(--menq-color-success); }
.pa-vital-value--na { color: var(--brops-muted); opacity: 0.6; }
.pa-vital-unit { font-size: 11px; color: var(--brops-muted); }
.pa-vitals-note { font-size: 12px; }
@media (max-width: 1000px) { .pa-vitals { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 640px) { .pa-vitals { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

/* blocked state */
.pa-blocked { text-align: center; padding: var(--menq-space-7) var(--menq-space-4); }
.pa-blocked-glyph { font-size: 30px; color: var(--menq-color-warning); }
.pa-blocked-title { font-weight: 700; margin: var(--menq-space-3) 0 6px; }
.pa-blocked-reason { font-size: 12px; margin-top: 8px; font-family: var(--menq-font-mono); opacity: 0.8; }

/* beat detail */
.pa-detail { background: var(--brops-surface); border: 1px solid var(--brops-border); border-radius: var(--menq-radius-md); padding: var(--menq-space-4); }
.pa-detail-head { display: flex; align-items: center; justify-content: space-between; gap: var(--menq-space-3); margin-bottom: var(--menq-space-4); }
.pa-detail-title { font-weight: 600; }
.pa-detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--menq-space-4); }
.pa-field { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.pa-field-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--brops-muted); }
.pa-field-value { min-width: 0; overflow-wrap: anywhere; }
.pa-mono { font-family: var(--menq-font-mono); font-size: 0.9em; }
@media (max-width: 640px) { .pa-detail-grid { grid-template-columns: 1fr; } }

@media (prefers-reduced-motion: reduce) {
  .pa-now-dot, .pa-sweep, .pa-blip, .pa-skeleton-line { animation: none !important; }
  .pa-blip { opacity: 1; }
  .pa-blip-dot, .pa-blip:hover .pa-blip-dot { transition: none; }
}
`;
