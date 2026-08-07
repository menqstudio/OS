// Decisions view strings. Extracted verbatim from the previous inline bilingual
// (EN + HY) helper so the visible copy is re-sourced, never re-authored: the EN and
// HY values are byte-for-byte what the fail-closed governance view showed before, and
// a natural RU translation is added so the Russian locale is no longer broken.
//
// Only the visible strings live here. No status/Ok/Blocked/Unreachable logic, no
// evidence-chain honest-state semantics, and no test-asserted role text is changed.
//
// A handful of keys are prefixes/suffixes for runtime-interpolated messages (a
// decision title or a count is spliced between them at the call site); those are
// commented as such and keep the exact surrounding punctuation.
export const STR = {
  // --- Decision-stats strip ---
  ledgerCount: { en: 'decisions · ledger', hy: 'որոշում · մատյան', ru: 'решения · журнал' },
  owners: { en: 'owners', hy: 'հեղինակ', ru: 'авторы' },
  awaiting: { en: 'awaiting', hy: 'սպասում է', ru: 'ожидают' },
  blocked: { en: 'blocked', hy: 'արգելափակված', ru: 'заблокировано' },

  // --- Live-region announcements ---
  // Prefix + suffix around the decision title: `${readingChainFor}${title}${readingChainForEnd}`
  readingChainFor: {
    en: 'Reading the engine evidence chain for “',
    hy: 'Կարդում ենք «',
    ru: 'Читаем цепочку доказательств движка для «',
  },
  readingChainForEnd: {
    en: '”…',
    hy: '» որոշման շարժիչի ապացույցների շղթան…',
    ru: '»…',
  },
  chainMirrored: {
    en: 'Engine evidence chain mirrored.',
    hy: 'Շարժիչի ապացույցների շղթան արտացոլվեց։',
    ru: 'Цепочка доказательств движка отзеркалена.',
  },
  chainSealedAnnounce: {
    en: 'Evidence chain is sealed — the engine chain is not exposed to the desktop.',
    hy: 'Ապացույցների շղթան կնքված է — շարժիչի շղթան հասանելի չէ desktop-ին։',
    ru: 'Цепочка доказательств запечатана — цепочка движка недоступна для десктопа.',
  },
  // Prefix before the decision title: `${selectedPrefix}${title}`
  selectedPrefix: { en: 'Selected: ', hy: 'Ընտրված է՝ ', ru: 'Выбрано: ' },

  // --- Ledger ---
  ledgerAria: {
    en: 'Decision ledger (append-only, read-only)',
    hy: 'Որոշումների մատյան (միայն ավելացվող, կարդալու)',
    ru: 'Журнал решений (только добавление, только чтение)',
  },
  noDecisions: { en: 'No decisions yet', hy: 'Դեռ որոշումներ չկան', ru: 'Пока нет решений' },
  ledgerEmptyHint: {
    en: 'The engine ledger is empty. Accepted decisions will appear here.',
    hy: 'Շարժիչի մատյանը դատարկ է։ Ընդունված որոշումները կհայտնվեն այստեղ։',
    ru: 'Журнал движка пуст. Принятые решения появятся здесь.',
  },

  // --- Evidence readout ---
  evidenceInspectHint: {
    en: 'Press Enter or Open evidence to inspect this decision’s engine chain.',
    hy: 'Enter-ով կամ «Բացել ապացույցները»-ով դիտիր այս որոշման շարժիչի շղթան։',
    ru: 'Нажмите Enter или «Открыть доказательства», чтобы изучить цепочку движка этого решения.',
  },
  evidenceChainLabel: { en: 'EVIDENCE CHAIN', hy: 'ԱՊԱՑՈՒՅՑԻ ՇՂԹԱ', ru: 'ЦЕПОЧКА ДОКАЗАТЕЛЬСТВ' },
  readingChainShort: {
    en: 'Reading the engine evidence chain…',
    hy: 'Կարդում ենք շարժիչի ապացույցների շղթան…',
    ru: 'Читаем цепочку доказательств движка…',
  },
  // Prefix before the record count: `${engineEvidenceCount}${n}`
  engineEvidenceCount: {
    en: 'ENGINE EVIDENCE · ',
    hy: 'ՇԱՐԺԻՉԻ ԱՊԱՑՈՒՅՑ · ',
    ru: 'ДОКАЗАТЕЛЬСТВА ДВИЖКА · ',
  },
  mirroredReadOnly: {
    en: 'Mirrored read-only from the engine chain. The desktop displays it; it never decides on it.',
    hy: 'Արտացոլված է շարժիչի շղթայից միայն ընթերցմամբ։ Desktop-ը ցուցադրում է, բայց երբեք չի որոշում։',
    ru: 'Отзеркалено только для чтения из цепочки движка. Десктоп показывает её, но никогда не решает по ней.',
  },
  // Shown whenever mirrored records ARE displayed: they are schema-checked only, and
  // their origin is not authenticated — so nothing here may read as a verdict.
  unauthenticatedTag: {
    en: 'UNAUTHENTICATED MIRROR',
    hy: 'ՉՀԱՍՏԱՏՎԱԾ ԱՐՏԱՑՈԼՈՒՄ',
    ru: 'НЕПОДТВЕРЖДЁННОЕ ЗЕРКАЛО',
  },
  unauthenticatedBody: {
    en: 'These records are checked for shape only. They carry no signature, and the desktop '
      + 'does not authenticate the process that supplied them, so it cannot confirm they came '
      + 'from the engine. Read them as unverified mirror data — not as proof.',
    hy: 'Այս գրառումները ստուգվում են միայն ձևով։ Դրանք ստորագրություն չեն կրում, և desktop-ը '
      + 'չի հաստատում դրանք տրամադրող գործընթացը, ուստի չի կարող հաստատել, որ դրանք եկել են '
      + 'շարժիչից։ Կարդացեք դրանք որպես չստուգված արտացոլման տվյալ, ոչ որպես ապացույց։',
    ru: 'Эти записи проверены только по форме. Они не содержат подписи, и десктоп не '
      + 'аутентифицирует процесс, который их выдал, поэтому не может подтвердить, что они '
      + 'пришли из движка. Читайте их как непроверенные зеркальные данные, а не как доказательство.',
  },
  // An `ok` read that carried ZERO records: honest absence of evidence, never a
  // satisfied evidence chain.
  evidenceNone: { en: 'No evidence', hy: 'Ապացույց չկա', ru: 'Нет доказательств' },
  evidenceNoneBody: {
    en: 'The engine chain answered for this decision and returned no records at all. '
      + 'There is no evidence to show — an empty chain is not a verified chain.',
    hy: 'Շարժիչի շղթան պատասխանեց այս որոշման համար և ոչ մի գրառում չվերադարձրեց։ '
      + 'Ցուցադրելու ապացույց չկա — դատարկ շղթան ստուգված շղթա չէ։',
    ru: 'Цепочка движка ответила по этому решению и не вернула ни одной записи. '
      + 'Показывать нечего — пустая цепочка не является проверенной цепочкой.',
  },
  chainEmptyAnnounce: {
    en: 'Engine evidence chain answered with no records — there is no evidence.',
    hy: 'Շարժիչի ապացույցների շղթան պատասխանեց առանց գրառումների — ապացույց չկա։',
    ru: 'Цепочка доказательств движка ответила без записей — доказательств нет.',
  },
  // --- The ENGINE's own account of an empty surface ---
  // When a governance surface comes back empty the engine says WHY, in its own words
  // ("the orchestration runtime holds no tasks, so nothing has been recorded"). These
  // labels ATTRIBUTE that sentence: the sentence itself is quoted verbatim, never
  // translated and never re-voiced as the desktop's own finding, because the desktop
  // did not read the engine's store — it only relays what the engine claimed about it.
  engineSaysLabel: {
    en: 'The engine’s own account:',
    hy: 'Շարժիչի սեփական բացատրությունը՝',
    ru: 'Собственное объяснение движка:',
  },
  engineUnknownTask: {
    en: 'The engine also states its orchestration runtime has never heard of this decision id — '
      + 'which is a different fact from “this decision recorded nothing”.',
    hy: 'Շարժիչը նաև նշում է, որ իր orchestration runtime-ը երբեք չի լսել այս որոշման id-ի մասին — '
      + 'դա այլ փաստ է, քան «այս որոշումը ոչինչ չի գրանցել»։',
    ru: 'Движок также заявляет, что его orchestration runtime никогда не слышал об этом '
      + 'идентификаторе решения — это не то же самое, что «по этому решению ничего не записано».',
  },
  // Provenance, never proof: the engine names the store it read; the desktop neither
  // opened it nor verified anything in it.
  engineSourceLabel: {
    en: 'Store the engine says it read: ',
    hy: 'Պահոցը, որը շարժիչն ասում է կարդացել է՝ ',
    ru: 'Хранилище, которое движок сообщает, что прочитал: ',
  },

  evidenceUnreachable: {
    en: 'Evidence chain unreachable',
    hy: 'Ապացույցների շղթան անհասանելի է',
    ru: 'Цепочка доказательств недоступна',
  },
  evidenceSealed: { en: 'Evidence sealed', hy: 'Ապացույցները կնքված են', ru: 'Доказательства запечатаны' },
  sealedBody: {
    en: 'The engine evidence chain is read-only and is not exposed to the desktop yet. The ledger mirrors the decision; it never holds or fabricates the sealed evidence.',
    hy: 'Շարժիչի ապացույցների շղթան կարդալու է և դեռ հասանելի չէ desktop-ին։ Մատյանն արտացոլում է որոշումը, բայց երբեք չի պահում կամ կեղծում կնքված ապացույցը։',
    ru: 'Цепочка доказательств движка доступна только для чтения и пока не открыта для десктопа. Журнал отзеркаливает решение; он никогда не хранит и не фабрикует запечатанные доказательства.',
  },
  // Prefix before the engine-supplied reason: `${reasonPrefix}${reason}`
  reasonPrefix: { en: 'Reason: ', hy: 'Պատճառ՝ ', ru: 'Причина: ' },

  // --- Evidence-chain lifecycle nodes ---
  nodeRecorded: { en: 'recorded', hy: 'Գրանցված', ru: 'записано' },
  nodeDeliberation: { en: 'deliberation', hy: 'Դատում', ru: 'обсуждение' },
  nodeEvidence: { en: 'evidence', hy: 'Ապացույց', ru: 'доказательство' },
  // The evidence node never goes green on today's data. These two labels say WHY:
  // the chain came back empty, or it came back unauthenticated.
  nodeEvidenceNone: { en: 'no evidence', hy: 'ապացույց չկա', ru: 'нет доказательств' },
  nodeEvidenceUnauthenticated: {
    en: 'evidence · unverified',
    hy: 'ապացույց · չստուգված',
    ru: 'доказательство · непроверено',
  },
  chainAria: {
    en: 'Decision evidence chain',
    hy: 'Որոշման ապացույցների շղթա',
    ru: 'Цепочка доказательств решения',
  },

  // --- Chamber ---
  chamberUnavailable: { en: 'Chamber unavailable', hy: 'Պալատն անհասանելի է', ru: 'Палата недоступна' },
  chamberUnavailableHint: {
    en: 'The decision ledger could not be read from the engine.',
    hy: 'Որոշումների մատյանը չհաջողվեց կարդալ շարժիչից։',
    ru: 'Не удалось прочитать журнал решений из движка.',
  },
  selectDecision: { en: 'Select a decision', hy: 'Ընտրիր որոշում', ru: 'Выберите решение' },
  selectDecisionHint: {
    en: 'Arrow-navigate the ledger; press Enter to open its evidence.',
    hy: 'Սլաքներով շրջիր մատյանում, Enter-ով բացիր ապացույցները։',
    ru: 'Перемещайтесь по журналу стрелками; нажмите Enter, чтобы открыть доказательства.',
  },
  deliberationEyebrow: {
    en: 'DELIBERATION · ENGINE LEDGER',
    hy: 'ՈՐՈՇՄԱՆ ԴԱՀԼԻՃ · DELIBERATION',
    ru: 'ОБСУЖДЕНИЕ · ЖУРНАЛ ДВИЖКА',
  },
  recordedField: { en: 'Recorded', hy: 'Գրանցված', ru: 'Записано' },
  updatedField: { en: 'Updated', hy: 'Թարմացված', ru: 'Обновлено' },
  evidenceChainSection: { en: 'Evidence chain', hy: 'Ապացույցների շղթա', ru: 'Цепочка доказательств' },
  openEvidence: { en: 'Open evidence', hy: 'Բացել ապացույցները', ru: 'Открыть доказательства' },
  reweighTitle: {
    en: 'Reweigh is adjudicated by the engine — the desktop cannot alter the ledger.',
    hy: 'Վերակշռումը որոշում է շարժիչը — desktop-ը չի կարող փոխել մատյանը։',
    ru: 'Перевзвешивание решает движок — десктоп не может изменять журнал.',
  },
  reweigh: { en: '↻ Reweigh', hy: '↻ Վերակշռել', ru: '↻ Перевзвесить' },

  // --- Page header / footer ---
  pageEyebrow: {
    en: 'VERDICT INTELLIGENCE · DECISION CHAMBER',
    hy: 'ՈՐՈՇՄԱՆ ԻՆՏԵԼԵԿՏ · VERDICT CHAMBER',
    ru: 'ИНТЕЛЛЕКТ ВЕРДИКТА · ПАЛАТА РЕШЕНИЙ',
  },
  readOnlyMirror: { en: 'Read-only mirror', hy: 'Միայն ընթերցում', ru: 'Зеркало только для чтения' },
  decisionLedger: { en: 'Decision ledger', hy: 'Որոշումների մատյան', ru: 'Журнал решений' },
  selectRowHint: {
    en: 'Select a row to open its chamber',
    hy: 'Ընտրիր տողը՝ դահլիճը բացելու համար',
    ru: 'Выберите строку, чтобы открыть её палату',
  },
  activeDecisions: { en: 'active decisions', hy: 'ակտիվ որոշում', ru: 'активных решений' },
} as const;
