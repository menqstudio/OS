// The vocabulary the local-write-record surface may never use — ONE list.
//
// It belongs to the signed governed-receipt path. Nothing on the Memory or Knowledge page is
// signed, nothing has custody of anything, and a write record attests CONTENT, never the
// writer; so a word from this list on either page is a claim the backend cannot back.
//
// It used to be written three times: `writeRecord.test.tsx` (13 patterns),
// `Memory.honesty.test.tsx` and `Knowledge.honesty.test.tsx` (9 each, and none of the Armenian
// or Russian ones). Three copies of a guard drift, and these already had. This module is the
// list all three now test against; it is test support, imported by tests only.
//
// The two page guards still SPELL OUT the nine English patterns in their own files, ahead of a
// spread of this list: `tools/test_check_source_control_bytes.py` pins that literal text there.
// Those nine are a subset of this list, so a page guard can never be narrower than it.
//
// THE ARMENIAN AND RUSSIAN HALVES ARE PER CONCEPT, AND SAY WHERE THEY STOP. The English half
// names nine patterns over five concepts; the other two languages used to cover two stems
// each (signed, verified), so a Russian `доверенный` or an Armenian `վստահելի` in a catalog
// passed. Each concept now has a stem in each language where one exists that cannot collide
// with honest copy. `custody` is the exception: Russian renders it with `хранение`, which
// shares its stem with `хранилище` ("store") — a word these pages legitimately use — so no
// Russian stem is listed for it and the English pattern, which runs over every language's
// text, is what catches the loanword.

export interface ForbiddenTerm {
  /** The concept the pattern stands for, for a failure message a reader can act on. */
  concept: 'verified' | 'trusted' | 'signed' | 'receipt' | 'custody' | 'tamper-proof';
  pattern: RegExp;
}

export const FORBIDDEN_RECEIPT_VOCABULARY: readonly ForbiddenTerm[] = [
  // ── English (also catches the untranslated loanword inside hy / ru copy) ──
  { concept: 'verified', pattern: /verifiable/i },
  { concept: 'verified', pattern: /\bverified\b/i },
  { concept: 'trusted', pattern: /trusted[ _-]?verified/i },
  { concept: 'trusted', pattern: /\btrusted\b/i },
  { concept: 'signed', pattern: /\bsigned\b/i },
  { concept: 'receipt', pattern: /governed receipt/i },
  { concept: 'receipt', pattern: /\breceipt\b/i },
  { concept: 'custody', pattern: /\bcustody\b/i },
  { concept: 'tamper-proof', pattern: /tamper[ -]?proof/i },
  // ── Armenian ──
  { concept: 'verified', pattern: /վավերաց/i },          // վավերացված
  { concept: 'verified', pattern: /ստուգված/i },         // "checked / verified"
  { concept: 'trusted', pattern: /վստահելի/i },
  { concept: 'signed', pattern: /ստորագր/i },
  { concept: 'receipt', pattern: /ստացական/i },
  { concept: 'custody', pattern: /պահառու/i },           // պահառություն
  { concept: 'tamper-proof', pattern: /կեղծումից պաշտպան/i },
  // ── Russian ──
  { concept: 'verified', pattern: /заверен/i },
  { concept: 'verified', pattern: /проверен/i },         // проверено / проверенный
  { concept: 'trusted', pattern: /доверен/i },           // доверенный
  { concept: 'signed', pattern: /подпис/i },
  { concept: 'receipt', pattern: /квитанц/i },
  { concept: 'tamper-proof', pattern: /защищ[её]н\S* от подделки/i },
];

/** The patterns alone, for a caller that only needs to test text. */
export const FORBIDDEN: readonly RegExp[] = FORBIDDEN_RECEIPT_VOCABULARY.map((t) => t.pattern);
