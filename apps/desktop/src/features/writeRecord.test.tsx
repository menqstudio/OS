import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, renderHook, screen, waitFor } from '@testing-library/react';

// The hook and the notice are exercised for real below, so the IPC boundary is mocked here —
// the pure functions above them never touch it.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import {
  parseWriteRecordState, writeRecordKind, writeRecordCounts, writeRecordLabel,
  writeRecordDetail, writeRecordReason, UNRECOGNISED_REPLY,
  useWriteRecordStates, WriteRecordNotice,
  type WriteRecordRead,
} from './writeRecord';
import type { WriteRecord } from '../services/desktop';
import * as RECORD_COPY from './writeRecord.strings';
import * as MEMORY_COPY from './Memory.strings';
import * as KNOWLEDGE_COPY from './Knowledge.strings';
import { FORBIDDEN, FORBIDDEN_RECEIPT_VOCABULARY } from './writeRecord.vocabulary';

const RECORD_STR = RECORD_COPY.STR;
const MEMORY_STR = MEMORY_COPY.STR;
const KNOWLEDGE_STR = KNOWLEDGE_COPY.STR;

beforeEach(() => invokeMock.mockReset());

// ---------------------------------------------------------------------------
// The shared reader, tested away from the pages.
//
// Its whole job is to say no more than the backend proved. Two properties matter most:
// an unrecognised reply must NEVER become `unrecorded` (a fault dressed as an innocent
// absence), and no state may be labelled with the governed-receipt vocabulary, because
// nothing here is signed and the record attests content rather than the writer.
// ---------------------------------------------------------------------------

const RECORD: WriteRecord = {
  id: 'wr-1',
  seq: 1,
  subjectKind: 'memory_entry',
  subjectId: 'm-1',
  operation: 'created',
  contentSha256: 'a'.repeat(64),
  prevRecordSha256: '0'.repeat(64),
  recordSha256: 'b'.repeat(64),
  recordedAt: '1700000000000',
};

describe('parseWriteRecordState — the four states the backend can defend', () => {
  it('accepts each real state verbatim', () => {
    expect(parseWriteRecordState({ state: 'unrecorded' })).toEqual({ state: 'unrecorded' });
    expect(parseWriteRecordState({ state: 'recorded', record: RECORD }))
      .toEqual({ state: 'recorded', record: RECORD });
    expect(parseWriteRecordState({ state: 'deleted_but_present', record: RECORD }))
      .toEqual({ state: 'deleted_but_present', record: RECORD });
    expect(parseWriteRecordState({
      state: 'content_diverged', record: RECORD, actual_content_sha256: 'c'.repeat(64),
    })).toEqual({
      state: 'content_diverged', record: RECORD, actual_content_sha256: 'c'.repeat(64),
    });
  });

  it('rejects anything it cannot interpret rather than guessing a state', () => {
    for (const raw of [
      null,
      undefined,
      'recorded',
      {},
      { state: 'verified' },
      { state: 'recorded' },                                   // a state with no record
      { state: 'recorded', record: { ...RECORD, seq: '1' } },  // seq mistyped
      { state: 'recorded', record: { ...RECORD, operation: 'renamed' } },
      { state: 'recorded', record: { ...RECORD, subjectKind: 'run_step' } },
      { state: 'content_diverged', record: RECORD },           // divergence with no digest
    ]) {
      expect(parseWriteRecordState(raw), JSON.stringify(raw ?? null)).toBeNull();
    }
  });

  it('refuses an unknown state at the parser', () => {
    expect(parseWriteRecordState({ state: 'brand_new_state' })).toBeNull();
  });
});

