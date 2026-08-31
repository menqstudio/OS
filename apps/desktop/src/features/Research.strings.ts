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

  // -- §D: the governed run, its verified-receipt badge, and its `blocked` state --
  runPanel: {
    en: 'GOVERNED RUN',
    hy: 'ԿԱՌԱՎԱՐՎՈՂ ԿԱՏԱՐՈՒՄ',
    ru: 'УПРАВЛЯЕМЫЙ ЗАПУСК',
  },
  runIt: {
    en: 'Run this question',
    hy: 'Կատարել այս հարցը',
    ru: 'Выполнить этот вопрос',
  },
  running: {
    en: 'Running…',
    hy: 'Կատարվում ա…',
    ru: 'Выполняется…',
  },
  runHint: {
    en: 'Enter runs · Esc cancels. The question goes through the governed turn — the same path chat uses.',
    hy: 'Enter-ը կատարում ա · Esc-ը չեղարկում։ Հարցը գնում ա կառավարվող շրջանով՝ նույն ուղին, ինչ չաթը։',
    ru: 'Enter запускает · Esc отменяет. Вопрос идёт через управляемый ход — тот же путь, что и чат.',
  },
  needQuestion: {
    en: 'This record has no question to run.',
    hy: 'Այս գրառումը կատարելու հարց չունի։',
    ru: 'У этой записи нет вопроса для выполнения.',
  },
  runBlocked: {
    en: 'Refused at the governed wall',
    hy: 'Մերժվել ա կառավարվող պատի մոտ',
    ru: 'Отклонено управляемой стеной',
  },
  runBlockedNote: {
    en: 'No result was produced and nothing was saved. The reason is the engine’s own, shown exactly as it arrived.',
    hy: 'Արդյունք չի ստացվել ու ոչինչ չի պահպանվել։ Պատճառը շարժիչինն ա, ցույց ա տրված ուղիղ այնպես, ինչպես եկել ա։',
    ru: 'Результат не получен и ничего не сохранено. Причина — от движка, показана ровно так, как пришла.',
  },
  runFailed: {
    en: 'The run failed',
    hy: 'Կատարումը ձախողվեց',
    ru: 'Запуск не удался',
  },
  // The held answer, described by what ACTUALLY produced it — sixth independent audit, `A-05`.
  //
  // There used to be ONE pair here, `verifiedHeld` / `verifiedHeldNote`, reading "Verified · held"
  // and "Verified desktop-side and held by the backend" for every held answer. Two paths stash
  // one, and on a shipped install the only reachable path runs no governed turn, issues no
  // challenge and produces no receipt. The strongest claim on the page was attached to the weakest
  // outcome the app has.
  //
  // Four pairs now, one per provenance — including one for a value this version does not
  // recognise, because an unknown outcome must read as a warning and never as a pass.
  heldVerified: {
    en: 'Verified · held',
    hy: 'Ստուգված · պահված',
    ru: 'Проверено · удержано',
  },
  heldVerifiedNote: {
    en: 'A governed turn produced this and its receipt verified against a trusted manifest. It is held by the backend; saving files it to knowledge, and the app window never receives the text.',
    hy: 'Սա արտադրել ա կառավարվող փոխանցումը, ու ստացականը ստուգվել ա վստահելի manifest-ով։ Պահվում ա backend-ի մոտ; պահպանելը գրանցում ա գիտելիքում, ու պատուհանը տեքստը չի ստանում։',
    ru: 'Это произвёл управляемый ход, и его квитанция проверена по доверенному манифесту. Удерживается бэкендом; сохранение записывает его в знания, окно текст не получает.',
  },
  heldDevelopment: {
    en: 'Development · not trusted',
    hy: 'Մշակում · վստահելի չէ',
    ru: 'Разработка · не доверенное',
  },
  heldDevelopmentNote: {
    en: 'A governed turn produced this, but the receipt verified against NO trusted manifest — this is the development outcome, not a production one. It is held by the backend; the app window never receives the text.',
    hy: 'Սա արտադրել ա կառավարվող փոխանցումը, բայց ստացականը ստուգվել ա ԱՌԱՆՑ վստահելի manifest-ի — սա մշակման արդյունք ա, ոչ արտադրական։ Պահվում ա backend-ի մոտ; պատուհանը տեքստը չի ստանում։',
    ru: 'Это произвёл управляемый ход, но квитанция проверена БЕЗ доверенного манифеста — это результат разработки, а не production. Удерживается бэкендом; окно текст не получает.',
  },
  heldUngoverned: {
    en: 'Ungoverned · no receipt',
    hy: 'Չկառավարվող · առանց ստացականի',
    ru: 'Неуправляемое · без квитанции',
  },
  heldUngovernedNote: {
    en: 'No governed turn ran. No challenge, no receipt, nothing verified — this answer came straight from the model. It is held by the backend, and saving it records that provenance in the note.',
    hy: 'Կառավարվող փոխանցում չի կատարվել։ Ոչ մարտահրավեր, ոչ ստացական, ոչինչ ստուգված չէ — այս պատասխանը ուղիղ մոդելից ա։ Պահվում ա backend-ի մոտ, ու պահպանելը գրանցում ա հենց այդ ծագումը գրառման մեջ։',
    ru: 'Управляемый ход не выполнялся. Ни вызова, ни квитанции, ничего не проверено — этот ответ пришёл прямо от модели. Удерживается бэкендом, и сохранение записывает это происхождение в заметку.',
  },
  heldUnknown: {
    en: 'Unrecognised outcome',
    hy: 'Չճանաչված արդյունք',
    ru: 'Нераспознанный результат',
  },
  heldUnknownNote: {
    en: 'The backend reported a provenance this version does not recognise. Treated as unverified: an outcome nobody can name is not a pass.',
    hy: 'Backend-ը հաղորդել ա ծագում, որ այս տարբերակը չի ճանաչում։ Համարվում ա չստուգված․ արդյունքը, որին ոչ ոք անուն չի տալիս, անցում չէ։',
    ru: 'Бэкенд сообщил происхождение, которое эта версия не распознаёт. Считается непроверенным: результат, который никто не может назвать, — не пропуск.',
  },
  saveToKnowledge: {
    en: 'Save to knowledge',
    hy: 'Պահպանել գիտելիքում',
    ru: 'Сохранить в знания',
  },
  savedToKnowledge: {
    en: 'Saved to knowledge',
    hy: 'Պահպանվեց գիտելիքում',
    ru: 'Сохранено в знания',
  },
} as const;
