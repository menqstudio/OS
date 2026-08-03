import type { Lang } from '../domain/enums';

// Trilingual copy for the Activity ("System Pulse Monitor") view. Every visible
// string lives here under a short camelCase key with a real en / hy / ru value.
// Static strings go in STR (indexed via the L() helper in Activity.tsx); the few
// strings that interpolate live numbers/labels are the parameterized helpers below.

export const STR = {
  loadingBeatline: {
    en: 'Loading activity beatline…',
    hy: 'Բեռնվում է ակտիվության զարկագիծը…',
    ru: 'Загрузка ленты активности…',
  },
  loadingBeatlineShort: {
    en: 'Loading beatline',
    hy: 'Բեռնվում է զարկագիծը',
    ru: 'Загрузка ленты',
  },
  connecting: {
    en: 'CONNECTING',
    hy: 'ՄԻԱՆՈՒՄ',
    ru: 'ПОДКЛЮЧЕНИЕ',
  },
  offline: {
    en: 'OFFLINE',
    hy: 'ԱՆՋԱՏՎԱԾ',
    ru: 'ОФФЛАЙН',
  },
  rhythmStable: {
    en: 'RHYTHM · STABLE',
    hy: 'ՌԻԹՄ · ԿԱՅՈՒՆ',
    ru: 'РИТМ · СТАБИЛЬНЫЙ',
  },
  telemetryBlocked: {
    en: 'Telemetry stream blocked',
    hy: 'Հեռաչափման հոսքն արգելափակված է',
    ru: 'Поток телеметрии заблокирован',
  },
  telemetryBlockedBody: {
    en: 'The runtime telemetry stream did not clear the governance wall. No live data crosses until it is approved.',
    hy: 'Հեռաչափման հոսքը չանցավ կառավարման պատը։ Կենդանի տվյալ չի փոխանցվում մինչ հաստատում։',
    ru: 'Поток телеметрии среды выполнения не прошёл стену управления. Живые данные не передаются, пока он не будет одобрен.',
  },
  noActivity: {
    en: 'No activity yet',
    hy: 'Դեռ ակտիվություն չկա',
    ru: 'Пока нет активности',
  },
  noActivityHint: {
    en: 'Beats will appear here as the engine records events.',
    hy: 'Զարկերը կհայտնվեն այստեղ, երբ շարժիչը գրանցի իրադարձություններ։',
    ru: 'Удары появятся здесь по мере того, как движок будет записывать события.',
  },
  leadSystem: {
    en: 'LEAD · SYSTEM',
    hy: 'LEAD · ՀԱՄԱԿԱՐԳ',
    ru: 'ОТВЕДЕНИЕ · СИСТЕМА',
  },
  freeze: {
    en: 'Freeze',
    hy: 'Սառեցնել',
    ru: 'Заморозить',
  },
  frozen: {
    en: 'Frozen',
    hy: 'Սառեցված',
    ru: 'Заморожено',
  },
  beatlineAria: {
    en: 'Activity beatline — arrow keys scrub beats, Enter opens a beat, Space freezes',
    hy: 'Ակտիվության զարկագիծ — սլաքներով անցեք զարկերով, Enter՝ բացել, Space՝ սառեցնել',
    ru: 'Лента активности — стрелки листают удары, Enter открывает удар, Пробел замораживает',
  },
  systemPulse: {
    en: 'System pulse',
    hy: 'Համակարգի զարկերակ',
    ru: 'Пульс системы',
  },
  perMin: {
    en: '/min',
    hy: 'զարկ/ր',
    ru: '/мин',
  },
  eventTypes: {
    en: 'Event types',
    hy: 'Տեսակներ',
    ru: 'Типы событий',
  },
  typesUnit: {
    en: 'types',
    hy: 'տիպ',
    ru: 'типы',
  },
  plotted: {
    en: 'Plotted',
    hy: 'Ցուցադրված',
    ru: 'Показано',
  },
  lastBeat: {
    en: 'Last beat',
    hy: 'Վերջին զարկ',
    ru: 'Последний удар',
  },
  peakBeats: {
    en: 'Peak beats',
    hy: 'Գագաթ',
    ru: 'Пик ударов',
  },
  busiestHour: {
    en: 'Busiest hour',
    hy: 'Ամենազբաղ ժամ',
    ru: 'Час пик',
  },
  eventsFlow: {
    en: 'EVENTS FLOW · /min',
    hy: 'ԿԱՆՉԵՐԻ ՀՈՍՔ · /Ր',
    ru: 'ПОТОК СОБЫТИЙ · /мин',
  },
  beats: {
    en: 'beats',
    hy: 'զարկ',
    ru: 'ударов',
  },
  lastEvent: {
    en: 'last event',
    hy: 'վերջին իրադարձություն',
    ru: 'последнее событие',
  },
  beatTimeline: {
    en: 'Beat timeline',
    hy: 'Զարկերի ժամանակագիծ',
    ru: 'Хронология ударов',
  },
  beatTimelineHint: {
    en: 'recent system events · click to locate on the strip',
    hy: 'վերջին համակարգային իրադարձությունները · սեղմիր՝ շերտի վրա գտնելու',
    ru: 'недавние системные события · нажмите, чтобы найти на ленте',
  },
  intensity: {
    en: 'intensity',
    hy: 'ինտենսիվ',
    ru: 'интенсивность',
  },
  vitals: {
    en: 'Vitals',
    hy: 'Կենսանշաններ',
    ru: 'Показатели',
  },
  recordOnly: {
    en: 'record only',
    hy: 'միայն գրանցում',
    ru: 'только запись',
  },
  byEventType: {
    en: 'By event type',
    hy: 'Ըստ տեսակի',
    ru: 'По типу события',
  },
  topActors: {
    en: 'Top actors',
    hy: 'Ըստ դերակատարի',
    ru: 'Топ участников',
  },
  system: {
    en: 'system',
    hy: 'համակարգ',
    ru: 'система',
  },
  telemetryOmitted: {
    en: 'Live runtime telemetry (response, network load, error rate) is not wired to this build, so those vitals are omitted rather than shown as numbers. The beats and counts above are the real event record.',
    hy: 'Կենդանի հեռաչափումը (արձագանք, ցանցի բեռ, սխալի հաճախ.) միացված չէ այս կառուցվածքին, ուստի այդ կենսանշանները բաց են թողնված, ոչ թե ցուցադրված որպես թվեր։ Վերևի զարկերը և հաշվարկները իրական գրառումն են։',
    ru: 'Живая телеметрия среды выполнения (отклик, нагрузка на сеть, частота ошибок) не подключена к этой сборке, поэтому эти показатели опущены, а не показаны цифрами. Удары и счётчики выше — это реальная запись событий.',
  },
  beatDetail: {
    en: 'Beat detail',
    hy: 'Զարկի մանրամասն',
    ru: 'Детали удара',
  },
  closeEsc: {
    en: 'Close (Esc)',
    hy: 'Փակել (Esc)',
    ru: 'Закрыть (Esc)',
  },
  closeBeatDetail: {
    en: 'Close beat detail',
    hy: 'Փակել',
    ru: 'Закрыть детали удара',
  },
  actor: {
    en: 'Actor',
    hy: 'Դերակատար',
    ru: 'Участник',
  },
  entity: {
    en: 'Entity',
    hy: 'Օբյեկտ',
    ru: 'Объект',
  },
  entityId: {
    en: 'Entity ID',
    hy: 'Օբյեկտի ID',
    ru: 'ID объекта',
  },
  when: {
    en: 'When',
    hy: 'Ե՞րբ',
    ru: 'Когда',
  },
  pageEyebrow: {
    en: 'SYSTEM PULSE · VITALS MONITOR',
    hy: 'ՀԱՄԱԿԱՐԳԻ ԶԱՐԿԵՐԱԿ · VITALS MONITOR',
    ru: 'ПУЛЬС СИСТЕМЫ · МОНИТОР ПОКАЗАТЕЛЕЙ',
  },
} as const;

