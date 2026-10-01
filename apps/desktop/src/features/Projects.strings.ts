// Trilingual (en/hy/ru) UI strings for the Projects (Հոսքերի դաշտ / workstream
// field) screen. The shared i18n dictionary is not edited; these are the strings
// local to this reskin. Each key carries natural translations in all three
// languages — the bilingual "ARM · ENGLISH" eyebrow is localized per language,
// never left as mixed text. Central `t('…')` keys and technical ids/brand names
// (e.g. `Bro`) stay outside this table.
export const STR = {
  // Status LABELS are not here: the pills, the field legend and the select read
  // `statusLabel()` from `domain/statusLabels.ts`, the one table for every status in the app.
  statusNotChanged: {
    en: 'Status not changed',
    hy: 'Կարգավիճակը չի փոխվել',
    ru: 'Статус не изменён',
  },

  eyebrow: {
    en: 'Strategic Work · Workstreams',
    hy: 'ՌԱԶՄԱՎԱՐԱԿԱՆ ԱՇԽԱՏԱՆՔ · ՀՈՍՔԵՐ',
    ru: 'СТРАТЕГИЧЕСКАЯ РАБОТА · РАБОЧИЕ ПОТОКИ',
  },
  activeWord: { en: 'active', hy: 'ակտիվ', ru: 'активных' },
  totalWord: { en: 'total', hy: 'ընդամենը', ru: 'всего' },
  blockedWord: { en: 'blocked', hy: 'արգելափակված', ru: 'заблокировано' },
  completedWord: { en: 'completed', hy: 'ավարտված', ru: 'завершено' },
  heroHint: {
    en: 'Active workstreams · select to expand',
    hy: 'Ակտիվ հոսքեր · ընտրի՛ր՝ մանրամասնելու',
    ru: 'Активные потоки · выберите для детализации',
  },
  boardHead: { en: 'Portfolio read', hy: 'Պորտֆելի ընթերցում', ru: 'Обзор портфеля' },
  boardNote: {
    en: 'Aggregate signals · live counts',
    hy: 'Ամփոփ ազդանշաններ · իրական հաշվարկ',
    ru: 'Сводные сигналы · живой подсчёт',
  },
  readEyebrow: { en: "Bro's read", hy: 'Bro-Ի ԸՆԹԵՐՑՈՒՄ', ru: 'ЧТЕНИЕ Bro' },
  readPending: {
    en: "Bro's portfolio read is issued by the governed engine. That subscription is not wired in this build — no narrative or confidence score is fabricated here.",
    hy: 'Bro-ի պորտֆելի ընթերցումը տրամադրվում է կառավարվող շարժիչի կողմից։ Այդ բաժանորդագրությունը միացված չէ այս կառուցվածքում — վերլուծություն կամ վստահության գնահատական չեն ցուցադրվում։',
    ru: 'Обзор портфеля от Bro выдаётся управляемым движком. Эта подписка не подключена в данной сборке — здесь не выдумываются ни описание, ни оценка достоверности.',
  },
  building: {
    en: 'Building the workstream field…',
    hy: 'Հոսքերի դաշտը կառուցվում է…',
    ru: 'Построение поля потоков…',
  },
  linkLost: {
    en: 'Link to the data layer was lost — the workstreams are unavailable.',
    hy: 'Կապը տվյալների շերտի հետ կորավ — հոսքերն անհասանելի են։',
    ru: 'Связь со слоем данных потеряна — потоки недоступны.',
  },
  emptyTitle: { en: 'No workstreams yet', hy: 'Ակտիվ հոսքեր չկան', ru: 'Пока нет потоков' },
  emptyHint: {
    en: 'When a project is created it appears here as its own energy line.',
    hy: 'Երբ ստեղծվի նախագիծ, այն կհայտնվի այստեղ՝ որպես առանձին էներգիայի գիծ։',
    ru: 'Когда проект создан, он появится здесь как отдельная энергетическая линия.',
  },
  tasksDone: { en: 'done', hy: 'ավարտ', ru: 'выполнено' },
  tasksBuilding: {
    en: 'Loading linked tasks…',
    hy: 'Կապված առաջադրանքները բեռնվում են…',
    ru: 'Загрузка связанных задач…',
  },
  tasksLinkLost: {
    en: 'Linked tasks are unavailable.',
    hy: 'Առաջադրանքներն անհասանելի են։',
    ru: 'Связанные задачи недоступны.',
  },
  retry: { en: 'Retry', hy: 'Կրկնել', ru: 'Повторить' },
} as const;

export type StrKey = keyof typeof STR;
