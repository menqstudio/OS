// Trilingual copy for the Conversations (Chat / Group Chat) view — the context
// rail and the few inline status words the central catalog does not carry. Every
// visible string lives here under a short camelCase key with a real en / hy / ru
// value, indexed via the L() helper in Conversations.tsx. The shared chat catalog
// keys (t('chat.…'), receiptBadge, message/stream copy) stay in the central store.

export const STR = {
  liveChatEyebrow: {
    en: 'LIVE CHAT',
    hy: 'ԿԵՆԴԱՆԻ ԶՐՈՒՅՑ',
    ru: 'ЖИВОЙ ЧАТ',
  },
  groupChatEyebrow: {
    en: 'GROUP CHAT',
    hy: 'ԽՄԲԱՅԻՆ ԶՐՈՒՅՑ',
    ru: 'ГРУППОВОЙ ЧАТ',
  },
  typing: {
    en: 'typing…',
    hy: 'գրում է…',
    ru: 'печатает…',
  },
  ready: {
    en: 'ready',
    hy: 'պատրաստ',
    ru: 'готов',
  },
  stop: {
    en: 'Stop',
    hy: 'Կանգնեցնել',
    ru: 'Остановить',
  },
  queuedOne: {
    en: '1 message queued',
    hy: '1 հաղորդագրություն հերթում',
    ru: '1 сообщение в очереди',
  },
  queuedMany: {
    en: 'messages queued',
    hy: 'հաղորդագրություն հերթում',
    ru: 'сообщений в очереди',
  },
  copy: {
    en: 'Copy',
    hy: 'Պատճենել',
    ru: 'Копировать',
  },
  copied: {
    en: 'Copied',
    hy: 'Պատճենվեց',
    ru: 'Скопировано',
  },
  thinkingCap: {
    en: 'THINKING',
    hy: 'ՄՏԱԾՈՒՄ',
    ru: 'ДУМАЕТ',
  },
  unavailable: {
    en: 'UNAVAILABLE',
    hy: 'ԱՆՀԱՍԱՆԵԼԻ',
    ru: 'НЕДОСТУПНО',
  },
  readyCap: {
    en: 'READY',
    hy: 'ՊԱՏՐԱՍՏ',
    ru: 'ГОТОВ',
  },
  attnFieldAria: {
    en: 'Attention field',
    hy: 'Ուշադրության դաշտ',
    ru: 'Поле внимания',
  },
  attnFieldEyebrow: {
    en: 'ATTENTION FIELD',
    hy: 'ՈՒՇԱԴՐՈՒԹՅԱՆ ԴԱՇՏ',
    ru: 'ПОЛЕ ВНИМАНИЯ',
  },
  liveState: {
    en: "Bro's live state right now.",
    hy: 'Ի՞նչ վիճակում է Bro-ն հենց հիմա։',
    ru: 'Текущее состояние Bro прямо сейчас.',
  },
  contextLabel: {
    en: 'CONTEXT',
    hy: 'ՀԱՄԱՏԵՔՍՏ',
    ru: 'КОНТЕКСТ',
  },
  messagesUnit: {
    en: 'MESSAGES',
    hy: 'ՀԱՂՈՐԴԱԳՐՈՒԹՅՈՒՆ',
    ru: 'СООБЩЕНИЙ',
  },
  agentsUnit: {
    en: 'AGENTS',
    hy: 'ԳՈՐԾԱԿԱԼ',
    ru: 'АГЕНТОВ',
  },
  inRoomEyebrow: {
    en: 'IN THE ROOM',
    hy: 'ՍԵՆՅԱԿՈՒՄ',
    ru: 'В КОМНАТЕ',
  },
  participantsUnit: {
    en: 'PARTICIPANTS',
    hy: 'ՄԱՍՆԱԿԻՑ',
    ru: 'УЧАСТНИКОВ',
  },
  broRole: {
    en: 'Core · orchestrator',
    hy: 'Միջուկ · օրկեստրավար',
    ru: 'Ядро · оркестратор',
  },
  statusWorking: {
    en: 'WORKING',
    hy: 'ԱՇԽԱՏՈՒՄ',
    ru: 'РАБОТАЕТ',
  },
  statusIdle: {
    en: 'IDLE',
    hy: 'ՊԱՐԱՊ',
    ru: 'СВОБОДЕН',
  },
  responseEyebrow: {
    en: 'RESPONSE',
    hy: 'ԱՐՁԱԳԱՆՔ',
    ru: 'ОТКЛИК',
  },
  tempoNote: {
    en: 'Live typing tempo is not tracked.',
    hy: 'Կենդանի գրելու տեմպ չի չափվում։',
    ru: 'Живой темп набора не отслеживается.',
  },
} as const;
