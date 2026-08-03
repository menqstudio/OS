import { useCallback, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import { useApp } from '../app/store';
import { Button, Avatar, EmptyState, Skeleton, ErrorState, usePrefersReducedMotion } from '../components/ui';
import { Mark } from '../components/Ambient';
import { useAsync } from '../hooks/useAsync';
import { desktop, hasBackend } from '../services/desktop';
import { StripChart, type StripPoint } from '../components/charts/Chart';
import type { ActivityEvent } from '../domain/entities';
import {
  STR,
  blipLabelStr,
  rateSummaryStr,
  liveTextStr,
  telemetryLostStr,
  peakInlineStr,
  hiddenTailStr,
} from './Activity.strings';

// ─────────────────────────────────────────────────────────────────────────────
// activity ♥ Զարկերակ — the "System Pulse Monitor".
//
// Every beat is a REAL system event from `desktop.listActivity()`. The ECG strip
// stays the interactive `StripChart` primitive — one keyboard-scrubbable blip per
// real event, deterministic geometry, reduced-motion aware. The surrounding HUD
// (hero brackets, pulse-rail core, beat timeline, vitals panel) is re-dressed to
// the aios "vitals monitor" mockup, but every number shown is DERIVED from the
// real events array (total beats, event types, plotted count, rate/min, last-beat
// time). The richer instruments are honest too, computed straight from the events:
// the rate histogram bins events by createdAt (count per time bin); per-beat
// intensity is that beat's bin density (busy burst → tall, isolated → short);
// the distribution meters are real per-eventType and per-actor tallies; peak /
// busiest-hour come from the same bins. The mockup's live runtime telemetry that
// has NO backing signal — avg response, network load, error rate, rhythm % — is
// still omitted rather than fabricated; the honest "telemetry not connected" note stays.
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

export function Activity() {
  const { t, lang } = useApp();
  const reduced = usePrefersReducedMotion();
  const state = useAsync<ActivityEvent[]>(() => desktop.listActivity());

  const L = (k: keyof typeof STR) => STR[k][lang] ?? STR[k].en;

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
    return blipLabelStr(lang, i + 1, e.eventType, target);
  }, [lang]);

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

  // Richer instruments — all derived from the same real events array. Nothing here
  // is generated: histogram = counts per time bin; intensity = a beat's bin density;
  // distributions = real tallies; peak / busiest-hour read straight off the bins.
  const analytics = useMemo(() => {
    const ts = events
      .map((e) => parseTime(e.createdAt))
      .filter((n): n is number => n != null)
      .sort((a, b) => a - b);
    const n = ts.length;
    const min = n ? ts[0] : 0;
    const max = n ? ts[n - 1] : 0;
    const span = max - min;

    // Rate histogram: bucket every event into 12–24 equal time bins (never more
    // bins than events), bar height = real count in that bin.
    const binCount = Math.max(1, Math.min(24, n));
    const bins = new Array<number>(binCount).fill(0);
    const binOf = (t: number): number => {
      if (span <= 0) return 0;
      const idx = Math.floor(((t - min) / span) * binCount);
      return idx >= binCount ? binCount - 1 : idx < 0 ? 0 : idx;
    };
    for (const t of ts) bins[binOf(t)] += 1;
    const maxBin = Math.max(1, ...bins);
    const peakIdx = bins.indexOf(Math.max(...bins));
    const binMs = span > 0 ? span / binCount : 0;
    const peakStart = min + peakIdx * binMs;
    const peakCount = bins[peakIdx] ?? 0;

    // Per-beat intensity 0..100 = density of the bin the beat falls in (real signal).
    const intensityOf = (t: number | null): number =>
      t == null ? 0 : Math.round((100 * bins[binOf(t)]) / maxBin);

    // Real distribution tallies (sorted desc), per eventType and per actor.
    const tally = (key: (e: ActivityEvent) => string) => {
      const m = new Map<string, number>();
      for (const e of events) m.set(key(e), (m.get(key(e)) ?? 0) + 1);
      const rows = [...m.entries()].sort((a, b) => b[1] - a[1]);
      return { rows, max: rows.length ? rows[0][1] : 1 };
    };
    const SYS = ' system';
    const byType = tally((e) => e.eventType);
    const byActor = tally((e) => e.actorId ?? SYS);

    // Busiest local clock hour (real count of events in that hour-of-day).
    const hours = new Map<number, number>();
    for (const t of ts) {
      const h = new Date(t).getHours();
      hours.set(h, (hours.get(h) ?? 0) + 1);
    }
    let busiestHour: number | null = null;
    let busiestHourCount = 0;
    for (const [h, c] of hours) if (c > busiestHourCount) { busiestHour = h; busiestHourCount = c; }

    return { bins, maxBin, binCount, span, peakStart, peakCount, intensityOf, byType, byActor, SYS, busiestHour, busiestHourCount };
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
  const peakTime = analytics.span > 0 ? fmtTime(String(analytics.peakStart)) : clock;
  const busiestHourLabel = analytics.busiestHour != null
    ? `${String(analytics.busiestHour).padStart(2, '0')}:00`
    : '—';
  // Accessible one-line summary for the (decorative) rate histogram.
  const rateSummary = rateSummaryStr(lang, metrics.count, analytics.binCount, analytics.peakCount, peakTime);

  const selEvent = displayed[sel];
  const openEvent = opened !== null ? displayed[opened] : null;

  // Text-equivalent live region (§D a11y). Only real facts: beat count, derived
  // rate when a real time-span exists, and the focused beat.
  const liveText = state.loading
    ? L('loadingBeatline')
    : liveTextStr(
      lang,
      metrics.count,
      metrics.rate,
      selEvent ? { pos: sel + 1, total: displayed.length, eventType: selEvent.eventType } : null,
    );

  // Header status pill + power mark, driven by the real load state.
  const markState = state.loading ? 'boot' : state.error ? 'alert' : 'live';
  const pillTone = state.loading ? 'info' : state.error ? 'warn' : 'live';
  const pillText = state.loading
    ? L('connecting')
    : state.error ? L('offline') : L('rhythmStable');

  // ── Resolve the §D state → the main region ──────────────────────────────────
  let main: ReactNode;
  if (state.loading && state.data === null) {
    main = (
      <StateFrame>
        <div className="pa-skel" aria-busy="true" aria-label={L('loadingBeatlineShort')}>
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
          <div className="pa-blocked-title">{L('telemetryBlocked')}</div>
          <p className="note" style={{ maxWidth: 460, marginInline: 'auto' }}>
            {L('telemetryBlockedBody')}
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
          message={telemetryLostStr(lang, state.error)}
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
          title={L('noActivity')}
          hint={L('noActivityHint')}
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
              <span className="eyebrow">{L('leadSystem')}</span>
              <span className="mon-clock mono">{clock}</span>
              <button
                type="button"
                className={`chip mon-freeze${frozen ? ' on' : ''}`}
                aria-pressed={frozen}
                onClick={() => setFrozen((f) => !f)}
                title={L('freeze')}
              >
                <span className="fz-ico" aria-hidden="true" />
                {frozen ? L('frozen') : L('freeze')}
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
              ariaLabel={L('beatlineAria')}
              onSelect={setSel}
              onOpen={setOpened}
              onToggleFreeze={() => setFrozen((f) => !f)}
              onCloseOpened={() => setOpened(null)}
            />

            {/* vitals readout — real derived numbers only */}
            <div className="vitals">
              <Vread i={4} label={L('systemPulse')} value={metrics.rate ?? '—'} unit={L('perMin')} />
              <Vread i={5} label={L('eventTypes')} value={metrics.types} unit={L('typesUnit')} />
              <Vread i={6} label={L('plotted')} value={displayed.length} unit={`/${metrics.count}`} />
              <Vread i={7} label={L('lastBeat')} value={clock} />
              <Vread i={8} label={L('peakBeats')} value={analytics.peakCount} unit={peakTime} />
              <Vread i={9} label={L('busiestHour')} value={busiestHourLabel} unit={analytics.busiestHourCount ? String(analytics.busiestHourCount) : undefined} />
            </div>

            {/* rate histogram — real event counts per time bin (decorative bars + text summary) */}
            <div className="pa-rate">
              <div className="mon-top">
                <span className="eyebrow">{L('eventsFlow')}</span>
                <span className="mon-clock mono">{peakInlineStr(lang, analytics.peakCount, peakTime)}</span>
              </div>
              <div className="bars" role="img" aria-label={rateSummary}>
                {analytics.bins.map((c, i) => (
                  <i
                    key={i}
                    style={{ height: `${c === 0 ? 0 : Math.round((100 * c) / analytics.maxBin)}%`, animationDelay: `${i * 0.03}s` } as CSSProperties}
                  />
                ))}
              </div>
              <p className="note rate-cap">{rateSummary}</p>
            </div>
          </div>

          {/* right: the beating pulse core (real total beats) */}
          <aside className="pulse-rail">
            <div className="vcore">
              <span className="vc-ring" aria-hidden="true" />
              <span className="vc-ring r2" aria-hidden="true" />
              <span className="vc-disc">
                <b className="num">{beatCount}</b>
                <span className="micro">{L('beats')}</span>
              </span>
            </div>
            <div className="vc-cap">
              <b>{clock}</b>
              <span className="micro">{L('lastEvent')}</span>
            </div>
          </aside>
        </section>

        {/* ── BOARD · beat timeline + honest vitals panel ──────────────────── */}
        <div className="pboard">
          <section className="surface soft ptimeline rise" style={cv(2)}>
            <div className="sec-head">
              <h2>{L('beatTimeline')}</h2>
              <span className="note">{L('beatTimelineHint')}</span>
            </div>
            <div className="beatline">
              {timeline.map(({ e, i }) => {
                const isNow = metrics.latest != null && parseTime(e.createdAt) === metrics.latest;
                const target = e.entityId ?? e.entityType ?? '';
                const intensity = analytics.intensityOf(parseTime(e.createdAt));
                return (
                  <button
                    type="button"
                    key={e.id}
                    className={`node${i === sel ? ' sel' : ''}${isNow ? ' now' : ''}`}
                    aria-pressed={i === sel}
                    aria-label={`${blipLabel(e, i)} · ${L('intensity')} ${intensity}`}
                    title={blipLabel(e, i)}
                    onClick={() => { setSel(i); setOpened(i); }}
                  >
                    <div className="nd-top">
                      <span className={`pill ${isNow ? 'live' : 'info'}`}>{e.eventType}</span>
                      <span className="mono nd-time">{fmtTime(e.createdAt)}</span>
                    </div>
                    <p className="nd-lbl">{target || e.eventType}</p>
                    <div className="nd-amp">
                      <span className="micro">{L('intensity')}</span>
                      <span className="meter" aria-hidden="true" style={{ ['--p']: `${intensity}%` } as CSSProperties}><span /></span>
                      <span className="mono nd-av">{intensity}</span>
                    </div>
                  </button>
                );
              })}
            </div>
            {hiddenCount > 0 && (
              <p className="note pa-tail">{hiddenTailStr(lang, hiddenCount)}</p>
            )}
          </section>

          <section className="surface soft pmetrics rise" style={cv(3)}>
            <div className="sec-head">
              <h2>{L('vitals')}</h2>
              <span className="pill info">{L('recordOnly')}</span>
            </div>

            {/* real distribution meters — honest tallies straight off the events */}
            <div className="pa-grp">
              <span className="eyebrow">{L('byEventType')}</span>
              <div className="signs" role="list">
                {analytics.byType.rows.slice(0, 6).map(([type, count]) => (
                  <div className="sign" role="listitem" key={type}>
                    <span className="micro">{type}</span>
                    <span className="meter" aria-hidden="true" style={{ ['--p']: `${Math.round((100 * count) / analytics.byType.max)}%` } as CSSProperties}><span /></span>
                    <b className="mono">{count}</b>
                  </div>
                ))}
              </div>
            </div>

            <div className="pa-grp">
              <span className="eyebrow">{L('topActors')}</span>
              <div className="signs" role="list">
                {analytics.byActor.rows.slice(0, 6).map(([actor, count]) => (
                  <div className="sign" role="listitem" key={actor}>
                    <span className="micro">{actor === analytics.SYS ? L('system') : actor}</span>
                    <span className="meter" aria-hidden="true" style={{ ['--p']: `${Math.round((100 * count) / analytics.byActor.max)}%` } as CSSProperties}><span /></span>
                    <b className="mono">{count}</b>
                  </div>
                ))}
              </div>
            </div>

            <p className="note pa-grp" role="note">
              {L('telemetryOmitted')}
            </p>
            <div className="wire" aria-hidden="true" />

            {openEvent && (
              <div className="surface soft pa-detail" role="region" aria-label={L('beatDetail')}>
                <div className="pa-detail-head">
                  <div className="row" style={{ gap: 8 }}>
                    <span className="pill info">{openEvent.eventType}</span>
                    <span className="pa-detail-title">{blipLabel(openEvent, opened ?? 0)}</span>
                  </div>
                  <button type="button" className="iconbtn" onClick={() => setOpened(null)} title={L('closeEsc')} aria-label={L('closeBeatDetail')}>✕</button>
                </div>
                <div className="pa-detail-grid">
                  <PaField label={L('actor')}>
                    <span className="row" style={{ gap: 6 }}><Avatar name={openEvent.actorId ?? 'system'} />{openEvent.actorId ?? L('system')}</span>
                  </PaField>
                  <PaField label={L('entity')}>{openEvent.entityType ?? '—'}</PaField>
                  <PaField label={L('entityId')}><code className="pa-mono">{openEvent.entityId ?? '—'}</code></PaField>
                  <PaField label={L('when')}>{fmtWhen(openEvent.createdAt)}</PaField>
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
            <span className="eyebrow">{L('pageEyebrow')}</span>
            <h1>{L('systemPulse')} ♥ Զարկերակ</h1>
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

/* six vitals readouts now flow instead of forcing four columns */
.v-activity .vitals { grid-template-columns: repeat(auto-fit, minmax(116px, 1fr)); }
/* rate histogram block + the labelled distribution groups (reuse .bars/.signs/.sign) */
.v-activity .pa-rate { margin-top: var(--s2); }
.v-activity .pa-rate .rate-cap { margin-top: 8px; }
.v-activity .pa-grp { margin-top: 16px; }
.v-activity .pa-grp .eyebrow { display: block; margin-bottom: 8px; }
.v-activity .pa-grp .signs { margin-top: 0; }
`;
