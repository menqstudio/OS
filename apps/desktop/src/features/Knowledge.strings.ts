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
  recallActive: {
    en: 'Bro recall · active',
    hy: 'Bro վերհիշում · ակտիվ',
    ru: 'Bro память · активна',
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
} as const;
