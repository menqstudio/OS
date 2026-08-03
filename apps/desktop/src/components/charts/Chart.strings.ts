import type { Lang } from '../../domain/enums';

// ─────────────────────────────────────────────────────────────────────────────
// Trilingual catalog for the strings that Chart.tsx OWNS (i.e. hardcodes when a
// caller does not pass an override prop). Callers may still pass explicit labels
// (legendLabel, totalLabel, valueHeader, …); those win. These are only the
// fallbacks + the interpolated accessible summaries the primitives build.
// ─────────────────────────────────────────────────────────────────────────────

export const STR = {
  // Beatline
  emptyTitle: {
    en: 'No data yet',
    hy: 'Դեռ տվյալներ չկան',
    ru: 'Пока нет данных',
  },
  labelHeader: {
    en: 'Point',
    hy: 'Կետ',
    ru: 'Точка',
  },
  // shared
  valueHeader: {
    en: 'Value',
    hy: 'Արժեք',
    ru: 'Значение',
  },
  showDataTable: {
    en: 'Show data table',
    hy: 'Ցույց տալ տվյալների աղյուսակը',
    ru: 'Показать таблицу данных',
  },
  // BarChart
  legendLabel: {
    en: 'Toggle series',
    hy: 'Փոխարկել շարքերը',
    ru: 'Переключить ряды',
  },
  showLabel: {
    en: 'Show',
    hy: 'Ցուցադրել',
    ru: 'Показать',
  },
  hideLabel: {
    en: 'Hide',
    hy: 'Թաքցնել',
    ru: 'Скрыть',
  },
  hiddenWord: {
    en: 'hidden',
    hy: 'թաքցված',
    ru: 'скрыто',
  },
  allHiddenNote: {
    en: 'All series hidden — enable one in the legend.',
    hy: 'Բոլոր շարքերը թաքցված են — միացրեք որևէ մեկը լեգենդում։',
    ru: 'Все ряды скрыты — включите один в легенде.',
  },
  totalLabel: {
    en: 'Total',
    hy: 'Ընդամենը',
    ru: 'Всего',
  },
  nodeHeader: {
    en: 'Series',
    hy: 'Շարք',
    ru: 'Ряд',
  },
  shareHeader: {
    en: 'Share',
    hy: 'Բաժին',
    ru: 'Доля',
  },
} as const;

export type StrKey = keyof typeof STR;

/** Resolve a catalog key for a language, falling back to English. */
export function localize(lang: Lang, key: StrKey): string {
  return STR[key][lang] ?? STR[key].en;
}

/** Accessible one-line summary for Beatline. */
export function beatSummary(
  lang: Lang,
  caption: string,
  count: number,
  min: number,
  max: number,
  last: number,
  u: string,
): string {
  switch (lang) {
    case 'hy':
      return `${caption}՝ ${count} կետ՝ ${min}${u}-ից մինչև ${max}${u}։ Վերջինը՝ ${last}${u}։`;
    case 'ru':
      return `${caption}: ${count} точек, от ${min}${u} до ${max}${u}. Последнее ${last}${u}.`;
    default:
      return `${caption}: ${count} points, from ${min}${u} to ${max}${u}. Latest ${last}${u}.`;
  }
}

/** Accessible one-line summary for BarChart. */
export function barSummary(
  lang: Lang,
  visibleCount: number,
  total: number,
  u: string,
  top: { label: string; value: number } | null,
): string {
  if (visibleCount === 0) {
    switch (lang) {
      case 'hy':
        return 'Ոչ մի շարք ընտրված չէ։';
      case 'ru':
        return 'Ряды не выбраны.';
      default:
        return 'No series selected.';
    }
  }
  switch (lang) {
    case 'hy':
      return `${visibleCount} շարք՝ ընդամենը ${total}${u}։${top ? ` Ամենաբարձրը՝ ${top.label} (${top.value}${u})։` : ''}`;
    case 'ru':
      return `${visibleCount} рядов, всего ${total}${u}.${top ? ` Наибольший: ${top.label} (${top.value}${u}).` : ''}`;
    default:
      return `${visibleCount} series, total ${total}${u}.${top ? ` Highest: ${top.label} (${top.value}${u}).` : ''}`;
  }
}
