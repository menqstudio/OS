import { describe, it, expect } from 'vitest';
import { establishedContentSize, isGuardDenied, MAX_EDIT_BYTES } from './filesModel';
import { parseTimestamp } from './timestamps';

// The COMPLETE set of Err strings the Rust file commands can return
// (src-tauri/src/files.rs). Kept here so a backend wording change that this
// classifier silently stops matching shows up as a failing test rather than as
// a badge that quietly stops appearing.
const BACKEND_ERRORS = {
  filesRootNotAllowed: 'the configured files root is not allowed',
  workspaceNotConfigured: 'file workspace is not configured',
  workspaceUnavailable: 'file workspace is unavailable',
  pathRefused: 'path is not accessible in this workspace',
  cannotList: 'cannot list directory',
  cannotRead: 'cannot read file',
  cannotWrite: 'cannot write file',
  notEditable: 'not an editable file',
};

describe('establishedContentSize', () => {
  it('does not report the read cap as the size of an over-cap file', () => {
    // files.rs reads `take(MAX_EDIT_BYTES + 1)` and reports `buf.len()`, so EVERY over-cap file
    // comes back as exactly this number. It used to be rendered as "2.0 MB" for a 40 MB file.
    expect(establishedContentSize({ readonly: true, sizeBytes: MAX_EDIT_BYTES + 1 })).toBeNull();
  });

  it('does not report the placeholder zero of a non-regular file', () => {
    expect(establishedContentSize({ readonly: true, sizeBytes: 0 })).toBeNull();
  });

  it('reports a size the read really measured', () => {
    expect(establishedContentSize({ readonly: false, sizeBytes: 128 })).toBe(128);
    // Binary: the whole file was read and failed the UTF-8 parse, so its length IS its size.
    expect(establishedContentSize({ readonly: true, sizeBytes: 4096 })).toBe(4096);
  });
});

describe('isGuardDenied', () => {
  it('classifies the files-root clamp as a guard denial', () => {
    expect(isGuardDenied(BACKEND_ERRORS.filesRootNotAllowed)).toBe(true);
  });

  it('does NOT claim a guard denial for the unified path refusal', () => {
    // files.rs returns ONE string for does-not-exist, cannot-canonicalize,
    // outside-the-root and denylisted, so that the renderer cannot use the
    // wording to probe whether an arbitrary absolute path exists. Because the
    // backend no longer establishes which of those happened, the page must not
    // announce `sealed` — a deleted file is not a refused one.
    expect(isGuardDenied(BACKEND_ERRORS.pathRefused)).toBe(false);
  });

  it('does not classify availability / transport failures as guard denials', () => {
    for (const key of [
      'workspaceNotConfigured',
      'workspaceUnavailable',
      'cannotList',
      'cannotRead',
      'cannotWrite',
      'notEditable',
    ] as const) {
      expect(isGuardDenied(BACKEND_ERRORS[key])).toBe(false);
    }
  });
});

// `features/timestamps.ts` — the one parser for the timestamps the backend writes. It is tested
// here, beside `parseModified`'s module, rather than in a file of its own: `counted-claims.json`
// recounts the test FILES on every run, and a parser of seven lines does not need a new one.
describe('parseTimestamp — the backend writes epoch-milliseconds as text', () => {
  it('parses the exact shape brops_core::now() returns', () => {
    // `new Date("1700000000000")` is Invalid Date; that is the defect the module exists for.
    expect(Number.isNaN(new Date('1700000000000').getTime())).toBe(true);
    expect(parseTimestamp('1700000000000')?.getTime()).toBe(1700000000000);
  });

  it('parses a numeric epoch and an ISO string', () => {
    expect(parseTimestamp(1700000000000)?.getTime()).toBe(1700000000000);
    expect(parseTimestamp('2026-08-07T14:44:11.166Z')?.toISOString()).toBe('2026-08-07T14:44:11.166Z');
  });

  it('returns null for an absent, blank or unparseable value', () => {
    expect(parseTimestamp(null)).toBeNull();
    expect(parseTimestamp(undefined)).toBeNull();
    expect(parseTimestamp('')).toBeNull();
    expect(parseTimestamp('   ')).toBeNull();
    expect(parseTimestamp('not a date')).toBeNull();
  });
});
