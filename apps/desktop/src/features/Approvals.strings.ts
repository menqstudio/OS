// ── §D `approvals` — co-located trilingual UI string catalog ─────────────────
// Every visible/aria string that used to be an inline bilingual `bi('en','hy')`
// call in Approvals.tsx now lives here with a real Russian translation. Central
// i18n strings (used via `t('some.key')`) stay in the shared catalog and are NOT
// duplicated here. Interpolation that was string-concatenation is preserved by
// splitting the affected strings into prefix/suffix parts (see *Prefix / *Suffix
// / denyDialog* keys) and composing them in the component.

export const STR = {
  // ── status labels (statusMeta) ────────────────────────────────────────────
  approved:          { en: 'Approved',        hy: 'Հաստատված',        ru: 'Одобрено' },
  denied:            { en: 'Denied',          hy: 'Մերժված',          ru: 'Отклонено' },
  escalatedA3:       { en: 'Escalated · A3',  hy: 'Փոխանցված · A3',   ru: 'Передано · A3' },
  expiredHeld:       { en: 'Expired · held',  hy: 'Ժամկետանց · պահված', ru: 'Истекло · удержано' },
  broReviewing:      { en: 'Bro reviewing',   hy: 'Bro վերլուծում է',  ru: 'Bro проверяет' },
  awaitingDecision:  { en: 'Awaiting decision', hy: 'Սպասում է որոշման', ru: 'Ожидает решения' },

  // ── verdict announcements (interpolated with the item label) ───────────────
  grantedPrefix:            { en: 'Granted: ',  hy: 'Հաստատվեց՝ ', ru: 'Одобрено: ' },
  deniedPrefix:             { en: 'Denied: ',   hy: 'Մերժվեց՝ ',   ru: 'Отклонено: ' },
  escalatedPrefix:          { en: 'Escalated to A3 review: ', hy: 'Փոխանցվեց A3 վերանայման՝ ', ru: 'Передано на рассмотрение A3: ' },

  // ── page header ────────────────────────────────────────────────────────────
  eyebrowHitl: {
    en: 'HUMAN-IN-THE-LOOP · CONTROL GATE',
    hy: 'ՄԱՐԴ-ՀԱՆԳՈՒՅՑ ՀՍԿԻՉ · ՀԱՍՏԱՏՄԱՆ ԴԱՐՊԱՍ',
    ru: 'ЧЕЛОВЕК В КОНТУРЕ · КОНТРОЛЬНЫЙ ШЛЮЗ',
  },
  pending: { en: 'pending', hy: 'սպասում է', ru: 'ожидает' },

  // ── error / blocked / empty states ─────────────────────────────────────────
  engineUnreachable:     { en: 'Engine unreachable.', hy: 'Շարժիչն անհասանելի է։', ru: 'Движок недоступен.' },
  ownerNotAuthenticated: { en: 'Owner not authenticated', hy: 'Տերը նույնականացված չէ', ru: 'Владелец не аутентифицирован' },
  gateLockedBody: {
    en: 'The approval gate is locked until the owner authenticates with the engine. Grant, deny and escalate stay disabled — the desktop never decides on its own.',
    hy: 'Հաստատման դարպասը կողպված է, մինչև տերը նույնականացվի շարժիչի հետ։ Հաստատել, մերժել և բարձրացնել գործողություններն անջատված են — desktop-ը երբեք ինքնուրույն որոշում չի կայացնում։',
    ru: 'Шлюз одобрения заблокирован, пока владелец не аутентифицируется в движке. Одобрение, отклонение и эскалация остаются отключёнными — десктоп никогда не принимает решение сам.',
  },
  gateClear: {
    en: 'Gate clear — no pending approvals',
    hy: 'Դարպասը մաքուր է — չկան սպասող հաստատումներ',
    ru: 'Шлюз свободен — нет ожидающих одобрений',
  },
  newRequestsHint: {
    en: 'New engine requests will appear here as they arrive.',
    hy: 'Շարժիչի նոր հարցումները կհայտնվեն այստեղ, երբ ստացվեն։',
    ru: 'Новые запросы движка появятся здесь по мере поступления.',
  },

  // ── stats tiles ────────────────────────────────────────────────────────────
  inQueue:      { en: 'in queue',    hy: 'հերթում',        ru: 'в очереди' },
  pendingNow:   { en: 'pending now', hy: 'սպասում է հիմա',  ru: 'сейчас ожидает' },
  approvedLower:{ en: 'approved',    hy: 'հաստատված',      ru: 'одобрено' },
  deniedHeld:   { en: 'denied · held', hy: 'մերժված',      ru: 'отклонено · удержано' },

  // ── the gate (hero) ────────────────────────────────────────────────────────
  approvalGatePrefix: { en: 'Approval gate — ', hy: 'Հաստատման դարպաս — ', ru: 'Шлюз одобрения — ' },
  controlGate:        { en: 'CONTROL GATE', hy: 'ՀԱՍՏԱՏՄԱՆ ԴԱՐՊԱՍ', ru: 'КОНТРОЛЬНЫЙ ШЛЮЗ' },
  requestingAgent:    { en: 'REQUESTING AGENT', hy: 'ՊԱՀԱՆՋՈՂ ԳՈՐԾԱԿԱԼ', ru: 'ЗАПРАШИВАЮЩИЙ АГЕНТ' },
  requester:          { en: 'requester', hy: 'հայցող', ru: 'запрашивающий' },
  actionHeld:         { en: 'ACTION HELD', hy: 'ԳՈՐԾՈՂՈՒԹՅՈՒՆԸ ՊԱՀՎԱԾ Է', ru: 'ДЕЙСТВИЕ УДЕРЖАНО' },
  approvedStamp:      { en: 'APPROVED', hy: 'ՀԱՍՏԱՏՎԱԾ', ru: 'ОДОБРЕНО' },
  waiting:            { en: 'waiting', hy: 'սպասում է', ru: 'ожидает' },
  impactScope:        { en: 'IMPACT SCOPE', hy: 'ԱԶԴԵՑՈՒԹՅԱՆ ՇԱՌԱՎԻՂ', ru: 'ОБЛАСТЬ ВОЗДЕЙСТВИЯ' },
  requestedByLabel:   { en: 'Requested by', hy: 'Հայցող', ru: 'Запросил' },
  requestedAtLabel:   { en: 'Requested at', hy: 'Հայցվել է', ru: 'Запрошено в' },

  // ── authorization bar ──────────────────────────────────────────────────────
  requestedWord: { en: 'Requested', hy: 'Պահանջվել է', ru: 'Запрошено' },
  levelSuffix:   { en: ' level', hy: ' մակարդակ', ru: ' уровень' },
  denyAria:      { en: 'Deny — reject this action', hy: 'Մերժել — մերժել գործողությունը', ru: 'Отклонить — отклонить это действие' },
  deny:          { en: 'Deny', hy: 'Մերժել', ru: 'Отклонить' },
  escalateForReview: { en: 'Escalate for higher review', hy: 'Բարձրացնել՝ ավելի բարձր վերանայման', ru: 'Передать на вышестоящее рассмотрение' },
  escalateA3:    { en: 'Escalate A3', hy: 'Փոխանցել A3', ru: 'Передать A3' },
  pressHoldAria: { en: 'Press and hold to grant', hy: 'Սեղմիր և պահիր՝ հաստատելու', ru: 'Нажмите и удерживайте для одобрения' },
  pressHoldGrant:{ en: 'Press & hold to grant', hy: 'Սեղմիր և պահիր՝ հաստատելու', ru: 'Нажмите и удерживайте' },

  // ── keyboard hint ──────────────────────────────────────────────────────────
  select:           { en: 'select', hy: 'ընտրել', ru: 'выбрать' },
  holdGrantConfirm: { en: 'hold Grant to confirm', hy: 'պահիր՝ հաստատելու', ru: 'удерживайте «Одобрить» для подтверждения' },
  denyLower:        { en: 'deny', hy: 'մերժել', ru: 'отклонить' },
  escalateLower:    { en: 'escalate', hy: 'բարձրացնել', ru: 'передать' },

  // ── engine queue mirror notice ─────────────────────────────────────────────
  queueUnreachable: {
    en: 'Engine approval queue unreachable — showing the local mirror only.',
    hy: 'Շարժիչի հաստատումների հերթն անհասանելի է — ցուցադրվում է միայն տեղական արտացոլումը։',
    ru: 'Очередь одобрений движка недоступна — показано только локальное зеркало.',
  },
  queueSealed: {
    en: 'Engine approval queue is sealed — showing the local mirror only.',
    hy: 'Շարժիչի հաստատումների հերթը կնքված է — ցուցադրվում է միայն տեղական արտացոլումը։',
    ru: 'Очередь одобрений движка запечатана — показано только локальное зеркало.',
  },

  // ── queue section ──────────────────────────────────────────────────────────
  approvalQueue:    { en: 'Approval queue', hy: 'Հաստատման հերթ', ru: 'Очередь одобрений' },
  selectRowHint:    { en: 'Select a row to seat it at the gate · ', hy: 'Ընտրիր տողը՝ դարպասին բերելու համար · ', ru: 'Выберите строку, чтобы поместить её в шлюз · ' },
  inQueueSuffix:    { en: ' in queue', hy: ' գործողություն հերթում', ru: ' в очереди' },
  approvalQueueAria:{ en: 'Approval queue', hy: 'Հաստատումների հերթ', ru: 'Очередь одобрений' },
  target:           { en: 'Target', hy: 'Ազդեցություն', ru: 'Цель' },
  waitingLabel:     { en: 'Waiting', hy: 'Ժամկետ', ru: 'Ожидание' },

  // ── stats strip aria ───────────────────────────────────────────────────────
  approvalStats: { en: 'Approval statistics', hy: 'Հաստատումների վիճակագրություն', ru: 'Статистика одобрений' },

  // ── confirm dialog ─────────────────────────────────────────────────────────
  confirmDenial: { en: 'Confirm denial', hy: 'Մերժե՞լ', ru: 'Подтвердить отклонение' },
  denyDialogA:   { en: 'Deny “', hy: 'Մերժե՞լ «', ru: 'Отклонить «' },
  denyDialogB:   { en: '” on ', hy: '»՝ ', ru: '» на ' },
  denyDialogC: {
    en: '? This is the fail-safe reject path.',
    hy: '-ի վրա։ Սա fail-safe մերժման ուղին է։',
    ru: '? Это отказоустойчивый путь отклонения.',
  },
  escalateDialogA: { en: 'Escalate “', hy: 'Բարձրացնե՞լ «', ru: 'Передать «' },
  escalateDialogB: { en: '” on ', hy: '»՝ ', ru: '» на ' },
  escalateDialogC: {
    en: '? It routes to A3 review and notifies the owner — it neither grants nor denies.',
    hy: '-ի վրա։ Կուղղորդվի A3 վերանայման և կծանուցի տիրոջը — ոչ հաստատում է, ոչ մերժում։',
    ru: '? Направляется на рассмотрение A3 и уведомляет владельца — не одобряет и не отклоняет.',
  },
  escalate: { en: 'Escalate', hy: 'Բարձրացնել', ru: 'Передать' },

  // The `g` grant path. §D binds a `g` key alongside `d`/`e`, and §D also requires that
  // "all actions confirm before committing" — so `g` stages this dialog rather than
  // committing, and the pointer press-and-hold stays the mouse-driven equivalent. Neither
  // is the real gate: `confirm_approval` is adjudicated behind the native dialog (T-011).
  confirmGrant:   { en: 'Confirm grant', hy: 'Հաստատե՞լ', ru: 'Подтвердить одобрение' },
  grantDialogA:   { en: 'Grant “', hy: 'Հաստատե՞լ «', ru: 'Одобрить «' },
  grantDialogB:   { en: '” on ', hy: '»՝ ', ru: '» на ' },
  grantDialogC: {
    en: '? A native confirmation the app window cannot forge decides it.',
    hy: '-ի վրա։ Որոշում է native հաստատումը, որը app-ի պատուհանը չի կարող կեղծել։',
    ru: '? Решение принимает нативное подтверждение, которое окно приложения не может подделать.',
  },
  grant: { en: 'Grant', hy: 'Հաստատել', ru: 'Одобрить' },
} as const;