// The defect this guards: a reader that shrugs and reports "no record" makes a broken backend
// look like a clean, empty ledger. The mapping that could regress is in the HOOK
// (`parseWriteRecordState(raw) ?? unreadable`), so the hook is what is driven — for BOTH
// subjects, with a reply the parser cannot interpret. This used to assert `writeRecordKind` on a
// `{ phase: 'unreadable' }` literal the test had built itself, which no change to the hook
// could turn red.
describe('useWriteRecordStates — an uninterpretable reply is a fault, never "no record"', () => {
  for (const [subject, command] of [
    ['memory', 'memory_write_record_state'],
    ['knowledge', 'knowledge_write_record_state'],
  ] as const) {
    it(`${subject}: an unknown state reads back as unreadable`, async () => {
      invokeMock.mockImplementation((cmd: string) =>
        Promise.resolve(cmd === command ? { state: 'brand_new_state' } : null));
      const { result } = renderHook(() => useWriteRecordStates(subject, ['row-1']));
      await waitFor(() => expect(result.current.byId.get('row-1')?.phase).toBe('unreadable'));

      const read = result.current.byId.get('row-1');
      expect(read).toEqual({ phase: 'unreadable', reason: UNRECOGNISED_REPLY });
      expect(writeRecordKind(read)).toBe('unreadable');
      expect(writeRecordKind(read)).not.toBe('unrecorded');
      // …and the command asked was this subject's own.
      expect(invokeMock.mock.calls.some((c) => c[0] === command)).toBe(true);
    });

    it(`${subject}: a real "unrecorded" reply is still read as unrecorded`, async () => {
      // The control: the hook does not simply call everything a fault.
      invokeMock.mockImplementation(() => Promise.resolve({ state: 'unrecorded' }));
      const { result } = renderHook(() => useWriteRecordStates(subject, ['row-1']));
      await waitFor(() => expect(result.current.byId.get('row-1')?.phase).toBe('read'));
      expect(writeRecordKind(result.current.byId.get('row-1'))).toBe('unrecorded');
    });
  }
});

describe('WriteRecordNotice — reads the map the hook returns', () => {
  const diverged: WriteRecordRead = {
    phase: 'read',
    state: { state: 'content_diverged', record: RECORD, actual_content_sha256: 'c'.repeat(64) },
  };

  it('counts from a Map and survives a re-render with the same Map', () => {
    // Both pages used to pass `byId.values()` — a fresh ONE-SHOT iterator per render — so the
    // memo could never hit, and a second pass over the same iterator would have counted nothing.
    const reads = new Map<string, WriteRecordRead>([
      ['a', diverged], ['b', diverged], ['c', { phase: 'unreadable', reason: 'boom' }],
    ]);
    const { rerender } = render(<WriteRecordNotice reads={reads} lang="en" />);
    expect(screen.getByText(/2 rows no longer match their records/)).toBeInTheDocument();
    expect(screen.getByText(/1 record could not be read/)).toBeInTheDocument();

    rerender(<WriteRecordNotice reads={reads} lang="en" />);
    expect(screen.getByText(/2 rows no longer match their records/)).toBeInTheDocument();
    expect(screen.getByText(/1 record could not be read/)).toBeInTheDocument();
  });

  it('raises nothing for a page of ordinary rows', () => {
    const reads = new Map<string, WriteRecordRead>([
      ['a', { phase: 'read', state: { state: 'recorded', record: RECORD } }],
      ['b', { phase: 'read', state: { state: 'unrecorded' } }],
    ]);
    const { container } = render(<WriteRecordNotice reads={reads} lang="en" />);
    expect(container.querySelector('.wrec-notice')).toBeNull();
  });
});

describe('writeRecordKind — one kind per thing that can be said', () => {
  it('keeps the read phases out of the ledger states', () => {
    expect(writeRecordKind(undefined)).toBe('reading');
    expect(writeRecordKind({ phase: 'reading' })).toBe('reading');
    expect(writeRecordKind({ phase: 'unreadable', reason: 'boom' })).toBe('unreadable');
    expect(writeRecordKind({ phase: 'read', state: { state: 'unrecorded' } })).toBe('unrecorded');
    expect(writeRecordKind({ phase: 'read', state: { state: 'recorded', record: RECORD } }))
      .toBe('recorded');
    expect(writeRecordKind({
      phase: 'read',
      state: { state: 'content_diverged', record: RECORD, actual_content_sha256: 'c' },
    })).toBe('diverged');
    expect(writeRecordKind({ phase: 'read', state: { state: 'deleted_but_present', record: RECORD } }))
      .toBe('deletedPresent');
  });

  it('gives every kind its own label and its own sentence in every language', () => {
    const reads: WriteRecordRead[] = [
      { phase: 'reading' },
      { phase: 'unreadable', reason: 'boom' },
      { phase: 'read', state: { state: 'recorded', record: RECORD } },
      { phase: 'read', state: { state: 'unrecorded' } },
      { phase: 'read', state: { state: 'deleted_but_present', record: RECORD } },
      { phase: 'read', state: { state: 'content_diverged', record: RECORD, actual_content_sha256: 'c' } },
    ];
    for (const lang of ['en', 'hy', 'ru'] as const) {
      const labels = reads.map((r) => writeRecordLabel(r, lang));
      const details = reads.map((r) => writeRecordDetail(r, lang));
      expect(new Set(labels).size, `${lang} labels must all differ`).toBe(reads.length);
      expect(new Set(details).size, `${lang} sentences must all differ`).toBe(reads.length);
    }
  });
});

