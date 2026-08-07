// Bridge panel strings (EN + HY + RU), per-feature — the pattern used by every other
// view here. Nothing is added to `i18n/en.ts` / `hy.ts` / `ru.ts`.
//
// HONESTY RULE for every string in this file: none of them may assert that anything was
// verified, mirrored, connected, or refused. Each one names exactly one state the panel
// can actually establish from a real reply, and the "we do not know" states are written
// as absences, not as reassurances.
export const STR = {
  // --- Panel head ---
  panelEyebrow: {
    en: 'BRIDGE · RENDERER → BROKER → ENGINE',
    hy: 'ԿԱՄՈՒՐՋ · RENDERER → BROKER → ENGINE',
    ru: 'МОСТ · RENDERER → BROKER → ENGINE',
  },
  panelTitle: { en: 'Governed bridge', hy: 'Կառավարվող կամուրջ', ru: 'Управляемый мост' },
  panelIntro: {
    en: 'This panel shows only what the desktop actually received. The renderer holds no key, '
      + 'signs nothing, and cannot verify anything on its own — a verdict exists only when the '
      + 'broker or the engine produced one.',
    hy: 'Այս վահանակը ցույց ա տալիս միայն այն, ինչ desktop-ը իրոք ստացել ա։ Renderer-ը բանալի չի '
      + 'պահում, ոչինչ չի ստորագրում ու ինքնուրույն ոչինչ չի կարող հաստատել — վճիռը գոյություն ունի '
      + 'միայն երբ broker-ը կամ engine-ը այն արտադրել ա։',
    ru: 'Эта панель показывает только то, что десктоп действительно получил. Renderer не хранит '
      + 'ключей, ничего не подписывает и сам ничего не может подтвердить — вердикт существует, '
      + 'только если его вынес брокер или движок.',
  },
  rendererCannotVerify: {
    en: 'Renderer verifies nothing',
    hy: 'Renderer-ը ոչինչ չի հաստատում',
    ru: 'Renderer ничего не подтверждает',
  },

  // --- Governance-mirror rows ---
  mirrorsTitle: {
    en: 'Engine governance mirrors (read-only)',
    hy: 'Engine-ի կառավարման արտացոլումներ (միայն ընթերցում)',
    ru: 'Зеркала управления движка (только чтение)',
  },
  surfaceLedger: {
    en: 'Engine decision ledger',
    hy: 'Engine-ի որոշումների մատյան',
    ru: 'Журнал решений движка',
  },
  surfaceLedgerNote: {
    en: 'The engine’s own ledger, mirrored through the sidecar. Not the local decision table '
      + 'shown above — that one never leaves this machine.',
    hy: 'Engine-ի սեփական մատյանը՝ արտացոլված sidecar-ով։ Սա վերևի լոկալ աղյուսակը չի — '
      + 'դա երբեք չի հեռանում այս մեքենայից։',
    ru: 'Собственный журнал движка, отзеркаленный через sidecar. Это не локальная таблица выше — '
      + 'та никогда не покидает эту машину.',
  },
  surfaceVerdicts: {
    en: 'Independent-verifier verdicts',
    hy: 'Անկախ ստուգողի վճիռներ',
    ru: 'Вердикты независимого верификатора',
  },
  surfaceVerdictsNote: {
    en: 'Verifier receipts for the selected decision. The desktop shows them; it never issues one.',
    hy: 'Ընտրված որոշման ստուգողի ստացականները։ Desktop-ը ցուցադրում ա, բայց երբեք չի թողարկում։',
    ru: 'Квитанции верификатора по выбранному решению. Десктоп показывает их, но никогда не выдаёт.',
  },
  surfaceVerdictsNoSelection: {
    en: 'Reading every verdict the engine will mirror — no decision is selected, so this is not '
      + 'filtered to one.',
    hy: 'Կարդում ենք բոլոր վճիռները, որ engine-ը կարտացոլի — որոշում ընտրված չի, ուստի ֆիլտր չկա։',
    ru: 'Читаем все вердикты, которые отзеркалит движок — решение не выбрано, фильтра нет.',
  },

  stateReading: { en: 'reading…', hy: 'կարդում ենք…', ru: 'читаем…' },
  // An `ok` read carrying records. Prefix before the count: `${stateRecords}${n}`.
  stateRecords: { en: 'records · ', hy: 'գրառում · ', ru: 'записей · ' },
  // An `ok` read carrying NOTHING. This is the absence of data, never a satisfied surface.
  stateEmpty: {
    en: 'answered · nothing to mirror',
    hy: 'պատասխանեց · արտացոլելու բան չկա',
    ru: 'ответило · нечего отзеркаливать',
  },
  stateBlocked: { en: 'refused by the engine', hy: 'engine-ը մերժեց', ru: 'движок отказал' },
  stateUnreachable: { en: 'not reached', hy: 'չհասանք', ru: 'не достигнуто' },
  unverifiedOrigin: {
    en: 'ORIGIN NOT AUTHENTICATED',
    hy: 'ԾԱԳՈՒՄԸ ՀԱՍՏԱՏՎԱԾ ՉԷ',
    ru: 'ПРОИСХОЖДЕНИЕ НЕ ПОДТВЕРЖДЕНО',
  },
  unverifiedOriginBody: {
    en: 'These records were checked for shape only. Nothing here carries a signature the desktop '
      + 'could check, so they are mirror data, not proof.',
    hy: 'Այս գրառումները ստուգվել են միայն ձևով։ Ոչ մեկը չի կրում ստորագրություն, որ desktop-ը '
      + 'կարողանար ստուգել, ուստի սրանք արտացոլման տվյալ են, ոչ ապացույց։',
    ru: 'Эти записи проверены только по форме. Ни одна не содержит подписи, которую десктоп мог бы '
      + 'проверить, поэтому это зеркальные данные, а не доказательство.',
  },
  // Prefix before a machine reason: `${whyPrefix}${reason}`.
  whyPrefix: { en: 'why: ', hy: 'ինչու՝ ', ru: 'почему: ' },

  // --- Governed turn ---
  turnTitle: {
    en: 'Governed turn (renderer → broker)',
    hy: 'Կառավարվող քայլ (renderer → broker)',
    ru: 'Управляемый ход (renderer → broker)',
  },
  turnIntro: {
    en: 'The renderer can send the broker exactly one closed frame — a conversation id, an optional '
      + 'agent name and a fresh request id. It supplies no prompt, no history and no configuration, '
      + 'and it cannot mark a reply verified: only a broker-signed committed frame can.',
    hy: 'Renderer-ը կարա broker-ին ուղարկի ուղիղ մեկ փակ frame՝ conversation id, ըստ ցանկության '
      + 'agent-ի անուն ու նոր request id։ Ոչ prompt, ոչ history, ոչ կարգավորում չի տալիս ու չի կարա '
      + 'պատասխանը նշի որպես ստուգված — դա կարա միայն broker-ի committed frame-ը։',
    ru: 'Renderer может отправить брокеру ровно один закрытый кадр — id разговора, необязательное имя '
      + 'агента и новый id запроса. Он не передаёт ни промпта, ни истории, ни конфигурации и не может '
      + 'пометить ответ проверенным: это может только committed-кадр от брокера.',
  },
  turnConversation: { en: 'Conversation', hy: 'Զրույց', ru: 'Разговор' },
  turnNoConversations: {
    en: 'No conversation is available to address, so there is nothing to send.',
    hy: 'Հասցեագրելու զրույց չկա, ուստի ուղարկելու բան չկա։',
    ru: 'Нет разговора, к которому можно обратиться, значит и отправлять нечего.',
  },
  turnRun: { en: 'Send one governed turn', hy: 'Ուղարկել մեկ կառավարվող քայլ', ru: 'Отправить один управляемый ход' },
  turnRunning: { en: 'Waiting for the broker…', hy: 'Սպասում ենք broker-ին…', ru: 'Ждём брокера…' },
  turnIdle: {
    en: 'Nothing has been sent yet. Nothing on this screen claims a broker state until one replies.',
    hy: 'Դեռ ոչինչ չի ուղարկվել։ Այս էկրանին ոչինչ broker-ի վիճակ չի հայտարարում, մինչև որ պատասխան գա։',
    ru: 'Пока ничего не отправлено. Ничто на этом экране не заявляет о состоянии брокера, пока он не ответит.',
  },

  // The three outcomes. Each says who decided — or that nobody did.
  outcomeVerified: { en: 'Verified by the broker', hy: 'Broker-ը հաստատեց', ru: 'Подтверждено брокером' },
  outcomeVerifiedBody: {
    en: 'The broker committed this turn and marked it trusted_verified. The message below is the '
      + 'broker’s own projection, shown read-only.',
    hy: 'Broker-ը հաստատեց այս քայլը և նշեց trusted_verified։ Ներքևի հաղորդագրությունը broker-ի '
      + 'սեփական պրոյեկցիան ա՝ միայն ընթերցման։',
    ru: 'Брокер зафиксировал этот ход и пометил его trusted_verified. Сообщение ниже — собственная '
      + 'проекция брокера, показанная только для чтения.',
  },
  outcomeBlocked: { en: 'The broker refused this turn', hy: 'Broker-ը մերժեց այս քայլը', ru: 'Брокер отклонил этот ход' },
  outcomeBlockedBody: {
    en: 'The broker was reached and it decided: no message was produced. This is a real verdict.',
    hy: 'Broker-ին հասանք և նա որոշեց՝ հաղորդագրություն չի ստեղծվել։ Սա իրական վճիռ ա։',
    ru: 'Брокер был достигнут и вынес решение: сообщение не создано. Это настоящий вердикт.',
  },
  outcomeUnavailable: { en: 'No verdict exists', hy: 'Վճիռ գոյություն չունի', ru: 'Вердикта не существует' },
  outcomeUnavailableBody: {
    en: 'No broker allowed or refused this turn. Do not read this as a refusal — it is the absence '
      + 'of an answer, which is a different fact.',
    hy: 'Ոչ մի broker չի թույլատրել կամ մերժել այս քայլը։ Սա մերժում չի — սա պատասխանի բացակայությունն ա, '
      + 'ինչը այլ փաստ ա։',
    ru: 'Ни один брокер не разрешил и не отклонил этот ход. Не читайте это как отказ — это отсутствие '
      + 'ответа, а это другой факт.',
  },
  // Prefix before the closed broker reason / non-decision kind.
  reasonLabel: { en: 'broker reason: ', hy: 'broker-ի պատճառ՝ ', ru: 'причина брокера: ' },
  kindLabel: { en: 'kind: ', hy: 'տեսակ՝ ', ru: 'вид: ' },
  turnIdLabel: { en: 'broker turn: ', hy: 'broker-ի քայլ՝ ', ru: 'ход брокера: ' },

  // Plain-language gloss of each non-decision. These describe the transport, never a verdict.
  nd_broker_unsupported_platform: {
    en: 'This host has no governed-broker transport compiled in, so there was nothing to contact.',
    hy: 'Այս հոսթում governed-broker transport չկա կոմպիլացված, ուստի կապվելու բան չկար։',
    ru: 'На этом хосте не собран транспорт governed-broker, поэтому связываться было не с чем.',
  },
  nd_broker_unavailable: {
    en: 'A transport exists here, but the connection to the broker could not be established.',
    hy: 'Transport-ը կա, բայց broker-ի հետ կապը չհաստատվեց։',
    ru: 'Транспорт здесь есть, но соединение с брокером установить не удалось.',
  },
  nd_broker_transport_failed: {
    en: 'The broker was connected to, but the framed exchange failed before any reply arrived.',
    hy: 'Broker-ին միացանք, բայց frame-երի փոխանակումը ձախողվեց մինչև որևէ պատասխան։',
    ru: 'К брокеру подключились, но обмен кадрами сорвался до получения ответа.',
  },
  nd_malformed_request: {
    en: 'The request frame could not be built, so it never left this machine.',
    hy: 'Request frame-ը չկառուցվեց, ուստի երբեք չլքեց այս մեքենան։',
    ru: 'Кадр запроса не удалось построить, поэтому он не покинул эту машину.',
  },
  nd_malformed_broker_reply: {
    en: 'Something answered, but the reply is not a well-formed result frame — so it is refused '
      + 'rather than interpreted.',
    hy: 'Ինչ-որ բան պատասխանեց, բայց պատասխանը վավեր result frame չի — ուստի մերժվում ա, ոչ մեկնաբանվում։',
    ru: 'Что-то ответило, но ответ не является корректным кадром результата — поэтому он отклонён, '
      + 'а не интерпретирован.',
  },
  nd_no_desktop_backend: {
    en: 'There is no desktop backend here, so the governed proxy command does not exist at all.',
    hy: 'Այստեղ desktop backend չկա, ուստի governed proxy հրամանն ընդհանրապես գոյություն չունի։',
    ru: 'Здесь нет десктопного бэкенда, поэтому команды governed-прокси вообще не существует.',
  },
  nd_unclassified_transport_failure: {
    en: 'The transport failed with something outside the known taxonomy. It is reported verbatim '
      + 'rather than forced into a category it did not report.',
    hy: 'Transport-ը ձախողվեց հայտնի դասակարգումից դուրս մի բանով։ Հաղորդվում ա բառացի, ոչ թե խցկվում '
      + 'մի կատեգորիա, որը ինքը չի հայտնել։',
    ru: 'Транспорт отказал с чем-то за пределами известной таксономии. Сообщается дословно, а не '
      + 'втискивается в категорию, о которой он не заявлял.',
  },
} as const;
