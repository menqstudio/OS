/// <reference types="vite/client" />
import { describe, it, expect } from 'vitest';

/**
 * Per-page trilingual parity guard. Beyond the central en/hy/ru dictionaries
 * (i18n.parity.test.ts), every feature ships a co-located `*.strings.ts` catalog
 * exporting `STR = { key: { en, hy, ru }, ... }`. This locks the SAME invariant on
 * those tables: a page-local key missing a language — or left empty — fails CI instead
 * of silently shipping a language "falling back" mid-page.
 */
// `import.meta.glob` is a Vite build-time macro and MUST be called in this literal form
// (Vite statically analyses it); the vite/client reference above provides its type.
const modules = import.meta.glob('../features/*.strings.ts', { eager: true }) as Record<
  string,
  { STR?: Record<string, unknown> }
>;

const LANGS = ['en', 'hy', 'ru'] as const;

/** True for a value shaped like a trilingual entry (an object carrying an `en` string). */
function isLangMap(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && typeof (v as Record<string, unknown>).en === 'string';
}

describe('per-page i18n parity (*.strings.ts · en / hy / ru)', () => {
  const catalogs = Object.entries(modules).filter(([, m]) => m.STR);

  it('discovers the co-located per-page string catalogs', () => {
    expect(catalogs.length).toBeGreaterThan(0);
  });

  for (const [path, mod] of catalogs) {
    const STR = mod.STR as Record<string, unknown>;
    it(`${path}: every trilingual key carries a non-empty en/hy/ru`, () => {
      for (const [key, val] of Object.entries(STR)) {
        // Only entries authored as trilingual maps are guarded; a page may export a
        // helper or a non-string constant on STR, which we skip.
        if (!isLangMap(val)) continue;
        for (const lang of LANGS) {
          const s = (val as Record<string, unknown>)[lang];
          expect(typeof s, `${path} :: ${key}.${lang} must be a string`).toBe('string');
          expect((s as string).trim(), `${path} :: ${key}.${lang} must be non-empty`).not.toBe('');
        }
      }
    });
  }
});
