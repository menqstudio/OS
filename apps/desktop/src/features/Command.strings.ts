// Trilingual (en/hy/ru) copy for the Command reactor view. Every key holds a
// natural translation per language; `Command.tsx` resolves them with a small
// `L(key)` helper bound to the active `lang`. Status/lifecycle words are NOT here
// — those come from the shared `statusLabel()` so data values localize centrally.
export const STR = {
  // Header eyebrow (originally the mixed "ՀՐԱՄԱՆԻ ՄԻՋՈՒԿ · COMMAND REACTOR").
  eyebrowReactor: { en: 'COMMAND REACTOR', hy: 'ՀՐԱՄԱՆԻ ՄԻՋՈՒԿ', ru: 'КОМАНДНЫЙ РЕАКТОР' },
  // Reactor HUD readout labels (real step counts).
  hudSteps: { en: 'STEPS', hy: 'ՔԱՅԼԵՐ', ru: 'ШАГИ' },
  hudDone: { en: 'DONE', hy: 'ԱՎԱՐՏ', ru: 'ГОТОВО' },
  hudActive: { en: 'ACTIVE', hy: 'ԸՆԹԱՑՔ', ru: 'АКТИВНО' },
  hudGated: { en: 'APPROVAL', hy: 'ՀԱՍՏԱՏՈՒՄ', ru: 'СОГЛАСОВАНИЕ' },
  // Decorative reactor core label; BRO is brand and stays.
  coreName: { en: 'BRO · CORE', hy: 'BRO · ՄԻՋՈՒԿ', ru: 'BRO · ЯДРО' },
  // Dispatch-trace section eyebrow + its live badge.
  dispatchTrace: { en: 'DISPATCH TRACE', hy: 'ԱՌԱՔՄԱՆ ՀԵՏՔ', ru: 'ТРАССА ОТПРАВКИ' },
  live: { en: 'LIVE', hy: 'ՈՒՂԻՂ', ru: 'В ЭФИРЕ' },
  // Command dock quick-issue button + quick-command chip label.
  dockRun: { en: 'Run', hy: 'Կատարել', ru: 'Выполнить' },
  quickCommand: { en: 'QUICK COMMAND', hy: 'ԱՐԱԳ ՀՐԱՄԱՆ', ru: 'БЫСТРАЯ КОМАНДА' },

  // -- §D `blocked`: "dispatch denied by wall → reason" -------------------------
  // A governed refusal is NOT a failure, and rendering it as one teaches the owner
  // that the wall is a bug. It is the system working as designed; the engine's own
  // reason is carried verbatim rather than summarised.
  dispatchBlocked: {
    en: 'Dispatch refused at the governed wall',
    hy: 'Առաքումը մերժվել է կառավարվող պատի մոտ',
    ru: 'Отправка отклонена управляемой стеной',
  },
  dispatchBlockedNote: {
    en: 'The engine refused this step. Nothing ran. The reason it gave is shown exactly as it arrived.',
    hy: 'Շարժիչը մերժել ա այս քայլը։ Ոչինչ չի կատարվել։ Իր տված պատճառը ցույց ա տրված ուղիղ այնպես, ինչպես եկել ա։',
    ru: 'Движок отклонил этот шаг. Ничего не выполнялось. Причина показана ровно так, как пришла.',
  },
  dispatchFailed: {
    en: 'Dispatch failed',
    hy: 'Առաքումը ձախողվեց',
    ru: 'Отправка не удалась',
  },
} as const;
