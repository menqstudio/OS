import type { Lang } from '../domain/enums';

// ---------------------------------------------------------------------------
// Copy for the LOCAL WRITE RECORD surface shared by the Memory and Knowledge
// pages (`writeRecord.tsx`).
//
// Read `apps/desktop/src-tauri/core/src/local_write_record.rs` before touching a
// word here. What the backend can defend:
//
//   * every memory/knowledge write appends a record IN THE SAME TRANSACTION as
//     the row write, hashing the row's content into a prev-hash chain that the
//     database itself keeps append-only (three triggers, not a convention);
//   * so recomputing the digest from the row on screen detects a later edit made
//     outside the app — `content_diverged`.
//
// What it CANNOT defend: anything about the writer. Nothing is signed, there is
// no key, no manifest, no external authority and no containment; the record is
// produced by the same local process that performed the write. So this copy must
// never borrow the governed-receipt vocabulary ("verified", "trusted", "signed",
// "receipt") — a record proves the row has not been edited behind the app's back
// since it was written, and that is all it may be made to say.
//
// Trilingual (en / hy / ru), enforced by `src/i18n/strings.parity.test.ts`.
// ---------------------------------------------------------------------------

export const STR = {
  // ── Badge labels (one per rendered row) ────────────────────────────────
  badgeReading: {
    en: 'Reading record…',
    hy: 'Կարդում ենք գրանցումը…',
    ru: 'Читаем запись…',
  },
  // A FAULT: the read itself did not answer. Deliberately worded so it can never
  // be mistaken for "there is no record" — collapsing the two is how a broken
  // reader reads as an empty ledger.
  badgeUnreadable: {
    en: 'Record unreadable',
    hy: 'Գրանցումն ընթեռնելի չէ',
    ru: 'Запись не прочитана',
  },
  badgeRecorded: {
    en: 'Recorded',
    hy: 'Գրանցված',
    ru: 'Записано',
  },
  badgeDiverged: {
    en: 'Content diverged',
    hy: 'Բովանդակությունը շեղվել է',
    ru: 'Содержимое разошлось',
  },
  badgeDeletedPresent: {
    en: 'Deleted, yet present',
    hy: 'Ջնջված, բայց առկա',
    ru: 'Удалено, но присутствует',
  },
  // NOT a failure and NOT tampering: the row simply predates the record. There was
  // no back-fill, deliberately — minting a record for a write nobody witnessed
  // would be a forged receipt.
  badgeUnrecorded: {
    en: 'No record',
    hy: 'Գրանցում չկա',
    ru: 'Нет записи',
  },

  // ── Detail panel ───────────────────────────────────────────────────────
  panelTitle: {
    en: 'Local write record',
    hy: 'Տեղական գրման գրանցում',
    ru: 'Локальный журнал записи',
  },
  detailReading: {
    en: 'Reading this row’s record…',
    hy: 'Կարդում ենք այս տողի գրանցումը…',
    ru: 'Читаем запись этой строки…',
  },
  detailUnreadable: {
    en: 'The record could not be read, so this row’s state is unknown. This is a fault in the read — not a row without a record.',
    hy: 'Գրանցումը չհաջողվեց կարդալ, ուստի այս տողի վիճակն անհայտ է։ Սա ընթերցման խափանում է — ոչ թե առանց գրանցման տող։',
    ru: 'Запись не удалось прочитать, поэтому состояние этой строки неизвестно. Это сбой чтения — а не строка без записи.',
  },
  detailRecorded: {
    en: 'This row still matches the record appended when it was written: it has not been edited behind the app’s back since.',
    hy: 'Այս տողը դեռ համընկնում է գրելու պահին ավելացված գրանցման հետ. այդ ժամանակից ի վեր այն չի խմբագրվել հավելվածի թիկունքում։',
    ru: 'Эта строка по-прежнему совпадает с записью, добавленной при её записи: с тех пор её не правили в обход приложения.',
  },
  detailDiverged: {
    en: 'This row no longer matches its record. It was changed outside the app after it was written.',
    hy: 'Այս տողն այլևս չի համընկնում իր գրանցման հետ։ Գրվելուց հետո այն փոխվել է հավելվածից դուրս։',
    ru: 'Эта строка больше не совпадает со своей записью. После записи её изменили вне приложения.',
  },
  detailDeletedPresent: {
    en: 'The most recent record for this id says the row was deleted, yet a row is present under it.',
    hy: 'Այս id-ի վերջին գրանցումն ասում է, որ տողը ջնջվել է, բայց այդ id-ով տող առկա է։',
    ru: 'Последняя запись для этого id говорит, что строка удалена, однако строка под ним есть.',
  },
  detailUnrecorded: {
    en: 'No record was appended for this row: it was written before the record existed. Nothing was back-filled — a record for a write nobody witnessed would be invented.',
    hy: 'Այս տողի համար գրանցում չի ավելացվել. այն գրվել է գրանցումների գոյությունից առաջ։ Ոչինչ հետընթաց չի լրացվել — չտեսնված գրման համար գրանցում սարքելը հորինված կլիներ։',
    ru: 'Для этой строки запись не добавлялась: она записана до того, как журнал появился. Ничего не досоздавалось — запись о том, чего никто не наблюдал, была бы выдумкой.',
  },
  // The ceiling on every reading above, stated on the panel itself.
  panelScope: {
    en: 'A record pins the row’s content at the moment of the write. It says nothing about who wrote it, and nothing outside this machine vouches for it.',
    hy: 'Գրանցումը ամրագրում է տողի բովանդակությունը գրման պահին։ Այն ոչինչ չի ասում, թե ով է գրել, և այս մեքենայից դուրս ոչինչ դրա համար չի երաշխավորում։',
    ru: 'Запись фиксирует содержимое строки в момент записи. Она ничего не говорит о том, кто её записал, и ничто за пределами этой машины за неё не ручается.',
  },

  // ── Field labels on the panel ──────────────────────────────────────────
  fieldRecordedAt: { en: 'recorded', hy: 'գրանցվել է', ru: 'записано' },
  fieldChainPos: { en: 'chain position', hy: 'շղթայի դիրք', ru: 'позиция в цепочке' },
  fieldWrite: { en: 'write', hy: 'գրում', ru: 'операция' },
  fieldRecordedHash: { en: 'recorded hash', hy: 'գրանցված հեշ', ru: 'записанный хеш' },
  fieldRowHashNow: { en: 'row hash now', hy: 'տողի ներկա հեշ', ru: 'текущий хеш строки' },
  fieldReason: { en: 'reason', hy: 'պատճառ', ru: 'причина' },

  // ── Write operations, as stored ────────────────────────────────────────
  opCreated: { en: 'created', hy: 'ստեղծված', ru: 'создано' },
  opUpdated: { en: 'updated', hy: 'թարմացված', ru: 'обновлено' },
  opDeleted: { en: 'deleted', hy: 'ջնջված', ru: 'удалено' },

  // ── Page-level notice heading ──────────────────────────────────────────
  noticeTitle: {
    en: 'Write records',
    hy: 'Գրման գրանցումներ',
    ru: 'Записи журнала',
  },

  // The reply came back in a shape this build cannot read. Fail closed: an
  // uninterpretable answer is a fault, never "no record".
  unrecognisedReply: {
    en: 'the backend replied in a shape this page cannot read',
    hy: 'backend-ը պատասխանեց այնպիսի ձևով, որը այս էջը չի կարող կարդալ',
    ru: 'бэкенд ответил в формате, который эта страница не может прочитать',
  },
} as const;

