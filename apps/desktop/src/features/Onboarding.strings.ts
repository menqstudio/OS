// First-run onboarding — a short, HONEST intro shown once (localStorage-gated). Trilingual per the
// per-page parity guard. It never overstates: it says plainly what works today (fail-closed) and that
// production "Verified" is not yet enabled and is never faked.
export const STR = {
  welcomeTitle: {
    en: 'Welcome to BroPS',
    hy: 'Բարի գալուստ BroPS',
    ru: 'Добро пожаловать в BroPS',
  },
  welcomeBody: {
    en: 'Your governed AI-operations desktop — a safe cockpit for talking to Bro, running flows, and keeping every action accountable.',
    hy: 'Քո կառավարվող AI-գործառնությունների desktop-ը — ապահով cockpit՝ Bro-ի հետ խոսելու, հոսքեր վարելու և ամեն գործողություն հաշվետու պահելու համար։',
    ru: 'Ваш управляемый AI-desktop — безопасный кокпит для общения с Bro, запуска потоков и подотчётности каждого действия.',
  },
  howTitle: {
    en: 'How it works',
    hy: 'Ինչպես է աշխատում',
    ru: 'Как это работает',
  },
  howBody: {
    en: 'Local actions (notes, tasks, notifications, automations) run directly and reversibly. Anything that reaches the AI model runs through a governed chain — a lease and a verified receipt — and is refused if it cannot be verified.',
    hy: 'Տեղական գործողությունները (նշումներ, առաջադրանքներ, ծանուցումներ, ավտոմատներ) աշխատում են ուղղակի և հետշրջելի։ AI մոդելին հասնող ամեն ինչ անցնում է կառավարվող շղթայով՝ լիզինգ և հաստատված ստացական, և մերժվում է, եթե չի հաստատվում։',
    ru: 'Локальные действия (заметки, задачи, уведомления, автоматизации) выполняются напрямую и обратимо. Всё, что доходит до AI-модели, идёт через управляемую цепочку — аренда и проверенная квитанция — и отклоняется, если не может быть проверено.',
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
