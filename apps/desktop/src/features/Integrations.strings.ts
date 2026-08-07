// Trilingual (en/hy/ru) copy for the Integrations feature. Every user-facing
// string local to Integrations.tsx lives here so all three languages stay in
// sync. Central shared strings continue to resolve through `t('...')`.
//
// `{name}` / `{n}` / `{cmd}` are placeholders replaced at the call site.
//
// A note on wording, because it is the point of this page: nothing here says
// "Connected" about a connector whose channel has never been contacted. The local
// record earns the word "Enabled"; only a probe that genuinely answered earns
// "Connected · verified". See integrationsModel.ts for why the two are different.
export const STR = {
  // ── Verdict labels (pill / accessible name) ────────────────────────────────
  verdictConnectedVerified: {
    en: 'Connected · verified',
    hy: 'Միացած · հաստատված',
    ru: 'Подключено · подтверждено',
  },
  verdictEnabledUnverified: {
    en: 'Enabled · unverified',
    hy: 'Միացված · չհաստատված',
    ru: 'Включено · не подтверждено',
  },
  verdictUnreachable: { en: 'Did not answer', hy: 'Չի պատասխանել', ru: 'Не ответил' },
  verdictFaulted: { en: 'Faulted', hy: 'Անսարք', ru: 'Сбой' },
  verdictNotEnabled: { en: 'Not enabled', hy: 'Միացված չէ', ru: 'Не включено' },
  verdictUnknown: { en: 'Unrecognized state', hy: 'Անհայտ վիճակ', ru: 'Неизвестное состояние' },

  // ── Verdict explanations (shown under the pill in the detail pane) ─────────
  explainConnectedVerified: {
    en: 'Enabled here, and a reachability check really ran and the channel answered.',
    hy: 'Միացված է այստեղ, և հասանելիության ստուգումն իրոք կատարվել է՝ ալիքը պատասխանել է։',
    ru: 'Включено здесь, и проверка доступности действительно выполнена — канал ответил.',
  },
  explainEnabledUnverified: {
    en: 'Enabled in this desktop’s own record. Nothing external has been contacted, so whether it actually works is unknown.',
    hy: 'Միացված է այս աշխատասեղանի սեփական գրառմամբ։ Ոչ մի արտաքին կապ չի հաստատվել, ուստի իրականում աշխատում է թե ոչ՝ հայտնի չէ։',
    ru: 'Включено в собственной записи этого компьютера. Внешнее соединение не устанавливалось, поэтому работает ли оно на самом деле — неизвестно.',
  },
  explainUnreachable: {
    en: 'Enabled here, but a reachability check ran and the channel did not answer.',
    hy: 'Միացված է այստեղ, բայց հասանելիության ստուգումը կատարվել է, և ալիքը չի պատասխանել։',
    ru: 'Включено здесь, но проверка доступности выполнена и канал не ответил.',
  },
  explainFaulted: {
    en: 'The store recorded a fault for this connector.',
    hy: 'Պահոցը այս միակցիչի համար սխալ է գրանցել։',
    ru: 'Хранилище записало сбой для этого коннектора.',
  },
  explainNotEnabled: {
    en: 'The owner has not enabled this connector.',
    hy: 'Տերը չի միացրել այս միակցիչը։',
    ru: 'Владелец не включил этот коннектор.',
  },
  explainUnknown: {
    en: 'The record carries a status this build does not recognize, so it is treated as not enabled.',
    hy: 'Գրառումը կրում է կարգավիճակ, որը այս տարբերակը չի ճանաչում, ուստի այն համարվում է չմիացված։',
    ru: 'Запись содержит статус, который эта сборка не распознаёт, поэтому он считается невключённым.',
  },

  // ── The four-fact ledger ───────────────────────────────────────────────────
  ledgerTitle: {
    en: 'What is and is not connected',
    hy: 'Ինչն է կապված և ինչը՝ ոչ',
    ru: 'Что подключено, а что нет',
  },
  factDeclaration: { en: 'Declaration', hy: 'Հայտարարում', ru: 'Объявление' },
  factDeclarationValue: {
    en: 'Declared in the desktop registry',
    hy: 'Հայտարարված է աշխատասեղանի ռեեստրում',
    ru: 'Объявлен в реестре компьютера',
  },
  factDeclarationNote: {
    en: 'A name and a provider. This is all a connector row is.',
    hy: 'Անուն և մատակարար։ Միակցիչի գրառումն ընդամենը սա է։',
    ru: 'Имя и поставщик. Это всё, чем является запись коннектора.',
  },
  factEnablement: { en: 'Local enablement', hy: 'Տեղական միացում', ru: 'Локальное включение' },
  factEnablementNote: {
    en: 'Written by this desktop into its own database. Writing it contacts no external service.',
    hy: 'Գրված է այս աշխատասեղանի կողմից՝ իր սեփական տվյալների բազայում։ Դա ոչ մի արտաքին ծառայության չի դիմում։',
    ru: 'Записано этим компьютером в собственную базу данных. Запись не обращается ни к какой внешней службе.',
  },
  factCredential: { en: 'Credential', hy: 'Հավատարմագիր', ru: 'Учётные данные' },
  factReachability: { en: 'Reachability', hy: 'Հասանելիություն', ru: 'Доступность' },

  // ── Enablement values ──────────────────────────────────────────────────────
  enablementEnabled: { en: 'Enabled', hy: 'Միացված', ru: 'Включено' },
  enablementNotEnabled: { en: 'Not enabled', hy: 'Միացված չէ', ru: 'Не включено' },
  enablementFaulted: { en: 'Fault recorded', hy: 'Գրանցված սխալ', ru: 'Записан сбой' },
  enablementUnknown: { en: 'Unrecognized', hy: 'Չճանաչված', ru: 'Не распознано' },

  // ── Credential custody values ──────────────────────────────────────────────
  credentialNoReference: {
    en: 'Not configured here — none referenced',
    hy: 'Այստեղ կարգավորված չէ — հղում չկա',
    ru: 'Здесь не настроено — ссылки нет',
  },
  credentialNoReferenceNote: {
    en: 'This desktop stores no external secret, and this connector record names no engine-held one either. Until the operator provisions a secret and the record references it, the connector is unconfigured.',
    hy: 'Այս աշխատասեղանը ոչ մի արտաքին գաղտնիք չի պահում, և այս միակցիչի գրառումը նույնպես չի նշում շարժիչում պահվող որևէ մեկը։ Քանի դեռ օպերատորը գաղտնիք չի տրամադրել և գրառումը չի հղում դրան, միակցիչը կարգավորված չէ։',
    ru: 'Этот компьютер не хранит внешних секретов, и запись коннектора не указывает ни на один секрет, хранимый движком. Пока оператор не предоставит секрет и запись не сошлётся на него, коннектор не настроен.',
  },
  credentialReferenced: {
    en: 'References an engine-held secret',
    hy: 'Հղում է շարժիչում պահվող գաղտնիքին',
    ru: 'Ссылается на секрет, хранимый движком',
  },
  credentialReferencedNote: {
    en: 'The record names where the secret is held. That is a reference, not proof the secret exists or is still valid — only a reachability check can show that.',
    hy: 'Գրառումը նշում է, թե որտեղ է պահվում գաղտնիքը։ Դա հղում է, ոչ թե ապացույց, որ գաղտնիքը գոյություն ունի կամ դեռ վավեր է — դա կարող է ցույց տալ միայն հասանելիության ստուգումը։',
    ru: 'Запись указывает, где хранится секрет. Это ссылка, а не доказательство того, что секрет существует или всё ещё действителен — это может показать только проверка доступности.',
  },

  // ── Reachability values ────────────────────────────────────────────────────
  reachUntested: { en: 'Never tested', hy: 'Երբեք չի ստուգվել', ru: 'Никогда не проверялось' },
  reachUntestedNote: {
    en: 'No reachability check has been run for this connector. Nothing here claims it works.',
    hy: 'Այս միակցիչի համար հասանելիության ստուգում չի կատարվել։ Այստեղ ոչինչ չի պնդում, որ այն աշխատում է։',
    ru: 'Проверка доступности для этого коннектора не запускалась. Здесь ничто не утверждает, что он работает.',
  },
  reachReachable: { en: 'Answered', hy: 'Պատասխանել է', ru: 'Ответил' },
  reachUnreachable: { en: 'Did not answer', hy: 'Չի պատասխանել', ru: 'Не ответил' },
  reachIndeterminate: {
    en: 'No answer obtained',
    hy: 'Պատասխան չի ստացվել',
    ru: 'Ответ не получен',
  },
  reachIndeterminateNote: {
    en: 'The check was attempted but produced no usable answer. That says nothing about the service — only that we failed to learn anything.',
    hy: 'Ստուգումը փորձվել է, բայց օգտագործելի պատասխան չի տվել։ Դա ոչինչ չի ասում ծառայության մասին — միայն այն, որ մենք ոչինչ չիմացանք։',
    ru: 'Проверка была предпринята, но не дала пригодного ответа. Это ничего не говорит о службе — только о том, что мы ничего не узнали.',
  },
  reachUnsupported: {
    en: 'Cannot be tested from this build',
    hy: 'Այս տարբերակից հնարավոր չէ ստուգել',
    ru: 'Невозможно проверить в этой сборке',
  },
  reachUnsupportedNote: {
    en: 'The desktop has no reachability command to call: `{cmd}` is neither implemented nor granted in the window capability set. This is a missing feature here, not a broken service there.',
    hy: 'Աշխատասեղանը չունի կանչելու հասանելիության հրաման՝ `{cmd}`-ը ո՛չ իրականացված է, ո՛չ թույլատրված պատուհանի capability-ների մեջ։ Սա այստեղի բացակայող հնարավորություն է, ոչ թե այնտեղի խափանված ծառայություն։',
    ru: 'У компьютера нет команды проверки доступности: `{cmd}` не реализована и не разрешена в наборе capability окна. Это отсутствующая возможность здесь, а не сломанная служба там.',
  },
  probeReason: { en: 'Backend said', hy: 'Backend-ն ասաց', ru: 'Backend ответил' },
  lastAttempt: { en: 'Last attempt', hy: 'Վերջին փորձ', ru: 'Последняя попытка' },
  testReachability: {
    en: 'Test reachability',
    hy: 'Ստուգել հասանելիությունը',
    ru: 'Проверить доступность',
  },
  testing: { en: 'Testing…', hy: 'Ստուգվում է…', ru: 'Проверка…' },
  testNote: {
    en: 'Asks the governed backend to contact the connector and reports exactly what came back — including "I could not ask".',
    hy: 'Խնդրում է կառավարվող backend-ին կապվել միակցիչի հետ և հաղորդում է ճիշտ այն, ինչ վերադարձել է՝ ներառյալ «չկարողացա հարցնել»-ը։',
    ru: 'Просит управляемый backend связаться с коннектором и сообщает ровно то, что вернулось — включая «я не смог спросить».',
  },

  // ── Enable / disable action ────────────────────────────────────────────────
  enableAction: { en: 'Enable', hy: 'Միացնել', ru: 'Включить' },
  disableAction: { en: 'Disable', hy: 'Անջատել', ru: 'Отключить' },
  reconnect: { en: 'Re-enable', hy: 'Վերամիացնել', ru: 'Включить снова' },
  enableActionNote: {
    en: 'Records your intent in the local registry. It does not contact {name} and stores no credential.',
    hy: 'Գրանցում է Ձեր մտադրությունը տեղական ռեեստրում։ Այն չի կապվում {name}-ի հետ և հավատարմագիր չի պահում։',
    ru: 'Записывает ваше намерение в локальный реестр. Не связывается с {name} и не хранит учётные данные.',
  },
  enabledNamed: {
    en: '{name} enabled locally — not yet verified',
    hy: '{name}՝ միացված է տեղականորեն — դեռ չհաստատված',
    ru: '{name} включён локально — ещё не подтверждён',
  },
  disabledNamed: {
    en: '{name} disabled',
    hy: '{name}՝ անջատված է',
    ru: '{name} отключён',
  },
  blocked: { en: 'Blocked', hy: 'Արգելափակված', ru: 'Заблокировано' },

  // ── Detail head ────────────────────────────────────────────────────────────
  channel: { en: 'CHANNEL', hy: 'ԱԼԻՔ', ru: 'КАНАЛ' },

  // ── Fault state ────────────────────────────────────────────────────────────
  connectorUnhealthy: {
    en: 'Fault recorded for this connector',
    hy: 'Այս միակցիչի համար գրանցված է սխալ',
    ru: 'Для этого коннектора записан сбой',
  },
  connectorUnhealthyBody: {
    en: 'The local record holds status "error". Re-enabling only rewrites that record — it does not repair or contact anything; provisioning is done through the engine / operator.',
    hy: 'Տեղական գրառումը պահում է «error» կարգավիճակը։ Վերամիացումը միայն վերագրում է այդ գրառումը — այն ոչինչ չի վերանորոգում կամ կապվում. տրամադրումը կատարվում է շարժիչի/օպերատորի միջոցով։',
    ru: 'Локальная запись хранит статус «error». Повторное включение лишь перезаписывает эту запись — оно ничего не чинит и ни с чем не связывается; предоставление выполняется через движок / оператора.',
  },

  // ── Configuration section ──────────────────────────────────────────────────
  configuration: { en: 'Record', hy: 'Գրառում', ru: 'Запись' },
  provider: { en: 'Provider', hy: 'Մատակարար', ru: 'Поставщик' },
  recordStatus: { en: 'Stored status', hy: 'Պահված կարգավիճակ', ru: 'Сохранённый статус' },
  added: { en: 'Declared', hy: 'Հայտարարված', ru: 'Объявлен' },
  recordUpdated: {
    en: 'Record last written',
    hy: 'Գրառումը վերջին անգամ գրվել է',
    ru: 'Запись изменена',
  },

  // ── Authentication section ─────────────────────────────────────────────────
  authentication: { en: 'Authentication', hy: 'Նույնականացում', ru: 'Аутентификация' },
  handoff: {
    en: 'Handoff → engine / operator',
    hy: 'Փոխանցում → շարժիչ/օպերատոր',
    ru: 'Передача → движок / оператор',
  },
  authBody: {
    en: 'Secrets are held by the engine / operator — this desktop stores none, and this page never asks you for one. Enabling a connector hands authentication off; no credential is persisted here.',
    hy: 'Գաղտնիքները պահվում են շարժիչի/օպերատորի կողմից — այս աշխատասեղանը ոչ մեկը չի պահում, և այս էջը երբեք չի հարցնում Ձեզանից։ Միակցիչը միացնելը փոխանցում է նույնականացումը. այստեղ ոչ մի հավատարմագիր չի պահվում։',
    ru: 'Секреты хранятся движком / оператором — этот компьютер не хранит ни одного, и эта страница никогда их не запрашивает. Включение коннектора передаёт аутентификацию; здесь не сохраняются учётные данные.',
  },

  // ── Triggers & sinks section ───────────────────────────────────────────────
  triggersSinks: {
    en: 'Triggers & sinks',
    hy: 'Հրահրիչներ և ընդունիչներ',
    ru: 'Триггеры и приёмники',
  },
  triggersSinksTitle: {
    en: 'Inbound triggers & outbound sinks',
    hy: 'Մուտքային հրահրիչներ և ելքային ընդունիչներ',
    ru: 'Входящие триггеры и исходящие приёмники',
  },
  mappingNotProvisioned: {
    en: 'Mapping not provisioned',
    hy: 'Կապակցումը տրամադրված չէ',
    ru: 'Сопоставление не предоставлено',
  },
  mappingBody: {
    en: 'Trigger and sink mapping is not provisioned on this desktop. It stays blocked so an inbound event can never start ungoverned work and a sink can only send verified results.',
    hy: 'Հրահրիչ–ընդունիչ կապակցումն այս աշխատասեղանում տրամադրված չէ։ Այն արգելափակված է մնում, որպեսզի մուտքային իրադարձությունը երբեք չմեկնարկի չկառավարվող աշխատանք, իսկ ընդունիչն ուղարկի միայն ստուգված արդյունքներ։',
    ru: 'Сопоставление триггеров и приёмников не предоставлено на этом компьютере. Оно остаётся заблокированным, чтобы входящее событие никогда не запускало неуправляемую работу, а приёмник отправлял только проверенные результаты.',
  },
  howToProvision: { en: 'How to provision', hy: 'Ինչպես տրամադրել', ru: 'Как предоставить' },
  provisionStep1: {
    en: 'Ask the operator to register the connector secret in the engine.',
    hy: 'Խնդրե՛ք օպերատորին գրանցել միակցիչի գաղտնիքը շարժիչում։',
    ru: 'Попросите оператора зарегистрировать секрет коннектора в движке.',
  },
  provisionStep2: {
    en: 'Map inbound events to a governed task class (receipt required).',
    hy: 'Կապե՛ք մուտքային իրադարձությունները կառավարվող առաջադրանքի դասին (անհրաժեշտ է անդորրագիր)։',
    ru: 'Сопоставьте входящие события управляемому классу задач (требуется квитанция).',
  },
  provisionStep3: {
    en: 'Map an outbound sink that sends only verified results.',
    hy: 'Կապե՛ք ելքային ընդունիչ, որն ուղարկում է միայն ստուգված արդյունքներ։',
    ru: 'Сопоставьте исходящий приёмник, который отправляет только проверенные результаты.',
  },

  // ── Header ─────────────────────────────────────────────────────────────────
  headerEyebrow: {
    en: 'INTEGRATIONS · SYSTEM MAP',
    hy: 'ԻՆՏԵԳՐՈՒՄՆԵՐ · SYSTEM CONSTELLATION',
    ru: 'ИНТЕГРАЦИИ · КАРТА СИСТЕМЫ',
  },
  headerVerified: {
    en: '{n} verified',
    hy: '{n} հաստատված',
    ru: '{n} подтверждено',
  },
  headerEnabled: {
    en: '{n} enabled',
    hy: '{n} միացված',
    ru: '{n} включено',
  },

  // ── Hero telemetry ─────────────────────────────────────────────────────────
  integrationOverview: {
    en: 'Integration overview',
    hy: 'Ինտեգրումների ընդհանուր պատկեր',
    ru: 'Обзор интеграций',
  },
  statDeclared: { en: 'declared', hy: 'հայտարարված', ru: 'объявлено' },
  statEnabled: { en: 'enabled locally', hy: 'միացված տեղականորեն', ru: 'включено локально' },
  statVerified: {
    en: 'verified reachable',
    hy: 'հաստատված հասանելի',
    ru: 'подтверждённо доступно',
  },
  statFaulted: { en: 'faulted', hy: 'անսարք', ru: 'сбой' },
  statUntested: { en: 'never tested', hy: 'չստուգված', ru: 'не проверено' },
  stateScale: {
    en: 'Enabled counts what this desktop recorded. Verified counts what a reachability check actually confirmed — those are different numbers, and only the second one means a channel works.',
    hy: '«Միացված»-ը հաշվում է այն, ինչ գրանցել է այս աշխատասեղանը։ «Հաստատված»-ը հաշվում է այն, ինչ իրոք հաստատել է հասանելիության ստուգումը — սրանք տարբեր թվեր են, և միայն երկրորդն է նշանակում, որ ալիքն աշխատում է։',
    ru: '«Включено» считает то, что записал этот компьютер. «Подтверждено» считает то, что действительно подтвердила проверка доступности — это разные числа, и только второе означает, что канал работает.',
  },

  // ── Build-capability banner ────────────────────────────────────────────────
  capTitle: {
    en: 'Reachability testing is not wired in this build',
    hy: 'Հասանելիության ստուգումն այս տարբերակում միացված չէ',
    ru: 'Проверка доступности не подключена в этой сборке',
  },
  capBody: {
    en: 'The desktop exposes exactly two integration commands — list and set-status — so it can declare and enable connectors but cannot contact one. Until `{probe}` ships and is granted, every connector stays honestly unverified.',
    hy: 'Աշխատասեղանը տրամադրում է ուղիղ երկու ինտեգրման հրաման՝ list և set-status, ուստի կարող է հայտարարել և միացնել միակցիչներ, բայց չի կարող կապվել դրանցից որևէ մեկի հետ։ Քանի դեռ `{probe}`-ը չի ավելացվել և թույլատրվել, ամեն միակցիչ ազնվորեն մնում է չհաստատված։',
    ru: 'Компьютер предоставляет ровно две команды интеграций — list и set-status, поэтому он может объявлять и включать коннекторы, но не может связаться ни с одним. Пока `{probe}` не появится и не будет разрешена, каждый коннектор честно остаётся неподтверждённым.',
  },

  // ── Declare a connector ────────────────────────────────────────────────────
  declareTitle: { en: 'Declare a connector', hy: 'Հայտարարել միակցիչ', ru: 'Объявить коннектор' },
  declareBody: {
    en: 'Declares a name and a provider — never a credential. A new connector starts not enabled, unconfigured and untested.',
    hy: 'Հայտարարում է անուն և մատակարար — երբեք հավատարմագիր։ Նոր միակցիչը սկսում է որպես չմիացված, չկարգավորված և չստուգված։',
    ru: 'Объявляет имя и поставщика — никогда учётные данные. Новый коннектор начинает как невключённый, ненастроенный и непроверенный.',
  },
  declareName: { en: 'Name', hy: 'Անուն', ru: 'Имя' },
  declareNamePlaceholder: { en: 'GitHub', hy: 'GitHub', ru: 'GitHub' },
  declareProvider: { en: 'Provider', hy: 'Մատակարար', ru: 'Поставщик' },
  declareProviderPlaceholder: { en: 'github', hy: 'github', ru: 'github' },
  declareSubmit: { en: 'Declare', hy: 'Հայտարարել', ru: 'Объявить' },
  declaring: { en: 'Declaring…', hy: 'Հայտարարվում է…', ru: 'Объявление…' },
  declareOpen: { en: 'Declare a connector…', hy: 'Հայտարարել միակցիչ…', ru: 'Объявить коннектор…' },
  declareCancel: { en: 'Cancel', hy: 'Չեղարկել', ru: 'Отмена' },
  declaredNamed: {
    en: '{name} declared — not enabled, unconfigured, untested',
    hy: '{name}՝ հայտարարված — չմիացված, չկարգավորված, չստուգված',
    ru: '{name} объявлен — не включён, не настроен, не проверен',
  },
  declareUnsupported: {
    en: 'This build cannot declare connectors',
    hy: 'Այս տարբերակը չի կարող միակցիչներ հայտարարել',
    ru: 'Эта сборка не может объявлять коннекторы',
  },
  declareUnsupportedBody: {
    en: 'The registry is read-plus-status-only here: `{cmd}` is not exposed as a command and not granted in the window capability set, so the desktop cannot add a row. The store already supports it — the operator needs to expose and grant it.',
    hy: 'Ռեեստրն այստեղ միայն կարդալու և կարգավիճակ փոխելու համար է՝ `{cmd}`-ը որպես հրաման հասանելի չէ և թույլատրված չէ պատուհանի capability-ների մեջ, ուստի աշխատասեղանը չի կարող տող ավելացնել։ Պահոցն արդեն աջակցում է դրան — օպերատորը պետք է բացի և թույլատրի այն։',
    ru: 'Реестр здесь доступен только для чтения и смены статуса: `{cmd}` не объявлена как команда и не разрешена в наборе capability окна, поэтому компьютер не может добавить строку. Хранилище это уже поддерживает — оператору нужно объявить и разрешить команду.',
  },
  declareRefused: { en: 'Declaration refused', hy: 'Հայտարարումը մերժվեց', ru: 'Объявление отклонено' },

  // ── Registry / catalog ─────────────────────────────────────────────────────
  connectorCatalog: { en: 'Connector catalog', hy: 'Միակցիչների կատալոգ', ru: 'Каталог коннекторов' },
  connectionRegistry: { en: 'Connection registry', hy: 'Միացման ռեեստր', ru: 'Реестр подключений' },
  selectRowHint: {
    en: 'Select a row to inspect its channel.',
    hy: 'ընտրիր տողը՝ մանրամասները բացելու համար',
    ru: 'Выберите строку, чтобы просмотреть её канал.',
  },
  searchPlaceholder: {
    en: 'Search catalog  (/)',
    hy: 'Փնտրել կատալոգը  (/)',
    ru: 'Поиск в каталоге  (/)',
  },
  searchAria: {
    en: 'Search connector catalog',
    hy: 'Փնտրել միակցիչների կատալոգում',
    ru: 'Поиск в каталоге коннекторов',
  },
  noIntegrations: { en: 'No integrations', hy: 'Ինտեգրումներ չկան', ru: 'Нет интеграций' },
  noIntegrationsHint: {
    en: 'Declare a connector to start. Declaring records a name, not a credential.',
    hy: 'Սկսելու համար հայտարարե՛ք միակցիչ։ Հայտարարելը գրանցում է անուն, ոչ թե հավատարմագիր։',
    ru: 'Объявите коннектор, чтобы начать. Объявление записывает имя, а не учётные данные.',
  },
  noMatches: { en: 'No matches', hy: 'Համընկնումներ չկան', ru: 'Нет совпадений' },
  noMatchesHint: {
    en: 'No connector matches your search.',
    hy: 'Ձեր որոնմանը համապատասխան միակցիչ չկա։',
    ru: 'Ни один коннектор не соответствует вашему запросу.',
  },
  groupEnabled: { en: 'Enabled', hy: 'Միացված', ru: 'Включённые' },
  enabledConnectors: {
    en: 'Enabled connectors',
    hy: 'Միացված միակցիչներ',
    ru: 'Включённые коннекторы',
  },
  groupNotEnabled: { en: 'Not enabled', hy: 'Միացված չէ', ru: 'Не включённые' },
  notEnabledConnectors: {
    en: 'Connectors that are not enabled',
    hy: 'Չմիացված միակցիչներ',
    ru: 'Невключённые коннекторы',
  },

  // ── Detail empty state ─────────────────────────────────────────────────────
  selectConnector: { en: 'Select a connector', hy: 'Ընտրե՛ք միակցիչ', ru: 'Выберите коннектор' },
  selectConnectorHint: {
    en: 'Choose a connector to see its record, whether a credential is configured, whether anything has ever been contacted, and its trigger / sink mapping.',
    hy: 'Ընտրե՛ք միակցիչ՝ տեսնելու դրա գրառումը, արդյոք հավատարմագիրը կարգավորված է, արդյոք երբևէ կապ է հաստատվել, և դրա հրահրիչ/ընդունիչ կապակցումը։',
    ru: 'Выберите коннектор, чтобы увидеть его запись, настроены ли учётные данные, устанавливалась ли когда-либо связь, и сопоставление триггеров / приёмников.',
  },
  connectorDetail: { en: 'Connector detail', hy: 'Միակցիչի մանրամասներ', ru: 'Детали коннектора' },
} as const;
