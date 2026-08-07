import { useMemo, useState, type CSSProperties } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Button, Badge, Skeleton, ErrorState, EmptyState,
  Modal, FormRow, Input, ConfirmDialog,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { statusTone, type Tone } from '../domain/enums';
import { kindLabel } from '../domain/statusLabels';
import type { CalendarEvent } from '../domain/entities';
import { STR } from './Calendar.strings';

// `startsAt` is free text: seed events store a millisecond-epoch string, while
// the old form let the user type anything. Parse defensively and treat an
// unparseable value as "undated".
function parseEventDate(startsAt: string): Date | null {
  const raw = startsAt.trim();
  if (!raw) return null;
  const d = new Date(isNaN(Number(raw)) ? raw : Number(raw));
  return isNaN(d.getTime()) ? null : d;
}

// Local `YYYY-MM-DD` key used to bucket events into day cells.
function dayKey(d: Date): string {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

// Value string an <input type="datetime-local"> expects (local time, no zone).
function toLocalInputValue(d: Date): string {
  const pad2 = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}T${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

// Fractional hour-of-day (0–24) used to place an event on the day timeline.
function hourOf(d: Date): number {
  return d.getHours() + d.getMinutes() / 60;
}

const pad = (n: number) => String(Math.floor(n)).padStart(2, '0');

// Allow CSS custom properties in inline styles without fighting the DOM types.
const v = (o: Record<string, string | number>): CSSProperties => o as CSSProperties;

// Map a kind's semantic tone to a concrete accent so day-dots / agenda markers
// carry real meaning instead of an invented status.
const TONE_VAR: Record<Tone, string> = {
  success: 'var(--success)',
  warning: 'var(--warning)',
  danger: 'var(--danger)',
  info: 'var(--cyan)',
  accent: 'var(--cyan)',
  neutral: 'var(--ink-muted)',
};
const toneOf = (kind: string): Tone => statusTone[kind] ?? 'accent';
const toneVar = (kind: string): string => TONE_VAR[toneOf(kind)];

// Per-view CSS that isn't already in the global aios.css theme. The daygrid /
// month / agenda classes themselves are all global; these only wire the ARIA
// grid rows and the day-plot scroller.
const viewStyles = `
.v-calendar .cal-cal{display:grid;gap:8px}
.v-calendar .cal-week{display:grid;grid-template-columns:repeat(7,1fr);gap:8px}
.v-calendar .day.is-out{opacity:.4}
.v-calendar .day.is-out .day-n{color:var(--ink-muted)}
.v-calendar .dg-plot{display:grid;gap:10px;min-width:620px}
.v-calendar .dg-empty{padding:var(--s5) 0}
.v-calendar .cm-nav{display:flex;align-items:center;gap:6px}
.v-calendar .ag-side .btn{white-space:nowrap}
.v-calendar .cal-delete-error{display:flex;flex-direction:column;align-items:flex-start;gap:6px;margin-bottom:14px;
  padding:10px 12px;border:1px solid rgb(var(--danger-rgb)/.4);border-radius:var(--r);
  background:rgb(var(--danger-rgb)/.08);font-size:13px}
.v-calendar .cal-delete-error b{color:var(--danger)}
.v-calendar .cal-delete-reason{color:var(--ink-muted);font-size:12px;word-break:break-word}
`;

function NewEventForm(
  { initialWhen, onClose, onCreated }:
  { initialWhen: string; onClose: () => void; onCreated: () => void },
) {
  const { t } = useApp();
  const [title, setTitle] = useState('');
  const [kind, setKind] = useState('event');
  const [location, setLocation] = useState('');
  const [when, setWhen] = useState(initialWhen);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = () => {
    if (!title.trim() || busy) return;
    setBusy(true);
    setError(null);
    // datetime-local yields a local wall-clock string; store a canonical ISO
    // instant. Empty stays '' (an undated event).
    const startsAt = when ? new Date(when).toISOString() : '';
    desktop
      .createEvent({
        title: title.trim(),
        kind: kind.trim() || 'event',
        location: location.trim(),
        startsAt,
        endsAt: null,
      })
      .then(() => {
        onCreated();
        onClose();
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
        setBusy(false);
      });
  };

  return (
    <Modal title={t('calendar.newEvent')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <FormRow label={t('field.title')}>
        <Input value={title} autoFocus onChange={(e) => setTitle(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.kind')}>
        <Input value={kind} onChange={(e) => setKind(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.location')}>
        <Input value={location} onChange={(e) => setLocation(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.when')}>
        <Input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
      </FormRow>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="primary" disabled={busy} onClick={submit}>{t('action.create')}</Button>
      </div>
    </Modal>
  );
}

export function Calendar() {
  const { t, lang } = useApp();
  const L = (k: keyof typeof STR) => STR[k][lang] ?? STR[k].en;
  // BCP47 locale for month/day/weekday names so they localize in all three langs.
  const locale = lang === 'hy' ? 'hy-AM' : lang === 'ru' ? 'ru-RU' : 'en-US';
  // `creating` holds the datetime-local prefill (empty string = no prefill).
  const [creating, setCreating] = useState<{ when: string } | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  // The backend's own reason for REFUSING a delete — surfaced, never swallowed.
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [viewDate, setViewDate] = useState(() => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), 1);
  });
  // The day whose timeline + agenda are shown (defaults to today).
  const [selectedDay, setSelectedDay] = useState(() => new Date());
  const s = useAsync(() => desktop.listEvents(), []);

  const timeFmt = useMemo(
    () => new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }),
    [locale],
  );
  const monthLabel = useMemo(
    () => new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric' }).format(viewDate),
    [locale, viewDate],
  );
  const fullDateFmt = useMemo(
    () => new Intl.DateTimeFormat(locale, { weekday: 'long', day: 'numeric', month: 'long' }),
    [locale],
  );
  // Short weekday labels (Mon-first). 2024-01-01 was a Monday.
  const weekdays = useMemo(() => {
    const fmt = new Intl.DateTimeFormat(locale, { weekday: 'short' });
    return Array.from({ length: 7 }, (_, i) => fmt.format(new Date(2024, 0, 1 + i)));
  }, [locale]);

  const shiftMonth = (delta: number) =>
    setViewDate((d) => new Date(d.getFullYear(), d.getMonth() + delta, 1));
  const goToday = () => {
    const now = new Date();
    setViewDate(new Date(now.getFullYear(), now.getMonth(), 1));
    setSelectedDay(now);
  };
  const pickDay = (d: Date) => {
    setSelectedDay(d);
    if (d.getMonth() !== viewDate.getMonth() || d.getFullYear() !== viewDate.getFullYear()) {
      setViewDate(new Date(d.getFullYear(), d.getMonth(), 1));
    }
  };

  // Not optimistic: the event leaves the calendar only when `delete_event` resolves.
  // A rejection keeps it and states the backend's reason.
  const remove = (id: string) => {
    if (deleteBusy) return;
    setDeleteBusy(true);
    setDeleteError(null);
    desktop.deleteEvent(id)
      .then(() => { setPendingDelete(null); s.reload(); })
      .catch((e: unknown) => {
        setPendingDelete(null);
        setDeleteError(e instanceof Error ? e.message : String(e));
        s.reload();
      })
      .finally(() => setDeleteBusy(false));
  };

  // Split loaded events into dated (sorted ascending) and undated buckets.
  const { dated, undated, byDay } = useMemo(() => {
    const events = s.data ?? [];
    const dated: { e: CalendarEvent; d: Date }[] = [];
    const undated: CalendarEvent[] = [];
    const byDay = new Map<string, CalendarEvent[]>();
    for (const e of events) {
      const d = parseEventDate(e.startsAt);
      if (d) {
        dated.push({ e, d });
        const key = dayKey(d);
        const list = byDay.get(key);
        if (list) list.push(e);
        else byDay.set(key, [e]);
      } else {
        undated.push(e);
      }
    }
    dated.sort((a, b) => a.d.getTime() - b.d.getTime());
    return { dated, undated, byDay };
  }, [s.data]);

  const totalCount = (s.data ?? []).length;
  const emptyAll = totalCount === 0;

  // 6 weeks (42 cells) starting on the Monday on/before the 1st.
  const weeks = useMemo(() => {
    const first = new Date(viewDate.getFullYear(), viewDate.getMonth(), 1);
    const offset = (first.getDay() + 6) % 7; // 0 = Monday
    const start = new Date(first.getFullYear(), first.getMonth(), 1 - offset);
    const cells = Array.from({ length: 42 }, (_, i) =>
      new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
    return Array.from({ length: 6 }, (_, r) => cells.slice(r * 7, r * 7 + 7));
  }, [viewDate]);

  const now = new Date();
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const todayKey = dayKey(now);
  const selectedKey = dayKey(selectedDay);
  const viewMonth = viewDate.getMonth();
  const viewYear = viewDate.getFullYear();
  const monthCount = dated.filter(
    ({ d }) => d.getMonth() === viewMonth && d.getFullYear() === viewYear,
  ).length;

  // Real events on the selected day (already time-sorted via `dated`).
  const dayEvents = dated.filter(({ d }) => dayKey(d) === selectedKey);
  const selectedLabel = fullDateFmt.format(selectedDay);
  const isToday = selectedKey === todayKey;

  // Timeline window derived from the day's real events (no invented span).
  const dayWindow = useMemo(() => {
    if (dayEvents.length === 0) return { startH: 6, endH: 20 };
    const starts = dayEvents.map(({ d }) => hourOf(d));
    const ends = dayEvents.map(({ e, d }) => {
      const end = e.endsAt ? parseEventDate(e.endsAt) : null;
      return end ? hourOf(end) : hourOf(d);
    });
    let startH = Math.floor(Math.min(...starts));
    let endH = Math.ceil(Math.max(...ends, startH + 1));
    startH -= startH % 2;
    if (endH % 2) endH += 1;
    if (endH - startH < 4) endH = startH + 4;
    return { startH: Math.max(0, startH), endH: Math.min(24, endH) };
  }, [dayEvents]);

  const span = dayWindow.endH - dayWindow.startH;
  const pct = (h: number) => Math.max(0, Math.min(100, ((h - dayWindow.startH) / span) * 100));
  const ticks: number[] = [];
  for (let h = dayWindow.startH; h <= dayWindow.endH; h += 2) ticks.push(h);

  const eventTime = (d: Date, endsAt: string | null): string => {
    const end = endsAt ? parseEventDate(endsAt) : null;
    return timeFmt.format(d) + (end ? `–${timeFmt.format(end)}` : '');
  };

  const agendaNode = (e: CalendarEvent, d: Date | null) => {
    const end = d && e.endsAt ? parseEventDate(e.endsAt) : null;
    return (
      <div key={e.id} className="ag-node node" style={v({ '--st': toneVar(e.kind) })}>
        <span className="ag-time mono">
          {d ? timeFmt.format(d) : '—'}
          {end && <i>–{timeFmt.format(end)}</i>}
        </span>
        <div className="ag-main">
          <b className="ag-t" title={e.title}>{e.title}</b>
          <span className="ag-crew micro">
            {e.location ? `${kindLabel(e.kind, lang)} · ${e.location}` : kindLabel(e.kind, lang)}
          </span>
        </div>
        <div className="ag-side">
          <Badge tone={toneOf(e.kind)}>{kindLabel(e.kind, lang)}</Badge>
          <Button
            variant="ghost"
            small
            disabled
            title={t('action.deleteDisabledSafety')}
            onClick={() => setPendingDelete(e.id)}
          >
            {t('action.delete')}
          </Button>
        </div>
      </div>
    );
  };

  return (
    <div className="v-calendar">
      <style>{viewStyles}</style>

      <PageHeader
        title={t('nav.calendar')}
        subtitle={t('calendar.subtitle')}
        actions={<Button variant="primary" onClick={() => setCreating({ when: '' })}>{t('action.new')}</Button>}
      />

      {creating && (
        <NewEventForm
          initialWhen={creating.when}
          onClose={() => setCreating(null)}
          onCreated={() => s.reload()}
        />
      )}

      {pendingDelete && (
        <ConfirmDialog
          title={t('confirm.deleteTitle')}
          message={t('confirm.deleteBody')}
          confirmLabel={deleteBusy ? L('deleting') : t('action.delete')}
          cancelLabel={t('action.cancel')}
          onConfirm={() => remove(pendingDelete)}
          onCancel={() => { if (!deleteBusy) setPendingDelete(null); }}
        />
      )}

      {/* A REFUSED delete, stated plainly and left on screen until dismissed. */}
      {deleteError && (
        <div className="cal-delete-error" role="alert">
          <b>{L('deleteRefusedTitle')}</b>
          <span>{L('deleteRefusedBody')}</span>
          <span className="mono cal-delete-reason">{deleteError}</span>
          <Button small variant="ghost" onClick={() => setDeleteError(null)}>{t('action.close')}</Button>
        </div>
      )}

      {s.loading && s.data === null ? (
        <section className="surface soft" style={{ padding: 'var(--s6)' }}>
          <Skeleton rows={8} />
        </section>
      ) : s.error ? (
        <section className="surface soft" style={{ padding: 'var(--s6)' }}>
          <ErrorState message={s.error} onRetry={s.reload} />
        </section>
      ) : (
        <>
          {/* ── HERO · the selected day's real events on an hour grid ───────── */}
          <section className="daygrid surface soft lg hud reveal" style={v({ '--i': 1 })} aria-label={`${t('calendar.agenda')} · ${selectedLabel}`}>
            <span className="bracket tl" aria-hidden="true" />
            <span className="bracket tr" aria-hidden="true" />
            <span className="bracket bl" aria-hidden="true" />
            <span className="bracket br" aria-hidden="true" />

            <div className="dg-top">
              <span className="eyebrow">{L('opsFlow')} · {selectedLabel}</span>
              <span className="pill info dg-attn">{dayEvents.length}&nbsp;{L('operations')}</span>
            </div>

            {dayEvents.length === 0 ? (
              <div className="dg-empty muted">{L('dayEmpty')}</div>
            ) : (
              <div className="rib-scroll">
                <div className="dg-plot">
                  <div className="rib-ruler" aria-hidden="true">
                    {ticks.map((h) => (
                      <span key={h} className="rk" style={v({ '--l': `${pct(h)}%` })}>
                        <i />
                        <b className="mono">{pad(h)}</b>
                      </span>
                    ))}
                  </div>
                  <div className="lane-track" role="list" aria-label={selectedLabel}>
                    {dayEvents.map(({ e, d }) => {
                      const end = e.endsAt ? parseEventDate(e.endsAt) : null;
                      const l = pct(hourOf(d));
                      const w = end ? Math.max(0, pct(hourOf(end)) - l) : 0;
                      const time = eventTime(d, e.endsAt);
                      return (
                        <span
                          key={e.id}
                          role="listitem"
                          className="ev st-queued"
                          style={v({ '--l': `${l}%`, '--w': `${w}%`, '--st': toneVar(e.kind) })}
                          aria-label={`${e.title} · ${time}`}
                        >
                          <b className="ev-t">{e.title}</b>
                          <span className="ev-time mono">{time}</span>
                        </span>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            <div className="dg-foot">
              <div className="dg-stats">
                <div className="dg-stat">
                  <b className="mono">{dayEvents.length}</b>
                  <span className="micro">{L('dayOps')}</span>
                </div>
                <div className="dg-stat">
                  <b className="mono">{totalCount}</b>
                  <span className="micro">{L('total')}</span>
                </div>
                <div className="dg-stat">
                  <b className="mono">{undated.length}</b>
                  <span className="micro">{L('undated')}</span>
                </div>
              </div>
            </div>
          </section>

          {/* ── month ops-grid + agenda rail ───────────────────────────────── */}
          <div className="cal-lower reveal" style={v({ '--i': 2 })}>
            <section className="cal-month surface soft" aria-label={monthLabel}>
              <div className="cal-month-head">
                <div className="cmh-l">
                  <span className="cm-nav">
                    <Button small title={t('calendar.prevMonth')} onClick={() => shiftMonth(-1)}>‹</Button>
                    <Button small onClick={goToday}>{t('calendar.today')}</Button>
                    <Button small title={t('calendar.nextMonth')} onClick={() => shiftMonth(1)}>›</Button>
                  </span>
                  <b className="cm-title">{monthLabel}</b>
                </div>
                <span className="micro cmh-r">{monthCount}&nbsp;{L('operations')}</span>
              </div>

              <div className="cal-cal" role="grid" aria-label={monthLabel}>
                <div className="cal-wds" role="row">
                  {weekdays.map((w) => (
                    <span key={w} role="columnheader" className="cal-wd micro">{w}</span>
                  ))}
                </div>
                {weeks.map((week, wi) => (
                  <div key={wi} role="row" className="cal-week">
                    {week.map((day) => {
                      const key = dayKey(day);
                      const evs = byDay.get(key) ?? [];
                      const shown = evs.slice(0, 4);
                      const hidden = evs.length - shown.length;
                      const outside = day.getMonth() !== viewMonth;
                      const cellToday = key === todayKey;
                      const cellSel = key === selectedKey;
                      const past = !outside && !cellToday && day.getTime() < startToday.getTime();
                      const cls = `day${cellToday ? ' is-today' : ''}${cellSel ? ' is-sel' : ''}`
                        + `${outside ? ' is-out' : ''}${past ? ' is-past' : ''}`;
                      return (
                        <button
                          type="button"
                          key={key}
                          role="gridcell"
                          aria-selected={cellSel}
                          aria-current={cellToday ? 'date' : undefined}
                          aria-label={`${fullDateFmt.format(day)} · ${evs.length} ${L('operations')}`}
                          className={cls}
                          onClick={() => pickDay(day)}
                        >
                          <b className="mono day-n">{day.getDate()}</b>
                          {evs.length > 0 && (
                            <span className="day-dots" aria-hidden="true">
                              {shown.map((e) => (
                                <i key={e.id} style={v({ '--st': toneVar(e.kind) })} />
                              ))}
                              {hidden > 0 && <i className="more">+{hidden}</i>}
                            </span>
                          )}
                          {evs.length > 0 && (
                            <span className="day-ct micro" aria-hidden="true">{evs.length}</span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                ))}
              </div>
            </section>

            <aside className="agenda surface soft" aria-label={`${t('calendar.agenda')} · ${selectedLabel}`}>
              <div className="ag-head">
                <span className="eyebrow">{L('agenda')} · {isToday ? L('today') : L('plan')}</span>
                <b className="ag-date">{selectedLabel}</b>
                <span className="micro ag-ct">{dayEvents.length}&nbsp;{L('operations')}</span>
              </div>

              {emptyAll ? (
                <EmptyState title={t('state.empty')} hint={t('state.emptyHint')} />
              ) : (
                <>
                  {dayEvents.length > 0 ? (
                    <div className="timeline ag-rail">
                      {dayEvents.map(({ e, d }) => agendaNode(e, d))}
                    </div>
                  ) : (
                    <div className="ag-empty muted">{L('dayEmpty')}</div>
                  )}

                  {undated.length > 0 && (
                    <>
                      <div className="cal-agenda-heading">{t('calendar.undated')}</div>
                      <div className="timeline ag-rail">
                        {undated.map((e) => agendaNode(e, null))}
                      </div>
                    </>
                  )}
                </>
              )}
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
