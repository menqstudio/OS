// First-run onboarding — a short, HONEST intro shown once (localStorage-gated). Trilingual per the
// per-page parity guard. It never overstates: it says plainly what works today (fail-closed) and that
// production "Verified" is not yet enabled and is never faked.
//
// `howBody` used to tell the owner that anything reaching the AI model runs through a lease and a
// verified receipt. That is only true when the backend resolves the governed engine provider; in the
// default configuration the command layer falls through to the ungoverned streaming path, so nothing
// about a reply is leased, receipted or verified. Since this is the screen read BEFORE deciding to
// trust the product, the copy now names the condition instead of asserting the guarantee.
export const STR = {
  welcomeTitle: {
    en: 'Welcome to BroPS',
    hy: 'Բարի գալուստ BroPS',
    ru: 'Добро пожаловать в BroPS',
  },
  welcomeBody: {
    en: 'Your AI-operations desktop — one cockpit for talking to Bro, running flows, and keeping every action accountable.',
    hy: 'Քո AI-գործառնությունների desktop-ը — մեկ cockpit՝ Bro-ի հետ խոսելու, հոսքեր վարելու և ամեն գործողություն հաշվետու պահելու համար։',
    ru: 'Ваш AI-desktop для операций — единый кокпит для общения с Bro, запуска потоков и подотчётности каждого действия.',
  },
  howTitle: {
    en: 'How it works',
    hy: 'Ինչպես է աշխատում',
    ru: 'Как это работает',
  },
  howBody: {
    en: 'Local actions (notes, tasks, notifications, automations) run directly and reversibly. '
      + 'Model calls are only governed when this install is configured with the governed engine: '
      + 'then a turn runs through a lease and a verified receipt, and is refused if it cannot be '
      + 'verified. That is NOT the default — with any other provider your replies run ungoverned, '
      + 'with no lease and no receipt. Settings → Governance always shows which one is actually running.',
    hy: 'Տեղական գործողությունները (նշումներ, առաջադրանքներ, ծանուցումներ, ավտոմատներ) աշխատում են '
      + 'ուղղակի և հետշրջելի։ Մոդելի կանչերը կառավարվում են միայն այն դեպքում, երբ այս տեղակայումը '
      + 'կարգավորված է կառավարվող շարժիչով. այդ դեպքում շրջադարձն անցնում է lease-ի և ստուգված '
      + 'անդորրագրի միջով և մերժվում է, եթե չի ստուգվում։ Դա լռելյայն ՉԷ — ցանկացած այլ մատակարարի '
      + 'դեպքում պատասխանները աշխատում են չկառավարվող՝ առանց lease-ի և առանց անդորրագրի։ '
      + 'Կարգավորումներ → Կառավարում-ը միշտ ցույց է տալիս, թե որն է իրականում աշխատում։',
    ru: 'Локальные действия (заметки, задачи, уведомления, автоматизации) выполняются напрямую и '
      + 'обратимо. Вызовы модели управляются, только если эта установка настроена на управляемый '
      + 'движок: тогда обращение идёт через аренду и проверенную квитанцию и отклоняется, если его '
      + 'нельзя проверить. По умолчанию это НЕ так — с любым другим провайдером ответы выполняются '
      + 'неуправляемо, без аренды и без квитанции. Настройки → Управление всегда показывают, что '
      + 'работает на самом деле.',
  },
  honestTitle: {
    en: 'Honest by design',
    hy: 'Ազնիվ ըստ նախագծի',
    ru: 'Честность по замыслу',
  },
  honestBody: {
    en: 'Production “Verified” is not enabled yet: the trust chain stays fail-closed until real signing and an independent audit land. A badge is never painted on work that was not truly verified.',
    hy: 'Production «Verified»-ը դեռ միացված չէ. trust-շղթան մնում է fail-closed, մինչև իսկական ստորագրում և անկախ աուդիտ լինեն։ Badge-ը երբեք չի դրվում այն աշխատանքի վրա, որն իրականում չի հաստատվել։',
    ru: 'Production «Verified» ещё не включён: цепочка доверия остаётся fail-closed, пока не появятся настоящая подпись и независимый аудит. Значок никогда не ставится на работу, которая не была действительно проверена.',
  },
  next: { en: 'Next', hy: 'Հաջորդ', ru: 'Далее' },
  back: { en: 'Back', hy: 'Հետ', ru: 'Назад' },
  done: { en: 'Get started', hy: 'Սկսել', ru: 'Начать' },
  skip: { en: 'Skip', hy: 'Բաց թողնել', ru: 'Пропустить' },
  stepOf: { en: 'Step', hy: 'Քայլ', ru: 'Шаг' },
} as const;
