// Trilingual UI strings for the Research Observatory screen (src/features/Research.tsx).
// Every user-facing string lives here in en/hy/ru. Consumed via a tiny `L(key)`
// helper that reads the active `lang` from useApp. Technical ids, brand names
// (Bro) and central `t('…')` dictionary keys are intentionally NOT duplicated here.
export const STR = {
  eyebrow: {
    en: 'RESEARCH OBSERVATORY',
    hy: 'ՀԵՏԱԶՈՏԱԿԱՆ ԴԻՏԱԿԵՏ',
    ru: 'ИССЛЕДОВАТЕЛЬСКАЯ ОБСЕРВАТОРИЯ',
  },
  subtitle: {
    en: 'Research records — a question, its findings, and status',
    hy: 'Հետազոտման գրառումներ — հարց, գտածոներ և կարգավիճակ',
    ru: 'Записи исследований — вопрос, его результаты и статус',
  },
  listPanel: {
    en: 'Research',
    hy: 'Հետազոտում',
    ru: 'Исследования',
  },
  detailPanel: {
    en: 'Record',
    hy: 'Գրառում',
    ru: 'Запись',
  },
  searchPlaceholder: {
    en: 'Search research…    press /',
    hy: 'Փնտրել հետազոտում…    սեղմեք /',
    ru: 'Искать исследования…    нажмите /',
  },
  searchLabel: {
    en: 'Search research',
    hy: 'Փնտրել հետազոտում',
    ru: 'Искать исследования',
  },
  emptyTitle: {
    en: 'Bro has run no research yet',
    hy: 'Bro-ն դեռ հետազոտում չի կատարել',
    ru: 'Bro ещё не проводил исследований',
  },
  emptyHint: {
    en: 'Record the first research question to start the log.',
    hy: 'Գրանցիր առաջին հետազոտման հարցը՝ մատյանը սկսելու համար։',
    ru: 'Запишите первый исследовательский вопрос, чтобы начать журнал.',
  },
  filteredTitle: {
    en: 'No matches',
    hy: 'Համընկնումներ չկան',
    ru: 'Нет совпадений',
  },
  filteredHint: {
    en: 'Nothing matches your search.',
    hy: 'Ոչինչ չի համընկնում ձեր որոնման հետ։',
    ru: 'Ничего не найдено по вашему запросу.',
  },
  clearSearch: {
    en: 'Clear search',
    hy: 'Մաքրել որոնումը',
    ru: 'Очистить поиск',
  },
  selectTitle: {
    en: 'Select a record',
    hy: 'Ընտրիր գրառում',
    ru: 'Выберите запись',
  },
  selectHint: {
    en: 'Pick a research record from the list, or press New to add one.',
    hy: 'Ընտրիր հետազոտման գրառում ցանկից կամ սեղմիր «Նոր»՝ ավելացնելու համար։',
    ru: 'Выберите запись исследования из списка или нажмите «Новая», чтобы добавить.',
  },
  question: {
    en: 'Question',
    hy: 'Հարց',
    ru: 'Вопрос',
  },
  findings: {
    en: 'Findings',
    hy: 'Գտածոներ',
    ru: 'Результаты',
  },
  noQuestion: {
    en: 'No question recorded.',
    hy: 'Հարց գրանցված չէ։',
    ru: 'Вопрос не записан.',
  },
  noFindings: {
    en: 'No findings recorded yet.',
    hy: 'Գտածոներ դեռ գրանցված չեն։',
    ru: 'Результаты пока не записаны.',
  },
  created: {
    en: 'Created',
    hy: 'Ստեղծված',
    ru: 'Создано',
  },
  updated: {
    en: 'Updated',
    hy: 'Թարմացված',
    ru: 'Обновлено',
  },
  loadFailed: {
    en: 'Couldn’t load research.',
    hy: 'Չհաջողվեց բեռնել հետազոտումը։',
    ru: 'Не удалось загрузить исследования.',
  },
  newTitle: {
    en: 'New research record',
    hy: 'Նոր հետազոտման գրառում',
    ru: 'Новая запись исследования',
  },
  fTitle: {
    en: 'Title',
    hy: 'Վերնագիր',
    ru: 'Заголовок',
  },
  fQuestion: {
    en: 'Question',
    hy: 'Հարց',
    ru: 'Вопрос',
  },
  fFindings: {
    en: 'Findings',
    hy: 'Գտածոներ',
    ru: 'Результаты',
  },
  fStatus: {
    en: 'Status',
    hy: 'Կարգավիճակ',
    ru: 'Статус',
  },
  questionPlaceholder: {
    en: 'What is being researched?',
    hy: 'Ի՞նչ է հետազոտվում',
    ru: 'Что исследуется?',
  },
  findingsPlaceholder: {
    en: 'What was found…',
    hy: 'Ի՞նչ գտնվեց…',
    ru: 'Что было найдено…',
  },
  saving: {
    en: 'Saving…',
    hy: 'Պահվում է…',
    ru: 'Сохранение…',
  },
  records: {
    en: 'Records',
    hy: 'Գրառումներ',
    ru: 'Записи',
  },
  listNote: {
    en: 'Real records from the store — select one to open it.',
    hy: 'Իրական գրառումներ պահոցից — ընտրիր՝ բացելու համար։',
    ru: 'Реальные записи из хранилища — выберите, чтобы открыть.',
  },
  deleteLabel: {
    en: 'Delete',
    hy: 'Ջնջել',
    ru: 'Удалить',
  },
  deleteTitle: {
    en: 'Delete research record',
    hy: 'Ջնջել հետազոտման գրառումը',
    ru: 'Удалить запись исследования',
  },
  deletePrompt: {
    en: 'This permanently removes the record.',
    hy: 'Սա ընդմիշտ հեռացնում է գրառումը։',
    ru: 'Это навсегда удалит запись.',
  },
  deleting: {
    en: 'Deleting…',
    hy: 'Ջնջվում է…',
    ru: 'Удаление…',
  },
  statusOpen: {
    en: 'Open',
    hy: 'Բաց',
    ru: 'Открыто',
  },
  statusInProgress: {
    en: 'In progress',
    hy: 'Ընթացքի մեջ',
    ru: 'В процессе',
  },
  statusDone: {
    en: 'Done',
    hy: 'Ավարտված',
    ru: 'Готово',
  },
} as const;
