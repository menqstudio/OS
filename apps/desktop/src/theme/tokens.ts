/**
 * BroPS semantic design tokens — the single typed source of truth.
 *
 * These values MIRROR apps/desktop/src/theme/tokens.css and
 * apps/desktop/src/theme/contrast-pairs.json exactly. tokens.css keeps the
 * stylesheet self-contained for first paint (no FOUC before React mounts);
 * this module lets TS code + <ThemeProvider> read/apply the same values and is
 * what tools/check_contrast.py validates for WCAG AA. If you edit a color here,
 * edit tokens.css and contrast-pairs.json in the same change — the contrast
 * gate is fail-closed on drift between them.
 *
 * Naming: every CSS custom property is `--menq-<group>-<name>`, matching the
 * existing convention in tokens.css / global.css / ui.css.
 */

/* --------------------------------------------------------------------------- */
/* Non-color scales (theme-independent)                                        */
/* --------------------------------------------------------------------------- */

export const space = {
  1: '4px',
  2: '8px',
  3: '12px',
  4: '16px',
  5: '24px',
  6: '32px',
  7: '48px',
} as const;

export const radius = {
  sm: '6px',
  md: '10px',
  card: '14px',
  pill: '999px',
} as const;

export const typography = {
  fontSans:
    '"Inter", "Segoe UI", system-ui, -apple-system, "Noto Sans Armenian", sans-serif',
  fontMono: '"JetBrains Mono", "Cascadia Code", ui-monospace, monospace',
  size: {
    xs: '12px',
    sm: '13px',
    base: '14px',
    lg: '16px',
    xl: '20px',
    '2xl': '28px',
  },
  weight: {
    regular: '400',
    medium: '500',
    semibold: '600',
    bold: '700',
  },
  lineHeight: {
    tight: '1.25',
    normal: '1.5',
    relaxed: '1.7',
  },
} as const;

export const shadow = {
  1: '0 1px 2px rgba(0, 0, 0, 0.18)',
  2: '0 8px 28px rgba(0, 0, 0, 0.28)',
} as const;

/**
 * Motion tokens. `motion` is the default (animated) set; `motionReduced` is the
 * variant applied under `prefers-reduced-motion: reduce` (or an explicit user
 * override) — durations collapse to a near-instant value so transitions still
 * fire their end events without perceptible movement. Matches the
 * reduced-motion rule in global.css.
 */
export const motion = {
  fast: '160ms',
  med: '240ms',
  slow: '360ms',
  easing: 'cubic-bezier(0.2, 0, 0, 1)',
} as const;

export const motionReduced = {
  fast: '0.01ms',
  med: '0.01ms',
  slow: '0.01ms',
  easing: 'linear',
} as const;

/* --------------------------------------------------------------------------- */
/* Color — light + dark semantic palettes                                      */
/* --------------------------------------------------------------------------- */

/** The full set of semantic color intents. Both palettes must implement all. */
export interface ColorTokens {
  bg: string;
  surface: string;
  elevated: string;
  text: string;
  muted: string;
  border: string;
  accent: string;
  accentText: string;
  success: string;
  warning: string;
  danger: string;
  info: string;
  focus: string;
  hover: string;
  selected: string;
}

export const lightColors: ColorTokens = {
  bg: '#f5f6f8',
  surface: '#ffffff',
  elevated: '#ffffff',
  text: '#10131a',
  muted: '#5b6473',
  border: '#e2e5ea',
  accent: '#3856fe',
  accentText: '#ffffff',
  success: '#187a42',
  warning: '#9b5c00',
  danger: '#c5314a',
  info: '#246bbf',
  focus: '#3856fe',
  hover: 'rgba(56, 86, 254, 0.08)',
  selected: 'rgba(56, 86, 254, 0.12)',
};

