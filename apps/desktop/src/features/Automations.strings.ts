// Page-local, trilingual string table for `Automations.tsx`. These are the copy
// fragments that are NOT in the central dictionary (t('…')): the manifold/
// schematic chrome, honest-state vocabulary, empty/error/skeleton branches and
// keyboard hints. Central `t('…')` keys stay in the shared dictionary — do not
// duplicate them here. Every entry carries en/hy/ru; the page selects with
// `L(key) = STR[key][lang] ?? STR[key].en`.
export const STR = {
  // ── create-form field hints (the honest small vocabulary) ────────────────────
  triggerHint: {
    en: 'every: 5m · every: 1h · every: 1d · manual',
    hy: 'every: 5m · every: 1h · every: 1d · manual',
    ru: 'every: 5m · every: 1h · every: 1d · manual',
  },
  actionHint: {
    en: 'notify: <text> · task: <title>',
    hy: 'notify: <տեքստ> · task: <վերնագիր>',
    ru: 'notify: <текст> · task: <заголовок>',
  },
  noRuns: {
    en: 'No runs yet — use “Run now”, or wait for an interval trigger to fire.',
    hy: 'Դեռ գործարկումներ չկան — սեղմիր «Գործարկել հիմա» կամ սպասիր interval trigger-ի։',
    ru: 'Запусков ещё нет — нажмите «Запустить сейчас» или дождитесь интервального триггера.',
  },
  // ── run-now action ───────────────────────────────────────────────────────────
  runNow: {
    en: 'Run now',
    hy: 'Գործարկել հիմա',
    ru: 'Запустить сейчас',
  },
  runNowTitle: {
    en: "Run this automation's action now. Local actions (notify, create task) run directly; anything that reaches the model/engine routes through the governed, fail-closed chain.",
    hy: 'Գործարկել այս ավտոմատի գործողությունը հիմա։ Տեղական գործողությունները (notify, task) աշխատում են ուղղակի; մոդելին/շարժիչին հասնողը անցնում է կառավարվող, fail-closed շղթայով։',
    ru: 'Запустить действие этой автоматизации сейчас. Локальные действия (notify, task) выполняются напрямую; всё, что доходит до модели/движка, идёт через управляемую, отказоустойчивую цепочку.',
  },
  // ── governance guarantee (authoring modal + selected conduit) ────────────────
  govern: {
    en: 'Local actions (notify, create task) run directly and reversibly. Any action that reaches the model or engine routes through the governed chain — a lease and a verified receipt — and is refused if it cannot be verified (fail-closed today).',
    hy: 'Տեղական գործողությունները (notify, task ստեղծել) աշխատում են ուղղակի և հետշրջելի։ Մոդելին կամ շարժիչին հասնող ցանկացած գործողություն անցնում է կառավարվող շղթայով՝ լիզինգ և հաստատված ստացական, և մերժվում է, եթե չի հաստատվում (այսօր fail-closed)։',
    ru: 'Локальные действия (notify, создать задачу) выполняются напрямую и обратимо. Любое действие, доходящее до модели или движка, идёт через управляемую цепочку — аренда и проверенная квитанция — и отклоняется, если не может быть проверено (сегодня fail-closed).',
  },
  telemetry: {
    en: 'Run counts, success rate and the recent-fire log appear once the runs backend is connected — none are shown until then.',
    hy: 'Վազքի քանակը, հաջողության տոկոսը և վերջին բռնկումների գրանցամատյանը կհայտնվեն, երբ միանա գործարկումների backend-ը — մինչ այդ ոչ մեկը չի ցուցադրվում։',
    ru: 'Счётчики запусков, процент успеха и журнал недавних срабатываний появятся после подключения бэкенда запусков — до этого ничего не показывается.',
  },

  // ── honest runtime-state vocabulary ──────────────────────────────────────────
  armedState: { en: 'Armed', hy: 'Զինված', ru: 'Заряжен' },
  offState: { en: 'Off', hy: 'Անջատված', ru: 'Выключен' },
  sealedState: { en: 'Sealed', hy: 'Փակված', ru: 'Запечатан' },
  allFilter: { en: 'All', hy: 'Բոլորը', ru: 'Все' },

  // ── page header ──────────────────────────────────────────────────────────────
  workflowManifold: {
    en: 'Workflow Energy Manifold',
    hy: 'ԱՇԽԱՏԱՆՔԱՅԻՆ ԷՆԵՐԳԱ-ՄԱՆԻՖՈԼԴ',
    ru: 'Энергетический коллектор рабочих процессов',
  },
  schedSweep: { en: 'Scheduler · sweep', hy: 'Պլանավորիչ · սկան', ru: 'Планировщик · обход' },
  newN: { en: 'New  ( n )', hy: 'Նոր  ( n )', ru: 'Новый  ( n )' },

  // ── blocked (wall/guard denial) ──────────────────────────────────────────────
  blockedByWall: { en: 'Blocked by the wall', hy: 'Արգելափակված է պատով', ru: 'Заблокировано стеной' },
  guardFix: {
    en: 'A guard tripped or the wall denied this action. Resolve the guard condition or request approval, then retry.',
    hy: 'Պահապանը գործարկվեց կամ պատը մերժեց այս գործողությունը։ Լուծեք պահապանի պայմանը կամ պահանջեք հաստատում, ապա կրկնեք։',
    ru: 'Сработал страж или стена отклонила это действие. Устраните условие стража или запросите одобрение, затем повторите.',
  },
  storeDenied: {
    en: 'This automation store is denied in the current mode or scope. Switch to work mode, or request the required scope/approval, then retry.',
    hy: 'Այս ավտոմատների պահեստը մերժված է ընթացիկ ռեժիմում կամ շրջանակում։ Անցեք work ռեժիմ կամ պահանջեք անհրաժեշտ շրջանակ/հաստատում, ապա կրկնեք։',
    ru: 'Это хранилище автоматизаций запрещено в текущем режиме или области. Переключитесь в режим work или запросите нужную область/одобрение, затем повторите.',
  },

  // ── conduit lane ─────────────────────────────────────────────────────────────
  anyEvent: { en: 'any event', hy: 'ցանկացած իրադարձություն', ru: 'любое событие' },
  runsPerHr: { en: 'runs/hr', hy: 'վազք/ժ', ru: 'запусков/ч' },

  // ── schematic ────────────────────────────────────────────────────────────────
  schematic: { en: 'Schematic', hy: 'Սխեմա', ru: 'Схема' },
  selectConduit: { en: 'Select a conduit', hy: 'Ընտրեք խողովակ', ru: 'Выберите канал' },
  chooseConduit: {
    en: 'Choose a conduit to forge its schematic.',
    hy: 'Ընտրեք խողովակ՝ դրա սխեման ձուլելու համար։',
    ru: 'Выберите канал, чтобы выковать его схему.',
  },
  trigger: { en: 'Trigger', hy: 'Բռնկիչ', ru: 'Триггер' },
  governed: { en: 'Governed', hy: 'Կառավարվող', ru: 'Управляемо' },
  guard: { en: 'guard', hy: 'պահապան', ru: 'страж' },
  action: { en: 'action', hy: 'գործողություն', ru: 'действие' },
  outlet: { en: 'Outlet', hy: 'Ելք', ru: 'Выход' },
  dispatch: { en: 'dispatch', hy: 'առաքում', ru: 'отправка' },
  triggerLabel: { en: 'Trigger:', hy: 'Բռնկիչ՝', ru: 'Триггер:' },
  actionLabel: { en: 'Action:', hy: 'Գործողություն՝', ru: 'Действие:' },
  stateFact: { en: 'State', hy: 'ՎԻՃԱԿ', ru: 'Состояние' },
  createdFact: { en: 'Created', hy: 'ՍՏԵՂԾՎԱԾ', ru: 'Создано' },
  updatedFact: { en: 'Updated', hy: 'ԹԱՐՄԱՑՎԱԾ', ru: 'Обновлено' },
  ownerFact: { en: 'Owner', hy: 'ՏԵՐ', ru: 'Владелец' },
  governedTelemetry: { en: 'Governed telemetry', hy: 'ԿԱՌԱՎԱՐՎՈՂ ՀԵՌԱՉԱՓ', ru: 'Управляемая телеметрия' },
  recentFires: { en: 'Recent fires', hy: 'Վերջին բռնկումներ', ru: 'Недавние срабатывания' },

  // ── index row ────────────────────────────────────────────────────────────────
  runs: { en: 'runs', hy: 'վազք', ru: 'запуски' },
  success: { en: 'success', hy: 'հաջող.', ru: 'успех' },

  // ── body branches: loading · error · empty ───────────────────────────────────
  manifold: { en: 'Manifold', hy: 'Մանիֆոլդ', ru: 'Коллектор' },
  manifoldEyebrow: { en: 'Manifold', hy: 'ՄԱՆԻՖՈԼԴ', ru: 'КОЛЛЕКТОР' },
  chargingManifold: { en: 'Charging the manifold…', hy: 'Մանիֆոլդը լիցքավորվում է…', ru: 'Зарядка коллектора…' },
  retry: { en: 'Retry', hy: 'Կրկնել', ru: 'Повторить' },
  noConduits: { en: 'No conduits yet', hy: 'Դեռ խողովակներ չկան', ru: 'Пока нет каналов' },
  forgeFirst: {
    en: 'Forge your first conduit — every run stays governed and verified.',
    hy: 'Ձուլեք ձեր առաջին խողովակը — ամեն գործարկում մնում է կառավարվող և հաստատված։',
    ru: 'Выкуйте свой первый канал — каждый запуск остаётся управляемым и проверенным.',
  },
  forgeConduit: { en: 'Forge conduit', hy: 'Ձուլել խողովակ', ru: 'Выковать канал' },

  // ── hero manifold ────────────────────────────────────────────────────────────
  energyManifold: { en: 'Energy Manifold', hy: 'ԷՆԵՐԳԱ-ՄԱՆԻՖՈԼԴ', ru: 'Энергетический коллектор' },
  triggerGatesOutlet: { en: 'Trigger ▸ gates ▸ outlet', hy: 'Բռնկիչ ▸ դարպասներ ▸ ելք', ru: 'Триггер ▸ ворота ▸ выход' },
  conduits: { en: 'conduits', hy: 'խողովակ', ru: 'каналов' },
  armedConduits: { en: 'armed conduits', hy: 'զինված խողովակ', ru: 'заряжённых каналов' },
  automationManifold: { en: 'Automation manifold', hy: 'Ավտոմատների մանիֆոլդ', ru: 'Коллектор автоматизаций' },
  noConduitInState: { en: 'No conduit in this state.', hy: 'Այս վիճակում խողովակ չկա։', ru: 'Нет каналов в этом состоянии.' },
  valveGate: {
    en: 'valve = trigger · gate = governed step',
    hy: 'փական = բռնկիչ · դարպաս = կառավարվող քայլ',
    ru: 'клапан = триггер · ворота = управляемый шаг',
  },

  // ── index section + census ───────────────────────────────────────────────────
  automationIndex: { en: 'Automation index', hy: 'Ավտոմատների ինդեքս', ru: 'Указатель автоматизаций' },
  filterByState: { en: 'Filter by state', hy: 'Զտել վիճակով', ru: 'Фильтр по состоянию' },
  conduitsManifold: { en: 'conduits · manifold', hy: 'ավտոմատ · մանիֆոլդ', ru: 'каналов · коллектор' },
  armed: { en: 'armed', hy: 'զինված', ru: 'заряжено' },
  off: { en: 'off', hy: 'անջատված', ru: 'выключено' },
  sealed: { en: 'sealed', hy: 'փակված', ru: 'запечатано' },

  // ── keyboard hint strip ──────────────────────────────────────────────────────
  kbdNew: { en: 'New', hy: 'Նոր', ru: 'Новый' },
  navigate: { en: 'Navigate', hy: 'Նավարկել', ru: 'Навигация' },
  open: { en: 'Open', hy: 'Բացել', ru: 'Открыть' },
} as const;
