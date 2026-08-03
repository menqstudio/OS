import { describe, it, expect } from 'vitest';
import { NAV, ALL_ITEMS } from './nav';
import { en } from '../i18n/en';
import { hy } from '../i18n/hy';
import { ru } from '../i18n/ru';

/**
 * Nav integrity. Guards the audit finding where eight real, backed views showed the
 * generic "Prototype workspace" subtitle, plus the trilingual + uniqueness invariants.
 */
describe('nav', () => {
  const dicts = { en, hy, ru } as Record<string, Record<string, string>>;

  it('every label + subtitle key resolves in all three languages', () => {
    for (const item of ALL_ITEMS) {
      for (const key of [item.labelKey, item.subtitleKey]) {
        for (const [lang, d] of Object.entries(dicts)) {
          expect(d[key], `${lang}:${key}`).toBeTruthy();
        }
      }
    }
  });

  it('no backed view falls back to the generic "Prototype workspace" subtitle', () => {
    const offenders = ALL_ITEMS.filter((i) => i.subtitleKey === 'generic.subtitle').map((i) => i.id);
    expect(offenders).toEqual([]);
  });

  it('route ids are unique across all nav groups', () => {
    const ids = ALL_ITEMS.map((i) => i.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('groups are non-empty', () => {
    for (const g of NAV) expect(g.items.length).toBeGreaterThan(0);
  });
});
