// Trilingual copy for the Chat screen's delegation surface — the part of a conversation that
// shows who Bro handed work to and what they were allowed to do.
//
// Local rather than in `i18n/en.ts`: the central catalog is outside this task's edit scope,
// and the sibling views already carry their own `*.strings.ts` (Conversations, Decisions,
// Approvals …) indexed through the same `L()` helper. Every key has a real en / hy / ru value.
//
// The wording is deliberate in two places, and both are honesty rather than style:
//  - `scopeUnenforced` says a scope was STATED, because on this path nothing enforces it;
//  - `capabilityEnforced` says the tool list IS the grant, because the `Task` tool really does
//    take it from the agent definition and Bro cannot widen it at spawn time.
// If either of those facts changes in the backend, the copy has to change with it.

export const STR = {
  eyebrow: {
    en: 'DELEGATION',
    hy: 'ՊԱՏՎԻՐԱԿՈՒՄ',
    ru: 'ДЕЛЕГИРОВАНИЕ',
  },
  sectionTitle: {
    en: 'Who Bro put on this',
    hy: 'Ում վրա Bro-ն դրեց սա',
    ru: 'Кому Bro это поручил',
  },
  sectionNote: {
    en: 'Every specialist Bro spawned in this chat, with the capability tier and the paths he granted them.',
    hy: 'Այս զրույցում Bro-ի բացած ամեն մասնագետ՝ իր capability tier-ով ու տրված ուղիներով։',
    ru: 'Каждый специалист, запущенный Bro в этом чате, с уровнем возможностей и выданными путями.',
  },
  countUnit: {
    en: 'delegations',
    hy: 'պատվիրակում',
    ru: 'делегирований',
  },
  reload: {
    en: 'Reload',
    hy: 'Թարմացնել',
    ru: 'Обновить',
  },
  loading: {
    en: 'Reading delegations…',
    hy: 'Կարդում ենք պատվիրակումները…',
    ru: 'Читаем делегирования…',
  },

  // ── The honest empty / unavailable states ─────────────────────────────────────────
  noneYet: {
    en: 'No delegation reported in this chat yet.',
    hy: 'Այս զրույցում դեռ պատվիրակում չի հաղորդվել։',
    ru: 'В этом чате пока не сообщено ни об одном делегировании.',
  },
  notEmittedTitle: {
    en: 'The backend does not report delegations yet',
    hy: 'Backend-ը դեռ չի հաղորդում պատվիրակումները',
    ru: 'Бэкенд пока не сообщает о делегированиях',
  },
  notEmittedBody: {
    en: 'Bro can delegate — he holds the Task tool — but the turn does not tell this window about it. '
      + 'Nothing is shown here rather than a card drawn over data we do not have.',
    hy: 'Bro-ն կարող է պատվիրակել — Task գործիքը իր մոտ է — բայց turn-ը այս պատուհանին չի հաղորդում դա։ '
      + 'Այստեղ ոչինչ չի ցուցադրվում, փոխանակ քարտ նկարելու տվյալների վրա, որոնք չունենք։',
    ru: 'Bro умеет делегировать — у него есть инструмент Task — но ход не сообщает об этом окну. '
      + 'Здесь ничего не показано, вместо карточки, нарисованной поверх данных, которых у нас нет.',
  },
  deniedTitle: {
    en: 'Reading delegations was refused',
    hy: 'Պատվիրակումների ընթերցումը մերժվեց',
    ru: 'Чтение делегирований отклонено',
  },
  errorTitle: {
    en: 'Delegations could not be read',
    hy: 'Չհաջողվեց կարդալ պատվիրակումները',
    ru: 'Не удалось прочитать делегирования',
  },
  noBackendTitle: {
    en: 'No desktop backend',
    hy: 'Desktop backend չկա',
    ru: 'Нет десктопного бэкенда',
  },
  noBackendBody: {
    en: 'This window is not running inside the desktop app, so there is nothing to ask.',
    hy: 'Այս պատուհանը desktop app-ի ներսում չի աշխատում, ուրեմն հարցնելու բան չկա։',
    ru: 'Это окно работает не внутри десктопного приложения, поэтому спрашивать нечего.',
  },
  backendSaid: {
    en: 'The backend said',
    hy: 'Backend-ն ասաց',
    ru: 'Бэкенд ответил',
  },

  // ── The card ──────────────────────────────────────────────────────────────────────
  delegatedTo: {
    en: 'delegated to',
    hy: 'պատվիրակեց',
    ru: 'поручил',
  },
  tierLabel: {
    en: 'TIER',
    hy: 'ՄԱԿԱՐԴԱԿ',
    ru: 'УРОВЕНЬ',
  },
  packRoleLabel: {
    en: 'PACK ROLE',
    hy: 'PACK ԴԵՐ',
    ru: 'РОЛЬ ПАКЕТА',
  },
  canDo: {
    en: 'CAN',
    hy: 'ԿԱՐՈՂ Է',
    ru: 'МОЖЕТ',
  },
  mayTouch: {
    en: 'MAY TOUCH',
    hy: 'ԿԱՐՈՂ Է ԴԻՊՉԵԼ',
    ru: 'МОЖЕТ ТРОГАТЬ',
  },
  mustNotTouch: {
    en: 'MUST NOT TOUCH',
    hy: 'ՉԻ ԿԱՐՈՂ ԴԻՊՉԵԼ',
    ru: 'НЕЛЬЗЯ ТРОГАТЬ',
  },
  capabilityEnforced: {
    en: 'Enforced — the Task tool takes this list from the agent definition; it cannot be widened at spawn.',
    hy: 'Կիրառված է — Task գործիքը այս ցանկը վերցնում է agent-ի սահմանումից; spawn-ի պահին չի կարող լայնանալ։',
    ru: 'Обеспечено — инструмент Task берёт этот список из определения агента; при запуске его нельзя расширить.',
  },
  capabilityFromTierTable: {
    en: 'From the local tier table, not read from the live agent definition.',
    hy: 'Լոկալ tier աղյուսակից, ոչ թե կենդանի agent-ի սահմանումից կարդացված։',
    ru: 'Из локальной таблицы уровней, а не из живого определения агента.',
  },
  capabilityUnknown: {
    en: 'Not reported — what this specialist may do is unknown here.',
    hy: 'Չի հաղորդվել — ինչ կարող է անել այս մասնագետը, այստեղ հայտնի չէ։',
    ru: 'Не сообщено — что может этот специалист, здесь неизвестно.',
  },
  capabilityConflict: {
    en: 'The agent definition and the tier table disagree. The wider of the two is shown — never assume the narrower one.',
    hy: 'Agent-ի սահմանումը ու tier աղյուսակը չեն համընկնում։ Ցուցադրված է ավելի լայնը — երբեք մի ենթադրիր նեղը։',
    ru: 'Определение агента и таблица уровней расходятся. Показан более широкий — никогда не считайте, что действует узкий.',
  },
  scopeUnenforced: {
    en: 'Stated, not enforced. These paths travel as text in the task; nothing on this path contains the agent to them.',
    hy: 'Նշված է, բայց չի կիրառվում։ Այս ուղիները task-ի մեջ տեքստ են; այս ճանապարհին ոչինչ agent-ին դրանցում չի պահում։',
    ru: 'Заявлено, но не обеспечено. Эти пути передаются текстом в задаче; на этом пути ничто не удерживает агента внутри них.',
  },
  scopeEnforcedByEngine: {
    en: 'Enforced by the engine — the run was bounded by enforce_scope.',
    hy: 'Կիրառված է engine-ի կողմից — run-ը սահմանափակված էր enforce_scope-ով։',
    ru: 'Обеспечено движком — запуск ограничен enforce_scope.',
  },
  grantNotStated: {
    en: 'No scope was stated for this delegation.',
    hy: 'Այս պատվիրակման համար scope նշված չէ։',
    ru: 'Для этого делегирования область не указана.',
  },
  grantInvalid: {
    en: 'The stated scope is not a valid work path, so it is shown as raw text and not as a grant. '
      + 'The engine would refuse it too.',
    hy: 'Նշված scope-ը վավեր work path չէ, ուրեմն ցուցադրվում է որպես հում տեքստ, ոչ որպես grant։ '
      + 'Engine-ն էլ կմերժեր այն։',
    ru: 'Указанная область не является допустимым рабочим путём, поэтому показана как сырой текст, а не как грант. '
      + 'Движок тоже отклонил бы её.',
  },
  offendingEntry: {
    en: 'Rejected entry',
    hy: 'Մերժված գրառում',
    ru: 'Отклонённая запись',
  },
  whatWasAsked: {
    en: 'What Bro asked for',
    hy: 'Ինչ խնդրեց Bro-ն',
    ru: 'О чём попросил Bro',
  },
  whatCameBack: {
    en: 'What came back',
    hy: 'Ինչ վերադարձավ',
    ru: 'Что вернулось',
  },
  noResultYet: {
    en: 'Still running — nothing has come back yet.',
    hy: 'Դեռ աշխատում է — դեռ ոչինչ չի վերադարձել։',
    ru: 'Ещё выполняется — пока ничего не вернулось.',
  },
  noSummary: {
    en: 'Finished, but the backend reported no result text.',
    hy: 'Ավարտվեց, բայց backend-ը արդյունքի տեքստ չհաղորդեց։',
    ru: 'Завершено, но бэкенд не сообщил текст результата.',
  },

  // ── Outcome words ─────────────────────────────────────────────────────────────────
  outcomeRunning: {
    en: 'running',
    hy: 'ընթացքում',
    ru: 'выполняется',
  },
  outcomeOk: {
    en: 'returned',
    hy: 'վերադարձավ',
    ru: 'вернулся',
  },
  outcomeError: {
    en: 'failed',
    hy: 'ձախողվեց',
    ru: 'ошибка',
  },
  outcomeCancelled: {
    en: 'cancelled',
    hy: 'չեղարկված',
    ru: 'отменено',
  },
  outcomeUnknown: {
    en: 'finished · outcome unreadable',
    hy: 'ավարտվեց · արդյունքն ընթեռնելի չէ',
    ru: 'завершено · итог не читается',
  },
} as const;

export type ChatStringKey = keyof typeof STR;
