// Page-local copy for the Knowledge codex. These are labels that live on this
// page rather than in the shared i18n dictionaries. Every entry is authored in
// all three supported languages (en / hy / ru) so no language falls back.

import type { Lang } from '../domain/enums';

export const STR = {
  // ── Article editor ─────────────────────────────────────────────────────
  editArticle: {
    en: 'Edit article',
    hy: 'Խմբագրել հոդվածը',
    ru: 'Редактировать статью',
  },
  codexEditor: {
    en: 'Codex editor',
    hy: 'Կոդեքսի խմբագրիչ',
    ru: 'Редактор кодекса',
  },
  articleEditor: {
    en: 'Article editor',
    hy: 'Հոդվածի խմբագրիչ',
    ru: 'Редактор статьи',
  },
  editNotAvailable: {
    en: 'Editing not available yet',
    hy: 'Խմբագրումը դեռ հասանելի չէ',
    ru: 'Редактирование пока недоступно',
  },
  editBlockedBody: {
    en: 'The desktop knowledge store has no update command yet, so this article cannot be re-saved. Its text is shown read-only below.',
    hy: 'Desktop-ի գիտելիքի պահոցը դեռ չունի թարմացման հրաման, ուստի այս հոդվածը չի կարող վերապահվել։ Տեքստը ցուցադրվում է միայն կարդալու համար։',
    ru: 'В хранилище знаний рабочего стола пока нет команды обновления, поэтому эту статью нельзя пересохранить. Её текст показан ниже только для чтения.',
  },
  sourcePlaceholder: {
    en: 'Citation — URL, book, or note',
    hy: 'Հղում — URL, գիրք կամ նշում',
    ru: 'Ссылка — URL, книга или заметка',
  },
  tagsPlaceholder: {
    en: 'architecture, sqlite',
    hy: 'ճարտարապետություն, sqlite',
    ru: 'архитектура, sqlite',
  },
  toSave: {
    en: 'to save',
    hy: 'պահելու համար',
    ru: 'чтобы сохранить',
  },
  toCancel: {
    en: 'to cancel',
    hy: 'չեղարկելու համար',
    ru: 'чтобы отменить',
  },
  editExistingBlocked: {
    en: 'Editing an existing article is not available yet.',
    hy: 'Առկա հոդվածի խմբագրումը դեռ հասանելի չէ։',
    ru: 'Редактирование существующей статьи пока недоступно.',
  },

  // ── Collections & metrics ──────────────────────────────────────────────
  allArticles: {
    en: 'All articles',
    hy: 'Բոլոր հոդվածները',
    ru: 'Все статьи',
  },
  untagged: {
    en: 'Untagged',
    hy: 'Առանց պիտակի',
    ru: 'Без метки',
  },
  metricArticles: {
    en: 'articles · store',
    hy: 'հոդված · պահոց',
    ru: 'статьи · хранилище',
  },
  metricCollections: {
    en: 'collections',
    hy: 'հավաքածու',
    ru: 'коллекции',
  },
  metricCited: {
    en: 'cited',
    hy: 'հղումով',
    ru: 'со ссылкой',
  },

  // ── Empty / list states ────────────────────────────────────────────────
  noMatchTitle: {
    en: 'No matching articles',
    hy: 'Համընկնող հոդվածներ չկան',
    ru: 'Нет подходящих статей',
  },
  noMatchHint: {
    en: 'No article matches this search or collection. Clear the filter to see all knowledge.',
    hy: 'Ոչ մի հոդված չի համընկնում այս որոնման կամ հավաքածուի հետ։ Մաքրիր զտիչը՝ ամբողջ գիտելիքը տեսնելու համար։',
    ru: 'Ни одна статья не соответствует этому поиску или коллекции. Очистите фильтр, чтобы увидеть все знания.',
  },
  emptyTitle: {
    en: 'Bro has no knowledge yet',
    hy: 'Bro-ն դեռ գիտելիք չունի',
    ru: 'У Bro пока нет знаний',
  },
  emptyHint: {
    en: 'Create the first article to start the knowledge base.',
    hy: 'Ստեղծիր առաջին հոդվածը՝ գիտելիքի բազան սկսելու համար։',
    ru: 'Создайте первую статью, чтобы начать базу знаний.',
  },
  articlesLabel: {
    en: 'Articles',
    hy: 'Հոդվածներ',
    ru: 'Статьи',
  },

  // ── Reading rail ───────────────────────────────────────────────────────
  codexCore: {
    en: 'CODEX CORE',
    hy: 'ԿՈԴԵՔՍԻ ՄԻՋՈՒԿ',
    ru: 'ЯДРО КОДЕКСА',
  },
  selectArticle: {
    en: 'Select an article',
    hy: 'Ընտրիր հոդված',
    ru: 'Выберите статью',
  },
  selectArticleHint: {
    en: 'Pick an article from the list, or press New to write one.',
    hy: 'Ընտրիր հոդված ցանկից կամ սեղմիր «Նոր»՝ գրելու համար։',
    ru: 'Выберите статью из списка или нажмите «Новая», чтобы написать.',
  },
  knowledgeNode: {
    en: 'KNOWLEDGE NODE · ARTICLE',
    hy: 'ԳԻՏԵԼԻՔ-ՀԱՆԳՈՒՅՑ · ՀՈԴՎԱԾ',
    ru: 'УЗЕЛ ЗНАНИЙ · СТАТЬЯ',
  },
  openEditor: {
    en: 'Open the editor for this article',
    hy: 'Բացել այս հոդվածի խմբագրիչը',
    ru: 'Открыть редактор этой статьи',
  },
  deleteArticle: {
    en: 'Delete this article',
    hy: 'Ջնջել այս հոդվածը',
    ru: 'Удалить эту статью',
  },
  articleBody: {
    en: 'Article body',
    hy: 'Հոդվածի բովանդակություն',
    ru: 'Тело статьи',
  },
  noBody: {
    en: 'This article has no body text.',
    hy: 'Այս հոդվածը մարմնի տեքստ չունի։',
    ru: 'У этой статьи нет основного текста.',
  },
  citations: {
    en: 'Citations',
    hy: 'Հղումներ',
    ru: 'Ссылки',
  },
  citation: {
    en: 'Citation',
    hy: 'Հղում',
    ru: 'Ссылка',
  },
  noSource: {
    en: 'No source recorded for this article.',
    hy: 'Այս հոդվածի համար աղբյուր գրանցված չէ։',
    ru: 'Для этой статьи источник не указан.',
  },
  details: {
    en: 'Details',
    hy: 'Մանրամասներ',
    ru: 'Подробности',
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

  // ── Page chrome ────────────────────────────────────────────────────────
  knowledgeBaseEyebrow: {
    en: 'KNOWLEDGE BASE · NEURAL MAP',
    hy: 'ԳԻՏԵԼԻՔԻ ԲԱԶԱ · ՆԵՅՐՈ-ՔԱՐՏԵԶ',
    ru: 'БАЗА ЗНАНИЙ · НЕЙРОКАРТА',
  },
  // Header pill — bound to the REAL `search_knowledge` / `list_knowledge` read state.
  // There is no background recall process to be "active": the page issues one read
  // and shows what came back, so the pill names that outcome and nothing more.
  recallReading: {
    en: 'Reading the store…',
    hy: 'Կարդում ենք պահոցը…',
    ru: 'Читаем хранилище…',
  },
  recallUnavailable: {
    en: 'Store unavailable',
    hy: 'Պահոցն անհասանելի է',
    ru: 'Хранилище недоступно',
  },
  recallLoaded: {
    en: 'Read from the store',
    hy: 'Կարդացված է պահոցից',
    ru: 'Прочитано из хранилища',
  },

  // ── Delete refusal (the delete command may be denied by the capability set) ──
  deleteRefusedTitle: {
    en: 'Delete refused — nothing was removed',
    hy: 'Ջնջումը մերժվեց — ոչինչ չհեռացվեց',
    ru: 'Удаление отклонено — ничего не удалено',
  },
  deleteRefusedBody: {
    en: 'The backend rejected this delete, so the article is still in the store and still listed below.',
    hy: 'Backend-ը մերժեց այս ջնջումը, ուստի հոդվածը դեռ պահոցում է և դեռ ցուցակում է ստորև։',
    ru: 'Бэкенд отклонил это удаление, поэтому статья всё ещё в хранилище и всё ещё в списке ниже.',
  },
  deleting: {
    en: 'Deleting…',
    hy: 'Ջնջվում է…',
    ru: 'Удаление…',
  },
  searchIndex: {
    en: 'Search index',
    hy: 'Որոնման ինդեքս',
    ru: 'Индекс поиска',
  },
  nodes: {
    en: 'nodes',
    hy: 'հանգույց',
    ru: 'узлы',
  },
  collections: {
    en: 'Collections',
    hy: 'Հավաքածուներ',
    ru: 'Коллекции',
  },
  knowledgeBase: {
    en: 'Knowledge base',
    hy: 'Գիտելիքի բազա',
    ru: 'База знаний',
  },
  countedFromStore: {
    en: 'counted from the store',
    hy: 'պահոցից հաշված',
    ru: 'посчитано из хранилища',
  },
  // Heading for the per-article local write record block.
  recordSection: {
    en: 'Write record',
    hy: 'Գրման գրանցում',
    ru: 'Журнал записи',
  },
  // Provenance stated plainly, exactly as the Memory page does — and kept CURRENT.
  //
  // This line used to read "Local store · no verification chain". That was true when it
  // was written and is not true now: every knowledge write appends a record in the same
  // transaction as the row (`core/src/local_write_record.rs`, migration 0021), hashing
  // the note's content into an append-only chain the database itself enforces, so a
  // later out-of-band edit reads back as `content_diverged`. A stale honest label
  // becomes a dishonest one, so the line now says what the record really is.
  //
  // What it must NOT say: nothing here is signed — no key, no manifest, no authority, no
  // containment — and the record attests CONTENT, never the writer. So no "verified", no
  // "trusted", and no badge a reader would file beside a governed turn's.
  provenance: {
    en: 'Local store · each write appends a local record · shows the row is unchanged since it was written, never who wrote it',
    hy: 'Տեղական պահոց · ամեն գրում ավելացնում է լոկալ գրանցում · ցույց է տալիս, որ տողը գրվելուց հետո չի փոխվել, բայց ոչ թե ով է գրել',
    ru: 'Локальное хранилище · каждая запись добавляет локальный журнальный след · показывает, что строка не менялась с момента записи, но не кто её записал',
  },
} as const;

// ── Interpolated strings — authored per language, args filled at the call
//    site. Each returns the natural phrasing for the active language.
export const fmt = {
  articlesFound: (lang: Lang, n: number): string => ({
    en: `${n} ${n === 1 ? 'article' : 'articles'} found`,
    hy: `Գտնվեց ${n} հոդված`,
    ru: `Найдено статей: ${n}`,
  }[lang]),
  articleSaved: (lang: Lang, title: string): string => ({
    en: `Article “${title}” saved`,
    hy: `«${title}» հոդվածը պահվեց`,
    ru: `Статья «${title}» сохранена`,
  }[lang]),
  articleDeleted: (lang: Lang, title: string): string => ({
    en: `Article “${title}” deleted`,
    hy: `«${title}» հոդվածը ջնջվեց`,
    ru: `Статья «${title}» удалена`,
  }[lang]),
  filterToTag: (lang: Lang, tag: string): string => ({
    en: `Filter to #${tag}`,
    hy: `Զտել #${tag}`,
    ru: `Фильтровать по #${tag}`,
  }[lang]),
  // Announced ONLY on a real backend rejection — the article was not deleted.
  articleDeleteRefused: (lang: Lang, title: string, reason: string): string => ({
    en: `Delete refused: article “${title}” was not removed. ${reason}`,
    hy: `Ջնջումը մերժվեց. «${title}» հոդվածը չհեռացվեց։ ${reason}`,
    ru: `Удаление отклонено: статья «${title}» не удалена. ${reason}`,
  }[lang]),
} as const;
