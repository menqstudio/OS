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

export function activitySummary(lang: Lang, total: number, buckets: number, peak: number): string {
  switch (lang) {
    case 'hy':
      return `${total} վերջին իրադարձ. ${buckets} ընդմիջումով։ Պիկ՝ ${peak} մեկ ընդմիջումում։`;
    case 'ru':
      return `${total} недавних событий за ${buckets} интервалов. Пик — ${peak} за интервал.`;
    default:
      return `${total} recent events across ${buckets} intervals. Peak ${peak} in an interval.`;
  }
}
