import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
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

  it('carries no key that nothing outside the dictionaries names', () => {
    // 24 of 238 keys were referenced nowhere: three translations each, maintained for no reader,
    // and parity (above) kept all 72 lines honest with each other while none of them was used.
    // Keys are always written whole — there is no `t(`prefix.${x}`)` in this tree — so a quoted
    // literal is the test. The day a key is built at runtime, this is where to say how.
    const here = dirname(fileURLToPath(import.meta.url));
    const src = resolve(here, '..');
    const dictionaries = new Set(['en.ts', 'hy.ts', 'ru.ts'].map((f) => resolve(here, f)));
    const walk = (dir: string): string[] =>
      readdirSync(dir).flatMap((name) => {
        const path = resolve(dir, name);
        return statSync(path).isDirectory() ? walk(path) : [path];
      });
    const rest = walk(src)
      .filter((f) => /\.tsx?$/.test(f) && !dictionaries.has(f))
      .map((f) => readFileSync(f, 'utf8'))
      .join('\n');
    const unused = Object.keys(en).filter((k) => !["'", '"', '`'].some((q) => rest.includes(q + k + q)));
    expect(unused).toEqual([]);
  });

  it('shows no task id to the user, in any language', () => {
    // A disabled Delete's tooltip promised safe-delete "arrives in T-011". T-011 shipped as
    // something else, and a ticket number means nothing to the person reading a tooltip.
    for (const [lang, d] of Object.entries(dicts)) {
      const named = Object.entries(d).filter(([, v]) => /\bT-\d{3}\b/.test(v)).map(([k]) => `${lang}:${k}`);
      expect(named).toEqual([]);
    }
  });

  it('does not call Memory "verifiable" in any language', () => {
    // `chat.receiptVerified` is a claim the engine backs. The Memory subtitle is "Inspectable" in
    // English because a "Verifiable memory" pill was removed for claiming exactly that — and the
    // Armenian and Russian subtitles went on saying it, with the same root as the receipt's word.
    for (const [lang, d] of Object.entries(dicts)) {
      const stem = d['chat.receiptVerified'].slice(0, 5).toLowerCase();
      expect(d['memory.subtitle'].toLowerCase(), `${lang}: shares the root "${stem}"`).not.toContain(stem);
    }
  });
});