export const darkColors: ColorTokens = {
  bg: '#0c0e13',
  surface: '#14171f',
  elevated: '#1b1f2a',
  text: '#eef1f6',
  muted: '#98a2b3',
  border: '#262b37',
  accent: '#7c8dff',
  accentText: '#0c0e13',
  success: '#4ade80',
  warning: '#f0b23a',
  danger: '#f2708a',
  info: '#6cb2ff',
  focus: '#7c8dff',
  hover: 'rgba(124, 141, 255, 0.12)',
  selected: 'rgba(124, 141, 255, 0.18)',
};

/* --------------------------------------------------------------------------- */
/* Theme assembly + CSS-variable projection                                    */
/* --------------------------------------------------------------------------- */

export type ThemeName = 'light' | 'dark';

/** Which theme a raw `light`/`dark`/`system` preference resolves to. */
export type ThemePreference = ThemeName | 'system';

export interface Theme {
  name: ThemeName;
  colors: ColorTokens;
  space: typeof space;
  radius: typeof radius;
  typography: typeof typography;
  shadow: typeof shadow;
  motion: typeof motion;
}

export const lightTheme: Theme = {
  name: 'light',
  colors: lightColors,
  space,
  radius,
  typography,
  shadow,
  motion,
};

export const darkTheme: Theme = {
  name: 'dark',
  colors: darkColors,
  space,
  radius,
  typography,
  shadow,
  motion,
};

export const themes: Record<ThemeName, Theme> = {
  light: lightTheme,
  dark: darkTheme,
};

const COLOR_VAR: Record<keyof ColorTokens, string> = {
  bg: '--menq-color-bg',
  surface: '--menq-color-surface',
  elevated: '--menq-color-elevated',
  text: '--menq-color-text',
  muted: '--menq-color-muted',
  border: '--menq-color-border',
  accent: '--menq-color-accent',
  accentText: '--menq-color-accent-text',
  success: '--menq-color-success',
  warning: '--menq-color-warning',
  danger: '--menq-color-danger',
  info: '--menq-color-info',
  focus: '--menq-color-focus',
  hover: '--menq-color-hover',
  selected: '--menq-color-selected',
};

/**
 * Flatten a theme (plus the resolved motion set) into the exact `--menq-*`
 * custom properties tokens.css declares. <ThemeProvider> writes these onto
 * :root so the TS token module is authoritative at runtime while remaining
 * byte-compatible with the stylesheet.
 */
export function cssVariables(
  theme: Theme,
  motionSet: typeof motion | typeof motionReduced = motion,
): Record<string, string> {
  const vars: Record<string, string> = {};

  for (const [key, prop] of Object.entries(COLOR_VAR) as [keyof ColorTokens, string][]) {
    vars[prop] = theme.colors[key];
  }

  vars['--menq-space-1'] = space[1];
  vars['--menq-space-2'] = space[2];
  vars['--menq-space-3'] = space[3];
  vars['--menq-space-4'] = space[4];
  vars['--menq-space-5'] = space[5];
  vars['--menq-space-6'] = space[6];
  vars['--menq-space-7'] = space[7];

  vars['--menq-radius-sm'] = radius.sm;
  vars['--menq-radius-md'] = radius.md;
  vars['--menq-radius-card'] = radius.card;
  vars['--menq-radius-pill'] = radius.pill;

  vars['--menq-font-sans'] = typography.fontSans;
  vars['--menq-font-mono'] = typography.fontMono;

  vars['--menq-shadow-1'] = shadow[1];
  vars['--menq-shadow-2'] = shadow[2];

  vars['--menq-motion-fast'] = motionSet.fast;
  vars['--menq-motion-med'] = motionSet.med;
  vars['--menq-motion-slow'] = motionSet.slow;
  vars['--menq-motion-easing'] = motionSet.easing;

  return vars;
}

/** Resolve a `system` preference against the OS color scheme. SSR-safe. */
export function resolveTheme(preference: ThemePreference): ThemeName {
  if (preference !== 'system') return preference;
  if (typeof window === 'undefined' || !window.matchMedia) return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