// ── Parameterized strings — static parts keyed per-lang, live values interpolated ──

/** Blip / beat accessible label: "Beat 3: created on note-1". */
export function blipLabelStr(lang: Lang, n: number, eventType: string, target: string): string {
  const lead = { en: 'Beat', hy: 'Զարկ', ru: 'Удар' }[lang];
  const sep = { en: ': ', hy: '․ ', ru: ': ' }[lang];
  const on = { en: ' on ', hy: ' · ', ru: ' · ' }[lang];
  return `${lead} ${n}${sep}${eventType}${target ? `${on}${target}` : ''}`;
}

/** Accessible one-line summary for the rate histogram. */
export function rateSummaryStr(lang: Lang, count: number, bins: number, peak: number, peakTime: string): string {
  if (lang === 'hy') {
    return `Ակտիվության հաճախություն — ${count} զարկ ${bins} ժամային կապոցում, գագաթ՝ ${peak} ${peakTime}-ի մոտ։`;
  }
  if (lang === 'ru') {
    return `Частота активности — ${count} ударов в ${bins} временных интервалах, пик ${peak} около ${peakTime}.`;
  }
  return `Activity rate — ${count} beats across ${bins} time bins, peak ${peak} around ${peakTime}.`;
}

/** Text-equivalent live region summary. rate is null when there is no real time span. */
export function liveTextStr(
  lang: Lang,
  count: number,
  rate: number | null,
  focus: { pos: number; total: number; eventType: string } | null,
): string {
  if (lang === 'hy') {
    const rateBit = rate != null ? ` Մոտ ${rate} զարկ/րոպե։` : '';
    const focusBit = focus ? ` Կիզակետում՝ զարկ ${focus.pos}/${focus.total}՝ ${focus.eventType}։` : '';
    return `${count} ակտիվության զարկ։${rateBit}${focusBit}`;
  }
  if (lang === 'ru') {
    const rateBit = rate != null ? ` Около ${rate} в минуту.` : '';
    const focusBit = focus ? ` Выделен удар ${focus.pos} из ${focus.total}: ${focus.eventType}.` : '';
    return `${count} ударов активности.${rateBit}${focusBit}`;
  }
  const rateBit = rate != null ? ` About ${rate} per minute.` : '';
  const focusBit = focus ? ` Focused beat ${focus.pos} of ${focus.total}: ${focus.eventType}.` : '';
  return `${count} activity beats.${rateBit}${focusBit}`;
}

/** Error message when the telemetry stream is lost. */
export function telemetryLostStr(lang: Lang, error: string): string {
  const lead = {
    en: 'Telemetry stream lost',
    hy: 'Հեռաչափման հոսքը կորավ',
    ru: 'Поток телеметрии потерян',
  }[lang];
  return `${lead} — ${error}`;
}

/** Compact inline "peak N · HH:MM" readout above the histogram. */
export function peakInlineStr(lang: Lang, peak: number, peakTime: string): string {
  const label = { en: 'peak', hy: 'գագաթ', ru: 'пик' }[lang];
  return `${label} ${peak} · ${peakTime}`;
}

/** Tail note when older beats are not plotted. */
export function hiddenTailStr(lang: Lang, hidden: number): string {
  if (lang === 'hy') return `+${hidden} ավելի վաղ զարկ չեն գծագրված`;
  if (lang === 'ru') return `+${hidden} более ранних ударов не показано`;
  return `+${hidden} earlier beats not plotted`;
}
