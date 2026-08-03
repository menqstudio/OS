// Trilingual (en/hy/ru) UI strings for the Tasks (Առաքելության տախտակ / mission
// board) screen. The shared i18n dictionary is not edited; these are the strings
// local to this reskin. Each key carries natural translations in all three
// languages — the bilingual eyebrow is localized per language, never left as
// mixed text. Status/priority DATA values are localized via the shared
// statusLabel/priorityLabel helpers, and central `t('…')` keys plus technical
// ids/brand names stay outside this table.
export const STR = {
  // Mission hero (HUD)
  eyebrow: { en: 'MISSION CONTROL', hy: 'ԱՌԱՔԵԼՈՒԹՅԱՆ ԿՈՆՏՐՈԼ', ru: 'ЦЕНТР УПРАВЛЕНИЯ' },
  pathClear: { en: 'PATH CLEAR', hy: 'ՈՒՂԻՆ ՄԱՔՈՒՐ', ru: 'ПУТЬ СВОБОДЕН' },
  blockersWord: { en: 'BLOCKED', hy: 'ԱՐԳԵԼՔ', ru: 'БЛОКИРОВОК' },
  doneCap: { en: 'Done', hy: 'Ավարտ', ru: 'Готово' },

  // Hero ledger (aggregate KPI words)
  kpi_total: { en: 'total', hy: 'ընդամենը', ru: 'всего' },
  kpi_active: { en: 'active', hy: 'ընթացքում', ru: 'активных' },
  kpi_blocked: { en: 'blocked', hy: 'արգելափակ', ru: 'заблокировано' },
  kpi_done: { en: 'done', hy: 'ավարտ', ru: 'готово' },

  // Board bar + legend
  boardTitle: { en: 'Mission board', hy: 'Առաքելության տախտակ', ru: 'Доска миссии' },
  boardNote: { en: 'dependencies + blockers', hy: 'կախվածություններ + արգելքներ', ru: 'зависимости + блокировки' },
  legendBlocked: { en: 'Blocked', hy: 'Արգելափակ', ru: 'Заблокировано' },
  legendDep: { en: 'Dependent', hy: 'Կախված', ru: 'Зависит' },

  // Lane names
  lane_queue: { en: 'Queue', hy: 'Հերթ', ru: 'Очередь' },
  lane_prog: { en: 'In progress', hy: 'Ընթացքում', ru: 'В процессе' },
  lane_block: { en: 'Blocked', hy: 'Արգելափակ', ru: 'Заблокировано' },
  lane_done: { en: 'Done', hy: 'Ավարտ', ru: 'Готово' },

  // Card blocker strip
  blocking: { en: 'Blocking', hy: 'Արգելափակում', ru: 'Блокировка' },
  release: { en: 'Release', hy: 'Ազատել', ru: 'Освободить' },
} as const;

export type StrKey = keyof typeof STR;
