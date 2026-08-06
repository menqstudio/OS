// Page-local trilingual strings for the Agents («Կենդանի Ցանց» / live lattice) view.
// Every VISIBLE string that used to live inline (English fallbacks + the mockup's
// bilingual eyebrows/labels) now lives here with en/hy/ru. This ONLY re-sources
// presentation text — it never touches the lattice / ringPositions / dossier logic,
// keyboard/aria behaviour or class names of Agents.tsx. Technical ids, the "Bro"
// brand, the agent slug/id/role data values are NOT localized and stay in the view.
export const STR = {
  // Panel chrome — eyebrow, census counters, instrument labels
  eyebrow: { en: 'Roster · Live Network', hy: 'ՌՈՍՏԵՐ · ԿԵՆԴԱՆԻ ՑԱՆՑ', ru: 'Состав · Живая сеть' },
  activeWord: { en: 'active', hy: 'ԱԿՏԻՎ', ru: 'активных' },
  agentWord: { en: 'agents', hy: 'ԳՈՐԾԱԿԱԼ', ru: 'агентов' },
  censusLabel: { en: 'State distribution', hy: 'Վիճակների բաշխում', ru: 'Распределение состояний' },
  latticeLabel: { en: 'Agent lattice', hy: 'Գործակալների ցանց', ru: 'Сеть агентов' },
  footHint: {
    en: 'Pick a node to open its dossier',
    hy: 'Ընտրի՛ր հանգույց՝ անձնագիրը բացելու համար',
    ru: 'Выберите узел, чтобы открыть досье',
  },
  keysHint: {
    en: 'Arrows move · Enter opens · Esc closes',
    hy: 'Սլաքներ՝ տեղաշարժ · Enter՝ բացել · Esc՝ փակել',
    ru: 'Стрелки — перемещение · Enter — открыть · Esc — закрыть',
  },

  // State branches — loading · error(link lost) · empty
  building: { en: 'Building lattice…', hy: 'Ցանցը կառուցվում է…', ru: 'Построение сети…' },
  linkLost: {
    en: 'Link to the engine supervisor was lost — the live pack state is unavailable.',
    hy: 'Կապը շարժիչի վերահսկիչի հետ կորավ — կենդանի փաթեթի վիճակն անհասանելի է։',
    ru: 'Связь с супервизором движка потеряна — состояние живого пакета недоступно.',
  },
  emptyTitle: { en: 'No active agents', hy: 'Ակտիվ գործակալներ չկան', ru: 'Нет активных агентов' },
  emptyHint: {
    en: 'When the conductor dispatches a governed pack, its builders appear here.',
    hy: 'Երբ դիրիժորը ուղարկի կառավարվող փաթեթ, նրա կառուցողները կհայտնվեն այստեղ։',
    ru: 'Когда дирижёр отправит управляемый пакет, его исполнители появятся здесь.',
  },

  // Dossier rail — role line, pick prompt, field labels, honest telemetry note
  conductor: { en: 'conductor', hy: 'դիրիժոր', ru: 'дирижёр' },
  pickTitle: { en: 'Select an agent', hy: 'Ընտրեք գործակալ', ru: 'Выберите агента' },
  pickHint: {
    en: 'Choose a node in the lattice — or press Enter — to open its dossier.',
    hy: 'Ընտրեք հանգույց ցանցում — կամ սեղմեք Enter — բացելու համար նրա անձնագիրը։',
    ru: 'Выберите узел в сети — или нажмите Enter — чтобы открыть его досье.',
  },
  details: { en: 'Details', hy: 'ՄԱՆՐԱՄԱՍՆԵՐ', ru: 'Подробности' },
  owner: { en: 'Owner', hy: 'ՏԵՐ', ru: 'Владелец' },
  model: { en: 'Model', hy: 'ՄՈԴԵԼ', ru: 'Модель' },
  slug: { en: 'Slug', hy: 'ԾԱԾԿԱԳԻՐ', ru: 'Слаг' },
  agentId: { en: 'Agent ID', hy: 'ԳՈՐԾԱԿԱԼԻ ID', ru: 'ID агента' },
  state: { en: 'State', hy: 'ՎԻՃԱԿ', ru: 'Состояние' },
  governed: { en: 'Governed telemetry', hy: 'ՀԵՌԱՉԱՓՈՒԹՅՈՒՆ', ru: 'Управляемая телеметрия' },
  telemetryPending: {
    en: 'Live lease & receipt telemetry is issued by the engine supervisor. That subscription is not wired in this build — no lease_id / receipt_id is shown, and the desktop never holds a lease.',
    hy: 'Կենդանի լիզինգի և ստացականի տվյալները տրամադրվում են շարժիչի վերահսկիչի կողմից։ Այդ բաժանորդագրությունը միացված չէ այս կառուցվածքում — lease_id / receipt_id չի ցուցադրվում, և աշխատասեղանը երբեք չի պահում լիզինգ։',
    ru: 'Живая телеметрия аренды и квитанций выдаётся супервизором движка. Эта подписка не подключена в данной сборке — lease_id / receipt_id не показываются, и рабочий стол никогда не удерживает аренду.',
  },
  blockedTitle: { en: 'Agent blocked', hy: 'Գործակալն արգելափակված է', ru: 'Агент заблокирован' },
  blockedBody: {
    en: 'A governed turn for this agent was halted by the wall. Its result is withheld until a verified receipt is produced.',
    hy: 'Այս գործակալի կառավարվող քայլը կանգնեցվեց պատի կողմից։ Արդյունքը պահվում է մինչև ստուգված ստացականի ստեղծումը։',
    ru: 'Управляемый шаг этого агента был остановлен стеной. Его результат удерживается до создания проверенной квитанции.',
  },
  retry: { en: 'Retry', hy: 'Կրկնել', ru: 'Повторить' },

  // Phase labels — legend, census segments, dossier pills, aria announcements
  phaseIdle: { en: 'idle', hy: 'պարապ', ru: 'простой' },
  phaseFlowing: { en: 'flowing', hy: 'հոսող', ru: 'в потоке' },
  phaseThrottled: { en: 'throttled', hy: 'զսպված', ru: 'придержан' },
  phaseBlocked: { en: 'blocked', hy: 'արգելափակված', ru: 'заблокирован' },
  phaseCompleted: { en: 'completed', hy: 'ավարտ', ru: 'завершён' },
} as const;
