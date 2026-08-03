// ── §D `library` ❑ Դարան — page-local trilingual copy (en / hy / ru). ─────────
// Every user-facing string on the Library screen lives here so switching the
// app language re-renders the whole page in one language. Central dictionary
// keys (`t('…')`) and technical ids / brand names stay out of this file.
export const STR = {
  eyebrow: {
    en: 'LIBRARY · ARCHIVE',
    hy: 'ԴԱՐԱՆ · ԱՐԽԻՎ',
    ru: 'БИБЛИОТЕКА · АРХИВ',
  },
  watching: {
    en: 'Bro · watching the library',
    hy: 'Bro · դարանը դիտում է',
    ru: 'Bro · наблюдает за библиотекой',
  },
  subtitle: {
    en: 'Component, prompt & pattern catalog with live previews',
    hy: 'Բաղադրիչների, հուշումների և ձևանմուշների դարան՝ կենդանի նախադիտումով',
    ru: 'Каталог компонентов, промптов и паттернов с живым предпросмотром',
  },
  searchPlaceholder: {
    en: 'Search the library…    press /',
    hy: 'Փնտրել դարանում…    սեղմեք /',
    ru: 'Искать в библиотеке…    нажмите /',
  },
  searchLabel: {
    en: 'Search the library',
    hy: 'Փնտրել դարանում',
    ru: 'Искать в библиотеке',
  },
  filterLabel: {
    en: 'Filter by type',
    hy: 'Զտել ըստ տեսակի',
    ru: 'Фильтровать по типу',
  },
  all: {
    en: 'All',
    hy: 'Բոլորը',
    ru: 'Все',
  },
  kindComponent: {
    en: 'Components',
    hy: 'Բաղադրիչներ',
    ru: 'Компоненты',
  },
  kindPrompt: {
    en: 'Prompts',
    hy: 'Հուշումներ',
    ru: 'Промпты',
  },
  kindPattern: {
    en: 'Patterns',
    hy: 'Ձևանմուշներ',
    ru: 'Паттерны',
  },
  totalsLabel: {
    en: 'Library totals',
    hy: 'Դարանի հաշվարկ',
    ru: 'Итоги библиотеки',
  },
  total: {
    en: 'total',
    hy: 'ընդամենը',
    ru: 'всего',
  },
  indexTitle: {
    en: 'Archive index',
    hy: 'Արխիվի ինդեքս',
    ru: 'Индекс архива',
  },
  emptyTitle: {
    en: 'Nothing saved yet',
    hy: 'Դեռ ոչինչ պահված չէ',
    ru: 'Пока ничего не сохранено',
  },
  emptyHint: {
    en: 'Save the first component, prompt or pattern to start the library.',
    hy: 'Պահիր առաջին բաղադրիչը, հուշումը կամ ձևանմուշը՝ դարանը սկսելու համար։',
    ru: 'Сохраните первый компонент, промпт или паттерн, чтобы начать библиотеку.',
  },
  filteredTitle: {
    en: 'No matches',
    hy: 'Համընկնումներ չկան',
    ru: 'Совпадений нет',
  },
  filteredHint: {
    en: 'Nothing matches your search and filters.',
    hy: 'Ոչինչ չի համընկնում ձեր որոնման և զտիչների հետ։',
    ru: 'Ничего не соответствует вашему поиску и фильтрам.',
  },
  clearFilters: {
    en: 'Clear search & filters',
    hy: 'Մաքրել որոնումն ու զտիչները',
    ru: 'Очистить поиск и фильтры',
  },
  previewEmpty: {
    en: 'Select an item to preview it.',
    hy: 'Ընտրեք տարր՝ նախադիտելու համար։',
    ru: 'Выберите элемент для предпросмотра.',
  },
  listLabel: {
    en: 'Library results',
    hy: 'Դարանի արդյունքներ',
    ru: 'Результаты библиотеки',
  },
  tags: {
    en: 'Tags',
    hy: 'Պիտակներ',
    ru: 'Теги',
  },
  loadFailed: {
    en: 'Couldn’t load the library.',
    hy: 'Չհաջողվեց բեռնել դարանը։',
    ru: 'Не удалось загрузить библиотеку.',
  },
  newTitle: {
    en: 'New library item',
    hy: 'Նոր դարանի տարր',
    ru: 'Новый элемент библиотеки',
  },
  fTitle: {
    en: 'Title',
    hy: 'Վերնագիր',
    ru: 'Название',
  },
  fKind: {
    en: 'Type',
    hy: 'Տեսակ',
    ru: 'Тип',
  },
  fBody: {
    en: 'Body',
    hy: 'Բովանդակություն',
    ru: 'Содержимое',
  },
  fTags: {
    en: 'Tags',
    hy: 'Պիտակներ',
    ru: 'Теги',
  },
  bodyPlaceholder: {
    en: 'The prompt, pattern or component blurb…',
    hy: 'Հուշումը, ձևանմուշը կամ բաղադրիչի նկարագիրը…',
    ru: 'Промпт, паттерн или описание компонента…',
  },
  tagsPlaceholder: {
    en: 'react, form, accessible',
    hy: 'react, form, accessible',
    ru: 'react, form, accessible',
  },
  saving: {
    en: 'Saving…',
    hy: 'Պահվում է…',
    ru: 'Сохранение…',
  },
  deleteTitle: {
    en: 'Delete library item',
    hy: 'Ջնջել դարանի տարրը',
    ru: 'Удалить элемент библиотеки',
  },
  deleteConfirm: {
    en: 'Delete this item? This can’t be undone.',
    hy: 'Ջնջե՞լ այս տարրը։ Սա հնարավոր չէ հետարկել։',
    ru: 'Удалить этот элемент? Это действие необратимо.',
  },
  previewPrefix: {
    en: 'Preview: ',
    hy: 'Նախադիտում՝ ',
    ru: 'Предпросмотр: ',
  },
  // Count-label noun forms — English singular/plural, Armenian invariant,
  // Russian three-way plural (1 / 2–4 / 5+).
  resultOne: {
    en: 'result',
    hy: 'արդյունք',
    ru: 'результат',
  },
  resultFew: {
    en: 'results',
    hy: 'արդյունք',
    ru: 'результата',
  },
  resultMany: {
    en: 'results',
    hy: 'արդյունք',
    ru: 'результатов',
  },
} as const;
