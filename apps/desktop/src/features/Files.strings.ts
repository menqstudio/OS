// Page-local copy for the Files bench. These are labels that live on this thin
// page rather than in the shared i18n dictionaries. Every entry is authored in
// all three supported languages (en / hy / ru) so no language falls back.

export const STR = {
  filter: {
    en: 'Filter files…',
    hy: 'Զտել ֆայլերը…',
    ru: 'Фильтр файлов…',
  },
  truncated: {
    en: 'This folder has more files than shown — the listing was capped.',
    hy: 'Այս պանակն ավելի շատ ֆայլ ունի, քան ցուցադրված է — ցանկը սահմանափակվել է։',
    ru: 'В этой папке больше файлов, чем показано — список ограничен.',
  },
  clearFilter: {
    en: 'Clear filter',
    hy: 'Մաքրել զտիչը',
    ru: 'Очистить фильтр',
  },
  all: {
    en: 'All',
    hy: 'Բոլորը',
    ru: 'Все',
  },
  folders: {
    en: 'Folders',
    hy: 'Թղթապանակներ',
    ru: 'Папки',
  },
  files: {
    en: 'Files',
    hy: 'Ֆայլեր',
    ru: 'Файлы',
  },
  items: {
    en: 'items',
    hy: 'տարր',
    ru: 'элем.',
  },
  hits: {
    en: 'matches',
    hy: 'համընկնում',
    ru: 'совпадений',
  },
  planePick: {
    en: 'Select a file to preview',
    hy: 'Ընտրիր ֆայլ նախադիտման համար',
    ru: 'Выберите файл для предпросмотра',
  },
  planePickHint: {
    en: 'Use ↑ ↓ to move, Enter to preview, Space to select.',
    hy: 'Օգտագործիր ↑ ↓ շարժվելու, Enter՝ նախադիտելու, Space՝ ընտրելու համար։',
    ru: 'Используйте ↑ ↓ для перемещения, Enter — предпросмотр, Space — выбор.',
  },
  edit: {
    en: 'Edit',
    hy: 'Խմբագրել',
    ru: 'Редактировать',
  },
  readonly: {
    en: 'Read-only',
    hy: 'Միայն ընթերցում',
    ru: 'Только чтение',
  },
  refresh: {
    en: 'Refresh',
    hy: 'Թարմացնել',
    ru: 'Обновить',
  },
  guardOpen: {
    en: 'open',
    hy: 'բաց',
    ru: 'открыт',
  },
  guardRead: {
    en: 'read-only',
    hy: 'միայն ընթերցում',
    ru: 'только чтение',
  },
  guardSealed: {
    en: 'sealed',
    hy: 'կնքված',
    ru: 'запечатан',
  },
  blockedTitle: {
    en: 'Sealed — cannot open',
    hy: 'Կնքված է — հնարավոր չէ բացել',
    ru: 'Запечатан — открыть нельзя',
  },
  blockedHint: {
    en: 'The engine scope guard denied this file. Reason:',
    hy: 'Շարժիչի scope-պահակը մերժեց այս ֆայլը։ Պատճառ՝',
    ru: 'Охрана области движка отклонила этот файл. Причина:',
  },
  selected: {
    en: 'Selected',
    hy: 'Ընտրված',
    ru: 'Выбрано',
  },
  clearSel: {
    en: 'Clear',
    hy: 'Մաքրել',
    ru: 'Очистить',
  },
  noMatch: {
    en: 'No files match',
    hy: 'Ֆայլ չի համընկնում',
    ru: 'Нет совпадающих файлов',
  },
  noMatchHint: {
    en: 'Try a different filter.',
    hy: 'Փորձիր այլ զտիչ։',
    ru: 'Попробуйте другой фильтр.',
  },
  entryFile: {
    en: 'file',
    hy: 'ֆայլ',
    ru: 'файл',
  },
  entryFolder: {
    en: 'folder',
    hy: 'թղթապանակ',
    ru: 'папка',
  },
  preview: {
    en: 'Preview',
    hy: 'Նախադիտում',
    ru: 'Предпросмотр',
  },
  keysHint: {
    en: '/ filter · ↑↓ move · Enter preview · Space select',
    hy: '/ զտել · ↑↓ շարժվել · Enter նախադիտել · Space ընտրել',
    ru: '/ фильтр · ↑↓ перемещение · Enter предпросмотр · Space выбор',
  },
  eyebrow: {
    en: 'DATA BENCH · SPATIAL WORKSPACE',
    hy: 'ՏՎՅԱԼ-ՍԵՂԱՆ · ՏԱՐԱԾԱԿԱՆ ԱՇԽԱՏԱՏԱՐԱԾՔ',
    ru: 'СТЕНД ДАННЫХ · ПРОСТРАНСТВЕННАЯ РАБОЧАЯ ОБЛАСТЬ',
  },
  // Was an unconditional "Bro · indexing" pill. Nothing indexes: the page calls
  // `list_dir` once per path and filters the returned entries in memory. These three
  // name the REAL state of that read.
  dirReading: {
    en: 'Reading the directory…',
    hy: 'Կարդում ենք թղթապանակը…',
    ru: 'Читаем каталог…',
  },
  dirUnavailable: {
    en: 'Directory unreadable',
    hy: 'Թղթապանակն ընթեռնելի չէ',
    ru: 'Каталог недоступен для чтения',
  },
  dirListed: {
    en: 'Listed from disk',
    hy: 'Ցուցակված է սկավառակից',
    ru: 'Получено с диска',
  },
  path: {
    en: 'Path',
    hy: 'Ուղի',
    ru: 'Путь',
  },
  home: {
    en: 'Home',
    hy: 'Տուն',
    ru: 'Домашняя',
  },
  kinds: {
    en: 'Filter by kind',
    hy: 'Զտիչ ըստ տեսակի',
    ru: 'Фильтр по типу',
  },
  bench: {
    en: 'File bench',
    hy: 'Ֆայլերի աշխատասեղան',
    ru: 'Стенд файлов',
  },

  // ── modified time ─────────────────────────────────────────────────────────
  // `list_dir` has always returned a `modified` timestamp per entry and the page
  // threw it away. These label the real value, and the honest absence of one.
  modified: {
    en: 'Modified',
    hy: 'Փոփոխված',
    ru: 'Изменён',
  },
  modifiedNone: {
    en: 'no modified time reported',
    hy: 'փոփոխման ժամանակ չի հաղորդվել',
    ru: 'время изменения не сообщено',
  },

  // ── ordering (a pure reordering of the real listing) ──────────────────────
  sort: {
    en: 'Sort',
    hy: 'Դասավորել',
    ru: 'Сортировка',
  },
  sortName: {
    en: 'Name',
    hy: 'Անուն',
    ru: 'Имя',
  },
  sortSize: {
    en: 'Size',
    hy: 'Չափ',
    ru: 'Размер',
  },
  sortModified: {
    en: 'Modified',
    hy: 'Փոփոխված',
    ru: 'Изменён',
  },
  sortAsc: {
    en: 'Ascending — click for descending',
    hy: 'Աճող — սեղմիր՝ նվազողի համար',
    ru: 'По возрастанию — нажмите для убывания',
  },
  sortDesc: {
    en: 'Descending — click for ascending',
    hy: 'Նվազող — սեղմիր՝ աճողի համար',
    ru: 'По убыванию — нажмите для возрастания',
  },

  // ── why a file came back read-only ────────────────────────────────────────
  // `read_file` collapses three situations into one `readonly` flag; the page
  // used to print one flat line for all of them. These say which one it was,
  // derived from the size the backend reported (see filesModel.readonlyReason).
  roNotRegular: {
    en: 'Not a regular file (a folder, link or device), so there is no text to show.',
    hy: 'Սովորական ֆայլ չէ (թղթապանակ, հղում կամ սարք) — ցուցադրելու տեքստ չկա։',
    ru: 'Не обычный файл (папка, ссылка или устройство) — текста для показа нет.',
  },
  roTooLarge: {
    en: 'Too large to open here — it is over the 2 MB edit limit, so it was not loaded.',
    hy: 'Չափազանց մեծ է այստեղ բացելու համար — անցնում է 2 ՄԲ սահմանը, ուստի չի բեռնվել։',
    ru: 'Слишком велик, чтобы открыть здесь — больше лимита в 2 МБ, поэтому не загружен.',
  },
  roBinary: {
    en: 'Not text — the bytes are not valid UTF-8, so this cannot be shown or edited here.',
    hy: 'Տեքստ չէ — բայթերը վավեր UTF-8 չեն, ուստի սա չի կարող ցուցադրվել կամ խմբագրվել այստեղ։',
    ru: 'Не текст — байты не являются корректным UTF-8, показать или изменить нельзя.',
  },

  // ── selection tray ────────────────────────────────────────────────────────
  selFilesTotal: {
    en: 'files, totalling',
    hy: 'ֆայլ՝ ընդհանուր',
    ru: 'файлов, всего',
  },
  selFolders: {
    en: 'folders (size not measured)',
    hy: 'թղթապանակ (չափը չի չափվել)',
    ru: 'папок (размер не измерялся)',
  },
} as const;
