// Page-local, trilingual string table for `Automations.tsx`. These are the copy
// fragments that are NOT in the central dictionary (t('…')): the manifold/
// schematic chrome, honest-state vocabulary, empty/error/skeleton branches and
// keyboard hints. Central `t('…')` keys stay in the shared dictionary — do not
// duplicate them here. Every entry carries en/hy/ru; the page selects with
// `L(key) = STR[key][lang] ?? STR[key].en`.
export const STR = {
  // ── create-form field hints (the honest small vocabulary) ────────────────────
  triggerHint: {
    en: 'every: 5m · every: 1h · every: 1d · manual',
    hy: 'every: 5m · every: 1h · every: 1d · manual',
    ru: 'every: 5m · every: 1h · every: 1d · manual',
  },
  actionHint: {
    en: 'notify: <text> · task: <title> · note: <title>',
    hy: 'notify: <տեքստ> · task: <վերնագիր> · note: <վերնագիր>',
    ru: 'notify: <текст> · task: <заголовок> · note: <заголовок>',
  },
  noRuns: {
    en: 'No runs yet — use “Run now”, or wait for an interval trigger to fire.',
    hy: 'Դեռ գործարկումներ չկան — սեղմիր «Գործարկել հիմա» կամ սպասիր interval trigger-ի։',
    ru: 'Запусков ещё нет — нажмите «Запустить сейчас» или дождитесь интервального триггера.',
  },
  // ── run-now action ───────────────────────────────────────────────────────────
  runNow: {
    en: 'Run now',
    hy: 'Գործարկել հիմա',
    ru: 'Запустить сейчас',
  },
  runNowTitle: {
    en: "Run this automation's action now, under the contract shown below. The contract is checked first: if it refuses, nothing is called and the reason is recorded.",
    hy: 'Գործարկել այս ավտոմատի գործողությունը հիմա՝ ներքևում ցուցադրված պայմանագրի ներքո։ Պայմանագիրը ստուգվում է առաջինը. եթե մերժի, ոչինչ չի կանչվում, իսկ պատճառը գրանցվում է։',
    ru: 'Запустить действие этой автоматизации сейчас — по контракту, показанному ниже. Контракт проверяется первым: если он отказывает, ничего не вызывается, а причина записывается.',
  },
  // ── governance posture (authoring modal + selected conduit) ─────────────────
  // This used to promise that a model-reaching action "routes through the governed chain —
  // a lease and a verified receipt". No such path exists for an automation: an unattended fire
  // holds no lease, and `run_automation` is a local SQLite write. The honest posture is the one
  // now enforced — the local vocabulary runs under a stated contract, and anything that would
  // reach the model is REFUSED rather than run ungoverned.
  govern: {
    en: 'An automation may only do three local things — notify, create a task, create a note — '
      + 'and each run happens under the contract shown here: who, under which role, over what '
      + 'scope, at what risk, and what evidence it leaves. An action that would reach the model '
      + 'is refused, at authoring time and again before any run: an unattended fire holds no '
      + 'lease, so there is no governed path for it. No automation run is signed or verified.',
    hy: 'Ավտոմատը կարող է անել միայն երեք տեղական բան՝ ծանուցել, task ստեղծել, նշում ստեղծել — '
      + 'ու ամեն գործարկում կատարվում է այստեղ ցուցադրված պայմանագրի ներքո՝ ով, ինչ դերով, ինչ '
      + 'շրջանակում, ինչ ռիսկով և ինչ ապացույց է թողնում։ Մոդելին հասնող գործողությունը մերժվում '
      + 'է՝ և՛ ստեղծելիս, և՛ ամեն գործարկումից առաջ. անհսկելի բռնկումը lease չունի, ուստի նրա '
      + 'համար կառավարվող ճանապարհ չկա։ Ոչ մի ավտոմատ գործարկում ստորագրված կամ ստուգված չէ։',
    ru: 'Автоматизация может делать только три локальные вещи — уведомить, создать задачу, '
      + 'создать заметку — и каждый запуск идёт по показанному здесь контракту: кто, в какой роли, '
      + 'в какой области, с каким риском и какое доказательство оставляет. Действие, доходящее до '
      + 'модели, отклоняется — и при создании, и перед каждым запуском: у срабатывания без '
      + 'присмотра нет аренды, значит нет и управляемого пути. Ни один запуск не подписан и не проверен.',
  },
  // The run log IS connected now (Phase 8, `list_automation_runs`), so the old "backend pending"
  // note was itself stale copy. What is still missing is the GOVERNANCE of a run: the
  // `automation_runs` table records id/time/outcome/detail and nothing about authority, so
  // per-conduit throughput and success rate stay "—" and the history says whose authority it
  // could not read. That is what this note now reports.
  telemetry: {
    en: 'The run log is real; the authority behind it is not recorded. `automation_runs` stores id, time, outcome and detail only — no actor, role, scope, risk or receipt — so rate and success readouts stay “—” and a stored run can only be shown as “authority not recorded”.',
    hy: 'Գործարկումների մատյանն իրական է, բայց դրա հեղինակությունը գրանցված չէ։ `automation_runs`-ը պահում է միայն id, ժամ, արդյունք և մանրամասն — ոչ դերակատար, ոչ դեր, ոչ շրջանակ, ոչ ռիսկ, ոչ անդորրագիր — ուստի արագության և հաջողության ցուցիչները մնում են «—», իսկ պահված գործարկումը կարող է ցուցադրվել միայն որպես «հեղինակությունը գրանցված չէ»։',
    ru: 'Журнал запусков настоящий, но полномочия за ним не записаны. `automation_runs` хранит только id, время, исход и детали — ни субъекта, ни роли, ни области, ни риска, ни квитанции — поэтому показатели частоты и успеха остаются «—», а сохранённый запуск можно показать лишь как «полномочия не записаны».',
  },

  // ── the run contract (who · which role · what scope · what risk · what evidence) ─────
  runContract: { en: 'Run contract', hy: 'Գործարկման պայմանագիր', ru: 'Контракт запуска' },
  contractAuthority: { en: 'Authority', hy: 'ՀԵՂԻՆԱԿՈՒԹՅՈՒՆ', ru: 'Полномочия' },
  contractRole: { en: 'Role', hy: 'ԴԵՐ', ru: 'Роль' },
  contractCommand: { en: 'Command', hy: 'ՀՐԱՄԱՆ', ru: 'Команда' },
  contractScope: { en: 'Scope', hy: 'ՇՐՋԱՆԱԿ', ru: 'Область' },
  contractRisk: { en: 'Risk', hy: 'ՌԻՍԿ', ru: 'Риск' },
  contractEvidence: { en: 'Evidence', hy: 'ԱՊԱՑՈՒՅՑ', ru: 'Доказательство' },
  contractSchedule: { en: 'Schedule', hy: 'ԺԱՄԱՆԱԿԱՑՈՒՅՑ', ru: 'Расписание' },

  actorOwner: { en: 'You — this session', hy: 'Դու — այս session-ը', ru: 'Вы — эта сессия' },
  actorScheduler: { en: 'Local scheduler — unattended', hy: 'Տեղական պլանավորիչ — առանց հսկողության', ru: 'Локальный планировщик — без присмотра' },
  actorUnrecorded: { en: 'Not recorded', hy: 'Գրանցված չէ', ru: 'Не записано' },
  roleDesktopOwner: { en: 'desktop-owner', hy: 'desktop-owner', ru: 'desktop-owner' },
  roleLocalScheduler: { en: 'local-scheduler', hy: 'local-scheduler', ru: 'local-scheduler' },
  roleNone: { en: 'none', hy: 'չկա', ru: 'нет' },

  tierLabel: { en: 'tier', hy: 'աստիճան', ru: 'уровень' },
  grantAllow: { en: 'granted', hy: 'թույլատրված', ru: 'разрешено' },
  grantDeny: { en: 'denied', hy: 'մերժված', ru: 'запрещено' },

  factorLocalEffectOnly: {
    en: 'writes one local row — no model, no network, no spend',
    hy: 'գրում է մեկ տեղական տող — ոչ մոդել, ոչ ցանց, ոչ ծախս',
    ru: 'пишет одну локальную строку — без модели, сети и трат',
  },
  factorNotRemovable: {
    en: 'what it creates cannot be removed from the app (no granted delete for that store)',
    hy: 'ստեղծածը հնարավոր չէ ջնջել հավելվածից (այդ պահեստի համար delete թույլատրված չէ)',
    ru: 'созданное нельзя удалить из приложения (для этого хранилища нет разрешённого delete)',
  },
  factorUnattended: {
    en: 'an interval trigger fires it with nobody present',
    hy: 'ինտերվալային բռնկիչը գործարկում է առանց ներկա մարդու',
    ru: 'интервальный триггер срабатывает, когда никого нет',
  },
  factorReachesModel: {
    en: 'would leave the local store — needs a lease this page cannot obtain',
    hy: 'դուրս կգա տեղական պահեստից — պահանջում է lease, որը այս էջը չի կարող ստանալ',
    ru: 'вышло бы за пределы локального хранилища — нужна аренда, которую эта страница получить не может',
  },

  evRunRow: { en: 'run row (automation_runs)', hy: 'գործարկման տող (automation_runs)', ru: 'строка запуска (automation_runs)' },
  evAuditEvent: { en: 'audit event (automation.ran)', hy: 'աուդիտի իրադարձություն (automation.ran)', ru: 'событие аудита (automation.ran)' },
  evEngineReceipt: { en: 'signed engine receipt', hy: 'ստորագրված շարժիչի անդորրագիր', ru: 'подписанная квитанция движка' },
  evObserved: { en: 'held', hy: 'ստացված', ru: 'получено' },
  evNotObserved: { en: 'not observed here', hy: 'այստեղ չի դիտվում', ru: 'здесь не наблюдается' },
  evNever: { en: 'never produced in this build', hy: 'այս build-ում երբեք չի արտադրվում', ru: 'в этой сборке не создаётся' },

  // ── trigger truth ────────────────────────────────────────────────────────────
  triggerScheduled: { en: 'scheduled — the scheduler fires it', hy: 'պլանավորված — պլանավորիչը գործարկում է', ru: 'по расписанию — запускает планировщик' },
  triggerManualOnly: { en: 'manual only — the scheduler never fires it', hy: 'միայն ձեռքով — պլանավորիչը երբեք չի գործարկում', ru: 'только вручную — планировщик никогда не запускает' },
  triggerUnrecognised: {
    en: 'not a recognised trigger — the scheduler ignores it, so this automation only ever runs from “Run now”',
    hy: 'չճանաչված բռնկիչ — պլանավորիչն անտեսում է, ուստի այս ավտոմատը գործարկվում է միայն «Գործարկել հիմա»-ով',
    ru: 'нераспознанный триггер — планировщик его игнорирует, поэтому автоматизация запускается только через «Запустить сейчас»',
  },
  everyLabel: { en: 'every', hy: 'ամեն', ru: 'каждые' },

  // ── refusals (closed set — same vocabulary at authoring time and at run time) ─
  refusalTitle: { en: 'Refused by the run contract', hy: 'Մերժված է գործարկման պայմանագրով', ru: 'Отклонено контрактом запуска' },
  refuseActionEmpty: { en: 'the action is empty — there is nothing to run', hy: 'գործողությունը դատարկ է — գործարկելու բան չկա', ru: 'действие пустое — запускать нечего' },
  refuseActionMalformed: {
    en: 'the action is not `verb: argument`, so nothing can say what it would touch',
    hy: 'գործողությունը `verb: argument` ձևաչափով չէ, ուստի հնարավոր չէ ասել՝ ինչին կդիպչի',
    ru: 'действие не в форме `verb: argument`, поэтому нельзя сказать, чего оно коснётся',
  },
  refuseActionArgumentMissing: {
    en: 'the verb has no argument',
    hy: 'բային արգումենտ չունի',
    ru: 'у глагола нет аргумента',
  },
  refuseActionVerbUnknown: {
    en: 'unknown verb — the only actions with a defined scope are notify, task and note',
    hy: 'անհայտ բայ — սահմանված շրջանակ ունեն միայն notify, task և note գործողությունները',
    ru: 'неизвестный глагол — определённую область имеют только notify, task и note',
  },
  refuseActionReachesModel: {
    en: 'this action would reach the model/engine. An automation fires unattended and this page holds no lease, so there is no governed path for it — it is refused rather than run ungoverned.',
    hy: 'այս գործողությունը կհասներ մոդելին/շարժիչին։ Ավտոմատը գործարկվում է առանց հսկողության, իսկ այս էջը lease չունի, ուստի կառավարվող ճանապարհ չկա — մերժվում է, ոչ թե գործարկվում չկառավարվող։',
    ru: 'это действие дошло бы до модели/движка. Автоматизация срабатывает без присмотра, а у страницы нет аренды, поэтому управляемого пути нет — оно отклоняется, а не выполняется неуправляемо.',
  },
  refuseAutomationDisabled: {
    en: 'the automation is off',
    hy: 'ավտոմատն անջատված է',
    ru: 'автоматизация выключена',
  },
  refuseCommandDenied: {
    en: 'the run command is not granted to this window',
    hy: 'գործարկման հրամանը թույլատրված չէ այս պատուհանին',
    ru: 'команда запуска не разрешена этому окну',
  },
  refuseRiskAboveCeiling: {
    en: 'the contract’s risk is above what an unleased local run may carry',
    hy: 'պայմանագրի ռիսկը գերազանցում է այն, ինչ կարող է կրել առանց lease-ի տեղական գործարկումը',
    ru: 'риск контракта выше того, что может нести локальный запуск без аренды',
  },
  fixVocabulary: {
    en: 'Rewrite the action as `notify: <text>`, `task: <title>` or `note: <title>` — the three effects with a declared scope.',
    hy: 'Վերաշարադրիր գործողությունը որպես `notify: <տեքստ>`, `task: <վերնագիր>` կամ `note: <վերնագիր>` — երեք էֆեկտները, որոնք հայտարարված շրջանակ ունեն։',
    ru: 'Перепишите действие как `notify: <текст>`, `task: <заголовок>` или `note: <заголовок>` — три эффекта с объявленной областью.',
  },
  fixEnable: {
    en: 'Enable the automation first — a disabled conduit refuses here and in the store.',
    hy: 'Նախ միացրու ավտոմատը — անջատված խողովակը մերժում է թե՛ այստեղ, թե՛ պահեստում։',
    ru: 'Сначала включите автоматизацию — выключенный канал отказывает и здесь, и в хранилище.',
  },
  fixNoGovernedPath: {
    en: 'Ask Bro directly in chat, where a turn can be governed. An unattended automation cannot be.',
    hy: 'Հարցրու Bro-ին ուղիղ չատում, որտեղ turn-ը կարող է կառավարվել։ Անհսկելի ավտոմատը չի կարող։',
    ru: 'Спросите Bro напрямую в чате, где ход может быть управляемым. Автоматизация без присмотра — нет.',
  },

  // ── the honest scope of what this page can govern ────────────────────────────
  contractNote: {
    en: 'This contract is enforced here, before the call. It binds runs started from this page in this session — the scheduler fires unattended runs in the backend, which this page cannot gate. No automation run produces a signed receipt in this build, so none is ever shown as verified.',
    hy: 'Այս պայմանագիրը կիրառվում է այստեղ՝ կանչից առաջ։ Այն կապում է այս էջից, այս session-ում սկսված գործարկումները — պլանավորիչը backend-ում գործարկում է անհսկելի վազքեր, որոնք այս էջը չի կարող զսպել։ Այս build-ում ոչ մի ավտոմատ գործարկում ստորագրված անդորրագիր չի արտադրում, ուստի ոչ մեկը երբեք չի ցուցադրվում որպես ստուգված։',
    ru: 'Этот контракт применяется здесь, до вызова. Он связывает запуски, начатые с этой страницы в этой сессии — планировщик запускает автоматизации в бэкенде без присмотра, и страница не может их перехватить. В этой сборке ни один запуск автоматизации не создаёт подписанную квитанцию, поэтому ни один не показывается как проверенный.',
  },
  schedulerUngoverned: {
    en: 'Unattended fires carry no contract',
    hy: 'Անհսկելի բռնկումները պայմանագիր չեն կրում',
    ru: 'Срабатывания без присмотра идут без контракта',
  },

  // ── history vocabulary ───────────────────────────────────────────────────────
  kindExecuted: { en: 'ran', hy: 'գործարկվեց', ru: 'выполнено' },
  kindRefused: { en: 'refused', hy: 'մերժվեց', ru: 'отклонено' },
  kindFailed: { en: 'failed', hy: 'ձախողվեց', ru: 'сбой' },
  provContracted: {
    en: 'contract enforced here',
    hy: 'պայմանագիրը կիրառվել է այստեղ',
    ru: 'контракт применён здесь',
  },
  provUnrecorded: {
    en: 'authority not recorded',
    hy: 'հեղինակությունը գրանցված չէ',
    ru: 'полномочия не записаны',
  },
  provRefusedPreflight: {
    en: 'refused before the call — nothing was written',
    hy: 'մերժվել է կանչից առաջ — ոչինչ չի գրվել',
    ru: 'отклонено до вызова — ничего не записано',
  },
  provRefusedStore: {
    en: 'refused by the store',
    hy: 'մերժվել է պահեստի կողմից',
    ru: 'отклонено хранилищем',
  },
  notPersisted: {
    en: 'this session only — the store has no table for refusals',
    hy: 'միայն այս session-ը — պահեստը մերժումների աղյուսակ չունի',
    ru: 'только эта сессия — в хранилище нет таблицы для отказов',
  },
  historyLegend: {
    en: 'ran · refused · failed — refusals from this session are not persisted',
    hy: 'գործարկվեց · մերժվեց · ձախողվեց — այս session-ի մերժումները չեն պահվում',
    ru: 'выполнено · отклонено · сбой — отказы этой сессии не сохраняются',
  },
  ledgerAttributed: { en: 'attributed', hy: 'վերագրված', ru: 'атрибутировано' },
  ledgerUnattributed: { en: 'unattributed', hy: 'չվերագրված', ru: 'без атрибуции' },
  neverRunNote: {
    en: 'No run has been recorded for this conduit.',
    hy: 'Այս խողովակի համար գործարկում գրանցված չէ։',
    ru: 'Для этого канала не записано ни одного запуска.',
  },

  // ── authoring-time gate ──────────────────────────────────────────────────────
  authoringRefused: {
    en: 'This rule cannot be created',
    hy: 'Այս կանոնը հնարավոր չէ ստեղծել',
    ru: 'Это правило нельзя создать',
  },
  contractPreview: { en: 'It would run under', hy: 'Կաշխատեր հետևյալի ներքո', ru: 'Оно выполнялось бы под' },

  // ── honest runtime-state vocabulary ──────────────────────────────────────────
  armedState: { en: 'Armed', hy: 'Զինված', ru: 'Заряжен' },
  offState: { en: 'Off', hy: 'Անջատված', ru: 'Выключен' },
  sealedState: { en: 'Sealed', hy: 'Փակված', ru: 'Запечатан' },
  allFilter: { en: 'All', hy: 'Բոլորը', ru: 'Все' },

  // ── page header ──────────────────────────────────────────────────────────────
  workflowManifold: {
    en: 'Workflow Energy Manifold',
    hy: 'ԱՇԽԱՏԱՆՔԱՅԻՆ ԷՆԵՐԳԱ-ՄԱՆԻՖՈԼԴ',
    ru: 'Энергетический коллектор рабочих процессов',
  },
  schedSweep: { en: 'Scheduler · sweep', hy: 'Պլանավորիչ · սկան', ru: 'Планировщик · обход' },
  newN: { en: 'New  ( n )', hy: 'Նոր  ( n )', ru: 'Новый  ( n )' },

  // ── blocked (wall/guard denial) ──────────────────────────────────────────────
  blockedByWall: { en: 'Blocked by the wall', hy: 'Արգելափակված է պատով', ru: 'Заблокировано стеной' },
  guardFix: {
    en: 'A guard tripped or the wall denied this action. Resolve the guard condition or request approval, then retry.',
    hy: 'Պահապանը գործարկվեց կամ պատը մերժեց այս գործողությունը։ Լուծեք պահապանի պայմանը կամ պահանջեք հաստատում, ապա կրկնեք։',
    ru: 'Сработал страж или стена отклонила это действие. Устраните условие стража или запросите одобрение, затем повторите.',
  },
  storeDenied: {
    en: 'This automation store is denied in the current mode or scope. Switch to work mode, or request the required scope/approval, then retry.',
    hy: 'Այս ավտոմատների պահեստը մերժված է ընթացիկ ռեժիմում կամ շրջանակում։ Անցեք work ռեժիմ կամ պահանջեք անհրաժեշտ շրջանակ/հաստատում, ապա կրկնեք։',
    ru: 'Это хранилище автоматизаций запрещено в текущем режиме или области. Переключитесь в режим work или запросите нужную область/одобрение, затем повторите.',
  },

  // ── conduit lane ─────────────────────────────────────────────────────────────
  anyEvent: { en: 'any event', hy: 'ցանկացած իրադարձություն', ru: 'любое событие' },
  runsPerHr: { en: 'runs/hr', hy: 'վազք/ժ', ru: 'запусков/ч' },

  // ── schematic ────────────────────────────────────────────────────────────────
  schematic: { en: 'Schematic', hy: 'Սխեմա', ru: 'Схема' },
  selectConduit: { en: 'Select a conduit', hy: 'Ընտրեք խողովակ', ru: 'Выберите канал' },
  chooseConduit: {
    en: 'Choose a conduit to forge its schematic.',
    hy: 'Ընտրեք խողովակ՝ դրա սխեման ձուլելու համար։',
    ru: 'Выберите канал, чтобы выковать его схему.',
  },
  trigger: { en: 'Trigger', hy: 'Բռնկիչ', ru: 'Триггер' },
  // The diagram track scrolls horizontally, so it needs a name and a tab stop or a keyboard
  // user cannot reach the part of it that is off-screen (axe `scrollable-region-focusable`,
  // found by the real-browser sweep -- jsdom has no layout and cannot know an element scrolls).
  flowAria: {
    en: 'Automation flow diagram — scrollable',
    hy: 'Ավտոմատացման հոսքի սխեմա — ոլորվող',
    ru: 'Схема потока автоматизации — прокручиваемая',
  },
  governed: { en: 'Governed', hy: 'Կառավարվող', ru: 'Управляемо' },
  guard: { en: 'guard', hy: 'պահապան', ru: 'страж' },
  action: { en: 'action', hy: 'գործողություն', ru: 'действие' },
  outlet: { en: 'Outlet', hy: 'Ելք', ru: 'Выход' },
  dispatch: { en: 'dispatch', hy: 'առաքում', ru: 'отправка' },
  triggerLabel: { en: 'Trigger:', hy: 'Բռնկիչ՝', ru: 'Триггер:' },
  actionLabel: { en: 'Action:', hy: 'Գործողություն՝', ru: 'Действие:' },
  stateFact: { en: 'State', hy: 'ՎԻՃԱԿ', ru: 'Состояние' },
  createdFact: { en: 'Created', hy: 'ՍՏԵՂԾՎԱԾ', ru: 'Создано' },
  updatedFact: { en: 'Updated', hy: 'ԹԱՐՄԱՑՎԱԾ', ru: 'Обновлено' },
  ownerFact: { en: 'Owner', hy: 'ՏԵՐ', ru: 'Владелец' },
  governedTelemetry: { en: 'Governed telemetry', hy: 'ԿԱՌԱՎԱՐՎՈՂ ՀԵՌԱՉԱՓ', ru: 'Управляемая телеметрия' },
  recentFires: { en: 'Recent fires', hy: 'Վերջին բռնկումներ', ru: 'Недавние срабатывания' },

  // ── index row ────────────────────────────────────────────────────────────────
  runs: { en: 'runs', hy: 'վազք', ru: 'запуски' },
  success: { en: 'success', hy: 'հաջող.', ru: 'успех' },

  // ── body branches: loading · error · empty ───────────────────────────────────
  manifold: { en: 'Manifold', hy: 'Մանիֆոլդ', ru: 'Коллектор' },
  manifoldEyebrow: { en: 'Manifold', hy: 'ՄԱՆԻՖՈԼԴ', ru: 'КОЛЛЕКТОР' },
  chargingManifold: { en: 'Charging the manifold…', hy: 'Մանիֆոլդը լիցքավորվում է…', ru: 'Зарядка коллектора…' },
  retry: { en: 'Retry', hy: 'Կրկնել', ru: 'Повторить' },
  noConduits: { en: 'No conduits yet', hy: 'Դեռ խողովակներ չկան', ru: 'Пока нет каналов' },
  // "every run stays governed and verified" was false twice over: nothing here is verified, and
  // the store records no authority for a scheduler fire. The claim is now the one that holds.
  forgeFirst: {
    en: 'Forge your first conduit — every run states the contract it acts under, and a run that cannot be governed is refused.',
    hy: 'Ձուլեք ձեր առաջին խողովակը — ամեն գործարկում հայտարարում է իր պայմանագիրը, իսկ չկառավարվող գործարկումը մերժվում է։',
    ru: 'Выкуйте свой первый канал — каждый запуск объявляет свой контракт, а неуправляемый запуск отклоняется.',
  },
  forgeConduit: { en: 'Forge conduit', hy: 'Ձուլել խողովակ', ru: 'Выковать канал' },

  // ── hero manifold ────────────────────────────────────────────────────────────
  energyManifold: { en: 'Energy Manifold', hy: 'ԷՆԵՐԳԱ-ՄԱՆԻՖՈԼԴ', ru: 'Энергетический коллектор' },
  triggerGatesOutlet: { en: 'Trigger ▸ gates ▸ outlet', hy: 'Բռնկիչ ▸ դարպասներ ▸ ելք', ru: 'Триггер ▸ ворота ▸ выход' },
  conduits: { en: 'conduits', hy: 'խողովակ', ru: 'каналов' },
  armedConduits: { en: 'armed conduits', hy: 'զինված խողովակ', ru: 'заряжённых каналов' },
  automationManifold: { en: 'Automation manifold', hy: 'Ավտոմատների մանիֆոլդ', ru: 'Коллектор автоматизаций' },
  noConduitInState: { en: 'No conduit in this state.', hy: 'Այս վիճակում խողովակ չկա։', ru: 'Нет каналов в этом состоянии.' },
  valveGate: {
    en: 'valve = trigger · gate = governed step',
    hy: 'փական = բռնկիչ · դարպաս = կառավարվող քայլ',
    ru: 'клапан = триггер · ворота = управляемый шаг',
  },

  // ── index section + census ───────────────────────────────────────────────────
  automationIndex: { en: 'Automation index', hy: 'Ավտոմատների ինդեքս', ru: 'Указатель автоматизаций' },
  filterByState: { en: 'Filter by state', hy: 'Զտել վիճակով', ru: 'Фильтр по состоянию' },
  conduitsManifold: { en: 'conduits · manifold', hy: 'ավտոմատ · մանիֆոլդ', ru: 'каналов · коллектор' },
  armed: { en: 'armed', hy: 'զինված', ru: 'заряжено' },
  off: { en: 'off', hy: 'անջատված', ru: 'выключено' },
  sealed: { en: 'sealed', hy: 'փակված', ru: 'запечатано' },

  // ── keyboard hint strip ──────────────────────────────────────────────────────
  kbdNew: { en: 'New', hy: 'Նոր', ru: 'Новый' },
  navigate: { en: 'Navigate', hy: 'Նավարկել', ru: 'Навигация' },
  open: { en: 'Open', hy: 'Բացել', ru: 'Открыть' },
} as const;
