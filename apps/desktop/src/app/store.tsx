import React, { createContext, useContext, useEffect, useMemo, useState, useCallback } from 'react';
import type { Lang, Theme } from '../domain/enums';
import { ALL_ITEMS, type RouteId } from './nav';
import { translate, type DictKey } from '../i18n';

/** A deep-link target: which entity a screen should auto-open on arrival.
 *  Set by the command palette (or any "jump to X" action); the receiving
 *  screen reads it, opens the matching detail, then clears it via clearFocus. */
export interface FocusTarget {
  kind: string;
  id: string;
}

/** The two conversation kinds the shared Conversations workspace serves: Chat renders
 *  `direct`, Group Chat renders `group`. They are separate screens with separate selections. */
export type ConversationKind = 'direct' | 'group';

/** Which conversation each Conversations surface currently has OPEN — the thread actually on
 *  screen, i.e. the explicit pick when there is one, the first row when there is not, and `null`
 *  when no thread is shown at all.
 *
 *  WHY it lives in the store: two other surfaces need this and could not get it. The delegation
 *  ledger beside the direct chat (`DelegationSurface`'s optional `conversationId`) and the
 *  consensus deck under Group Chat both have to know which conversation the owner is looking at,
 *  and `Conversations` kept that in private local state with no reader — so the ledger listed
 *  every delegation and the deck carried a second, independent room picker. Keyed BY KIND so one
 *  screen's selection can never be misread as the other's. */
export interface ConversationSelection {
  direct: string | null;
  group: string | null;
}

const NO_CONVERSATION_SELECTED: ConversationSelection = { direct: null, group: null };

interface AppState {
  route: RouteId;
  setRoute: (r: RouteId) => void;
  focus: FocusTarget | null;
  /** Navigate to `route` AND ask that screen to open entity `kind:id`. */
  openEntity: (route: RouteId, kind: string, id: string) => void;
  /** A screen calls this once it has consumed the pending focus target. */
  clearFocus: () => void;
  /** Read-side: the conversation each Conversations surface currently has open. */
  selectedConversation: ConversationSelection;
  /** Write-side, owned by the Conversations workspace: it publishes the thread it is actually
   *  showing whenever that changes, and clears its slot to `null` on unmount. Every other
   *  surface READS `selectedConversation`; nothing else should call this. */
  setSelectedConversation: (kind: ConversationKind, id: string | null) => void;
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

// The route a window opens on: the URL hash (`#tasks`) when present — so a reload or a
// right-click "Open in new window" lands on the same view — else home. An unknown slug
// is harmless (the router falls back to a generic view).
const isRoute = (id: string): id is RouteId => ALL_ITEMS.some((i) => i.id === id);

function routeFromHash(): RouteId {
  if (typeof window === 'undefined') return 'home';
  const h = window.location.hash.replace(/^#/, '').trim();
  // Only a KNOWN route id is honored — an unknown hash never becomes the route (which
  // would fall through to the Generic placeholder), it falls back to the last view.
  if (isRoute(h)) return h;
  const last = LS.get<RouteId>('brops.route', 'home');
  return isRoute(last) ? last : 'home';
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [route, setRouteState] = useState<RouteId>(routeFromHash);
  const [focus, setFocus] = useState<FocusTarget | null>(null);
  const [theme, setTheme] = useState<Theme>(() => LS.get<Theme>('brops.theme', 'dark'));
  const [lang, setLangState] = useState<Lang>(() => LS.get<Lang>('brops.lang', 'en'));
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [selectedConversation, setSelectedConversationState] =
    useState<ConversationSelection>(NO_CONVERSATION_SELECTED);

  // Plain navigation clears any pending focus so a later manual visit to the
  // same screen doesn't re-trigger a stale deep-link.
  const setRoute = useCallback((r: RouteId) => { setFocus(null); setRouteState(r); }, []);
  const openEntity = useCallback((r: RouteId, kind: string, id: string) => {
    setFocus({ kind, id });
    setRouteState(r);
  }, []);
  const clearFocus = useCallback(() => setFocus(null), []);
  // Stable identity + an unchanged-value short circuit, so the publishing effect in
  // Conversations can depend on this without re-rendering every consumer on each pass.
  const setSelectedConversation = useCallback((kind: ConversationKind, id: string | null) => {
    setSelectedConversationState((prev) => (prev[kind] === id ? prev : { ...prev, [kind]: id }));
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    LS.set('brops.theme', theme);
  }, [theme]);

  useEffect(() => {
    document.documentElement.setAttribute('lang', lang);
    LS.set('brops.lang', lang);
  }, [lang]);

  // Keep the URL hash in sync with the active route so a reload or a new window opens
  // on the same view. replaceState (not push) keeps the back stack clean.
  useEffect(() => {
    const h = `#${route}`;
    if (typeof window !== 'undefined' && window.location.hash !== h) {
      window.history.replaceState(null, '', h);
    }
    LS.set('brops.route', route);
  }, [route]);

  const toggleTheme = useCallback(() => setTheme((t) => (t === 'dark' ? 'light' : 'dark')), []);
  const setLang = useCallback((l: Lang) => setLangState(l), []);
  const t = useCallback((key: DictKey) => translate(lang, key), [lang]);

  const value = useMemo<AppState>(
    () => ({
      route, setRoute, focus, openEntity, clearFocus,
      selectedConversation, setSelectedConversation,
      theme, toggleTheme, lang, setLang, paletteOpen, setPaletteOpen, t,
    }),
    [
      route, setRoute, focus, openEntity, clearFocus,
      selectedConversation, setSelectedConversation,
      theme, toggleTheme, lang, setLang, paletteOpen, t,
    ],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppState {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used within AppProvider');
  return ctx;
}

/** Provider-safe variant: returns null instead of throwing when no AppProvider is
 *  present (e.g. a shared primitive rendered standalone in a unit test). Lets a
 *  low-level component localize when there's a provider and fall back otherwise. */
export function useAppOptional(): AppState | null {
  return useContext(AppContext);
}
