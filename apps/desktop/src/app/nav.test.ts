import { describe, it, expect } from 'vitest';
import { NAV, ALL_ITEMS, navLabel, navSubtitle } from './nav';
import { translate } from '../i18n';
import { en } from '../i18n/en';
import { hy } from '../i18n/hy';
import { ru } from '../i18n/ru';
import type { Lang } from '../domain/enums';

/**
 * Nav integrity. Guards the audit finding where eight real, backed views showed the
 * generic "Prototype workspace" subtitle, plus the trilingual + uniqueness invariants.
 *
 * A nav entry may take its copy from either source: the shared `i18n/*.ts` dictionaries,
 * or a trilingual `labelCopy`/`subtitleCopy` authored next to the page that owns it (the
 * `*.strings.ts` pattern — how `Bridge` carries its own copy). The invariant is the same
 * for both: real text in all three languages, never a key leaking to the screen.
 */
describe('nav', () => {
  const dicts = { en, hy, ru } as Record<string, Record<string, string>>;
  const LANGS: Lang[] = ['en', 'hy', 'ru'];

  it('every dictionary-backed label + subtitle key resolves in all three languages', () => {
    for (const item of ALL_ITEMS) {
      if (!item.labelCopy) {
        for (const [lang, d] of Object.entries(dicts)) {
          expect(d[item.labelKey], `${lang}:${item.labelKey}`).toBeTruthy();
        }
      }
      if (!item.subtitleCopy) {
        for (const [lang, d] of Object.entries(dicts)) {
          expect(d[item.subtitleKey], `${lang}:${item.subtitleKey}`).toBeTruthy();
        }
      }
    }
  });

  it('every item that carries its own copy carries all three languages', () => {
    for (const item of ALL_ITEMS) {
      for (const copy of [item.labelCopy, item.subtitleCopy]) {
        if (!copy) continue;
        for (const lang of LANGS) {
          expect(copy[lang]?.trim(), `${item.id}.${lang}`).toBeTruthy();
        }
      }
    }
  });

  /** The end-to-end property, whichever source the copy came from: what the sidebar and
   *  the command palette actually render is real text, not a raw key. */
  it('resolves a real label and subtitle for every item, in every language', () => {
    for (const item of ALL_ITEMS) {
      for (const lang of LANGS) {
        const t = (k: Parameters<typeof translate>[1]) => translate(lang, k);
        const label = navLabel(item, lang, t);
        const subtitle = navSubtitle(item, lang, t);
        expect(label.trim(), `${item.id} label (${lang})`).toBeTruthy();
        expect(label, `${item.id} label (${lang}) leaked a key`).not.toBe(item.labelKey);
        expect(subtitle.trim(), `${item.id} subtitle (${lang})`).toBeTruthy();
        expect(subtitle, `${item.id} subtitle (${lang}) leaked a key`).not.toBe(item.subtitleKey);
      }
    }
  });

  it('reads the bridge label from the page that owns it, not from the shared dictionary', () => {
    const bridge = ALL_ITEMS.find((i) => i.id === 'bridge');
    expect(bridge, 'the bridge must appear in the nav').toBeDefined();
    expect(bridge!.labelCopy).toBeDefined();
    // Its keys deliberately do NOT exist in i18n/*.ts — that is the point.
    expect(en[bridge!.labelKey]).toBeUndefined();
    expect(navLabel(bridge!, 'en', (k) => translate('en', k))).toBe('Governed bridge');
    expect(navLabel(bridge!, 'ru', (k) => translate('ru', k))).not.toBe(navLabel(bridge!, 'en', (k) => translate('en', k)));
  });

  it('no backed view falls back to the generic "Prototype workspace" subtitle', () => {
    const offenders = ALL_ITEMS.filter((i) => !i.subtitleCopy && i.subtitleKey === 'generic.subtitle').map((i) => i.id);
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
