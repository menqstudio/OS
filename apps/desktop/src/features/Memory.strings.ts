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
  // The old header pill read "Verifiable memory" unconditionally. Nothing verifies a
  // memory entry: `list_memory` returns plain rows from the local SQLite store with no
  // signature, receipt or chain behind them, so that claim was unbacked and is gone.
  // What IS real is the outcome of the one `list_memory` read, so the pill names that.
  storeReading: { en: 'Reading the store…', hy: 'Կարդում ենք պահոցը…', ru: 'Читаем хранилище…' },
  storeUnavailable: { en: 'Store unavailable', hy: 'Պահոցն անհասանելի է', ru: 'Хранилище недоступно' },
  storeLoaded: { en: 'Read from the store', hy: 'Կարդացված է պահոցից', ru: 'Прочитано из хранилища' },
  // Provenance, stated plainly next to the counts — and kept CURRENT.
  //
  // This line used to read "Local store · no verification chain". That was true when it
  // was written and is not true now: every memory write appends a record in the same
  // transaction as the row (`core/src/local_write_record.rs`, migration 0021), hashing
  // the row's content into an append-only chain the database itself enforces. A stale
  // honest label becomes a dishonest one, so the line says what the record really is.
  //
  // What it must NOT say: nothing here is signed — no key, no manifest, no authority, no
  // containment — and the record attests CONTENT, never the writer. So no "verified", no
  // "trusted", and nothing a reader would file next to a governed turn's badge.
  provenance: {
    en: 'Local store · each write appends a local record · shows the row is unchanged since it was written, never who wrote it',
    hy: 'Տեղական պահոց · ամեն գրում ավելացնում է լոկալ գրանցում · ցույց է տալիս, որ տողը գրվելուց հետո չի փոխվել, բայց ոչ թե ով է գրել',
    ru: 'Локальное хранилище · каждая запись добавляет локальный журнальный след · показывает, что строка не менялась с момента записи, но не кто её записал',
  },

  // --- Refused writes (delete/pin may be denied by the window capability set) --
  deleteRefusedTitle: {
    en: 'Delete refused — nothing was removed',
    hy: 'Ջնջումը մերժվեց — ոչինչ չհեռացվեց',
    ru: 'Удаление отклонено — ничего не удалено',
  },
  deleteRefusedBody: {
    en: 'The backend rejected this delete, so the memory is still in the store and still listed.',
    hy: 'Backend-ը մերժեց այս ջնջումը, ուստի հիշողությունը դեռ պահոցում է և դեռ ցուցակում է։',
    ru: 'Бэкенд отклонил это удаление, поэтому воспоминание всё ещё в хранилище и в списке.',
  },
  pinRefusedTitle: {
    en: 'Pin change refused — nothing was changed',
    hy: 'Ամրացման փոփոխությունը մերժվեց — ոչինչ չփոխվեց',
    ru: 'Изменение закрепления отклонено — ничего не изменено',
  },
  pinRefusedBody: {
    en: 'The backend rejected this change, so the pin state is exactly as it was.',
    hy: 'Backend-ը մերժեց այս փոփոխությունը, ուստի ամրացման վիճակը մնում է նույնը։',
    ru: 'Бэкенд отклонил это изменение, поэтому состояние закрепления осталось прежним.',
  },
  deleting: { en: 'Deleting…', hy: 'Ջնջվում է…', ru: 'Удаление…' },

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

/** Announced ONLY on a real backend rejection — the entry was not deleted. */
export function deleteRefusedLive(lang: Lang, reason: string): string {
  switch (lang) {
    case 'hy':
      return `Ջնջումը մերժվեց. հիշողությունը չհեռացվեց։ ${reason}`;
    case 'ru':
      return `Удаление отклонено: воспоминание не удалено. ${reason}`;
    default:
      return `Delete refused: the memory was not removed. ${reason}`;
  }
}

/** Announced ONLY on a real backend rejection — the pin state did not change. */
export function pinRefusedLive(lang: Lang, reason: string): string {
  switch (lang) {
    case 'hy':
      return `Ամրացումը մերժվեց. վիճակը չփոխվեց։ ${reason}`;
    case 'ru':
      return `Закрепление отклонено: состояние не изменилось. ${reason}`;
    default:
      return `Pin change refused: the pin state did not change. ${reason}`;
  }
}

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
