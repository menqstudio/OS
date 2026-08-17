import { describe, it, expect } from 'vitest';
import { heldLabel, heldNoteKey } from './Research.provenance';
import { STR } from './Research.strings';

/**
 * A-05, sixth independent audit — the renderer half.
 *
 * The Research panel rendered "Verified · held" and "Verified desktop-side and held by the
 * backend" for every held answer, including the one produced with no governed turn, no challenge
 * and no receipt. On a shipped install that ungoverned path is the ONLY one that can be reached,
 * so the strongest claim on the page was permanently attached to the weakest outcome the app has.
 *
 * These pin both halves of the fix: each provenance gets its own words, and anything unrecognised
 * fails toward the warning rather than toward the pass.
 */
describe('a held answer is described by what produced it', () => {
  it('a trusted verification is the only thing called verified', () => {
    expect(heldLabel('trusted_verified')).toMatchObject({ tone: 'success', key: 'heldVerified' });
    // And nothing else is.
    for (const p of ['development_untrusted', 'ungoverned', 'anything-else', '']) {
      expect(heldLabel(p).key, `${p} must not be labelled verified`).not.toBe('heldVerified');
      expect(heldNoteKey(p), `${p} must not get the verified note`).not.toBe('heldVerifiedNote');
    }
  });

  it('a development-untrusted turn is a warning, not a pass', () => {
    expect(heldLabel('development_untrusted')).toMatchObject({ tone: 'warn', key: 'heldDevelopment' });
    expect(heldNoteKey('development_untrusted')).toBe('heldDevelopmentNote');
  });

  it('the ungoverned path — the only one a shipped install reaches — reads as the worst case', () => {
    expect(heldLabel('ungoverned')).toMatchObject({ tone: 'bad', key: 'heldUngoverned' });
    expect(heldNoteKey('ungoverned')).toBe('heldUngovernedNote');
  });

  it('an outcome this version cannot name fails toward the warning', () => {
    // THE LOAD-BEARING ARM. The declared union is a hope about the backend; this is what holds.
    for (const p of ['', 'trusted', 'TRUSTED_VERIFIED', 'verified', 'governed', 'null']) {
      expect(heldLabel(p), `${p} must not pass`).toMatchObject({ tone: 'bad', key: 'heldUnknown' });
      expect(heldNoteKey(p)).toBe('heldUnknownNote');
    }
  });

  it('every key these functions can return actually exists, in all three languages', () => {
    // A label that resolves to a missing key renders the key name at the user. The i18n parity
    // gate covers `src/i18n/`, not the per-feature strings tables, so this is where it is checked.
    const keys = new Set<string>();
    for (const p of ['trusted_verified', 'development_untrusted', 'ungoverned', 'unknown']) {
      keys.add(heldLabel(p).key);
      keys.add(heldNoteKey(p));
    }
    expect(keys.size).toBe(8);
    for (const k of keys) {
      const entry = (STR as Record<string, { en?: string; hy?: string; ru?: string }>)[k];
      expect(entry, `${k} is returned by the labeller and missing from STR`).toBeTruthy();
      for (const lang of ['en', 'hy', 'ru'] as const) {
        expect(entry[lang], `${k}.${lang}`).toBeTruthy();
      }
    }
  });

  it('the tones it returns are ones the stylesheet defines', () => {
    // `pill success` and `pill bad` were APPLIED in this app and defined by no rule until
    // 2026-08-17 — the sixth audit's §E class, found while fixing A-05. This asserts the labeller
    // never reaches for a tone outside the vocabulary; `ui.browser.spec.tsx` asserts the
    // vocabulary is actually styled, in a real browser.
    const allowed = new Set(['success', 'warn', 'bad']);
    for (const p of ['trusted_verified', 'development_untrusted', 'ungoverned', 'unknown']) {
      expect(allowed.has(heldLabel(p).tone), `${p} → ${heldLabel(p).tone}`).toBe(true);
    }
  });
});
