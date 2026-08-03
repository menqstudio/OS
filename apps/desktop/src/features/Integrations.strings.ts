// Trilingual (en/hy/ru) copy for the Integrations feature. Every user-facing
// string local to Integrations.tsx lives here so all three languages stay in
// sync. Central shared strings continue to resolve through `t('...')`.
//
// `{name}` is a placeholder replaced at the call site (connector name).
export const STR = {
  // ── Health labels (pill / accessible name) ─────────────────────────────────
  healthConnected: { en: 'Connected', hy: 'Միացած', ru: 'Подключено' },
  healthUnhealthy: { en: 'Unhealthy', hy: 'Անսարք', ru: 'Неисправно' },
  healthDisconnected: { en: 'Disconnected', hy: 'Անջատված', ru: 'Отключено' },

  // ── Connect / disconnect announcements (live region) ───────────────────────
  connectedNamed: {
    en: '{name} connected',
    hy: '{name}՝ միացված է',
    ru: '{name} подключён',
  },
  disconnectedNamed: {
    en: '{name} disconnected',
    hy: '{name}՝ անջատված է',
    ru: '{name} отключён',
  },
  blocked: { en: 'Blocked', hy: 'Արգելափակված', ru: 'Заблокировано' },

  // ── Detail head ────────────────────────────────────────────────────────────
  channel: { en: 'CHANNEL', hy: 'ԱԼԻՔ', ru: 'КАНАЛ' },

  // ── Error state ────────────────────────────────────────────────────────────
  connectorUnhealthy: {
    en: 'Connector unhealthy',
    hy: 'Միակցիչն անսարք է',
    ru: 'Коннектор неисправен',
  },
  connectorUnhealthyBody: {
    en: 'This connector reported an error on its last health check. Reconnect to run its check again, or provision it through the engine / operator.',
    hy: 'Այս միակցիչը վերջին ստուգման ժամանակ սխալ է հաղորդել։ Վերամիացրե՛ք ստուգումը կրկնելու համար, կամ տրամադրե՛ք այն շարժիչի/օպերատորի միջոցով։',
    ru: 'Этот коннектор сообщил об ошибке при последней проверке состояния. Переподключите его, чтобы запустить проверку заново, или предоставьте его через движок / оператора.',
  },
  reconnect: { en: 'Reconnect', hy: 'Վերամիացնել', ru: 'Переподключить' },

  // ── Configuration section ──────────────────────────────────────────────────
  configuration: { en: 'Configuration', hy: 'Կարգավորում', ru: 'Настройка' },
  provider: { en: 'Provider', hy: 'Մատակարար', ru: 'Поставщик' },
  status: { en: 'Status', hy: 'Կարգավիճակ', ru: 'Статус' },
  added: { en: 'Added', hy: 'Ավելացված', ru: 'Добавлено' },
  lastChecked: { en: 'Last checked', hy: 'Վերջին ստուգում', ru: 'Последняя проверка' },

  // ── Authentication section ─────────────────────────────────────────────────
  authentication: { en: 'Authentication', hy: 'Նույնականացում', ru: 'Аутентификация' },
  handoff: {
    en: 'Handoff → engine / operator',
    hy: 'Փոխանցում → շարժիչ/օպերատոր',
    ru: 'Передача → движок / оператор',
  },
  authBody: {
    en: 'Secrets are held by the engine / operator — this desktop stores none. Connecting hands authentication off to the governed engine; no credential is persisted here.',
    hy: 'Գաղտնիքները պահվում են շարժիչի/օպերատորի կողմից — այս աշխատասեղանը ոչ մեկը չի պահում։ Միանալիս նույնականացումը փոխանցվում է կառավարվող շարժիչին. այստեղ ոչ մի հավատարմագիր չի պահվում։',
    ru: 'Секреты хранятся движком / оператором — этот компьютер не хранит ни одного. При подключении аутентификация передаётся управляемому движку; здесь не сохраняются учётные данные.',
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
  connectedLower: { en: 'connected', hy: 'միացած', ru: 'подключено' },

  // ── Hero telemetry ─────────────────────────────────────────────────────────
  integrationOverview: {
    en: 'Integration overview',
    hy: 'Ինտեգրումների ընդհանուր պատկեր',
    ru: 'Обзор интеграций',
  },
  integrationsUnit: { en: 'integrations', hy: 'ինտեգրում', ru: 'интеграций' },
  activeChannel: { en: 'active channel', hy: 'ակտիվ ալիք', ru: 'активный канал' },
  attention: { en: 'attention', hy: 'ուշադրություն', ru: 'внимание' },
  stateScale: {
    en: 'State is read from each connector — live only when genuinely connected.',
    hy: 'Վիճակը կարդացվում է յուրաքանչյուր միակցիչից՝ միացած է միայն իրապես կապվածը։',
    ru: 'Состояние считывается с каждого коннектора — активно только при действительном подключении.',
  },

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
    en: 'Connect a governed service to start.',
    hy: 'Սկսելու համար միացրե՛ք կառավարվող ծառայություն։',
    ru: 'Подключите управляемую службу, чтобы начать.',
  },
  noMatches: { en: 'No matches', hy: 'Համընկնումներ չկան', ru: 'Нет совпадений' },
  noMatchesHint: {
    en: 'No connector matches your search.',
    hy: 'Ձեր որոնմանը համապատասխան միակցիչ չկա։',
    ru: 'Ни один коннектор не соответствует вашему запросу.',
  },
  groupConnected: { en: 'Connected', hy: 'Միացված', ru: 'Подключённые' },
  connectedConnectors: {
    en: 'Connected connectors',
    hy: 'Միացված միակցիչներ',
    ru: 'Подключённые коннекторы',
  },
  groupAvailable: { en: 'Available', hy: 'Հասանելի', ru: 'Доступные' },
  availableConnectors: {
    en: 'Available connectors',
    hy: 'Հասանելի միակցիչներ',
    ru: 'Доступные коннекторы',
  },

  // ── Detail empty state ─────────────────────────────────────────────────────
  selectConnector: { en: 'Select a connector', hy: 'Ընտրե՛ք միակցիչ', ru: 'Выберите коннектор' },
  selectConnectorHint: {
    en: 'Choose a connector to view its configuration, health, authentication handoff, and trigger / sink mapping.',
    hy: 'Ընտրե՛ք միակցիչ՝ դրա կարգավորումը, առողջությունը, նույնականացման փոխանցումը և հրահրիչ/ընդունիչ կապակցումը տեսնելու համար։',
    ru: 'Выберите коннектор, чтобы просмотреть его настройку, состояние, передачу аутентификации и сопоставление триггеров / приёмников.',
  },
  connectorDetail: { en: 'Connector detail', hy: 'Միակցիչի մանրամասներ', ru: 'Детали коннектора' },
} as const;
