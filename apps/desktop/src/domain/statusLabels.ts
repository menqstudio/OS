import type { Lang } from './enums';

/**
 * Trilingual display labels for the status / lifecycle enum values that surface in
 * the UI (task/project/run/step/integration/agent/approval/decision states). The
 * shared StatusPill and any chart that shows a status use `statusLabel()` so these
 * data values localize too. Unknown values fall back to a humanized form of the raw
 * string, so nothing ever breaks — it just stays untranslated for that one value.
 */
const STATUS: Record<string, { en: string; hy: string; ru: string }> = {
  inbox: { en: 'Inbox', hy: 'Մուտք', ru: 'Входящие' },
  planned: { en: 'Planned', hy: 'Պլանավորված', ru: 'Запланировано' },
  active: { en: 'Active', hy: 'Ակտիվ', ru: 'Активно' },
  blocked: { en: 'Blocked', hy: 'Արգելափակված', ru: 'Заблокировано' },
  review: { en: 'Review', hy: 'Վերանայում', ru: 'На проверке' },
  done: { en: 'Done', hy: 'Ավարտված', ru: 'Готово' },
  cancelled: { en: 'Cancelled', hy: 'Չեղարկված', ru: 'Отменено' },
  completed: { en: 'Completed', hy: 'Ավարտված', ru: 'Завершено' },
  archived: { en: 'Archived', hy: 'Արխիվացված', ru: 'В архиве' },
  drafted: { en: 'Drafted', hy: 'Սևագիր', ru: 'Черновик' },
  queued: { en: 'Queued', hy: 'Հերթում', ru: 'В очереди' },
  planning: { en: 'Planning', hy: 'Պլանավորում', ru: 'Планирование' },
  awaiting_approval: { en: 'Awaiting approval', hy: 'Սպասում է հաստատման', ru: 'Ожидает согласования' },
  running: { en: 'Running', hy: 'Ընթացքում', ru: 'Выполняется' },
  paused: { en: 'Paused', hy: 'Դադարեցված', ru: 'Приостановлено' },
  succeeded: { en: 'Succeeded', hy: 'Հաջողված', ru: 'Успешно' },
  failed: { en: 'Failed', hy: 'Ձախողված', ru: 'Ошибка' },
  skipped: { en: 'Skipped', hy: 'Բաց թողնված', ru: 'Пропущено' },
  pending: { en: 'Pending', hy: 'Սպասում', ru: 'Ожидание' },
  disconnected: { en: 'Disconnected', hy: 'Անջատված', ru: 'Отключено' },
  connected: { en: 'Connected', hy: 'Միացված', ru: 'Подключено' },
  error: { en: 'Error', hy: 'Սխալ', ru: 'Ошибка' },
  idle: { en: 'Idle', hy: 'Պարապ', ru: 'Простой' },
  working: { en: 'Working', hy: 'Աշխատում է', ru: 'В работе' },
  observing: { en: 'Observing', hy: 'Դիտում է', ru: 'Наблюдает' },
  thinking: { en: 'Thinking', hy: 'Մտածում է', ru: 'Думает' },
  offline: { en: 'Offline', hy: 'Անցանց', ru: 'Не в сети' },
  approved: { en: 'Approved', hy: 'Հաստատված', ru: 'Одобрено' },
  rejected: { en: 'Rejected', hy: 'Մերժված', ru: 'Отклонено' },
  denied: { en: 'Denied', hy: 'Մերժված', ru: 'Отказано' },
  proposed: { en: 'Proposed', hy: 'Առաջարկված', ru: 'Предложено' },
  accepted: { en: 'Accepted', hy: 'Ընդունված', ru: 'Принято' },
};

/** Humanize an unknown status: `awaiting_approval` → `Awaiting approval`. */
function humanize(s: string): string {
  const w = s.replace(/_/g, ' ').trim();
  return w ? w[0].toUpperCase() + w.slice(1) : s;
}

/** Localized label for a status value, falling back to a humanized raw string. */
export function statusLabel(status: string, lang: Lang): string {
  const e = STATUS[status];
  return e ? (e[lang] ?? e.en) : humanize(status);
}
