// ── §D `approvals` — co-located trilingual UI string catalog ─────────────────
// Every visible/aria string that used to be an inline bilingual `bi('en','hy')`
// call in Approvals.tsx now lives here with a real Russian translation. Central
// i18n strings (used via `t('some.key')`) stay in the shared catalog and are NOT
// duplicated here. Interpolation that was string-concatenation is preserved by
// splitting the affected strings into prefix/suffix parts (see *Prefix / *Suffix
// / denyDialog* keys) and composing them in the component.

export const STR = {
  // ── the engine REQUEST (T-021) — a different system from the grant/deny above ───────────
  askSection: {
    en: 'Ask the engine to record a request',
    hy: 'Խնդրել շարժիչին գրանցել հարցում',
    ru: 'Попросить движок записать запрос',
  },
  askNote: {
    en: 'This is not the approval above. That one is this app’s own, over its local ledger. This asks the ENGINE to record a request, which only an owner-signed control-room command can then adjudicate — nothing here decides anything.',
    hy: 'Սա վերևի հաստատումը չէ։ Այն այս հավելվածի սեփականն է, իր տեղական մատյանի վրա։ Սա խնդրում է ՇԱՐԺԻՉԻՆ գրանցել հարցում, որը հետո վճռում է միայն տիրոջ ստորագրած control-room հրամանը — այստեղ ոչինչ ոչինչ չի որոշում։',
    ru: 'Это не одобрение выше. То — собственное для этого приложения, в его локальном журнале. Здесь ДВИЖОК просят записать запрос, который затем решает только подписанная владельцем команда control-room — здесь ничто ничего не решает.',
  },
  askTaskLabel: { en: 'Engine task', hy: 'Շարժիչի խնդիր', ru: 'Задача движка' },
  askWhoLabel: { en: 'Your name (recorded as claimed)', hy: 'Քո անունը (գրանցվում է որպես հայտարարված)', ru: 'Ваше имя (записывается как заявленное)' },
  askReasonLabel: { en: 'Why', hy: 'Ինչու', ru: 'Почему' },
  askApprove: { en: 'Ask: approve', hy: 'Խնդրել՝ հաստատել', ru: 'Просить: одобрить' },
  askDeny: { en: 'Ask: deny', hy: 'Խնդրել՝ մերժել', ru: 'Просить: отклонить' },
  askVerify: { en: 'Ask: verify first', hy: 'Խնդրել՝ նախ ստուգել', ru: 'Просить: сначала проверить' },
  askNeedsEngine: {
    en: 'The engine queue is not readable, so there is no task to ask about. Nothing was sent.',
    hy: 'Շարժիչի հերթը ընթեռնելի չէ, ուստի հարցնելու խնդիր չկա։ Ոչինչ չի ուղարկվել։',
    ru: 'Очередь движка недоступна, поэтому спрашивать не о чем. Ничего не отправлено.',
  },
  askRecorded: {
    en: 'Recorded, not adjudicated · entry ',
    hy: 'Գրանցվեց, չի վճռվել · գրառում ',
    ru: 'Записано, не решено · запись ',
  },
  askDuplicate: {
    en: ' (a repeat of an ask already recorded)',
    hy: ' (արդեն գրանցված հարցման կրկնություն)',
    ru: ' (повтор уже записанного запроса)',
  },
  askRefused: { en: 'The engine refused: ', hy: 'Շարժիչը մերժեց՝ ', ru: 'Движок отказал: ' },
  askBlocked: { en: 'Nothing was established: ', hy: 'Ոչինչ չհաստատվեց՝ ', ru: 'Ничего не установлено: ' },

  // ── status labels (statusMeta) ────────────────────────────────────────────
  approved:          { en: 'Approved',        hy: 'Հաստատված',        ru: 'Одобрено' },
  denied:            { en: 'Denied',          hy: 'Մերժված',          ru: 'Отклонено' },
  escalatedA3:       { en: 'Escalated · A3',  hy: 'Փոխանցված · A3',   ru: 'Передано · A3' },
  expiredHeld:       { en: 'Expired · held',  hy: 'Ժամկետանց · պահված', ru: 'Истекло · удержано' },
  broReviewing:      { en: 'Bro reviewing',   hy: 'Bro վերլուծում է',  ru: 'Bro проверяет' },
  awaitingDecision:  { en: 'Awaiting decision', hy: 'Սպասում է որոշման', ru: 'Ожидает решения' },
  // `consumed` is a real backend status: a grant that has been spent against its action. It
  // used to fall through to "Awaiting decision".
  consumedSpent:     { en: 'Consumed · grant spent', hy: 'Օգտագործված · հաստատումը ծախսված է', ru: 'Использовано · одобрение израсходовано' },
  // The row says `approved` but does not carry the native-confirmation provenance the backend
  // writes with a real grant. It is not shown as granted.
  approvedUnconfirmed: {
    en: 'Marked approved · no native confirmation on record',
    hy: 'Նշված է հաստատված · native հաստատման գրառում չկա',
    ru: 'Помечено одобренным · записи о нативном подтверждении нет',
  },
  // Prefix before a status string this build does not know: `${unknownStatus}${raw}`.
  unknownStatus:     { en: 'Unknown status · ', hy: 'Անհայտ կարգավիճակ · ', ru: 'Неизвестный статус · ' },

  // ── verdict announcements (interpolated with the item label) ───────────────
  grantedPrefix:            { en: 'Granted: ',  hy: 'Հաստատվեց՝ ', ru: 'Одобрено: ' },
  deniedPrefix:             { en: 'Denied: ',   hy: 'Մերժվեց՝ ',   ru: 'Отклонено: ' },
  escalatedPrefix:          { en: 'Escalated to A3, not decided: ', hy: 'Բարձրացվեց A3, չի որոշվել՝ ', ru: 'Передано на A3, не решено: ' },
  // The native confirmation dialog was dismissed. Nothing was decided; the row is still pending.
  grantNotConfirmedPrefix:  { en: 'Not confirmed — nothing was decided: ', hy: 'Չհաստատվեց — ոչինչ չի որոշվել՝ ', ru: 'Не подтверждено — ничего не решено: ' },
  // The command answered with a record that carries a different state from the one asked for.
  outcomeOtherPrefix:       { en: 'The ledger now says: ', hy: 'Մատյանն այժմ ասում է՝ ', ru: 'В журнале теперь: ' },
  // The command answered with something that is not an approval record: nothing is established.
  outcomeUnreadablePrefix:  { en: 'No readable record came back, so no outcome is established for: ', hy: 'Ընթեռնելի գրառում չվերադարձավ, ուստի արդյունք հաստատված չէ՝ ', ru: 'Читаемая запись не вернулась, поэтому результат не установлен для: ' },

  // ── page header ────────────────────────────────────────────────────────────
  eyebrowHitl: {
    en: 'HUMAN-IN-THE-LOOP · CONTROL GATE',
    hy: 'ՄԱՐԴ-ՀԱՆԳՈՒՅՑ ՀՍԿԻՉ · ՀԱՍՏԱՏՄԱՆ ԴԱՐՊԱՍ',
    ru: 'ЧЕЛОВЕК В КОНТУРЕ · КОНТРОЛЬНЫЙ ШЛЮЗ',
  },
  pending: { en: 'pending', hy: 'սպասում է', ru: 'ожидает' },

  // ── error / blocked / empty states ─────────────────────────────────────────
  // The list is `list_approvals`: the app's own approval table in local SQLite. Its failure used
  // to be labelled "Engine unreachable." and, for any error mentioning `owner` or `denied`,
  // "Owner not authenticated … until the owner authenticates with the engine". No engine is on
  // that path and nothing on it authenticates an owner.
  ledgerUnreadable: {
    en: 'The local approval ledger could not be read.',
    hy: 'Տեղական հաստատումների մատյանը չհաջողվեց կարդալ։',
    ru: 'Не удалось прочитать локальный журнал одобрений.',
  },
  gateClear: {
    en: 'Gate clear — no pending approvals',
    hy: 'Դարպասը մաքուր է — չկան սպասող հաստատումներ',
    ru: 'Шлюз свободен — нет ожидающих одобрений',
  },
  newRequestsHint: {
    en: 'New approval requests in this app’s local ledger will appear here as they arrive.',
    hy: 'Այս հավելվածի տեղական մատյանի նոր հաստատման հարցումները կհայտնվեն այստեղ, երբ ստացվեն։',
    ru: 'Новые запросы на одобрение из локального журнала этого приложения появятся здесь по мере поступления.',
  },

  // ── stats tiles ────────────────────────────────────────────────────────────
  inQueue:      { en: 'in queue',    hy: 'հերթում',        ru: 'в очереди' },
  pendingNow:   { en: 'pending now', hy: 'սպասում է հիմա',  ru: 'сейчас ожидает' },
  approvedLower:{ en: 'approved',    hy: 'հաստատված',      ru: 'одобрено' },
  deniedHeld:   { en: 'denied', hy: 'մերժված',      ru: 'отклонено' },
  // Shown only when the bucket has rows. Together with the four above they sum to `in queue`.
  consumedLower:    { en: 'consumed', hy: 'օգտագործված', ru: 'использовано' },
  escalatedTile:    { en: 'escalated · parked', hy: 'բարձրացված · կանգնեցված', ru: 'передано · отложено' },
  unconfirmedLower: { en: 'approved · unconfirmed', hy: 'հաստատված · չհիմնավորված', ru: 'одобрено · без подтверждения' },
  otherLower:       { en: 'expired · other', hy: 'ժամկետանց · այլ', ru: 'истекло · прочее' },

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
  // No higher-review surface exists in this app: escalating sets the row to A3 and parks it.
  escalateForReview: { en: 'Escalate — park at tier A3', hy: 'Բարձրացնել — կանգնեցնել A3 մակարդակում', ru: 'Эскалировать — оставить на уровне A3' },
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
    en: 'The engine approval queue could not be reached. The list on this page is this app’s own local ledger, not a copy of that queue.',
    hy: 'Շարժիչի հաստատումների հերթին հասնել չհաջողվեց։ Այս էջի ցուցակը այս հավելվածի սեփական տեղական մատյանն է, ոչ թե այդ հերթի պատճենը։',
    ru: 'До очереди одобрений движка добраться не удалось. Список на этой странице — собственный локальный журнал приложения, а не копия этой очереди.',
  },
  queueSealed: {
    en: 'The engine refused the approval-queue read. The list on this page is this app’s own local ledger, not a copy of that queue.',
    hy: 'Շարժիչը մերժեց հաստատումների հերթի ընթերցումը։ Այս էջի ցուցակը այս հավելվածի սեփական տեղական մատյանն է, ոչ թե այդ հերթի պատճենը։',
    ru: 'Движок отклонил чтение очереди одобрений. Список на этой странице — собственный локальный журнал приложения, а не копия этой очереди.',
  },

  // ── queue section ──────────────────────────────────────────────────────────
  approvalQueue:    { en: 'Approval queue', hy: 'Հաստատման հերթ', ru: 'Очередь одобрений' },
  selectRowHint:    { en: 'Select a row to seat it at the gate · ', hy: 'Ընտրիր տողը՝ դարպասին բերելու համար · ', ru: 'Выберите строку, чтобы поместить её в шлюз · ' },
  inQueueSuffix:    { en: ' in queue', hy: ' գործողություն հերթում', ru: ' в очереди' },
  approvalQueueAria:{ en: 'Approval queue', hy: 'Հաստատումների հերթ', ru: 'Очередь одобрений' },
  target:           { en: 'Target', hy: 'Թիրախ', ru: 'Цель' },
  waitingLabel:     { en: 'Waiting', hy: 'Սպասում', ru: 'Ожидание' },

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
  // What `escalate_approval` does, and what it leaves behind. It used to end "It routes to A3
  // review and notifies the owner — it neither grants nor denies", which is true and omits the
  // part that matters: `confirm_approval` and `reject_approval` are pending-only, nothing reads
  // an `escalated` row, and no A3 review surface exists — so the request can never be decided.
  escalateDialogC: {
    en: '? It marks the request escalated at tier A3 and posts a notification. It neither grants nor denies — and afterwards nothing in this app can grant or deny it: the request stays parked.',
    hy: '-ի վրա։ Հարցումը կնշվի բարձրացված՝ A3 մակարդակում, ու կհրապարակվի ծանուցում։ Դա ոչ հաստատում է, ոչ մերժում — ու դրանից հետո այս հավելվածում ոչինչ չի կարող այն հաստատել կամ մերժել. հարցումը մնում է կանգնեցված։',
    ru: '? Запрос будет помечен как переданный на уровень A3, и появится уведомление. Это не одобряет и не отклоняет — и после этого ничто в приложении не сможет его одобрить или отклонить: запрос остаётся отложенным.',
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
