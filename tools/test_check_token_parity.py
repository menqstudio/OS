#!/usr/bin/env python3
"""Self-tests for the design-token drift gate.

Run from tools/:  python -m unittest test_check_token_parity

Covers: the real on-disk tokens.ts/tokens.css pair staying GREEN (proves the gate
does not false-positive on the shipping tokens), value-drift and one-sided-token
detection in both themes (proves it fails closed), the tolerated TS-only runtime
extras, and the structural fail-closed paths.
"""
from __future__ import annotations

import pathlib
import unittest

import check_token_parity as tp

HERE = pathlib.Path(__file__).resolve().parent
_REPO_TS = HERE.parent / "apps" / "desktop" / "src" / "theme" / "tokens.ts"
_REPO_CSS = HERE.parent / "apps" / "desktop" / "src" / "theme" / "tokens.css"

# Minimal, self-contained fixtures mirroring the real files' shape (a couple of
# tokens per group) so evaluate() is hermetic. cssVariables() emits motion-slow /
# motion-easing which tokens.css omits by design — the fixture keeps that.
_TS = """
export const space = { 1: '4px', 2: '8px' } as const;
export const radius = { sm: '6px', md: '10px', card: '14px', pill: '999px' } as const;
export const typography = {
  fontSans: '"Inter", sans-serif',
  fontMono: '"JetBrains Mono", monospace',
  size: { xs: '12px' },
} as const;
export const shadow = { 1: '0 1px 2px rgba(0, 0, 0, 0.18)', 2: '0 8px 28px rgba(0, 0, 0, 0.28)' } as const;
export const motion = { fast: '160ms', med: '240ms', slow: '360ms', easing: 'cubic-bezier(0.2, 0, 0, 1)' } as const;
export const lightColors: ColorTokens = {
  bg: '#f5f6f8',
  accent: '#3d5afe',
  hover: 'rgba(61, 90, 254, 0.08)',
};
export const darkColors: ColorTokens = {
  bg: '#0c0e13',
  accent: '#7c8dff',
  hover: 'rgba(124, 141, 255, 0.12)',
};
const COLOR_VAR: Record<keyof ColorTokens, string> = {
  bg: '--menq-color-bg',
  accent: '--menq-color-accent',
  hover: '--menq-color-hover',
};
"""

_CSS = """
:root {
  --menq-space-1: 4px;
  --menq-space-2: 8px;
  --menq-radius-sm: 6px;
  --menq-radius-md: 10px;
  --menq-radius-card: 14px;
  --menq-radius-pill: 999px;
  --menq-font-sans: "Inter", sans-serif;
  --menq-font-mono: "JetBrains Mono", monospace;
  --menq-shadow-1: 0 1px 2px rgba(0, 0, 0, 0.18);
  --menq-shadow-2: 0 8px 28px rgba(0, 0, 0, 0.28);
  --menq-motion-fast: 160ms;
  --menq-motion-med: 240ms;
  --menq-color-bg: #f5f6f8;
  --menq-color-accent: #3d5afe;
  --menq-color-hover: rgba(61, 90, 254, 0.08);
}
:root[data-theme="dark"] {
  --menq-color-bg: #0c0e13;
  --menq-color-accent: #7c8dff;
  --menq-color-hover: rgba(124, 141, 255, 0.12);
}
:root {
  --brops-bg: var(--menq-color-bg);
}
"""


class FixtureTests(unittest.TestCase):
    def test_matching_fixture_is_green(self):
        self.assertEqual(tp.evaluate(_TS, _CSS), [])

    def test_tolerates_ts_only_motion_extras(self):
        # motion-slow / motion-easing are emitted by TS but not in the CSS fixture.
        light, _dark, _colors = tp.ts_variables(_TS)
        self.assertIn("--menq-motion-slow", light)
        self.assertIn("--menq-motion-easing", light)

    def test_detects_light_value_drift(self):
        bad = _CSS.replace("--menq-space-1: 4px;", "--menq-space-1: 5px;")
        problems = tp.evaluate(_TS, bad)
        self.assertTrue(any("--menq-space-1" in p and "light" in p for p in problems))

    def test_detects_dark_color_drift(self):
        bad = _CSS.replace("--menq-color-accent: #7c8dff;", "--menq-color-accent: #ffffff;")
        problems = tp.evaluate(_TS, bad)
        self.assertTrue(any("--menq-color-accent" in p and "dark" in p for p in problems))

    def test_detects_css_var_missing_from_ts(self):
        bad = _CSS.replace(
            "--menq-color-hover: rgba(61, 90, 254, 0.08);",
            "--menq-color-hover: rgba(61, 90, 254, 0.08);\n  --menq-color-mystery: #123456;",
        )
        problems = tp.evaluate(_TS, bad)
        self.assertTrue(any("--menq-color-mystery" in p for p in problems))

    def test_missing_dark_block_fails_closed(self):
        with self.assertRaises(tp.ParityError):
            tp.css_variables(":root { --menq-space-1: 4px; }")

    def test_malformed_ts_fails_closed(self):
        with self.assertRaises(tp.ParityError):
            tp.ts_variables("// no token objects here")


@unittest.skipUnless(_REPO_TS.exists() and _REPO_CSS.exists(), "repo token files not present")
class RealFileTests(unittest.TestCase):
    def test_shipping_tokens_are_green(self):
        problems = tp.evaluate(
            _REPO_TS.read_text(encoding="utf-8"),
            _REPO_CSS.read_text(encoding="utf-8"),
        )
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
