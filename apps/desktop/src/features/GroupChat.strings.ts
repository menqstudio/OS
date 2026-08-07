// Trilingual copy for the Group Chat view's CONSENSUS deck (Phase 7). Per-feature
// strings live here rather than in the central i18n catalog; the shared chat keys
// (t('chat.…'), t('action.…')) still come from the catalog.
//
// A note on the wording choices: every outcome string names what is true, never
// what is hoped. "NOT REACHED" and "PENDING" are stated as plainly as "REACHED",
// and the dissent labels never soften — a surface that says "mostly agreed" when
// someone said NO is the failure this deck exists to prevent.

export const STR = {
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
} as const;
