// Page-local copy for the Files bench. These are labels that live on this thin
// page rather than in the shared i18n dictionaries. Every entry is authored in
// all three supported languages (en / hy / ru) so no language falls back.

export const STR = {
  filter: {
    en: 'Filter files…',
    hy: 'Զտել ֆայլերը…',
    ru: 'Фильтр файлов…',
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
    hy: 'ՏՎՅԱԼ-ՍԵՂԱՆ · SPATIAL WORKSPACE',
    ru: 'СТЕНД ДАННЫХ · SPATIAL WORKSPACE',
  },
  indexing: {
    en: 'Bro · indexing',
    hy: 'Bro · ինդեքսավորում',
    ru: 'Bro · индексация',
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
} as const;
