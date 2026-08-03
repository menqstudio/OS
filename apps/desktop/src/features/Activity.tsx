import { useCallback, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import { useApp } from '../app/store';
import { Button, Avatar, EmptyState, Skeleton, ErrorState, usePrefersReducedMotion } from '../components/ui';
import { Mark } from '../components/Ambient';
import { useAsync } from '../hooks/useAsync';
import { desktop, hasBackend } from '../services/desktop';
import { StripChart, type StripPoint } from '../components/charts/Chart';
import type { ActivityEvent } from '../domain/entities';

// ─────────────────────────────────────────────────────────────────────────────
// activity ♥ Զարկերակ — the "System Pulse Monitor".
//
// Every beat is a REAL system event from `desktop.listActivity()`. The ECG strip
// stays the interactive `StripChart` primitive — one keyboard-scrubbable blip per
// real event, deterministic geometry, reduced-motion aware. The surrounding HUD
// (hero brackets, pulse-rail core, beat timeline, vitals panel) is re-dressed to
// the aios "vitals monitor" mockup, but every number shown is DERIVED from the
// real events array (total beats, event types, plotted count, rate/min, last-beat
// time). The mockup's live runtime telemetry — avg response, network load, error
// rate, per-beat intensity, sparklines, rhythm % — has no backing IPC, so it is
// omitted rather than fabricated; the honest "telemetry not connected" note stays.
// ─────────────────────────────────────────────────────────────────────────────

/** Longest run of blips we plot before collapsing the tail into a "+N" note. */
const MAX_BLIPS = 48;
/** ECG complexes drawn across the strip (visual cadence only — StripChart owns it). */
const ECG_BEATS = 8;

/** Parse an event timestamp (ISO or epoch string) to ms, or null if unparseable. */
function parseTime(raw: string): number | null {
  const n = Number(raw);
  const d = new Date(Number.isNaN(n) ? raw : n);
  const ms = d.getTime();
  return Number.isNaN(ms) ? null : ms;
}

/** Inline `--i` reveal-stagger custom property. */
const cv = (i: number): CSSProperties => ({ ['--i']: i } as CSSProperties);

/** HUD corner brackets + edge ticks — purely decorative chrome. */
function HudChrome() {
  return (
    <>
      <span className="bracket tl" aria-hidden="true" />
      <span className="bracket tr" aria-hidden="true" />
      <span className="bracket bl" aria-hidden="true" />
      <span className="bracket br" aria-hidden="true" />
      <span className="ticks" aria-hidden="true">
        {Array.from({ length: 9 }).map((_, k) => <i key={k} />)}
      </span>
    </>
  );
}

/** Integer count-up on the pulse core. Snaps instantly under reduced motion. */
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

interface Bi { (en: string, hy: string): string }

export function Activity() {
  const { t, lang } = useApp();
  const reduced = usePrefersReducedMotion();
  const state = useAsync<ActivityEvent[]>(() => desktop.listActivity());

  const bi = useCallback<Bi>((en, hy) => (lang === 'hy' ? hy : en), [lang]);

  const [frozen, setFrozen] = useState(false);
  const [sel, setSel] = useState(0);
  const [opened, setOpened] = useState<number | null>(null);

  const events = state.data ?? [];
  const displayed = useMemo(() => events.slice(0, MAX_BLIPS), [events]);
  const hiddenCount = events.length - displayed.length;

  // Keep selection/open in range as data changes.
  useEffect(() => {
    setSel((s) => (displayed.length === 0 ? 0 : Math.min(s, displayed.length - 1)));
    setOpened((o) => (o !== null && o >= displayed.length ? null : o));
  }, [displayed.length]);

  const dateFmt = useMemo(
    () => new Intl.DateTimeFormat(lang, { dateStyle: 'medium', timeStyle: 'short' }),
    [lang],
  );
  const timeFmt = useMemo(() => new Intl.DateTimeFormat(lang, { timeStyle: 'short' }), [lang]);
  const fmtWhen = useCallback((raw: string) => {
    const ms = parseTime(raw);
    return ms == null ? raw : dateFmt.format(new Date(ms));
  }, [dateFmt]);
  const fmtTime = useCallback((raw: string) => {
    const ms = parseTime(raw);
    return ms == null ? raw : timeFmt.format(new Date(ms));
  }, [timeFmt]);

  const blipLabel = useCallback((e: ActivityEvent, i: number) => {
    const target = e.entityId ?? e.entityType ?? '';
    return bi(
      `Beat ${i + 1}: ${e.eventType}${target ? ` on ${target}` : ''}`,
      `Զարկ ${i + 1}․ ${e.eventType}${target ? ` · ${target}` : ''}`,
    );
  }, [bi]);

  // One strip point per real event — StripChart owns geometry + roving keyboard.
  const points = useMemo<StripPoint[]>(
    () => displayed.map((e, i) => ({ id: e.id, label: blipLabel(e, i) })),
    [displayed, blipLabel],
  );

  // Real derived vitals — everything here comes straight from the events array.
  const metrics = useMemo(() => {
    const count = events.length;
    const ts = events.map((e) => parseTime(e.createdAt)).filter((n): n is number => n != null);
    const latest = ts.length ? Math.max(...ts) : null;
    const earliest = ts.length ? Math.min(...ts) : null;
    const spanMin = latest != null && earliest != null && latest > earliest ? (latest - earliest) / 60000 : 0;
    const rate = spanMin > 0 ? Math.max(1, Math.round(count / spanMin)) : null; // events / min
    const types = new Set(events.map((e) => e.eventType)).size;
    return { count, latest, earliest, spanMin, rate, types };
  }, [events]);

  // Timeline: real events, newest first, carrying their strip index for cross-link.
  const timeline = useMemo(
    () => displayed
      .map((e, i) => ({ e, i }))
      .sort((a, b) => (parseTime(b.e.createdAt) ?? 0) - (parseTime(a.e.createdAt) ?? 0)),
    [displayed],
  );

  const animate = !reduced && !state.loading && !state.error;
  const beatCount = useCountUp(metrics.count, animate);
  const clock = metrics.latest != null ? fmtTime(String(metrics.latest)) : '—';

  const selEvent = displayed[sel];
  const openEvent = opened !== null ? displayed[opened] : null;

  // Text-equivalent live region (§D a11y). Only real facts: beat count, derived
  // rate when a real time-span exists, and the focused beat.
  const liveText = state.loading
    ? bi('Loading activity beatline…', 'Բեռնվում է ակտիվության զարկագիծը…')
    : bi(
      `${metrics.count} activity beats.${metrics.rate != null ? ` About ${metrics.rate} per minute.` : ''}${selEvent ? ` Focused beat ${sel + 1} of ${displayed.length}: ${selEvent.eventType}.` : ''}`,
      `${metrics.count} ակտիվության զարկ։${metrics.rate != null ? ` Մոտ ${metrics.rate} զարկ/րոպե։` : ''}${selEvent ? ` Կիզակետում՝ զարկ ${sel + 1}/${displayed.length}՝ ${selEvent.eventType}։` : ''}`,
    );

  // Header status pill + power mark, driven by the real load state.
  const markState = state.loading ? 'boot' : state.error ? 'alert' : 'live';
  const pillTone = state.loading ? 'info' : state.error ? 'warn' : 'live';
  const pillText = state.loading
    ? bi('CONNECTING', 'ՄԻԱՆՈՒՄ')
    : state.error ? bi('OFFLINE', 'ԱՆՋԱՏՎԱԾ') : bi('RHYTHM · STABLE', 'ՌԻԹՄ · ԿԱՅՈՒՆ');

  // ── Resolve the §D state → the main region ──────────────────────────────────
  let main: ReactNode;
  if (state.loading && state.data === null) {
    main = (
      <StateFrame>
        <div className="pa-skel" aria-busy="true" aria-label={bi('Loading beatline', 'Բեռնվում է զարկագիծը')}>
          <Skeleton rows={4} />
        </div>
      </StateFrame>
    );
  } else if (state.error && !hasBackend()) {
    main = <StateFrame><EmptyState glyph="♥" title={t('state.offline')} hint={t('state.offlineHint')} /></StateFrame>;
  } else if (state.error && /denied|not permitted|permission|blocked/i.test(state.error)) {
    main = (
      <StateFrame>
        <div className="pa-blocked" role="status">
          <div className="pa-blocked-glyph" aria-hidden="true">⧉</div>
          <div className="pa-blocked-title">{bi('Telemetry stream blocked', 'Հեռաչափման հոսքն արգելափակված է')}</div>
          <p className="note" style={{ maxWidth: 460, marginInline: 'auto' }}>
            {bi('The runtime telemetry stream did not clear the governance wall. No live data crosses until it is approved.',
              'Հեռաչափման հոսքը չանցավ կառավարման պատը։ Կենդանի տվյալ չի փոխանցվում մինչ հաստատում։')}
          </p>
          <p className="micro pa-blocked-reason">{state.error}</p>
          <div style={{ marginTop: 12 }}><Button small onClick={state.reload}>{t('action.retry')}</Button></div>
        </div>
      </StateFrame>
    );
  } else if (state.error) {
    main = (
      <StateFrame>
        <ErrorState
          message={bi(`Telemetry stream lost — ${state.error}`, `Հեռաչափման հոսքը կորավ — ${state.error}`)}
          onRetry={state.reload}
          retryLabel={t('action.retry')}
        />
      </StateFrame>
    );
  } else if (displayed.length === 0) {
    main = (
      <StateFrame>
        <EmptyState
          glyph="♥"
          title={bi('No activity yet', 'Դեռ ակտիվություն չկա')}
          hint={bi('Beats will appear here as the engine records events.', 'Զարկերը կհայտնվեն այստեղ, երբ շարժիչը գրանցի իրադարձություններ։')}
        />
      </StateFrame>
    );
  } else {
    // default (live) — the full vitals monitor
    main = (
      <>
        {/* ── HERO · The Vitals Monitor ─────────────────────────────────── */}
        <section className={`pulse-hero surface soft lg hud reveal${frozen ? ' frozen' : ''}`} style={cv(1)}>
          <HudChrome />

          {/* left: the ECG strip (real events → StripChart) */}
          <div className="mon-wrap">
            <div className="mon-top">
              <span className="eyebrow">{bi('LEAD · SYSTEM', 'LEAD · ՀԱՄԱԿԱՐԳ')}</span>
              <span className="mon-clock mono">{clock}</span>
              <button
                type="button"
                className={`chip mon-freeze${frozen ? ' on' : ''}`}
                aria-pressed={frozen}
                onClick={() => setFrozen((f) => !f)}
                title={bi('Freeze', 'Սառեցնել')}
              >
                <span className="fz-ico" aria-hidden="true" />
                {frozen ? bi('Frozen', 'Սառեցված') : bi('Freeze', 'Սառեցնել')}
              </button>
            </div>

            <StripChart
              points={points}
              selected={sel}
              opened={opened}
              plot
              sweep={!reduced}
              frozen={frozen}
              beats={ECG_BEATS}
              ariaLabel={bi('Activity beatline — arrow keys scrub beats, Enter opens a beat, Space freezes',
                'Ակտիվության զարկագիծ — սլաքներով անցեք զարկերով, Enter՝ բացել, Space՝ սառեցնել')}
              onSelect={setSel}
              onOpen={setOpened}
              onToggleFreeze={() => setFrozen((f) => !f)}
              onCloseOpened={() => setOpened(null)}
            />

            {/* vitals readout — real derived numbers only */}
            <div className="vitals">
              <Vread i={4} label={bi('System pulse', 'Համակարգի զարկ')} value={metrics.rate ?? '—'} unit={bi('/min', 'զարկ/ր')} />
              <Vread i={5} label={bi('Event types', 'Տեսակներ')} value={metrics.types} unit={bi('types', 'տիպ')} />
              <Vread i={6} label={bi('Plotted', 'Ցուցադրված')} value={displayed.length} unit={`/${metrics.count}`} />
              <Vread i={7} label={bi('Last beat', 'Վերջին զարկ')} value={clock} />
            </div>
          </div>

          {/* right: the beating pulse core (real total beats) */}
          <aside className="pulse-rail">
            <div className="vcore">
              <span className="vc-ring" aria-hidden="true" />
              <span className="vc-ring r2" aria-hidden="true" />
              <span className="vc-disc">
                <b className="num">{beatCount}</b>
                <span className="micro">{bi('beats', 'զարկ')}</span>
              </span>
            </div>
            <div className="vc-cap">
              <b>{clock}</b>
              <span className="micro">{bi('last event', 'վերջին իրադարձություն')}</span>
            </div>
          </aside>
        </section>

        {/* ── BOARD · beat timeline + honest vitals panel ──────────────────── */}
        <div className="pboard">
          <section className="surface soft ptimeline rise" style={cv(2)}>
            <div className="sec-head">
              <h2>{bi('Beat timeline', 'Զարկերի ժամանակագիծ')}</h2>
              <span className="note">{bi('recent system events · click to locate on the strip', 'վերջին համակարգային իրադարձությունները · սեղմիր՝ շերտի վրա գտնելու')}</span>
            </div>
            <div className="beatline">
              {timeline.map(({ e, i }) => {
                const isNow = metrics.latest != null && parseTime(e.createdAt) === metrics.latest;
                const target = e.entityId ?? e.entityType ?? '';
                return (
                  <button
                    type="button"
                    key={e.id}
                    className={`node${i === sel ? ' sel' : ''}${isNow ? ' now' : ''}`}
                    aria-pressed={i === sel}
                    aria-label={blipLabel(e, i)}
                    title={blipLabel(e, i)}
                    onClick={() => { setSel(i); setOpened(i); }}
                  >
                    <div className="nd-top">
                      <span className={`pill ${isNow ? 'live' : 'info'}`}>{e.eventType}</span>
                      <span className="mono nd-time">{fmtTime(e.createdAt)}</span>
                    </div>
                    <p className="nd-lbl">{target || e.eventType}</p>
                  </button>
                );
              })}
            </div>
            {hiddenCount > 0 && (
              <p className="note pa-tail">{bi(`+${hiddenCount} earlier beats not plotted`, `+${hiddenCount} ավելի վաղ զարկ չեն գծագրված`)}</p>
            )}
          </section>

          <section className="surface soft pmetrics rise" style={cv(3)}>
            <div className="sec-head">
              <h2>{bi('Vitals', 'Կենսանշաններ')}</h2>
              <span className="pill info">{bi('record only', 'միայն գրանցում')}</span>
            </div>
            <p className="note" role="note">
              {bi('Live runtime telemetry (response, network load, error rate) is not wired to this build, so those vitals are omitted rather than shown as numbers. The beats and counts above are the real event record.',
                'Կենդանի հեռաչափումը (արձագանք, ցանցի բեռ, սխալի հաճախ.) միացված չէ այս կառուցվածքին, ուստի այդ կենսանշանները բաց են թողնված, ոչ թե ցուցադրված որպես թվեր։ Վերևի զարկերը և հաշվարկները իրական գրառումն են։')}
            </p>
            <div className="wire" aria-hidden="true" />

            {openEvent && (
              <div className="surface soft pa-detail" role="region" aria-label={bi('Beat detail', 'Զարկի մանրամասն')}>
                <div className="pa-detail-head">
                  <div className="row" style={{ gap: 8 }}>
                    <span className="pill info">{openEvent.eventType}</span>
                    <span className="pa-detail-title">{blipLabel(openEvent, opened ?? 0)}</span>
                  </div>
                  <button type="button" className="iconbtn" onClick={() => setOpened(null)} title={bi('Close (Esc)', 'Փակել (Esc)')} aria-label={bi('Close beat detail', 'Փակել')}>✕</button>
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
          </section>
        </div>
      </>
    );
  }

  return (
    <>
      <style>{PA_STYLE}</style>
      <div className="v-activity">
        <header className="pageHead reveal" style={cv(0)}>
          <div>
            <span className="eyebrow">{bi('SYSTEM PULSE · VITALS MONITOR', 'ՀԱՄԱԿԱՐԳԻ ԶԱՐԿԵՐԱԿ · VITALS MONITOR')}</span>
            <h1>{bi('System pulse', 'Համակարգի զարկ')} ♥ Զարկերակ</h1>
            <p className="sub">{t('activity.subtitle')}</p>
          </div>
          <div className="right">
            <Mark state={markState} size={22} />
            <span className={`pill ${pillTone}`}>{pillText}</span>
          </div>
        </header>

        {/* Text-equivalent live region for the strip (§D a11y). */}
        <span className="pa-sr" role="status" aria-live="polite" aria-atomic="true">{liveText}</span>

        {main}
      </div>
    </>
  );
}

function StateFrame({ children }: { children: ReactNode }) {
  return (
    <section className="surface soft lg hud reveal pa-state" style={cv(1)}>
      <HudChrome />
      {children}
    </section>
  );
}

function Vread({ i, label, value, unit }: { i: number; label: string; value: ReactNode; unit?: string }) {
  return (
    <div className="vread reveal" style={cv(i)}>
      <span className="micro">{label}</span>
      <b className="num">{value}{unit ? <i>{unit}</i> : null}</b>
    </div>
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

// Only page-local chrome not covered by aios.css lives here: the SR live region,
// the state-screen frame, the loading skeleton, the blocked panel, and the beat
// detail grid. Everything visual on the live view is aios classes.
const PA_STYLE = `
.pa-sr { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }

.v-activity .pa-state { grid-column: 1 / -1; display: grid; place-items: center; min-height: 240px; padding: 40px 24px; text-align: center; }
.v-activity .pa-skel { width: 100%; max-width: 720px; }

.v-activity .pa-blocked { text-align: center; padding: 12px; }
.v-activity .pa-blocked-glyph { font-size: 30px; }
.v-activity .pa-blocked-title { font-weight: 700; margin: 12px 0 6px; }
.v-activity .pa-blocked-reason { margin-top: 8px; font-family: var(--f-mono, monospace); opacity: .8; }

.v-activity .pa-tail { margin-top: 12px; }

.v-activity .pa-detail { padding: 14px; margin-top: 4px; }
.v-activity .pa-detail-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.v-activity .pa-detail-title { font-weight: 600; }
.v-activity .pa-detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.v-activity .pa-field { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.v-activity .pa-field-label { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; opacity: .65; }
.v-activity .pa-field-value { min-width: 0; overflow-wrap: anywhere; }
.v-activity .pa-mono { font-family: var(--f-mono, monospace); font-size: .9em; }
.v-activity .row { display: inline-flex; align-items: center; }
@media (max-width: 640px) { .v-activity .pa-detail-grid { grid-template-columns: 1fr; } }
`;
