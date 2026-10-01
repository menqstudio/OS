// Page-local trilingual copy for the Notifications (Signal Prism) view. Every
// entry carries en / hy / ru so Russian is correct rather than silently falling
// back to English. The shared i18n dictionary (`t()`) still serves every existing
// key; only these page-local labels — with no shared dict key yet — live here.
// No interpolation: counts are rendered as separate nodes, never spliced into a
// translated sentence (the lone count-prefixed line puts the number ahead of the
// phrase, which reads naturally in all three languages).
export const STR = {
  filterAll: { en: 'All', hy: 'Բոլորը', ru: 'Все' },
  filterUnread: { en: 'Unread', hy: 'Չկարդացված', ru: 'Непрочитанные' },
  clearTitle: { en: 'All clear', hy: 'Ամեն ինչ մաքուր է', ru: 'Всё чисто' },
  clearHint: { en: 'No signals right now.', hy: 'Այս պահին ազդանշաններ չկան։', ru: 'Сейчас сигналов нет.' },
  open: { en: 'Open', hy: 'Բացել', ru: 'Открыть' },
  collapse: { en: 'Collapse', hy: 'Փակել', ru: 'Свернуть' },
  dismiss: { en: 'Dismiss', hy: 'Անտեսել', ru: 'Отклонить' },
  unread: { en: 'unread', hy: 'չկարդացված', ru: 'непрочитано' },
  keyboardHint: {
    en: '↑/↓ navigate · Enter open · x dismiss',
    hy: '↑/↓ նավարկել · Enter բացել · x անտեսել',
    ru: '↑/↓ навигация · Enter открыть · x отклонить',
  },
  feedLabel: { en: 'Signal feed', hy: 'Ազդանշանների հոսք', ru: 'Лента сигналов' },
  filtersLabel: { en: 'Filter signals', hy: 'Զտել ազդանշանները', ru: 'Фильтровать сигналы' },
  liveCount: { en: 'signals shown', hy: 'ազդանշան ցուցադրված է', ru: 'сигналов показано' },
  eyebrowPrism: {
    en: 'SIGNAL PRISM · TRIAGE',
    hy: 'ԱԶԴԱՆՇԱՆՆԵՐԻ ՊՐԻԶՄԱ · SIGNAL PRISM',
    ru: 'ПРИЗМА СИГНАЛОВ · СОРТИРОВКА',
  },
  flowActive: { en: 'FLOW · ACTIVE', hy: 'ՀՈՍՔ · ԱԿՏԻՎ', ru: 'ПОТОК · АКТИВЕН' },
  flowIdle: { en: 'FLOW · IDLE', hy: 'ՀՈՍՔ · ԱՆԳՈՐԾ', ru: 'ПОТОК · ПРОСТОЙ' },
  readOnlyMirror: { en: 'Read-only mirror', hy: 'Միայն ընթերցում', ru: 'Зеркало только для чтения' },
  triageNow: { en: 'CURRENT TRIAGE', hy: 'ԸՆԹԱՑԻԿ ՏՐԻԱԺ', ru: 'ТЕКУЩАЯ СОРТИРОВКА' },
  triageEmpty: {
    en: 'Inbox is clear — nothing awaiting triage.',
    hy: 'Մուտքը մաքուր է — տրիաժի սպասող ազդանշան չկա։',
    ru: 'Входящие пусты — нет сигналов, ожидающих сортировки.',
  },
  statTotal: { en: 'signals', hy: 'ազդանշան', ru: 'сигналов' },
  statUnread: { en: 'unread', hy: 'չկարդացված', ru: 'непрочитано' },
  statShown: { en: 'shown', hy: 'ցուցադրված', ru: 'показано' },
  inboxHeading: { en: 'Ranked intake', hy: 'Դասակարգված մուտք', ru: 'Ранжированный поток' },
  inboxNote: {
    en: 'sorted by priority · pick a band to filter',
    hy: 'առաջնահերթությամբ դասավորված · սեղմիր շերտը՝ զտելու',
    ru: 'отсортировано по приоритету · выберите полосу для фильтрации',
  },
  unitSignal: { en: 'sig', hy: 'ազդ', ru: 'сиг' },
  gateHeading: {
    en: 'Engine governance signals',
    hy: 'Շարժիչի կառավարման ազդանշաններ',
    ru: 'Сигналы управления движком',
  },
  // One title per state of the read. There was ONE for everything that was not "records
  // arrived" — "Governance stream sealed" — shown while the read was in flight, when nothing
  // was reached, and over a read that had answered with no events.
  gateTitleReading: {
    en: 'Reading the governance stream',
    hy: 'Կարդում ենք կառավարման հոսքը',
    ru: 'Читаем поток управления',
  },
  gateTitleBlocked: {
    en: 'Governance stream read refused',
    hy: 'Կառավարման հոսքի ընթերցումը մերժվեց',
    ru: 'Чтение потока управления отклонено',
  },
  gateTitleUnreachable: {
    en: 'Governance stream not reached',
    hy: 'Կառավարման հոսքին հասնել չհաջողվեց',
    ru: 'До потока управления добраться не удалось',
  },
  gateTitleEmpty: {
    en: 'Governance stream answered — no events',
    hy: 'Կառավարման հոսքը պատասխանեց — իրադարձություն չկա',
    ru: 'Поток управления ответил — событий нет',
  },
  gateTitleOk: {
    en: 'Governance stream mirrored',
    hy: 'Կառավարման հոսքն արտացոլված է',
    ru: 'Поток управления отражён',
  },
  gateReading: {
    en: 'Reading the engine governance stream…',
    hy: 'Կարդում ենք շարժիչի կառավարման հոսքը…',
    ru: 'Читаем поток управления движком…',
  },
  gateMirrored: {
    en: 'event(s) mirrored from the engine chain.',
    hy: 'իրադարձություն արտացոլված է շարժիչի շղթայից։',
    ru: 'событий отражено из цепочки движка.',
  },
  gateReasonLabel: { en: 'Reason: ', hy: 'Պատճառ՝ ', ru: 'Причина: ' },
  // An `ok` read that carried zero events: the honest absence of a stream, which must
  // not be worded (or lit) as a mirrored one.
  gateEmpty: {
    en: 'The engine chain answered with no events. There is nothing mirrored here yet — '
      + 'an empty stream is not a verified one.',
    hy: 'Շարժիչի շղթան պատասխանեց առանց իրադարձությունների։ Այստեղ դեռ ոչինչ արտացոլված չէ — '
      + 'դատարկ հոսքը ստուգված չէ։',
    ru: 'Цепочка движка ответила без событий. Здесь пока ничего не отражено — '
      + 'пустой поток не является проверенным.',
  },
  // Shown whenever events ARE displayed: schema-checked only, origin not authenticated.
  gateUnauthenticated: {
    en: 'Unauthenticated mirror: these events are checked for shape only and carry no '
      + 'signature, and the desktop does not authenticate the process that supplied them.',
    hy: 'Չհաստատված արտացոլում. այս իրադարձությունները ստուգվում են միայն ձևով և '
      + 'ստորագրություն չեն կրում, իսկ desktop-ը չի հաստատում դրանք տրամադրող գործընթացը։',
    ru: 'Неподтверждённое зеркало: эти события проверены только по форме и не содержат '
      + 'подписи, а десктоп не аутентифицирует процесс, который их выдал.',
  },
  // --- The ENGINE's own account of an empty stream ---
  // The engine explains an empty surface in its own words. This label ATTRIBUTES that
  // sentence; the sentence is quoted verbatim and never re-voiced as the desktop's
  // finding — the desktop read nothing itself, it only relays the engine's claim.
  gateEngineSays: {
    en: 'The engine’s own account:',
    hy: 'Շարժիչի սեփական բացատրությունը՝',
    ru: 'Собственное объяснение движка:',
  },
  // Provenance, never proof: the engine names the store it read.
  gateEngineSource: {
    en: 'Store the engine says it read: ',
    hy: 'Պահոցը, որը շարժիչն ասում է կարդացել է՝ ',
    ru: 'Хранилище, которое движок сообщает, что прочитал: ',
  },
  // The read exists and this page calls it; these used to be one sentence saying the stream "is
  // not connected to this desktop yet" and would appear "once the read bridge lands".
  gateBodyBlocked: {
    en: 'The engine refused this read of its governance-event chain, so nothing is mirrored '
      + 'here. The desktop mirrors; it never decides.',
    hy: 'Շարժիչը մերժեց իր կառավարման իրադարձությունների շղթայի այս ընթերցումը, ուստի այստեղ '
      + 'ոչինչ արտացոլված չէ։ Աշխատասեղանը արտացոլում է, երբեք չի որոշում։',
    ru: 'Движок отклонил это чтение своей цепочки событий управления, поэтому здесь ничего '
      + 'не отражено. Рабочий стол отражает, но никогда не решает.',
  },
  gateBodyUnreachable: {
    en: 'The read of the engine governance-event chain reached nothing, so nothing is mirrored '
      + 'here. The desktop mirrors; it never decides.',
    hy: 'Շարժիչի կառավարման իրադարձությունների շղթայի ընթերցումը ոչնչի չհասավ, ուստի այստեղ '
      + 'ոչինչ արտացոլված չէ։ Աշխատասեղանը արտացոլում է, երբեք չի որոշում։',
    ru: 'Чтение цепочки событий управления движка ни до чего не добралось, поэтому здесь ничего '
      + 'не отражено. Рабочий стол отражает, но никогда не решает.',
  },
  // A mark-as-read the store rejected.
  markReadRefusedTitle: {
    en: 'Not marked as read',
    hy: 'Չնշվեց որպես կարդացված',
    ru: 'Не отмечено как прочитанное',
  },
  markReadRefusedBody: {
    en: 'The store rejected the change, so the signal is still unread and still listed.',
    hy: 'Պահոցը մերժեց փոփոխությունը, ուստի ազդանշանը դեռ չկարդացված է ու դեռ ցուցակում է։',
    ru: 'Хранилище отклонило изменение, поэтому сигнал всё ещё не прочитан и остаётся в списке.',
  },
  dismissNotice: { en: 'Close', hy: 'Փակել', ru: 'Закрыть' },
  gateChainMirror: { en: 'MIRROR', hy: 'ԱՐՏԱՑՈԼՈՒՄ', ru: 'ЗЕРКАЛО' },
  gateChainEngine: { en: 'ENGINE', hy: 'ՇԱՐԺԻՉ', ru: 'ДВИЖОК' },

  // ── Read-path chain node labels ────────────────────────────────────────────
  // The strip used to hard-code the ENGINE node lit (`done`) whatever came back, so a
  // blocked or unreachable read still painted a satisfied first node. Every node now
  // maps to a fact from the actual GovernanceRead, and says which honest case it is.
  gateChainRead: { en: 'READ', hy: 'ԸՆԹԵՐՑՈՒՄ', ru: 'ЧТЕНИЕ' },
  gateChainEngineSealed: {
    en: 'ENGINE · sealed',
    hy: 'ՇԱՐԺԻՉ · կնքված',
    ru: 'ДВИЖОК · запечатан',
  },
  gateChainEngineUnreachable: {
    en: 'ENGINE · unreachable',
    hy: 'ՇԱՐԺԻՉ · անհասանելի',
    ru: 'ДВИЖОК · недоступен',
  },
  gateChainMirrorNone: {
    en: 'MIRROR · no events',
    hy: 'ԱՐՏԱՑՈԼՈՒՄ · իրադարձություններ չկան',
    ru: 'ЗЕРКАЛО · нет событий',
  },
  gateChainMirrorUnverified: {
    en: 'MIRROR · unverified',
    hy: 'ԱՐՏԱՑՈԼՈՒՄ · չստուգված',
    ru: 'ЗЕРКАЛО · не проверено',
  },
} as const;
