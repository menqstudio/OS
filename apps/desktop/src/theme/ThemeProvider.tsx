// ARCHITECTURE NOTE (Phase-4 theme reconcile — read before wiring this in).
// This provider is a REFERENCE implementation and is INTENTIONALLY NOT MOUNTED. Runtime
// theming is owned by two stylesheet layers switched by a single `data-theme` attribute:
//   • `theme/aios.css` — the `--*` design vars (dark `:root` + light `:root[data-theme=light]`)
//   • `theme/tokens.css` — the typed `--menq-*` token contract (both themes), which the
//     components actually consume (Chart, ui, Decisions, Files, Notifications, …).
// `app/store.tsx` (AppProvider) is the runtime theme authority: it sets `data-theme` on
// <html> (default dark, persisted), which switches BOTH stylesheet layers at once. The
// TYPED source of truth is `tokens.ts`, kept in lockstep with `tokens.css` by the
// design-gates CI (token-drift + WCAG-AA contrast). So the `--menq-*` layer is fully
// runtime-functional via the stylesheet WITHOUT this JS provider — mounting it would only
// re-write the same variables inline. Keep it as a typed reference / opt-in; do not add a
// second runtime theme authority without removing AppProvider's `data-theme` toggle first.
import React from 'react';
import {
  cssVariables,
  motion,
  motionReduced,
  resolveTheme,
  themes,
  type Theme,
  type ThemeName,
  type ThemePreference,
} from './tokens';

/**
 * ThemeProvider — projects the typed design tokens onto the document as the
 * `--menq-*` CSS custom properties, tracks the light/dark/system preference,
 * and honours `prefers-color-scheme` + `prefers-reduced-motion` live.
 *
 * Framework-consistent with components/ui.tsx: a plain function component tree,
 * hooks only, a small typed context (mirrors how ui.tsx consumes `useApp`), no
 * external state library. The provider is additive over tokens.css — it writes
 * the same variables tokens.css declares, so removing the provider degrades
 * gracefully to the stylesheet defaults rather than to unstyled markup.
 */

export interface ThemeContextValue {
  /** The user's raw preference: 'light' | 'dark' | 'system'. */
  preference: ThemePreference;
  /** The concrete theme currently applied (system already resolved). */
  theme: ThemeName;
  /** Whether motion is currently reduced (OS setting or explicit override). */
  reducedMotion: boolean;
  /** The resolved token bundle for the active theme. */
  tokens: Theme;
  /** Set the preference; persisted and applied immediately. */
  setTheme: (preference: ThemePreference) => void;
  /** Convenience toggle between explicit light/dark (leaves 'system'). */
  toggleTheme: () => void;
}

const ThemeContext = React.createContext<ThemeContextValue | null>(null);

const STORAGE_KEY = 'brops.theme-preference';

function readStoredPreference(): ThemePreference {
  if (typeof window === 'undefined') return 'system';
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    if (v === 'light' || v === 'dark' || v === 'system') return v;
  } catch {
    /* storage may be unavailable (private mode / sandbox) — fall through */
  }
  return 'system';
}

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** Write the resolved variables + data-theme attribute onto :root. */
function applyTheme(themeName: ThemeName, reduced: boolean): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  const vars = cssVariables(themes[themeName], reduced ? motionReduced : motion);
  for (const [prop, value] of Object.entries(vars)) {
    root.style.setProperty(prop, value);
  }
  // Drives the existing `:root[data-theme="dark"]` selectors in tokens.css and
  // keeps native form controls / scrollbars in the right scheme.
  root.setAttribute('data-theme', themeName);
  root.style.colorScheme = themeName;
}

export function ThemeProvider({
  children,
  defaultPreference,
}: {
  children: React.ReactNode;
  /** Override the stored/system default (mainly for tests / storybook). */
  defaultPreference?: ThemePreference;
}) {
  const [preference, setPreference] = React.useState<ThemePreference>(
    () => defaultPreference ?? readStoredPreference(),
  );
  const [systemTheme, setSystemTheme] = React.useState<ThemeName>(() =>
    resolveTheme('system'),
  );
  const [reducedMotion, setReducedMotion] = React.useState<boolean>(prefersReducedMotion);

  // Live-track the OS color scheme so `system` follows it without a reload.
  React.useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => setSystemTheme(mq.matches ? 'dark' : 'light');
    onChange();
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  // Live-track reduced-motion.
  React.useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onChange = () => setReducedMotion(mq.matches);
    onChange();
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  const theme: ThemeName = preference === 'system' ? systemTheme : preference;

  // Apply on every relevant change. Layout effect avoids a one-frame flash of
  // the previous theme when the preference changes at runtime.
  React.useLayoutEffect(() => {
    applyTheme(theme, reducedMotion);
  }, [theme, reducedMotion]);

  const setTheme = React.useCallback((next: ThemePreference) => {
    setPreference(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* non-fatal: preference simply won't persist */
    }
  }, []);

  const toggleTheme = React.useCallback(() => {
    setTheme(theme === 'dark' ? 'light' : 'dark');
  }, [theme, setTheme]);

  const value = React.useMemo<ThemeContextValue>(
    () => ({
      preference,
      theme,
      reducedMotion,
      tokens: themes[theme],
      setTheme,
      toggleTheme,
    }),
    [preference, theme, reducedMotion, setTheme, toggleTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

/** Access the active theme + setter. Throws if used outside <ThemeProvider>. */
export function useTheme(): ThemeContextValue {
  const ctx = React.useContext(ThemeContext);
  if (!ctx) {
    throw new Error('useTheme must be used within a <ThemeProvider>');
  }
  return ctx;
}
