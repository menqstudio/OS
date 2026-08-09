import { describe, it, expect } from 'vitest';
import { isGuardDenied } from './filesModel';

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
