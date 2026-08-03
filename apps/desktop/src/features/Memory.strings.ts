import type { Lang } from '../domain/enums';

// Page-local trilingual copy for the §D `memory` page instruments that have no
// shared i18n key yet. Every entry carries en / hy / ru so Russian is correct
// rather than silently falling back to English. `t()` still serves every
// existing dict key; only these page-local labels live here. Fixed strings —
// they carry no data. Armenian is verbatim from the mockup vocabulary.
export const STR = {
  // --- Edit-entry modal -----------------------------------------------------
  editTitle: { en: 'Edit memory', hy: 'Խմբագրել հիշողությունը', ru: 'Редактировать воспоминание' },
  editNotWired: {
    en: 'Editing a memory is not wired yet — the desktop store has no update command. Fields are shown read-only.',
    hy: 'Հիշողության խմբագրումը դեռ միացված չէ — store-ը թարմացման հրաման չունի։ Դաշտերը միայն ընթերցման համար են։',
    ru: 'Редактирование воспоминания ещё не подключено — в хранилище нет команды обновления. Поля показаны только для чтения.',
  },
  editArrives: {
    en: 'Editing arrives with the update command.',
    hy: 'Խմբագրումը գալիս է թարմացման հրամանի հետ։',
    ru: 'Редактирование появится вместе с командой обновления.',
  },

  // --- Recall rail / memory detail ------------------------------------------
  memoryEyebrow: { en: 'MEMORY', hy: 'ՀԻՇՈՂՈՒԹՅՈՒՆ', ru: 'ПАМЯТЬ' },
  sealed: { en: 'Sealed', hy: 'Կնքված', ru: 'Запечатано' },
  refSealedEvidence: {
    en: 'References sealed evidence',
    hy: 'Հղում է կնքված ապացույցին',
    ru: 'Ссылается на запечатанные доказательства',
  },
  sealedExplain: {
    en: 'This memory points at evidence the local store cannot surface. The referenced material stays sealed:',
    hy: 'Այս հիշողությունը հղում է ապացույցի, որը լոկալ store-ը չի կարող ցուցադրել։ Հղված նյութը մնում է կնքված․',
    ru: 'Это воспоминание указывает на доказательства, которые локальное хранилище не может показать. Указанный материал остаётся запечатанным:',
  },
  sealedUnavailable: { en: 'Sealed / unavailable', hy: 'Կնքված / անհասանելի', ru: 'Запечатано / недоступно' },
  formed: { en: 'formed', hy: 'ձևավորվել է', ru: 'создано' },
  updated: { en: 'updated', hy: 'թարմացվել է', ru: 'обновлено' },
  links: { en: 'links', hy: 'հղում', ru: 'ссылки' },
  references: { en: 'References', hy: 'Հղումներ', ru: 'Ссылки' },

  // --- Metric strip / core grid ---------------------------------------------
  memoriesStore: { en: 'memories · store', hy: 'հիշողություն · store', ru: 'воспоминаний · хранилище' },
  pinned: { en: 'pinned', hy: 'ամրակցված', ru: 'закреплено' },
  sealedRefs: { en: 'sealed refs', hy: 'կնքված հղում', ru: 'запечатанные ссылки' },
  memoriesUnit: { en: 'memories', hy: 'հիշողություն', ru: 'воспоминаний' },

  // --- Live region ----------------------------------------------------------
  loading: { en: 'Loading memories…', hy: 'Հիշողությունները բեռնվում են…', ru: 'Загрузка воспоминаний…' },
  loadError: { en: 'Could not load memories.', hy: 'Չհաջողվեց բեռնել հիշողությունները։', ru: 'Не удалось загрузить воспоминания.' },
  noMemoriesLive: { en: 'Bro has no memories yet.', hy: 'Bro-ն դեռ հիշողություններ չունի։', ru: 'У Bro пока нет воспоминаний.' },

  // --- Header ---------------------------------------------------------------
  fieldEyebrow: {
    en: 'MEMORY FIELD · TEMPORAL FIELD',
    hy: 'ՀԻՇՈՂՈՒԹՅԱՆ ԴԱՇՏ · ԺԱՄԱՆԱԿԱՅԻՆ ԴԱՇՏ',
    ru: 'ПОЛЕ ПАМЯТИ · ТЕМПОРАЛЬНОЕ ПОЛЕ',
  },
  verifiable: { en: 'Verifiable memory', hy: 'Ստուգելի հիշողություն', ru: 'Проверяемая память' },

  // --- Browser --------------------------------------------------------------
  memoriesHeading: { en: 'Memories', hy: 'Հիշողություններ', ru: 'Воспоминания' },
  inField: { en: 'in field', hy: 'դաշտում', ru: 'в поле' },
  searchPlaceholder: {
    en: 'Search memories…  ( / )',
    hy: 'Փնտրիր հիշողություններ…  ( / )',
    ru: 'Поиск воспоминаний…  ( / )',
  },
  searchLabel: { en: 'Search memories', hy: 'Փնտրիր հիշողություններ', ru: 'Поиск воспоминаний' },
  filterByType: { en: 'Filter by type', hy: 'Զտել ըստ տեսակի', ru: 'Фильтр по типу' },
  all: { en: 'All', hy: 'Բոլորը', ru: 'Все' },
  noMemoriesTitle: { en: 'Bro has no memories yet', hy: 'Bro-ն դեռ հիշողություններ չունի', ru: 'У Bro пока нет воспоминаний' },
  noMemoriesHint: {
    en: 'Create the first memory to build persistent context.',
    hy: 'Ստեղծիր առաջին հիշողությունը՝ մշտական համատեքստ կառուցելու համար։',
    ru: 'Создайте первое воспоминание, чтобы построить постоянный контекст.',
  },
  noMatch: { en: 'No memories match', hy: 'Համընկնող հիշողություն չկա', ru: 'Нет подходящих воспоминаний' },
  noMatchHint: {
    en: 'Adjust the search or type filter.',
    hy: 'Փոխիր որոնումը կամ տեսակի զտիչը։',
    ru: 'Измените поиск или фильтр по типу.',
  },

  // --- Recall-rail core placeholder -----------------------------------------
  memoryCore: { en: 'MEMORY CORE', hy: 'ՀԻՇՈՂՈՒԹՅԱՆ ՄԻՋՈՒԿ', ru: 'ЯДРО ПАМЯТИ' },
  pickMemory: {
    en: 'Pick a memory to inspect it',
    hy: 'Ընտրիր հիշողություն՝ ստուգելու համար',
    ru: 'Выберите воспоминание для просмотра',
  },
  coreHint: {
    en: 'Enter opens the focused item · n new · e edit · / search',
    hy: 'Enter՝ բացել · n՝ նոր · e՝ խմբագրել · /՝ որոնում',
    ru: 'Enter — открыть · n — новое · e — изменить · / — поиск',
  },

  // --- Link graph -----------------------------------------------------------
  linkGraph: { en: 'Link graph', hy: 'Հղումների գրաֆ', ru: 'Граф ссылок' },
  derivedFrom: { en: 'derived from real [[links]]', hy: 'իրական [[հղումներից]]', ru: 'из реальных [[ссылок]]' },
  noLinks: {
    en: 'No [[links]] between memories yet.',
    hy: 'Հիշողությունների միջև դեռ [[հղումներ]] չկան։',
    ru: 'Между воспоминаниями пока нет [[ссылок]].',
  },
  memoryLinks: { en: 'Memory links', hy: 'Հիշողությունների հղումներ', ru: 'Ссылки воспоминаний' },
  sealedLower: { en: 'sealed', hy: 'կնքված', ru: 'запечатано' },

  // --- Honest metric strip --------------------------------------------------
  memoryState: { en: 'Memory state', hy: 'Հիշողության վիճակ', ru: 'Состояние памяти' },
  countedStore: { en: 'counted from the store', hy: 'store-ից հաշված', ru: 'подсчитано из хранилища' },
} as const;

// Parameterised copy — kept as per-language builders so the real counts
// interpolate into each language's phrasing (Russian included).

// "{shown} of {total} memories." — live-region result count.
export function liveCount(lang: Lang, shown: number, total: number): string {
  switch (lang) {
    case 'hy':
      return `${shown} / ${total} հիշողություն։`;
    case 'ru':
      return `${shown} из ${total} воспоминаний.`;
    default:
      return `${shown} of ${total} memories.`;
  }
}

// "{n} refs" — link-graph source count, with correct plural per language.
export function refCount(lang: Lang, n: number): string {
  switch (lang) {
    case 'hy':
      return `${n} հղում`;
    case 'ru': {
      const mod10 = n % 10;
      const mod100 = n % 100;
      const unit =
        mod10 === 1 && mod100 !== 11
          ? 'ссылка'
          : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)
            ? 'ссылки'
            : 'ссылок';
      return `${n} ${unit}`;
    }
    default:
      return `${n} ref${n === 1 ? '' : 's'}`;
  }
}