describe('writeRecordCounts — the page-level summary counts real rows', () => {
  it('counts each kind separately, faults included', () => {
    const counts = writeRecordCounts([
      { phase: 'read', state: { state: 'recorded', record: RECORD } },
      { phase: 'read', state: { state: 'recorded', record: RECORD } },
      { phase: 'read', state: { state: 'unrecorded' } },
      { phase: 'unreadable', reason: 'boom' },
      { phase: 'read', state: { state: 'content_diverged', record: RECORD, actual_content_sha256: 'c' } },
      { phase: 'read', state: { state: 'deleted_but_present', record: RECORD } },
    ]);
    expect(counts).toEqual({
      reading: 0, recorded: 2, unrecorded: 1, unreadable: 1, diverged: 1, deletedPresent: 1,
    });
  });
});

describe('writeRecordReason — a fault reads in the user’s language', () => {
  it('translates the sentinel and passes a real backend message through untouched', () => {
    expect(writeRecordReason(UNRECOGNISED_REPLY, 'en')).toMatch(/shape this page cannot read/i);
    expect(writeRecordReason(UNRECOGNISED_REPLY, 'ru')).not.toEqual(UNRECOGNISED_REPLY);
    expect(writeRecordReason(UNRECOGNISED_REPLY, 'hy')).not.toEqual(UNRECOGNISED_REPLY);
    expect(writeRecordReason('delete_memory not allowed.', 'en')).toBe('delete_memory not allowed.');
  });
});

// The vocabulary guard at its source: everything the three modules can put on screen, in all
// three languages. The list itself is `writeRecord.vocabulary.ts`, which the two rendered-page
// guards test against too — they used to carry only their own, shorter ones.
//
// "Everything" is the point. This used to walk the `STR` lang-maps only, under a comment saying
// "a word that never enters the catalog can never reach the screen" — while the parameterised
// copy (`divergedNotice`, `deletedPresentNotice`, `unreadableNotice`, Memory's `*Live` /
// `*Count` builders, Knowledge's `fmt.*`) is exported beside the catalog, IS rendered, and was
// never scanned. Every exported function is now called, per language and for a singular and a
// plural count, and its output held to the same list.
const LANGS = ['en', 'hy', 'ru'] as const;

/** Every string a strings module can produce: `[where, text]`. */
function everyString(moduleExports: Record<string, unknown>): [string, string][] {
  const out: [string, string][] = [];
  const call = (name: string, fn: (...a: unknown[]) => unknown) => {
    for (const lang of LANGS) {
      // The builders take `(lang, count | text, …)`. A number is valid for either kind of
      // parameter (it is only ever interpolated), and 1 / 2 reach both plural arms.
      for (const n of [1, 2]) {
        const text = fn(lang, n, n);
        if (typeof text === 'string') out.push([`${name}(${lang}, ${n})`, text]);
      }
    }
  };
  const walk = (path: string, val: unknown) => {
    if (typeof val === 'function') { call(path, val as (...a: unknown[]) => unknown); return; }
    if (typeof val !== 'object' || val === null) return;
    for (const [key, inner] of Object.entries(val as Record<string, unknown>)) {
      if (typeof inner === 'string') out.push([`${path}.${key}`, inner]);
      else walk(`${path}.${key}`, inner);
    }
  };
  for (const [name, val] of Object.entries(moduleExports)) walk(name, val);
  return out;
}

