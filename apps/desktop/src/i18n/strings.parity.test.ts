/// <reference types="vite/client" />
import { describe, it, expect } from 'vitest';

/**
 * Per-page trilingual parity guard. Beyond the central en/hy/ru dictionaries
 * (i18n.parity.test.ts), every feature ships a co-located `*.strings.ts` catalog
 * exporting `STR = { key: { en, hy, ru }, ... }`. This locks the SAME invariant on
 * those tables: a page-local key missing a language — or left empty — fails CI instead
 * of silently shipping a language "falling back" mid-page.
 *
 * Two holes it had. The glob was `../features/*.strings.ts`, so a catalog anywhere else —
 * `components/charts/Chart.strings.ts`, which every chart's fallback labels come from — was
 * never looked at. And an entry counted as trilingual only if it had an `en` string, so the
 * one shape this guard exists to catch at its worst, a key with hy and ru and NO en, was
 * skipped rather than failed.
 *
 * Still not covered: a trilingual table that is not in a `*.strings.ts` file at all
 * (`SURFACE_STR` in features/delegationView.tsx is one).
 */
// `import.meta.glob` is a Vite build-time macro and MUST be called in this literal form
// (Vite statically analyses it); the vite/client reference above provides its type.
const modules = import.meta.glob('../**/*.strings.ts', { eager: true }) as Record<
  string,
  { STR?: Record<string, unknown> }
>;

const LANGS = ['en', 'hy', 'ru'] as const;

/** True for a value shaped like a trilingual entry: an object carrying ANY of en / hy / ru. */
function isLangMap(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && LANGS.some((lang) => lang in (v as Record<string, unknown>));
}

describe('per-page i18n parity (*.strings.ts · en / hy / ru)', () => {
  const catalogs = Object.entries(modules).filter(([, m]) => m.STR);

  it('discovers the co-located per-page string catalogs', () => {
    expect(catalogs.length).toBeGreaterThan(0);
  });

  it('discovers catalogs outside features/ too', () => {
    expect(catalogs.map(([path]) => path)).toContain('../components/charts/Chart.strings.ts');
  });

  it('counts an entry with no `en` as trilingual, so it fails instead of being skipped', () => {
    expect(isLangMap({ hy: 'միայն', ru: 'только' })).toBe(true);
    expect(isLangMap({ en: 'only' })).toBe(true);
    expect(isLangMap('a helper constant')).toBe(false);
    expect(isLangMap({ unrelated: 1 })).toBe(false);
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
