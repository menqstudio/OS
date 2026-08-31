// Trilingual (en/hy/ru) string table for the Analytics ("Signal Deck") page.
// Every user-facing literal that used to live inline in Analytics.tsx as an
// `L('en','hy')` bilingual call now lives here under a short camelCase key,
// with a natural Russian translation added alongside.
export const STR = {
  // -- distribution plot (AnPlot) + accessible summary -----------------------
  noNodesSelected: {
    en: 'No nodes selected.',
    hy: 'Ընտրված հանգույց չկա։',
    ru: 'Узлы не выбраны.',
  },
  nodesTotal: {
    en: 'nodes, total',
    hy: 'հանգույց, ընդամենը',
    ru: 'узлов, всего',
  },
  sentenceDot: {
    en: '.',
    hy: '։',
    ru: '.',
  },
  highestPrefix: {
    en: 'Highest: ',
    hy: 'Ամենաբարձրը՝ ',
    ru: 'Наибольшее: ',
  },
  distByNode: {
    en: 'Distribution by node',
    hy: 'Բաշխում ըստ հանգույցի',
    ru: 'Распределение по узлам',
  },
  toggleNodes: {
    en: 'Toggle nodes',
    hy: 'Փոխարկել հանգույցները',
    ru: 'Переключить узлы',
  },
  showNode: {
    en: 'Show node',
    hy: 'Ցուցադրել հանգույցը',
    ru: 'Показать узел',
  },
  hideNode: {
    en: 'Hide node',
    hy: 'Թաքցնել հանգույցը',
    ru: 'Скрыть узел',
  },
  hiddenWord: {
    en: 'hidden',
    hy: 'թաքցված',
    ru: 'скрыто',
  },
  allNodesHidden: {
    en: 'All nodes hidden — enable one in the legend.',
    hy: 'Բոլոր հանգույցները թաքցված են․ միացրեք որևէ մեկը լեգենդից։',
    ru: 'Все узлы скрыты — включите один в легенде.',
  },
  totalAcrossNodes: {
    en: 'Total across nodes',
    hy: 'Ընդամենը հանգույցներով',
    ru: 'Всего по узлам',
  },
  nodeHeader: {
    en: 'Node',
    hy: 'Հանգույց',
    ru: 'Узел',
  },
  value: {
    en: 'Value',
    hy: 'Արժեք',
    ru: 'Значение',
  },
  share: {
    en: 'Share',
    hy: 'Բաժին',
    ru: 'Доля',
  },
  showDataTable: {
    en: 'Show data table',
    hy: 'Ցուցադրել աղյուսակը',
    ru: 'Показать таблицу данных',
  },
  noBreakdown: {
    en: 'No breakdown available',
    hy: 'Բաժանում առկա չէ',
    ru: 'Разбивка недоступна',
  },

  // -- aria-live data-state announcements ------------------------------------
  loadingAnalytics: {
    en: 'Loading analytics…',
    hy: 'Վերլուծությունը բեռնվում է…',
    ru: 'Загрузка аналитики…',
  },
  analyticsUnavailable: {
    en: 'Analytics unavailable.',
    hy: 'Վերլուծությունն անհասանելի է։',
    ru: 'Аналитика недоступна.',
  },
  noAnalyticsData: {
    en: 'No analytics data.',
    hy: 'Վերլուծության տվյալներ չկան։',
    ru: 'Нет данных аналитики.',
  },
  nodesDot: {
    en: 'nodes.',
    hy: 'հանգույց։',
    ru: 'узлов.',
  },

  // -- governed-wall block (denied) ------------------------------------------
  governedBlocked: {
    en: 'This analytics aggregate is governed. The request was blocked at the wall; nothing was read.',
    hy: 'Այս վերլուծական ագրեգատը կառավարվող է։ Հարցումը արգելափակվեց պատի մոտ․ ոչինչ չկարդացվեց։',
    ru: 'Этот аналитический агрегат управляемый. Запрос был заблокирован на стене; ничего не было прочитано.',
  },

  // -- hero deck framing ------------------------------------------------------
  // There is no stream. `get_analytics` is a one-shot read of an all-time aggregate,
  // so the old always-on "STREAM · LIVE" pill was decoration dressed as telemetry.
  // These three name the REAL state of that single read instead.
  readReading: {
    en: 'READ · in flight',
    hy: 'ԸՆԹԵՐՑՈՒՄ · ընթացքում',
    ru: 'ЧТЕНИЕ · выполняется',
  },
  readUnavailable: {
    en: 'READ · unavailable',
    hy: 'ԸՆԹԵՐՑՈՒՄ · անհասանելի',
    ru: 'ЧТЕНИЕ · недоступно',
  },
  readBlocked: {
    en: 'READ · blocked at the wall',
    hy: 'ԸՆԹԵՐՑՈՒՄ · արգելափակված է պատի մոտ',
    ru: 'ЧТЕНИЕ · заблокировано на стене',
  },
  readSnapshot: {
    en: 'SNAPSHOT · all-time aggregate',
    hy: 'ԴԻՊՈՒԿ · ամբողջ ժամանակի ագրեգատ',
    ru: 'СНИМОК · агрегат за всё время',
  },
  nodes: {
    en: 'nodes',
    hy: 'հանգույց',
    ru: 'узлов',
  },

  // -- honest lower board: districts -----------------------------------------
  distByDistrict: {
    en: 'Distribution by district',
    hy: 'Բաշխում ըստ շրջանների',
    ru: 'Распределение по районам',
  },
  routedCalls: {
    en: 'routed calls',
    hy: 'ուղղորդված կանչ',
    ru: 'маршрутизированные вызовы',
  },
  districtHint: {
    en: 'The engine does not expose a per-district aggregate yet, so no breakdown is shown.',
    hy: 'Շարժիչը դեռ չի տրամադրում ըստ շրջանի ագրեգատ, ուստի բաժանում ցուցադրված չէ։',
    ru: 'Движок пока не предоставляет агрегат по районам, поэтому разбивка не показана.',
  },
  districtTableHint: {
    en: 'No district aggregate from the engine.',
    hy: 'Շարժիչից շրջանի ագրեգատ չկա։',
    ru: 'Нет агрегата по районам от движка.',
  },
  district: {
    en: 'District',
    hy: 'Շրջան',
    ru: 'Район',
  },

  // -- honest lower board: autonomy ------------------------------------------
  autonomy: {
    en: 'Autonomy',
    hy: 'Ինքնավարություն',
    ru: 'Автономность',
  },
  autonomyHint: {
    en: 'The engine does not expose an autonomy-level aggregate yet, so no split is shown.',
    hy: 'Շարժիչը դեռ չի տրամադրում ինքնավարության մակարդակի ագրեգատ, ուստի բաժանում ցուցադրված չէ։',
    ru: 'Движок пока не предоставляет агрегат по уровню автономности, поэтому разбивка не показана.',
  },
  autonomyTableHint: {
    en: 'No autonomy aggregate from the engine.',
    hy: 'Շարժիչից ինքնավարության ագրեգատ չկա։',
    ru: 'Нет агрегата по автономности от движка.',
  },
  segment: {
    en: 'Segment',
    hy: 'Հատված',
    ru: 'Сегмент',
  },

  // -- honest lower board: channel -------------------------------------------
  channelSplit: {
    en: 'Channel split',
    hy: 'Ալիքների բաժանում',
    ru: 'Разделение по каналам',
  },
  channelHint: {
    en: 'The engine does not expose a per-channel aggregate yet, so no split is shown.',
    hy: 'Շարժիչը դեռ չի տրամադրում ըստ ալիքի ագրեգատ, ուստի բաժանում ցուցադրված չէ։',
    ru: 'Движок пока не предоставляет агрегат по каналам, поэтому разбивка не показана.',
  },
  channelTableHint: {
    en: 'No channel aggregate from the engine.',
    hy: 'Շարժիչից ալիքի ագրեգատ չկա։',
    ru: 'Нет агрегата по каналам от движка.',
  },
  channel: {
    en: 'Channel',
    hy: 'Ալիք',
    ru: 'Канал',
  },

  // -- rank scrubber (AnScrub) --------------------------------------------------
  // §D asks for a scrubber. The engine exposes ONE all-time aggregate with no time
  // dimension, so a TIME scrubber would be inventing an axis — exactly what this page
  // refuses to do in its other three panels. What this one scrubs is real: the rank
  // cut-off, how far down the ranked distribution is shown.
  scrubLabel: {
    en: 'Show top nodes',
    hy: 'Ցույց տալ առաջին հանգույցները',
    ru: 'Показать первые узлы',
  },
  scrubTop: {
    en: 'top',
    hy: 'առաջին',
    ru: 'первые',
  },
  scrubOf: {
    en: 'of',
    hy: '-ը',
    ru: 'из',
  },
  scrubAll: {
    en: 'all nodes',
    hy: 'բոլոր հանգույցները',
    ru: 'все узлы',
  },
  scrubHint: {
    en: 'Ranked by value. Arrows, Home and End move the cut.',
    hy: 'Դասավորված ըստ արժեքի։ Սլաքները, Home-ը և End-ը շարժում են սահմանը։',
    ru: 'Отсортировано по значению. Стрелки, Home и End двигают срез.',
  },

  // -- page header ------------------------------------------------------------
  intelCentre: {
    en: 'INTELLIGENCE CENTRE · ANALYTICS',
    hy: 'ԻՆՏԵԼԵԿՏԻ ԿԵՆՏՐՈՆ · ՎԵՐԼՈՒԾՈՒԹՅՈՒՆ',
    ru: 'ЦЕНТР РАЗВЕДКИ · АНАЛИТИКА',
  },
} as const;
