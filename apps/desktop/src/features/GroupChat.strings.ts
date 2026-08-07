// Trilingual copy for the Group Chat view's CONSENSUS deck (Phase 7). Per-feature
// strings live here rather than in the central i18n catalog; the shared chat keys
// (t('chat.…'), t('action.…')) still come from the catalog.
//
// A note on the wording choices: every outcome string names what is true, never
// what is hoped. "NOT REACHED" and "PENDING" are stated as plainly as "REACHED",
// and the dissent labels never soften — a surface that says "mostly agreed" when
// someone said NO is the failure this deck exists to prevent.

export const STR = {
  // The room shows TWO delegation panels covering different streams: the one the chat thread
  // renders for its own turns, and this one for the asks the consensus deck sends. They need
  // different accessible names, or neither can say which turns it actually saw.
  deckDelegationsLabel: {
    en: 'Specialists the consensus deck put on this',
    hy: 'Մասնագետներ, որոնց կոնսենսուսի վահանակը գործ է տվել',
    ru: 'Специалисты, которых панель консенсуса привлекла',
  },
  consensusEyebrow: {
    en: 'CONSENSUS',
    hy: 'ԿՈՆՍԵՆՍՈՒՍ',
    ru: 'КОНСЕНСУС',
  },
  consensusNote: {
    en: 'Positions are read from this room’s transcript — each one is a message a participant actually wrote.',
    hy: 'Դիրքորոշումները կարդացվում են այս սենյակի գրառումներից — ամեն մեկը հաղորդագրություն է, որ մասնակիցն իրոք գրել է։',
    ru: 'Позиции читаются из стенограммы этой комнаты — каждая из них сообщение, которое участник действительно написал.',
  },
  roomLabel: {
    en: 'Room',
    hy: 'Սենյակ',
    ru: 'Комната',
  },
  showRoom: {
    en: 'Show this room above',
    hy: 'Ցույց տալ այս սենյակը վերևում',
    ru: 'Показать эту комнату выше',
  },
  noRooms: {
    en: 'No group rooms yet',
    hy: 'Դեռ խմբային սենյակ չկա',
    ru: 'Групповых комнат пока нет',
  },
  noRoomsHint: {
    en: 'Create a room above, then a consensus round can be opened in it.',
    hy: 'Ստեղծիր սենյակ վերևում, հետո դրանում կարելի է կոնսենսուսի փուլ բացել։',
    ru: 'Создайте комнату выше — затем в ней можно открыть раунд консенсуса.',
  },
  noRounds: {
    en: 'No consensus round has been opened in this room',
    hy: 'Այս սենյակում կոնսենսուսի փուլ չի բացվել',
    ru: 'В этой комнате не открыт ни один раунд консенсуса',
  },
  noRoundsHint: {
    en: 'Ask the room a question below. The rule and who is asked are fixed when the round opens.',
    hy: 'Ներքևում հարց տուր սենյակին։ Կանոնը և ում են հարցնում ամրագրվում են փուլը բացելիս։',
    ru: 'Задайте комнате вопрос ниже. Правило и состав опрошенных фиксируются при открытии раунда.',
  },

  // ── opening a round ───────────────────────────────────────────────────────
  openRoundTitle: {
    en: 'Ask the room',
    hy: 'Հարցրու սենյակին',
    ru: 'Спросить комнату',
  },
  questionLabel: {
    en: 'Question',
    hy: 'Հարց',
    ru: 'Вопрос',
  },
  questionPlaceholder: {
    en: 'One question the room decides…',
    hy: 'Մեկ հարց, որ սենյակը որոշում է…',
    ru: 'Один вопрос, который решает комната…',
  },
  ruleLabel: {
    en: 'Rule',
    hy: 'Կանոն',
    ru: 'Правило',
  },
  askLabel: {
    en: 'Ask',
    hy: 'Հարցնել',
    ru: 'Опросить',
  },
  openRound: {
    en: 'Open round',
    hy: 'Բացել փուլը',
    ru: 'Открыть раунд',
  },
  opening: {
    en: 'Asking…',
    hy: 'Հարցնում է…',
    ru: 'Опрашивает…',
  },
  askMissing: {
    en: 'Ask again those who have not answered',
    hy: 'Կրկին հարցնել նրանց, ովքեր չեն պատասխանել',
    ru: 'Спросить ещё раз тех, кто не ответил',
  },
  needQuestion: {
    en: 'Write the question the room is deciding.',
    hy: 'Գրիր հարցը, որ սենյակը որոշում է։',
    ru: 'Напишите вопрос, который решает комната.',
  },
  needParticipants: {
    en: 'Pick at least one participant to ask.',
    hy: 'Ընտրիր առնվազն մեկ մասնակից, ում հարցնել։',
    ru: 'Выберите хотя бы одного участника для опроса.',
  },
  postFailed: {
    en: 'The round was not opened',
    hy: 'Փուլը չբացվեց',
    ru: 'Раунд не был открыт',
  },
  askFailed: {
    en: 'No position was collected from',
    hy: 'Դիրքորոշում չհավաքվեց՝',
    ru: 'Позиция не получена от',
  },

  // ── rules ─────────────────────────────────────────────────────────────────
  ruleUnanimous: {
    en: 'Unanimous',
    hy: 'Միաձայն',
    ru: 'Единогласно',
  },
  ruleMajority: {
    en: 'Majority',
    hy: 'Մեծամասնություն',
    ru: 'Большинство',
  },
  ruleSupermajority: {
    en: 'Two thirds',
    hy: 'Երկու երրորդ',
    ru: 'Две трети',
  },
  ruleStated: {
    en: 'Rule',
    hy: 'Կանոն',
    ru: 'Правило',
  },
  needsYes: {
    en: 'YES needed',
    hy: 'ԱՅՈ պետք է',
    ru: 'нужно ДА',
  },
  fullParticipation: {
    en: 'and everyone asked must answer',
    hy: 'և բոլոր հարցվածները պիտի պատասխանեն',
    ru: 'и все опрошенные должны ответить',
  },
  ruleFixedNote: {
    en: 'The rule and the roster were fixed when the round opened — they cannot be chosen after the answers are in.',
    hy: 'Կանոնը և կազմը ամրագրվել են փուլը բացելիս — դրանք հնարավոր չէ ընտրել պատասխաններից հետո։',
    ru: 'Правило и состав зафиксированы при открытии раунда — их нельзя выбрать после получения ответов.',
  },

  // ── outcomes ──────────────────────────────────────────────────────────────
  outcomeReached: {
    en: 'CONSENSUS REACHED',
    hy: 'ԿՈՆՍԵՆՍՈՒՍԸ ՁԵՌՔ Է ԲԵՐՎԱԾ',
    ru: 'КОНСЕНСУС ДОСТИГНУТ',
  },
  outcomeNotReached: {
    en: 'NOT REACHED',
    hy: 'ՁԵՌՔ ՉԻ ԲԵՐՎԵԼ',
    ru: 'НЕ ДОСТИГНУТ',
  },
  outcomePending: {
    en: 'STILL OPEN',
    hy: 'ԴԵՌ ԲԱՑ Է',
    ru: 'ЕЩЁ ОТКРЫТ',
  },
  reasonThresholdMet: {
    en: 'Everyone asked answered and the rule’s threshold was met.',
    hy: 'Բոլոր հարցվածները պատասխանել են, և կանոնի շեմը լրացվել է։',
    ru: 'Все опрошенные ответили, и порог правила достигнут.',
  },
  reasonThresholdMissed: {
    en: 'Everyone asked answered, but the rule’s threshold was not met.',
    hy: 'Բոլոր հարցվածները պատասխանել են, բայց կանոնի շեմը չի լրացվել։',
    ru: 'Все опрошенные ответили, но порог правила не достигнут.',
  },
  reasonThresholdUnreachable: {
    en: 'The threshold can no longer be met, even if everyone still silent said YES.',
    hy: 'Շեմն այլևս հնարավոր չէ լրացնել, նույնիսկ եթե բոլոր լռողները ԱՅՈ ասեն։',
    ru: 'Порог уже недостижим, даже если все молчащие скажут ДА.',
  },
  reasonAwaitingPositions: {
    en: 'Not everyone asked has answered. Silence is not agreement, so nothing is decided yet.',
    hy: 'Ոչ բոլոր հարցվածներն են պատասխանել։ Լռությունը համաձայնություն չէ, ուստի դեռ ոչինչ որոշված չէ։',
    ru: 'Ответили не все опрошенные. Молчание не согласие, поэтому решения ещё нет.',
  },
  reasonNoParticipants: {
    en: 'This round asked nobody, so there is nothing to agree to.',
    hy: 'Այս փուլը ոչ մեկին չի հարցրել, ուստի համաձայնվելու բան չկա։',
    ru: 'В этом раунде никого не спросили, поэтому соглашаться не о чем.',
  },

  // ── tally & dissent ───────────────────────────────────────────────────────
  tallyLabel: {
    en: 'TALLY',
    hy: 'ՀԱՇՎԱՐԿ',
    ru: 'ПОДСЧЁТ',
  },
  stanceYes: {
    en: 'YES',
    hy: 'ԱՅՈ',
    ru: 'ДА',
  },
  stanceNo: {
    en: 'NO',
    hy: 'ՈՉ',
    ru: 'НЕТ',
  },
  stanceAbstain: {
    en: 'ABSTAINED',
    hy: 'ՁԵՌՆՊԱՀ',
    ru: 'ВОЗДЕРЖАЛСЯ',
  },
  noAnswer: {
    en: 'NO ANSWER',
    hy: 'ՊԱՏԱՍԽԱՆ ՉԿԱ',
    ru: 'НЕТ ОТВЕТА',
  },
  dissentLabel: {
    en: 'DISSENT',
    hy: 'ԱՆՀԱՄԱՁԱՅՆՈՒԹՅՈՒՆ',
    ru: 'НЕСОГЛАСИЕ',
  },
  noDissent: {
    en: 'Nobody recorded a NO and nobody abstained.',
    hy: 'Ոչ ոք ՈՉ չի գրանցել և ոչ ոք ձեռնպահ չի մնացել։',
    ru: 'Никто не записал НЕТ и никто не воздержался.',
  },
  noReason: {
    en: 'no reason given',
    hy: 'պատճառ նշված չէ',
    ru: 'причина не указана',
  },
  silentLabel: {
    en: 'ASKED, NOT ANSWERED',
    hy: 'ՀԱՐՑՎԵԼ Է, ՉԻ ՊԱՏԱՍԽԱՆԵԼ',
    ru: 'СПРОШЕН, НЕ ОТВЕТИЛ',
  },
  revisedLabel: {
    en: 'REVISED — an earlier answer was replaced',
    hy: 'ՎԵՐԱՆԱՅՎԱԾ — ավելի վաղ պատասխանը փոխարինվել է',
    ru: 'ИЗМЕНЕНО — более ранний ответ заменён',
  },
  unsolicitedLabel: {
    en: 'NOT ASKED — recorded, not counted',
    hy: 'ՉԻ ՀԱՐՑՎԵԼ — գրանցված է, հաշվված չէ',
    ru: 'НЕ СПРАШИВАЛИ — записано, не засчитано',
  },
  ambiguousLabel: {
    en: 'UNREADABLE ANSWER — not counted',
    hy: 'ԱՆԸՆԹԵՌՆԵԼԻ ՊԱՏԱՍԽԱՆ — հաշվված չէ',
    ru: 'НЕЧИТАЕМЫЙ ОТВЕТ — не засчитан',
  },
  malformedLabel: {
    en: 'MALFORMED — this opened no round',
    hy: 'ԱՆՎԱՎԵՐ — սա փուլ չի բացել',
    ru: 'НЕКОРРЕКТНО — раунд не открыт',
  },
  malformedMissingQuestion: {
    en: 'no question',
    hy: 'հարց չկա',
    ru: 'нет вопроса',
  },
  malformedUnknownRule: {
    en: 'unknown rule',
    hy: 'անհայտ կանոն',
    ru: 'неизвестное правило',
  },
  malformedMissingAsked: {
    en: 'nobody asked',
    hy: 'ոչ ոքի չեն հարցրել',
    ru: 'никого не спросили',
  },
  askedByLabel: {
    en: 'asked by',
    hy: 'հարցրել է',
    ru: 'спросил',
  },
  earlierRounds: {
    en: 'Earlier rounds',
    hy: 'Նախորդ փուլերը',
    ru: 'Предыдущие раунды',
  },

  // ── delegation inside the room ────────────────────────────────────────────
  // Everything below is written so a partial list can never read as the room's whole
  // record. The section shows delegations reported by the turns THIS deck starts (the
  // asks it sends for a round); the room's ordinary chat turns report to the workspace
  // above, which draws them nowhere. That is a gap, and the copy names it rather than
  // letting silence imply completeness.
  delegationLabel: {
    en: 'DELEGATION IN THIS ROOM',
    hy: 'ՊԱՏՎԻՐԱԿՈՒՄ ԱՅՍ ՍԵՆՅԱԿՈՒՄ',
    ru: 'ДЕЛЕГИРОВАНИЕ В ЭТОЙ КОМНАТЕ',
  },
  delegationScopeNote: {
    en: 'Bound to the room selected above. This window is told about a delegation only by a turn '
      + 'it started itself — the asks this deck sends for a round. A delegation made in the room’s '
      + 'ordinary chat above is reported to that workspace, which draws it nowhere, and will not '
      + 'appear here. So the section below covers this deck’s asks, not everything Bro did in the '
      + 'room, whatever its own wording says.',
    hy: 'Կապված է վերևում ընտրված սենյակի հետ։ Այս պատուհանին պատվիրակման մասին ասում է միայն այն turn-ը, '
      + 'որը ինքն է սկսել — այս deck-ի ուղարկած հարցումները փուլի համար։ Սենյակի սովորական զրույցում արված '
      + 'պատվիրակումը հաղորդվում է վերևի workspace-ին, որը այն ոչ մի տեղ չի նկարում, ու այստեղ չի հայտնվի։ '
      + 'Ուրեմն ներքևի բաժինը ցույց է տալիս այս deck-ի հարցումները, ոչ թե այն ամենը, ինչ Bro-ն արել է սենյակում՝ '
      + 'անկախ նրանից, թե ինքն ինչ է գրում։',
    ru: 'Привязано к комнате, выбранной выше. Об одном делегировании этому окну сообщает только ход, '
      + 'который оно само и начало, — запросы, которые эта панель отправляет для раунда. Делегирование, '
      + 'сделанное в обычном чате комнаты выше, сообщается той рабочей области, которая его нигде не '
      + 'рисует, и здесь не появится. Поэтому раздел ниже охватывает запросы этой панели, а не всё, что '
      + 'Bro сделал в комнате, что бы ни говорил его собственный текст.',
  },
  delegationTrailLabel: {
    en: 'WHICH ASK REPORTED IT',
    hy: 'ՈՐ ՀԱՐՑՈՒՄՆ Է ՀԱՂՈՐԴԵԼ',
    ru: 'КАКОЙ ЗАПРОС ЭТО СООБЩИЛ',
  },
  delegationTrailNote: {
    en: 'Each row is the ask this window had running when the frame arrived — the turn that '
      + 'reported it. The frame itself names no consensus round, and no requester either (the '
      + 'backend labels every delegation “Bro”), so this is this window’s record of what it '
      + 'started. It is not evidence that the specialist was told about the decision, and not a '
      + 'link the specialist reported.',
    hy: 'Ամեն տող այն հարցումն է, որ այս պատուհանը կատարում էր, երբ frame-ը հասավ — այն turn-ը, որը '
      + 'հաղորդեց այն։ Frame-ը ինքը ոչ կոնսենսուսի փուլ է նշում, ոչ էլ հարցնողին (backend-ը ամեն '
      + 'պատվիրակում պիտակում է «Bro»), ուրեմն սա այս պատուհանի գրանցումն է իր սկսածի մասին։ Սա ապացույց '
      + 'չէ, որ մասնագետին ասել են որոշման մասին, ու կապ չէ, որ մասնագետը հաղորդել է։',
    ru: 'Каждая строка — это запрос, который выполняло это окно, когда пришёл кадр: ход, который о нём '
      + 'сообщил. Сам кадр не называет ни раунда консенсуса, ни запрашивающего (бэкенд помечает каждое '
      + 'делегирование как «Bro»), так что это запись самого окна о том, что оно начало. Это не '
      + 'доказательство, что специалисту рассказали о решении, и не связь, о которой сообщил специалист.',
  },
  delegationAskPrefix: {
    en: 'ask to',
    hy: 'հարցում՝',
    ru: 'запрос к',
  },
  delegationRoundPrefix: {
    en: 'round:',
    hy: 'փուլ՝',
    ru: 'раунд:',
  },
  delegationNoRound: {
    en: 'no round context recorded',
    hy: 'փուլի կոնտեքստ գրանցված չէ',
    ru: 'контекст раунда не записан',
  },
} as const;
