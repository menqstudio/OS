import { en, type DictKey } from './en';
import { hy } from './hy';
import { ru } from './ru';
import type { Lang } from '../domain/enums';

export type { DictKey };

export const dicts: Record<Lang, Record<DictKey, string>> = { en, hy, ru };

export const languageNames: Record<Lang, string> = {
  hy: 'Հայերեն',
  en: 'English',
  ru: 'Русский',
};

// English is the safe fallback when a key is genuinely missing.
export function translate(lang: Lang, key: DictKey): string {
  return dicts[lang][key] ?? en[key] ?? key;
}
