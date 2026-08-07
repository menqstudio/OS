import { describe, it, expect } from 'vitest';

import {
  parseWriteRecordState, writeRecordKind, writeRecordCounts, writeRecordLabel,
  writeRecordDetail, writeRecordReason, UNRECOGNISED_REPLY,
  type WriteRecordRead,
} from './writeRecord';
import type { WriteRecord } from '../services/desktop';
import { STR as RECORD_STR } from './writeRecord.strings';
import { STR as MEMORY_STR } from './Memory.strings';
import { STR as KNOWLEDGE_STR } from './Knowledge.strings';

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

  it('never turns an uninterpretable reply into "unrecorded"', () => {
    // The defect this guards: a reader that shrugs and reports "no record" makes a broken
    // backend look like a clean, empty ledger.
    expect(parseWriteRecordState({ state: 'brand_new_state' })).not.toEqual({ state: 'unrecorded' });
    const read: WriteRecordRead = { phase: 'unreadable', reason: UNRECOGNISED_REPLY };
    expect(writeRecordKind(read)).toBe('unreadable');
    expect(writeRecordKind(read)).not.toBe('unrecorded');
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

// The vocabulary guard at its source: the catalogs themselves, in all three languages.
// A word that never enters the catalog can never reach the screen.
const FORBIDDEN = [
  /verifiable/i,
  /\bverified\b/i,
  /trusted[ _-]?verified/i,
  /\btrusted\b/i,
  /\bsigned\b/i,
  /governed receipt/i,
  /\breceipt\b/i,
  /\bcustody\b/i,
  /tamper[ -]?proof/i,
  /ստորագր/i,   // "signed" (hy)
  /վավերաց/i,   // "verified" (hy)
  /подпис/i,    // "signed" (ru)
  /заверен/i,   // "certified" (ru)
];

function values(catalog: Record<string, unknown>): [string, string][] {
  const out: [string, string][] = [];
  for (const [key, val] of Object.entries(catalog)) {
    if (typeof val !== 'object' || val === null) continue;
    for (const [lang, text] of Object.entries(val as Record<string, unknown>)) {
      if (typeof text === 'string') out.push([`${key}.${lang}`, text]);
    }
  }
  return out;
}

describe('the record surface never borrows the receipt vocabulary', () => {
  for (const [name, catalog] of [
    ['writeRecord.strings.ts', RECORD_STR],
    ['Memory.strings.ts', MEMORY_STR],
    ['Knowledge.strings.ts', KNOWLEDGE_STR],
  ] as const) {
    it(`${name} claims nothing stronger than the record supports`, () => {
      for (const [where, text] of values(catalog as unknown as Record<string, unknown>)) {
        for (const forbidden of FORBIDDEN) {
          expect(text, `${name} :: ${where} must not contain ${forbidden}`).not.toMatch(forbidden);
        }
      }
    });
  }

  it('states the ceiling explicitly: content, never the writer', () => {
    expect(RECORD_STR.panelScope.en).toMatch(/says nothing about who wrote it/i);
    expect(MEMORY_STR.provenance.en).toMatch(/never who wrote it/i);
    expect(KNOWLEDGE_STR.provenance.en).toMatch(/never who wrote it/i);
  });

  it('no longer carries the provenance line that stopped being true', () => {
    // "Local store · no verification chain" was honest when written; every write now
    // appends a record, so leaving it would have been the dishonest choice.
    expect(MEMORY_STR.provenance.en).not.toMatch(/no verification chain/i);
    expect(KNOWLEDGE_STR.provenance.en).not.toMatch(/no verification chain/i);
    for (const line of [MEMORY_STR.provenance, KNOWLEDGE_STR.provenance]) {
      for (const lang of ['en', 'hy', 'ru'] as const) {
        expect(line[lang].length, `${lang} provenance must say what backs the rows`)
          .toBeGreaterThan(20);
      }
    }
  });
});