describe('the record surface never borrows the receipt vocabulary', () => {
  const MODULES = [
    ['writeRecord.strings.ts', RECORD_COPY, 3],
    ['Memory.strings.ts', MEMORY_COPY, 4],
    ['Knowledge.strings.ts', KNOWLEDGE_COPY, 5],
  ] as const;

  for (const [name, moduleExports, builders] of MODULES) {
    it(`${name} claims nothing stronger than the record supports — catalog AND builders`, () => {
      const strings = everyString(moduleExports as unknown as Record<string, unknown>);
      // Not vacuous: the builders really were called (each yields 3 languages × 2 counts).
      const built = strings.filter(([where]) => where.includes('('));
      expect(built.length, `${name}: parameterised copy scanned`).toBe(builders * LANGS.length * 2);
      expect(strings.length).toBeGreaterThan(built.length);

      for (const [where, text] of strings) {
        for (const forbidden of FORBIDDEN) {
          expect(text, `${name} :: ${where} must not contain ${forbidden}`).not.toMatch(forbidden);
        }
      }
    });
  }

  it('the guard reaches parameterised copy: a builder that said "verified" would fail it', () => {
    const planted = { leak: (lang: string, n: number) => `${n} rows verified (${lang})` };
    const hits = everyString(planted).filter(([, text]) => FORBIDDEN.some((re) => re.test(text)));
    expect(hits.length).toBe(LANGS.length * 2);
  });

  it('every forbidden concept has a pattern in each language, except the one that cannot', () => {
    // The hy / ru halves used to hold two stems each (signed, verified), so `доверенный`,
    // `квитанция`, `ստուգված` or `վստահելի` in a catalog passed.
    const samples: Record<string, Record<string, string>> = {
      verified: { hy: 'տողը ստուգված է', ru: 'строка проверена' },
      trusted: { hy: 'վստահելի գրանցում', ru: 'доверенная запись' },
      signed: { hy: 'ստորագրված է', ru: 'подписано' },
      receipt: { hy: 'ստացական', ru: 'квитанция' },
      'tamper-proof': { hy: 'կեղծումից պաշտպանված', ru: 'защищён от подделки' },
      // `custody` has an Armenian stem and deliberately NO Russian one (see the module).
      custody: { hy: 'պահառություն' },
    };
    for (const [concept, byLang] of Object.entries(samples)) {
      for (const [lang, sample] of Object.entries(byLang)) {
        const caught = FORBIDDEN_RECEIPT_VOCABULARY
          .filter((t) => t.concept === concept)
          .some((t) => t.pattern.test(sample));
        expect(caught, `${concept} (${lang}): "${sample}" must be caught`).toBe(true);
      }
    }
    // Honest copy the pages DO use must not trip the Russian half.
    for (const honest of ['Локальное хранилище', 'Прочитано из хранилища', 'Записано']) {
      expect(FORBIDDEN.some((re) => re.test(honest)), honest).toBe(false);
    }
  });

  it('states the ceiling explicitly: content, never the writer', () => {
    expect(RECORD_STR.panelScope.en).toMatch(/says nothing about who wrote it/i);
    expect(RECORD_STR.provenance.en).toMatch(/never who wrote it/i);
  });

  it('the provenance line exists once, in the shared catalog', () => {
    // It was copied verbatim, in all three languages, into both page catalogs — in the module
    // that exists so the two pages say exactly the same thing.
    expect('provenance' in MEMORY_STR).toBe(false);
    expect('provenance' in KNOWLEDGE_STR).toBe(false);
  });

  it('no longer carries the provenance line that stopped being true', () => {
    // "Local store · no verification chain" was honest when written; every write now
    // appends a record, so leaving it would have been the dishonest choice.
    expect(RECORD_STR.provenance.en).not.toMatch(/no verification chain/i);
    for (const lang of LANGS) {
      expect(RECORD_STR.provenance[lang].length, `${lang} provenance must say what backs the rows`)
        .toBeGreaterThan(20);
    }
  });

  it('"no record" names both causes and asserts neither', () => {
    // The backend returns `Unrecorded` for a row written before migration 0021 AND for a row
    // written by a path that does not record (its own test: a raw INSERT made after 0021). The
    // copy said only "it was written before the record existed" — which tells the owner an
    // out-of-band insert is benign legacy.
    expect(RECORD_STR.detailUnrecorded.en).toMatch(/Either it was written before the record existed, or it was inserted/);
    expect(RECORD_STR.detailUnrecorded.en).toMatch(/cannot tell which/);
    expect(RECORD_STR.detailUnrecorded.hy).toMatch(/Կամ .* կամ /);
    expect(RECORD_STR.detailUnrecorded.ru).toMatch(/Либо .* либо /);
    for (const lang of LANGS) {
      expect(writeRecordDetail({ phase: 'read', state: { state: 'unrecorded' } }, lang))
        .toBe(RECORD_STR.detailUnrecorded[lang]);
    }
  });
});