// ── Parameterised copy — authored per language so counts read naturally ──

/** Rows whose current content no longer hashes to their own record. */
export function divergedNotice(lang: Lang, n: number): string {
  switch (lang) {
    case 'hy':
      return `${n} տող այլևս չի համընկնում իր գրանցման հետ — փոխվել է հավելվածից դուրս։`;
    case 'ru':
      return `Строк, не совпадающих со своей записью: ${n}. Они изменены вне приложения.`;
    default:
      return n === 1
        ? '1 row no longer matches its record — it was changed outside the app.'
        : `${n} rows no longer match their records — they were changed outside the app.`;
  }
}

/** Rows present under an id whose latest record says "deleted". */
export function deletedPresentNotice(lang: Lang, n: number): string {
  switch (lang) {
    case 'hy':
      return `${n} տող առկա է այնպիսի id-ով, որի վերջին գրանցումն ասում է՝ ջնջված է։`;
    case 'ru':
      return `Строк под id, последняя запись которых говорит «удалено»: ${n}.`;
    default:
      return n === 1
        ? '1 row is present under an id whose latest record says it was deleted.'
        : `${n} rows are present under ids whose latest record says they were deleted.`;
  }
}

/** Records the page FAILED to read. Never folded into "no record". */
export function unreadableNotice(lang: Lang, n: number): string {
  switch (lang) {
    case 'hy':
      return `${n} գրանցում չհաջողվեց կարդալ։ Սա ընթերցման խափանում է, ոչ թե բացակայող գրանցում։`;
    case 'ru':
      return `Записей, которые не удалось прочитать: ${n}. Это сбой чтения, а не отсутствие записи.`;
    default:
      return n === 1
        ? '1 record could not be read. That is a read fault, not a missing record.'
        : `${n} records could not be read. That is a read fault, not missing records.`;
  }
}
