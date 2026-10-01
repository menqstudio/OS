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
  // A refusal is NOT a failure, and rendering it as one teaches the owner that a rule
  // doing its job is a bug. The reason is carried verbatim rather than summarised.
  //
  // These used to say "refused at the governed wall" and "The engine refused this step.
  // Nothing ran." The page cannot know either: the backend sends one untyped error, the
  // page tells a refusal from a breakdown by its WORDING, the refusal may be the desktop's
  // own approval ledger ("approval was rejected for this step") rather than the engine,
  // and a governed turn can be refused after the model has already answered. What IS true
  // of every such outcome is that the step's result was not recorded.
  dispatchBlocked: {
    en: 'Dispatch refused',
    hy: 'Առաքումը մերժվել ա',
    ru: 'Отправка отклонена',
  },
  dispatchBlockedNote: {
    en: 'This step was refused and its result was not recorded. The reason is shown exactly as it '
      + 'arrived; this page tells a refusal from a failure by that wording, not by a typed verdict.',
    hy: 'Այս քայլը մերժվել ա, ու դրա արդյունքը չի գրանցվել։ Պատճառը ցույց ա տրված ուղիղ այնպես, ինչպես '
      + 'եկել ա. այս էջը մերժումը ձախողումից տարբերում ա հենց այդ ձևակերպումով, ոչ թե տիպավորված վճռով։',
    ru: 'Этот шаг отклонён, и его результат не записан. Причина показана ровно так, как пришла; '
      + 'страница отличает отказ от сбоя по этой формулировке, а не по типизированному вердикту.',
  },
  dispatchFailed: {
    en: 'Dispatch failed',
    hy: 'Առաքումը ձախողվեց',
    ru: 'Отправка не удалась',
  },
} as const;
