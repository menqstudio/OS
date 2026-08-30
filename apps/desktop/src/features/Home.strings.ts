import type { Lang } from '../domain/enums';

// Page-local trilingual copy for the Home instruments that have no shared i18n
// key yet. Every entry carries en / hy / ru so Russian is correct rather than
// silently falling back to English. `t()` still serves every existing dict key;
// only these page-local labels live here. Fixed strings — they carry no data.
export const STR = {
  derivedRatios: { en: 'Derived ratios', hy: 'Ածանցյալ հարաբերակցություններ', ru: 'Производные показатели' },
  agentsBusy: { en: 'agents busy', hy: 'զբաղված գործակալ', ru: 'агентов занято' },
  tasksBlocked: { en: 'tasks blocked', hy: 'արգելափակ առաջադրանք', ru: 'задач заблокировано' },
  approvalsPending: { en: 'approvals pending', hy: 'սպասող հաստատում', ru: 'согласований в ожидании' },

  taskProgress: { en: 'Task progress', hy: 'Առաջադրանքների ընթացք', ru: 'Прогресс задач' },
  progressUnavailable: { en: 'Progress unavailable', hy: 'Ընթացքն անհասանելի է', ru: 'Прогресс недоступен' },
  done: { en: 'done', hy: 'ավարտ', ru: 'готово' },

  agentsByStatus: { en: 'Agents by status', hy: 'Գործակալներն ըստ վիճակի', ru: 'Агенты по статусу' },
  distributionUnavailable: { en: 'Distribution unavailable', hy: 'Բաշխումն անհասանելի է', ru: 'Распределение недоступно' },
  agentsUnit: { en: 'agents', hy: 'գործ.', ru: 'агент.' },
  total: { en: 'Total', hy: 'Ընդամենը', ru: 'Всего' },
  statusHeader: { en: 'Status', hy: 'Վիճակ', ru: 'Статус' },
  countHeader: { en: 'Count', hy: 'Քանակ', ru: 'Количество' },
  shareHeader: { en: 'Share', hy: 'Բաժին', ru: 'Доля' },
  showDataTable: { en: 'Show data table', hy: 'Ցույց տալ աղյուսակը', ru: 'Показать таблицу данных' },

  recentActivity: { en: 'Recent activity', hy: 'Վերջին ակտիվություն', ru: 'Недавняя активность' },
  eventsPerInterval: { en: 'events per interval', hy: 'իրադարձ. ընդմիջումով', ru: 'событий за интервал' },
  activityUnavailable: { en: 'Activity unavailable', hy: 'Ակտիվությունն անհասանելի է', ru: 'Активность недоступна' },
  recentActivityCaption: {
    en: 'Recent activity — events over time',
    hy: 'Վերջին ակտիվություն — իրադարձ. ժամանակի ընթացքում',
    ru: 'Недавняя активность — события во времени',
  },
  eventsUnit: { en: 'events', hy: 'իրադ.', ru: 'соб.' },
  eventsHeader: { en: 'Events', hy: 'Իրադ.', ru: 'События' },
  timeHeader: { en: 'Time', hy: 'Ժամ', ru: 'Время' },
  noActivityYet: { en: 'No activity yet', hy: 'Դեռ ակտիվություն չկա', ru: 'Пока нет активности' },

  // ── Honest-absence vocabulary ─────────────────────────────────────────────
  // Three DIFFERENT states that used to render as the same `0` / `—`. They are
  // worded (and styled) apart on purpose: an owner must be able to tell a quiet
  // workspace from a broken read at a glance, because only one of them is a bug.
  reading: { en: 'reading…', hy: 'կարդում է…', ru: 'чтение…' },
  readingLabel: { en: 'Reading', hy: 'Կարդում է', ru: 'Чтение' },
  noDataYet: { en: 'no data yet', hy: 'դեռ տվյալ չկա', ru: 'пока нет данных' },
  couldNotRead: { en: 'could not read', hy: 'չհաջողվեց կարդալ', ru: 'не удалось прочитать' },
  couldNotReadLabel: {
    en: 'Could not read this value',
    hy: 'Չհաջողվեց կարդալ այս արժեքը',
    ru: 'Не удалось прочитать это значение',
  },
  tasksUnavailable: {
    en: 'Task list could not be read',
    hy: 'Առաջադրանքների ցանկը չհաջողվեց կարդալ',
    ru: 'Не удалось прочитать список задач',
  },
} as const;

// Parameterised accessible-text equivalents. Kept as per-language builders so
// the real counts interpolate correctly into each language's phrasing.
export function taskSummary(lang: Lang, done: number, total: number, active: number, blocked: number): string {
  switch (lang) {
    case 'hy':
      return `${done}/${total} ավարտ · ${active} ակտիվ · ${blocked} արգելափակ`;
    case 'ru':
      return `${done} из ${total} задач готово · ${active} активных · ${blocked} заблокировано`;
    default:
      return `${done} of ${total} tasks done · ${active} active · ${blocked} blocked`;
  }
}

/** T-057: `seeded` is how many of `total` were FABRICATED by `repo::seed`.
 *
 * It is said out loud, not omitted when zero-ish, because this sparkline is the
 * exact surface those 56 rows were written to animate — a heartbeat drawn from
 * invented events, presented beside real ones. A reader who is not told cannot
 * tell. When nothing is seeded the sentence is unchanged, so a real install
 * reads no differently than before. */
export function activitySummary(
  lang: Lang, total: number, buckets: number, peak: number, seeded = 0,
): string {
  const base = (() => {
    switch (lang) {
      case 'hy':
        return `${total} վերջին իրադարձ. ${buckets} ընդմիջումով։ Պիկ՝ ${peak} մեկ ընդմիջումում։`;
      case 'ru':
        return `${total} недавних событий за ${buckets} интервалов. Пик — ${peak} за интервал.`;
      default:
        return `${total} recent events across ${buckets} intervals. Peak ${peak} in an interval.`;
    }
  })();
  if (seeded <= 0) return base;
  switch (lang) {
    case 'hy':
      return `${base} Դրանցից ${seeded}-ը ցուցադրական սերմ ա, ոչ իրական։`;
    case 'ru':
      return `${base} Из них ${seeded} — демонстрационные, не настоящие.`;
    default:
      return `${base} ${seeded} of them are seeded demo data, not real.`;
  }
}
