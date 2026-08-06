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
