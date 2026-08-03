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

const PRIORITY: Record<string, { en: string; hy: string; ru: string }> = {
  low: { en: 'Low', hy: 'Ցածր', ru: 'Низкий' },
  normal: { en: 'Normal', hy: 'Սովորական', ru: 'Обычный' },
  medium: { en: 'Medium', hy: 'Միջին', ru: 'Средний' },
  high: { en: 'High', hy: 'Բարձր', ru: 'Высокий' },
  critical: { en: 'Critical', hy: 'Կրիտիկական', ru: 'Критический' },
};

/** Localized label for a priority OR risk-level value (low/normal/medium/high/critical). */
export function priorityLabel(priority: string, lang: Lang): string {
  const e = PRIORITY[priority];
  return e ? (e[lang] ?? e.en) : humanize(priority);
}

/** Alias: risk levels use the same low/medium/high/critical scale. */
export const riskLabel = priorityLabel;

const KIND: Record<string, { en: string; hy: string; ru: string }> = {
  // memory kinds
  fact: { en: 'Fact', hy: 'Փաստ', ru: 'Факт' },
  preference: { en: 'Preference', hy: 'Նախապատվություն', ru: 'Предпочтение' },
  note: { en: 'Note', hy: 'Նշում', ru: 'Заметка' },
  reference: { en: 'Reference', hy: 'Հղում', ru: 'Ссылка' },
  // scope
  global: { en: 'Global', hy: 'Գլոբալ', ru: 'Глобальный' },
  // calendar / event kinds
  event: { en: 'Event', hy: 'Իրադարձություն', ru: 'Событие' },
  meeting: { en: 'Meeting', hy: 'Հանդիպում', ru: 'Встреча' },
  review: { en: 'Review', hy: 'Վերանայում', ru: 'Обзор' },
  ops: { en: 'Ops', hy: 'Օպերացիա', ru: 'Операции' },
  maintenance: { en: 'Maintenance', hy: 'Սպասարկում', ru: 'Обслуживание' },
  // library item kinds
  component: { en: 'Component', hy: 'Բաղադրիչ', ru: 'Компонент' },
  prompt: { en: 'Prompt', hy: 'Հուշում', ru: 'Промпт' },
  pattern: { en: 'Pattern', hy: 'Օրինաչափություն', ru: 'Шаблон' },
};

/** Localized label for a kind/scope value (memory kind, event kind, item kind, scope). */
export function kindLabel(kind: string, lang: Lang): string {
  const e = KIND[kind];
  return e ? (e[lang] ?? e.en) : humanize(kind);
}

const SEVERITY: Record<string, { en: string; hy: string; ru: string }> = {
  info: { en: 'Info', hy: 'Տեղեկություն', ru: 'Инфо' },
  success: { en: 'Success', hy: 'Հաջողություն', ru: 'Успех' },
  warning: { en: 'Warning', hy: 'Զգուշացում', ru: 'Предупреждение' },
  error: { en: 'Error', hy: 'Սխալ', ru: 'Ошибка' },
  critical: { en: 'Critical', hy: 'Կրիտիկական', ru: 'Критический' },
};

/** Localized label for a notification severity (info/success/warning/error/critical). */
export function severityLabel(sev: string, lang: Lang): string {
  const e = SEVERITY[sev];
  return e ? (e[lang] ?? e.en) : humanize(sev);
}

/** Localized analytics metric label from its key (Projects/Tasks/…). */
const METRIC: Record<string, { en: string; hy: string; ru: string }> = {
  projects: { en: 'Projects', hy: 'Նախագծեր', ru: 'Проекты' },
  tasks: { en: 'Tasks', hy: 'Առաջադրանքներ', ru: 'Задачи' },
  agents: { en: 'Agents', hy: 'Գործակալներ', ru: 'Агенты' },
  runs: { en: 'Runs', hy: 'Գործարկումներ', ru: 'Запуски' },
  decisions: { en: 'Decisions', hy: 'Որոշումներ', ru: 'Решения' },
  approvals: { en: 'Approvals', hy: 'Հաստատումներ', ru: 'Согласования' },
  events: { en: 'Events', hy: 'Իրադարձություններ', ru: 'События' },
  automations: { en: 'Automations', hy: 'Ավտոմատներ', ru: 'Автоматизации' },
  conversations: { en: 'Conversations', hy: 'Զրույցներ', ru: 'Беседы' },
  messages: { en: 'Messages', hy: 'Հաղորդագրություններ', ru: 'Сообщения' },
  notifications: { en: 'Notifications', hy: 'Ծանուցումներ', ru: 'Уведомления' },
  knowledge: { en: 'Knowledge', hy: 'Գիտելիք', ru: 'Знания' },
};

/** Localized metric label from its key, falling back to a provided label or humanized key. */
export function metricLabel(key: string, lang: Lang, fallback?: string): string {
  const e = METRIC[key];
  return e ? (e[lang] ?? e.en) : (fallback ?? humanize(key));
}
