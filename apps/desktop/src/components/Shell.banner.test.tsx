import { describe, it, expect } from 'vitest';
import { dicts } from '../i18n';

// The no-backend banner used to read "Prototype — mock data, no backend connected."
// That lies in the OTHER direction: there is no mock layer anywhere in this build.
// `services/desktop.ts` maps every IPC name to a registered `#[tauri::command]`, so
// outside the Tauri runtime each call simply rejects and each panel renders its own
// error state. A user told they are looking at mock data would distrust real numbers
// and trust fabricated ones — exactly backwards.
const LANGS = ['en', 'hy', 'ru'] as const;

describe('Shell no-backend banner — the copy matches what the build actually does', () => {
  it('exists in all three languages', () => {
    for (const lang of LANGS) {
      const s = dicts[lang]['state.prototype'];
      expect(typeof s, `${lang} must carry state.prototype`).toBe('string');
      expect(s.trim()).not.toBe('');
    }
  });

  it('never asserts that mock/test data is on screen, in any language', () => {
    // The exact affirmative claims the old copy made, per language.
    const FALSE_CLAIMS: Record<(typeof LANGS)[number], RegExp> = {
      en: /[—-]\s*mock data/i,
      hy: /փորձնական տվյալներ,/,
      ru: /тестовые данные/i,
    };
    for (const lang of LANGS) {
      const s = dicts[lang]['state.prototype'];
      expect(
        FALSE_CLAIMS[lang].test(s),
        `${lang}: banner must not advertise mock data`,
      ).toBe(false);
    }
  });

  it('states the real situation in every language: no backend, and no mock data either', () => {
    expect(dicts.en['state.prototype']).toMatch(/no.*backend.*connected/i);
    // Each language explicitly DENIES the mock data the old copy asserted.
    expect(dicts.en['state.prototype']).toMatch(/there is no mock data/i);
    expect(dicts.hy['state.prototype']).toMatch(/Փորձնական տվյալներ չկան/);
    expect(dicts.ru['state.prototype']).toMatch(/Тестовых данных нет/);
  });
});
