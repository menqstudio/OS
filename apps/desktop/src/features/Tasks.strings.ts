// Trilingual (en/hy/ru) UI strings for the Tasks (Առաքելության տախտակ / mission
// board) screen. The shared i18n dictionary is not edited; these are the strings
// local to this reskin. Each key carries natural translations in all three
// languages — the bilingual eyebrow is localized per language, never left as
// mixed text. Status/priority DATA values are localized via the shared
// statusLabel/priorityLabel helpers, and central `t('…')` keys plus technical
// ids/brand names stay outside this table.
export const STR = {
  // Mission hero (HUD)
  eyebrow: { en: 'MISSION CONTROL', hy: 'ԱՌԱՔԵԼՈՒԹՅԱՆ ԿՈՆՏՐՈԼ', ru: 'ЦЕНТР УПРАВЛЕНИЯ' },
  pathClear: { en: 'PATH CLEAR', hy: 'ՈՒՂԻՆ ՄԱՔՈՒՐ', ru: 'ПУТЬ СВОБОДЕН' },
  blockersWord: { en: 'BLOCKED', hy: 'ԱՐԳԵԼՔ', ru: 'БЛОКИРОВОК' },
  doneCap: { en: 'Done', hy: 'Ավարտ', ru: 'Готово' },

  // Hero ledger (aggregate KPI words)
  kpi_total: { en: 'total', hy: 'ընդամենը', ru: 'всего' },
  kpi_active: { en: 'active', hy: 'ընթացքում', ru: 'активных' },
  kpi_blocked: { en: 'blocked', hy: 'արգելափակ', ru: 'заблокировано' },
  kpi_done: { en: 'done', hy: 'ավարտ', ru: 'готово' },

  // Board bar + legend
  boardTitle: { en: 'Mission board', hy: 'Առաքելության տախտակ', ru: 'Доска миссии' },
  boardNote: { en: 'dependencies + blockers', hy: 'կախվածություններ + արգելքներ', ru: 'зависимости + блокировки' },
  legendBlocked: { en: 'Blocked', hy: 'Արգելափակ', ru: 'Заблокировано' },
  legendDep: { en: 'Dependent', hy: 'Կախված', ru: 'Зависит' },

  // Lane names
  lane_queue: { en: 'Queue', hy: 'Հերթ', ru: 'Очередь' },
  lane_prog: { en: 'In progress', hy: 'Ընթացքում', ru: 'В процессе' },
  lane_block: { en: 'Blocked', hy: 'Արգելափակ', ru: 'Заблокировано' },
  lane_done: { en: 'Done', hy: 'Ավարտ', ru: 'Готово' },

  // Card blocker strip
  blocking: { en: 'Blocking', hy: 'Արգելափակում', ru: 'Блокировка' },
  release: { en: 'Release', hy: 'Ազատել', ru: 'Освободить' },

  // ── Governed dispatch (Phase 6) ────────────────────────────────────────────
  // Every string below describes a REAL state of the dispatch attempt. None of
  // them may be reused to describe a different state — "accepted" in particular
  // is only ever shown for an engine-accepted frame.
  dispatch: { en: 'Dispatch', hy: 'Ուղարկել', ru: 'Отправить' },
  dispatchTitle: { en: 'Governed dispatch', hy: 'Կառավարվող ուղարկում', ru: 'Управляемая отправка' },
  dispatchIntro: {
    en: 'One assignment = one capability tier (what actually bounds the specialist) + one task-contract draft (where it may act). Bro decides who gets what capability at which path.',
    hy: 'Մեկ հանձնարարական = մեկ կարողության մակարդակ (ինչն իրականում սահմանափակում է մասնագետին) + մեկ task-contract-ի սևագիր (որտեղ կարող է գործել)։ Bro-ն որոշում է ով ինչ կարողություն է ստանում ու ո՛ր ուղու վրա։',
    ru: 'Одно назначение = один уровень возможностей (то, что реально ограничивает специалиста) + черновик task-contract (где он может действовать). Bro решает, кто получает какую возможность и по какому пути.',
  },
  draftWarning: {
    en: 'This is a DRAFT, not a sealed contract. The schema requires a repository block with base_commit and tree_identity; those are facts about a real worktree that the desktop has no way to observe, so it does not invent them. The engine seals that block at dispatch.',
    hy: 'Սա ՍԵՎԱԳԻՐ է, ոչ թե կնքված պայմանագիր։ Սխեման պահանջում է repository բլոկ՝ base_commit-ով ու tree_identity-ով; դրանք իրական worktree-ի փաստեր են, որ աշխատասեղանը չի կարող դիտարկել, ուստի չի հորինում։ Շարժիչն է կնքում այդ բլոկը ուղարկելիս։',
    ru: 'Это ЧЕРНОВИК, а не запечатанный контракт. Схема требует блок repository с base_commit и tree_identity; это факты о реальном worktree, которые рабочий стол наблюдать не может, поэтому он их не выдумывает. Этот блок запечатывает движок при отправке.',
  },

  // Field labels
  fAgent: { en: 'Agent', hy: 'Գործակալ', ru: 'Агент' },
  fTier: { en: 'Capability tier', hy: 'Կարողության մակարդակ', ru: 'Уровень возможностей' },
  fMode: { en: 'Mode', hy: 'Ռեժիմ', ru: 'Режим' },
  fRisk: { en: 'Risk', hy: 'Ռիսկ', ru: 'Риск' },
  fPack: { en: 'Pack id', hy: 'Փաթեթի id', ru: 'ID пакета' },
  fObjective: { en: 'Objective', hy: 'Նպատակ', ru: 'Цель' },
  fScope: { en: 'Scope — one path per line', hy: 'Շրջանակ — մեկ ուղի տողում', ru: 'Область — по одному пути в строке' },
  fProhibited: { en: 'Prohibited scope', hy: 'Արգելված շրջանակ', ru: 'Запрещённая область' },
  fSkills: { en: 'Core skill ids', hy: 'Հիմնական հմտությունների id-ներ', ru: 'ID основных навыков' },
  fDone: { en: 'Done criteria', hy: 'Ավարտի չափանիշներ', ru: 'Критерии готовности' },
  fVerifier: { en: 'Verifier', hy: 'Ստուգող', ru: 'Проверяющий' },
  fVerifyCmds: { en: 'Verification commands', hy: 'Ստուգման հրամաններ', ru: 'Команды проверки' },
  fRollback: { en: 'Rollback strategy', hy: 'Հետշրջման ռազմավարություն', ru: 'Стратегия отката' },
  noVerifier: { en: 'none', hy: 'չկա', ru: 'нет' },
  grantTitle: { en: 'Capability grant', hy: 'Կարողության շնորհում', ru: 'Предоставление возможностей' },
  toolsWord: { en: 'Tools', hy: 'Գործիքներ', ru: 'Инструменты' },
  // The enforced/advisory split. The tier is spawned and its tools are passed to the CLI
  // inline; the pack role is only read. Labelling them the same would claim containment
  // the pack role does not provide.
  enforcedWord: { en: 'Enforced', hy: 'ԿԻՐԱՌՎՈՂ', ru: 'Применяется' },
  advisoryWord: { en: 'Advisory only', hy: 'ՄԻԱՅՆ ԽՈՐՀՐԴԱՏՎԱԿԱՆ', ru: 'Только справочно' },
  enforcedNote: {
    en: 'The tier is what actually bounds this specialist: it is the definition that gets spawned, and its tool list is what the CLI receives.',
    hy: 'Մակարդակն է իրականում սահմանափակում այս մասնագետին. հենց այդ սահմանումն է գործարկվում, ու իր գործիքների ցանկն է ստանում CLI-ն։',
    ru: 'Именно уровень реально ограничивает специалиста: запускается это определение, и его список инструментов получает CLI.',
  },
  packRoleNote: {
    en: 'The pack-role definition is READ — for the specialism and the authority record it falls under — and then the matching tier is spawned. It bounds nothing by itself.',
    hy: 'Փաթեթ-դերի սահմանումը ԿԱՐԴԱՑՎՈՒՄ Է՝ մասնագիտացման ու համապատասխան հեղինակության գրառման համար — ու հետո գործարկվում է համապատասխան մակարդակը։ Ինքնին ոչինչ չի սահմանափակում։',
    ru: 'Определение роли пакета ЧИТАЕТСЯ — ради специализации и записи полномочий — после чего запускается соответствующий уровень. Само по себе оно ничего не ограничивает.',
  },
  packRoleUnset: {
    en: 'No pack role referenced yet — it resolves once a pack id is stated.',
    hy: 'Փաթեթի դեր դեռ նշված չէ — կլուծվի, երբ նշվի փաթեթի id-ն։',
    ru: 'Роль пакета пока не указана — определится, когда будет задан id пакета.',
  },
  previewTitle: { en: 'What would be sent', hy: 'Ինչ կուղարկվի', ru: 'Что будет отправлено' },
  problemsTitle: { en: 'Refused before sending', hy: 'Մերժված է ուղարկելուց առաջ', ru: 'Отклонено до отправки' },
  problemsNote: {
    en: 'These are the renderer\'s own pre-flight checks against the engine schema and the default authority record. Passing them means "locally well-formed" — never "accepted".',
    hy: 'Սրանք renderer-ի սեփական նախնական ստուգումներն են՝ շարժիչի սխեմայի ու հեղինակության լռելյայն գրառման դեմ։ Դրանք անցնելը նշանակում է «տեղում ճիշտ ձևավորված», ոչ երբեք՝ «ընդունված»։',
    ru: 'Это собственные предполётные проверки рендерера по схеме движка и записи полномочий по умолчанию. Их прохождение означает «локально корректно сформировано», но никогда — «принято».',
  },
  wellFormed: {
    en: 'Locally well-formed — not accepted by anything yet.',
    hy: 'Տեղում ճիշտ ձևավորված — դեռ ոչինչ չի ընդունել։',
    ru: 'Локально корректно — пока ничем не принято.',
  },

  // Outcome states — one string per REAL state
  outAccepted: { en: 'Accepted by the engine', hy: 'Ընդունված է շարժիչի կողմից', ru: 'Принято движком' },
  outRefused: { en: 'Refused by the engine', hy: 'Մերժված է շարժիչի կողմից', ru: 'Отклонено движком' },
  outUnreachable: { en: 'Not dispatched — no governed channel', hy: 'Չուղարկվեց — կառավարվող ալիք չկա', ru: 'Не отправлено — управляемого канала нет' },
  outInvalid: { en: 'Not sent — the draft is not contract-shaped', hy: 'Չուղարկվեց — սևագիրը պայմանագրի ձև չունի', ru: 'Не отправлено — черновик не соответствует форме контракта' },
  unreachableNote: {
    en: 'Nothing was assigned to anyone. This build registers no dispatch command, so the attempt could not reach the engine. Required:',
    hy: 'Ոչ ոքի ոչինչ չի հանձնարարվել։ Այս կառուցվածքը dispatch հրաման չի գրանցում, ուստի փորձը չհասավ շարժիչին։ Պահանջվում է՝',
    ru: 'Никому ничего не назначено. В этой сборке команда отправки не зарегистрирована, поэтому попытка не достигла движка. Требуется:',
  },
  assignmentId: { en: 'Assignment', hy: 'Հանձնարարական', ru: 'Назначение' },
  contractDigest: { en: 'Contract digest', hy: 'Պայմանագրի ամփոփ', ru: 'Дайджест контракта' },
  leaseId: { en: 'Lease', hy: 'Լիզինգ', ru: 'Аренда' },
  sending: { en: 'Dispatching…', hy: 'Ուղարկվում է…', ru: 'Отправка…' },
  noAgents: {
    en: 'No agents in the roster — there is nobody to dispatch to.',
    hy: 'Ռոստերում գործակալներ չկան — ուղարկելու համար ոչ ոք չկա։',
    ru: 'В составе нет агентов — отправлять некому.',
  },
} as const;

export type StrKey = keyof typeof STR;
