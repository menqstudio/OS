// Trilingual UI strings local to the Calendar view. Kept out of the central
// `t()` catalog because they are view-specific microcopy (eyebrows, day/agenda
// labels, count words, empty-day text). Many render through CSS
// `text-transform:uppercase` (.eyebrow/.pill/.micro), so natural sentence case
// here still displays uppercased where the design calls for it.
export const STR = {
  // HERO eyebrow: "OPERATIONAL FLOW · <date>"
  opsFlow: {
    en: 'Operational flow',
    hy: 'Օպերացիոն հոսք',
    ru: 'Операционный поток',
  },
  // Count word used as "<n> operations" (hero pill, month head, agenda count).
  operations: {
    en: 'operations',
    hy: 'գործողություն',
    ru: 'операций',
  },
  // Hero footer stat captions.
  dayOps: {
    en: "day's operations",
    hy: 'օրվա գործողություն',
    ru: 'операций за день',
  },
  total: {
    en: 'total',
    hy: 'ընդամենը',
    ru: 'всего',
  },
  undated: {
    en: 'undated',
    hy: 'անթվակիր',
    ru: 'без даты',
  },
  // Agenda eyebrow: "AGENDA · TODAY|PLAN".
  agenda: {
    en: 'Agenda',
    hy: 'Օրակարգ',
    ru: 'Повестка',
  },
  today: {
    en: 'Today',
    hy: 'Այսօր',
    ru: 'Сегодня',
  },
  plan: {
    en: 'Plan',
    hy: 'Պլան',
    ru: 'План',
  },
  // Empty-day message (hero + agenda rail).
  dayEmpty: {
    en: 'No operations are planned for this day.',
    hy: 'Այս օրվա համար պլանավորված գործողություն չկա։',
    ru: 'На этот день не запланировано ни одной операции.',
  },
  // `delete_event` is denied by the window capability set today; the refusal used to be
  // swallowed and the event simply reappeared on the next read with nothing said.
  deleteRefusedTitle: {
    en: 'Delete refused — nothing was removed',
    hy: 'Ջնջումը մերժվեց — ոչինչ չհեռացվեց',
    ru: 'Удаление отклонено — ничего не удалено',
  },
  deleteRefusedBody: {
    en: 'The backend rejected this delete, so the event is still on the calendar.',
    hy: 'Backend-ը մերժեց այս ջնջումը, ուստի իրադարձությունը դեռ օրացույցում է։',
    ru: 'Бэкенд отклонил это удаление, поэтому событие всё ещё в календаре.',
  },
  deleting: {
    en: 'Deleting…',
    hy: 'Ջնջվում է…',
    ru: 'Удаление…',
  },
} as const;
