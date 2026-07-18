import React, { createContext, useContext, useEffect, useMemo, useState, useCallback } from 'react';
import type { Lang, Theme } from '../domain/enums';
import type { RouteId } from './nav';
import { translate, type DictKey } from '../i18n';

interface AppState {
  route: RouteId;
  setRoute: (r: RouteId) => void;
  theme: Theme;
  toggleTheme: () => void;
  lang: Lang;
  setLang: (l: Lang) => void;
  paletteOpen: boolean;
  setPaletteOpen: (v: boolean) => void;
  t: (key: DictKey) => string;
}

const AppContext = createContext<AppState | null>(null);

const LS = {
  get<T>(k: string, fallback: T): T {
    try {
      const v = localStorage.getItem(k);
      return v ? (JSON.parse(v) as T) : fallback;
    } catch {
      return fallback;
    }
  },
  set(k: string, v: unknown) {
    try {
      localStorage.setItem(k, JSON.stringify(v));
    } catch {
      /* ignore */
    }
  },
};

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [route, setRoute] = useState<RouteId>('home');
  const [theme, setTheme] = useState<Theme>(() => LS.get<Theme>('brops.theme', 'dark'));
  const [lang, setLangState] = useState<Lang>(() => LS.get<Lang>('brops.lang', 'en'));
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    LS.set('brops.theme', theme);
  }, [theme]);

  useEffect(() => {
    document.documentElement.setAttribute('lang', lang);
    LS.set('brops.lang', lang);
  }, [lang]);

  const toggleTheme = useCallback(() => setTheme((t) => (t === 'dark' ? 'light' : 'dark')), []);
  const setLang = useCallback((l: Lang) => setLangState(l), []);
  const t = useCallback((key: DictKey) => translate(lang, key), [lang]);

  const value = useMemo<AppState>(
    () => ({ route, setRoute, theme, toggleTheme, lang, setLang, paletteOpen, setPaletteOpen, t }),
    [route, theme, toggleTheme, lang, setLang, paletteOpen, t],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppState {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used within AppProvider');
  return ctx;
}
