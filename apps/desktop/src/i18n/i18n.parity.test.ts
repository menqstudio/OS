import { describe, it, expect } from 'vitest';
import { en } from './en';
import { hy } from './hy';
import { ru } from './ru';

/**
 * Trilingual parity guard. Every user-facing string in the cockpit is authored in
 * en / hy / ru; this locks that invariant so a future key added to one dictionary but
 * not the others (a language "falling back" mid-page) fails CI instead of shipping.
 */
describe('i18n parity (en / hy / ru)', () => {
  const dicts = { en, hy, ru } as const;
  const keysOf = (d: Record<string, string>) => Object.keys(d).sort();

  it('all three dictionaries carry the identical key set', () => {
    const base = keysOf(en);
    expect(keysOf(hy)).toEqual(base);
    expect(keysOf(ru)).toEqual(base);
  });

  it('no dictionary has an empty or whitespace-only value', () => {
    for (const [lang, d] of Object.entries(dicts)) {
      for (const [k, v] of Object.entries(d)) {
        expect(v.trim(), `${lang}:${k} must be non-empty`).not.toBe('');
      }
    }
  });
});
