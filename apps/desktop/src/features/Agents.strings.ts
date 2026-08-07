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

  // ── Grant block (Phase 6) ─────────────────────────────────────────────────
  // What Bro would be granting if he dispatched to THIS agent. Everything here is
  // either a real fact about the agent, or an explicit statement that the desktop
  // cannot know it. Nothing is inferred to fill a gap.
  grantTitle: { en: 'Grant', hy: 'ՇՆՈՐՀՈՒՄ', ru: 'Предоставление' },
  contractAgentId: { en: 'Contract agent_id', hy: 'ՊԱՅՄԱՆԱԳՐԻ agent_id', ru: 'agent_id контракта' },
  idValid: { en: 'valid id', hy: 'վավեր id', ru: 'корректный id' },
  idInvalid: { en: 'not a valid contract id', hy: 'վավեր պայմանագրային id չէ', ru: 'некорректный id контракта' },
  idInvalidNote: {
    en: 'This agent\'s slug cannot be written into a task contract as-is: the schema requires ^[a-z0-9][a-z0-9._-]{1,127}$. It could not be dispatched under this identity.',
    hy: 'Այս գործակալի slug-ը չի կարող այս տեսքով գրվել task contract-ում. սխեման պահանջում է ^[a-z0-9][a-z0-9._-]{1,127}$։ Այս ինքնությամբ չի կարող ուղարկվել։',
    ru: 'Слаг этого агента нельзя записать в task contract как есть: схема требует ^[a-z0-9][a-z0-9._-]{1,127}$. Под этой личностью его отправить нельзя.',
  },
  authorityTitle: { en: 'Authority the desktop can apply', hy: 'ՀԵՂԻՆԱԿՈՒԹՅՈՒՆ, ՈՐ ԿԱՐՈՂ Է ԿԻՐԱՌԵԼ', ru: 'Полномочия, применимые рабочим столом' },
  modesWord: { en: 'Modes', hy: 'Ռեժիմներ', ru: 'Режимы' },
  ceilingWord: { en: 'Risk ceiling', hy: 'Ռիսկի առաստաղ', ru: 'Потолок риска' },
  authorityNote: {
    en: 'This is the DEFAULT record only. The engine also holds designated-verifier and exact per-role overrides, and the desktop has no IPC that can read which one applies to this agent — so it refuses beyond the default rather than assuming an override exists.',
    hy: 'Սա միայն ԼՌԵԼՅԱՅՆ գրառումն է։ Շարժիչը պահում է նաև designated-verifier ու ճշգրիտ դերային բացառություններ, իսկ աշխատասեղանը IPC չունի իմանալու, թե որն է կիրառելի այս գործակալի համար — ուստի մերժում է լռելյայնից այն կողմ, փոխանակ ենթադրի։',
    ru: 'Это только запись ПО УМОЛЧАНИЮ. У движка есть ещё designated-verifier и точные переопределения по ролям, а у рабочего стола нет IPC, чтобы узнать, какая применима к этому агенту — поэтому он отказывает сверх умолчания, а не предполагает переопределение.',
  },
  tiersTitle: { en: 'Capability tiers Bro may grant', hy: 'ԿԱՐՈՂՈՒԹՅԱՆ ՄԱԿԱՐԴԱԿՆԵՐ', ru: 'Уровни возможностей' },
  tiersNote: {
    en: 'A tier is the ONLY thing that bounds a specialist: it is the definition that gets spawned, and its tool list is what the CLI receives. The generated pack-role definitions are READ — for the specialism and the authority record it falls under — and then the matching tier is spawned; they enforce nothing themselves. Paths stay a property of the JOB, in the task contract\'s scope. Which tier this agent last ran at is engine state, not desktop state, so it is not shown here: it is not known here.',
    hy: 'Մակարդակն է ՄԻԱԿ բանը, որ սահմանափակում է մասնագետին. հենց այդ սահմանումն է գործարկվում, ու իր գործիքների ցանկն է ստանում CLI-ն։ Գեներացված փաթեթ-դերի սահմանումները ԿԱՐԴԱՑՎՈՒՄ ԵՆ՝ մասնագիտացման ու համապատասխան հեղինակության գրառման համար — ու հետո գործարկվում է համապատասխան մակարդակը; իրենք ոչինչ չեն կիրառում։ Ուղիները մնում են ԱՇԽԱՏԱՆՔԻ հատկություն՝ պայմանագրի scope-ում։ Այս գործակալի վերջին մակարդակը շարժիչի վիճակ է, ոչ աշխատասեղանի, ուստի այստեղ ցույց չի տրվում՝ այստեղ հայտնի չէ։',
    ru: 'Уровень — ЕДИНСТВЕННОЕ, что ограничивает специалиста: запускается это определение, и его список инструментов получает CLI. Сгенерированные определения ролей пакетов ЧИТАЮТСЯ — ради специализации и записи полномочий — после чего запускается соответствующий уровень; сами они ничего не применяют. Пути остаются свойством ЗАДАЧИ, в scope контракта. Уровень последнего запуска этого агента — состояние движка, а не рабочего стола, поэтому здесь не показан: здесь он неизвестен.',
  },
  channelTitle: { en: 'Dispatch channel', hy: 'ՈՒՂԱՐԿՄԱՆ ԱԼԻՔ', ru: 'Канал отправки' },
  channelCheck: { en: 'Check the channel', hy: 'Ստուգել ալիքը', ru: 'Проверить канал' },
  channelChecking: { en: 'Checking…', hy: 'Ստուգվում է…', ru: 'Проверка…' },
  channelUnknown: {
    en: 'Not checked. The probe sends a frame that carries no contract, so it can never be mistaken for a dispatch.',
    hy: 'Չստուգված։ Զոնդը ուղարկում է շրջանակ, որ պայմանագիր չի կրում, ուստի երբեք չի կարող շփոթվել ուղարկման հետ։',
    ru: 'Не проверено. Зонд отправляет кадр без контракта, поэтому его нельзя принять за отправку.',
  },
  channelPresent: { en: 'A dispatch command answered', hy: 'Ուղարկման հրամանը պատասխանեց', ru: 'Команда отправки ответила' },
  channelAbsent: { en: 'No dispatch channel', hy: 'Ուղարկման ալիք չկա', ru: 'Канала отправки нет' },
  channelPresentNote: {
    en: 'Something answered on that command. That is all this proves — it says nothing about whether a contract would be accepted.',
    hy: 'Ինչ-որ բան պատասխանեց այդ հրամանին։ Սա միայն դա է ապացուցում — ոչինչ չի ասում այն մասին, թե պայմանագիրը կընդունվի՞։',
    ru: 'На эту команду что-то ответило. Это всё, что доказано — о принятии контракта это ничего не говорит.',
  },
  channelAbsentNote: {
    en: 'Nothing can be dispatched to this agent from the desktop. Required:',
    hy: 'Այս գործակալին աշխատասեղանից ոչինչ չի կարող ուղարկվել։ Պահանջվում է՝',
    ru: 'С рабочего стола этому агенту ничего отправить нельзя. Требуется:',
  },

  // Phase labels — legend, census segments, dossier pills, aria announcements
  phaseIdle: { en: 'idle', hy: 'պարապ', ru: 'простой' },
  phaseFlowing: { en: 'flowing', hy: 'հոսող', ru: 'в потоке' },
  phaseThrottled: { en: 'throttled', hy: 'զսպված', ru: 'придержан' },
  phaseBlocked: { en: 'blocked', hy: 'արգելափակված', ru: 'заблокирован' },
  phaseCompleted: { en: 'completed', hy: 'ավարտ', ru: 'завершён' },
} as const;
