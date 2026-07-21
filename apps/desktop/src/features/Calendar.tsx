import { useMemo, useState } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, Badge, Skeleton, ErrorState, EmptyState,
  Modal, FormRow, Input, ConfirmDialog,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { statusTone } from '../domain/enums';
import type { CalendarEvent } from '../domain/entities';

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
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

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

function EventBadge({ kind }: { kind: string }) {
  return <Badge tone={statusTone[kind] ?? 'accent'}>{kind}</Badge>;
}

function MonthGrid(
  { viewDate, events, onPrev, onToday, onNext, onPickDay }:
  {
    viewDate: Date;
    events: CalendarEvent[];
    onPrev: () => void;
    onToday: () => void;
    onNext: () => void;
    onPickDay: (d: Date) => void;
  },
) {
  const { t, lang } = useApp();

  // Short weekday labels (Mon-first). 2024-01-01 was a Monday.
  const weekdays = useMemo(() => {
    const fmt = new Intl.DateTimeFormat(lang, { weekday: 'short' });
    return Array.from({ length: 7 }, (_, i) => fmt.format(new Date(2024, 0, 1 + i)));
  }, [lang]);

  const monthLabel = useMemo(
    () => new Intl.DateTimeFormat(lang, { month: 'long', year: 'numeric' }).format(viewDate),
    [lang, viewDate],
  );

  // Bucket the month's datable events by local day.
  const byDay = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();
    for (const e of events) {
      const d = parseEventDate(e.startsAt);
      if (!d) continue;
      const key = dayKey(d);
      const list = map.get(key);
      if (list) list.push(e);
      else map.set(key, [e]);
    }
    return map;
  }, [events]);

  // 6 weeks (42 cells) starting on the Monday on/before the 1st.
  const cells = useMemo(() => {
    const first = new Date(viewDate.getFullYear(), viewDate.getMonth(), 1);
    const offset = (first.getDay() + 6) % 7; // 0 = Monday
    const start = new Date(first.getFullYear(), first.getMonth(), 1 - offset);
    return Array.from({ length: 42 }, (_, i) =>
      new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
  }, [viewDate]);

  const today = new Date();
  const todayKey = dayKey(today);
  const viewMonth = viewDate.getMonth();

  return (
    <div className="stack">
      <div className="cal-toolbar">
        <div className="cal-month">{monthLabel}</div>
        <div className="row" style={{ gap: 8 }}>
          <Button small title={t('calendar.prevMonth')} onClick={onPrev}>‹</Button>
          <Button small onClick={onToday}>{t('calendar.today')}</Button>
          <Button small title={t('calendar.nextMonth')} onClick={onNext}>›</Button>
        </div>
      </div>

      <div className="cal-grid-wrap">
        <div className="cal-weekdays">
          {weekdays.map((w) => <div key={w} className="cal-weekday">{w}</div>)}
        </div>
        <div className="cal-grid">
          {cells.map((day) => {
            const key = dayKey(day);
            const dayEvents = byDay.get(key) ?? [];
            const shown = dayEvents.slice(0, 3);
            const hidden = dayEvents.length - shown.length;
            const outside = day.getMonth() !== viewMonth;
            const isToday = key === todayKey;
            return (
              <button
                type="button"
                key={key}
                className={`cal-cell${outside ? ' cal-cell--out' : ''}${isToday ? ' cal-cell--today' : ''}`}
                onClick={() => onPickDay(day)}
                title={t('calendar.newEvent')}
              >
                <span className="cal-daynum">{day.getDate()}</span>
                <span className="cal-events">
                  {shown.map((e) => (
                    <span key={e.id} className="cal-event" title={e.title}>
                      <Badge tone={statusTone[e.kind] ?? 'accent'}>{e.title}</Badge>
                    </span>
                  ))}
                  {hidden > 0 && (
                    <span className="cal-more">{`+${hidden} ${t('calendar.more')}`}</span>
                  )}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function Calendar() {
  const { t, lang } = useApp();
  // `creating` holds the datetime-local prefill (empty string = no prefill).
  const [creating, setCreating] = useState<{ when: string } | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [viewDate, setViewDate] = useState(() => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), 1);
  });
  const s = useAsync(() => desktop.listEvents(), []);

  const dateFmt = useMemo(
    () => new Intl.DateTimeFormat(lang, { dateStyle: 'medium', timeStyle: 'short' }),
    [lang],
  );

  const shiftMonth = (delta: number) =>
    setViewDate((d) => new Date(d.getFullYear(), d.getMonth() + delta, 1));
  const goToday = () => {
    const now = new Date();
    setViewDate(new Date(now.getFullYear(), now.getMonth(), 1));
  };

  const remove = (id: string) => {
    setPendingDelete(null);
    desktop.deleteEvent(id).then(() => s.reload()).catch(() => s.reload());
  };

  // Split loaded events into dated (sorted ascending) and undated buckets.
  const { dated, undated } = useMemo(() => {
    const events = s.data ?? [];
    const dated: { e: CalendarEvent; d: Date }[] = [];
    const undated: CalendarEvent[] = [];
    for (const e of events) {
      const d = parseEventDate(e.startsAt);
      if (d) dated.push({ e, d });
      else undated.push(e);
    }
    dated.sort((a, b) => a.d.getTime() - b.d.getTime());
    return { dated, undated };
  }, [s.data]);

  const renderAgendaCard = (e: CalendarEvent, when: string | null) => (
    <div key={e.id} className="agenda-card">
      <div className="row" style={{ gap: 8, minWidth: 0 }}>
        <EventBadge kind={e.kind} />
        <span className="agenda-title">{e.title}</span>
      </div>
      <div className="row" style={{ gap: 12 }}>
        {e.location && <span className="muted">{e.location}</span>}
        <span className="muted">{when ?? t('calendar.undated')}</span>
        <Button variant="ghost" small disabled title={t('action.deleteDisabledSafety')} onClick={() => setPendingDelete(e.id)}>{t('action.delete')}</Button>
      </div>
    </div>
  );

  return (
    <>
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
          confirmLabel={t('action.delete')}
          cancelLabel={t('action.cancel')}
          onConfirm={() => remove(pendingDelete)}
          onCancel={() => setPendingDelete(null)}
        />
      )}

      <Panel title={t('nav.calendar')}>
        {s.loading && s.data === null ? (
          <Skeleton rows={6} />
        ) : s.error ? (
          <ErrorState message={s.error} onRetry={s.reload} />
        ) : (
          <MonthGrid
            viewDate={viewDate}
            events={s.data ?? []}
            onPrev={() => shiftMonth(-1)}
            onToday={goToday}
            onNext={() => shiftMonth(1)}
            onPickDay={(d) => setCreating({ when: toLocalInputValue(new Date(d.getFullYear(), d.getMonth(), d.getDate(), 9, 0)) })}
          />
        )}
      </Panel>

      <Panel title={t('calendar.agenda')}>
        {s.loading && s.data === null ? (
          <Skeleton rows={3} />
        ) : dated.length === 0 && undated.length === 0 ? (
          <EmptyState title={t('state.empty')} hint={t('state.emptyHint')} />
        ) : (
          <div className="stack">
            {dated.map(({ e, d }) => renderAgendaCard(e, dateFmt.format(d)))}
            {undated.length > 0 && (
              <>
                <div className="cal-agenda-heading">{t('calendar.undated')}</div>
                {undated.map((e) => renderAgendaCard(e, null))}
              </>
            )}
          </div>
        )}
      </Panel>
    </>
  );
}
