#!/usr/bin/env python3
"""Design-token drift gate: theme/tokens.ts  ==  theme/tokens.css.

The design system keeps two copies of the same `--menq-*` custom properties:

    apps/desktop/src/theme/tokens.css   the stylesheet (first paint, no FOUC)
    apps/desktop/src/theme/tokens.ts    the typed source <ThemeProvider> applies

tokens.ts's own header says the two "MIRROR ... exactly" and that an edit to one
without the other must fail closed. This gate is that wall. It reconstructs the
`--menq-*` variables the TS `cssVariables()` projection emits (for the light and
dark palettes) straight from the TS literals, parses the `:root` (light) and
`:root[data-theme="dark"]` blocks of tokens.css, and fails on any value drift or
missing variable — in either direction.

The TS runtime intentionally emits two variables the stylesheet does not need for
first paint (`--menq-motion-slow`, `--menq-motion-easing`); those are the only
allowed TS-only extras and are listed explicitly, so a *new* accidental TS-only
token still fails the gate.

Pure Python standard library only — same stdlib-only contract as the other
tools/ gates (check_contrast.py, check_bundle_budget.py).

Usage:  python tools/check_token_parity.py [--ts PATH] [--css PATH]
Exit 0 + "GREEN: ..." when every `--menq-*` variable agrees across both files in
both themes; exit 1 + the offending variables otherwise. A malformed / missing
file also fails closed.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

# Repo-relative defaults so the gate runs as `python tools/check_token_parity.py`
# from the repository root (same convention as the other tools/ gates).
DEFAULT_TS = pathlib.Path("apps/desktop/src/theme/tokens.ts")
DEFAULT_CSS = pathlib.Path("apps/desktop/src/theme/tokens.css")

# Variables cssVariables() emits for runtime but tokens.css omits by design
# (not needed before React mounts). The ONLY tolerated TS-only light-theme extras.
TS_ONLY_LIGHT = frozenset({"--menq-motion-slow", "--menq-motion-easing"})


class ParityError(Exception):
    """Structurally invalid input (fail-closed, never a silent pass)."""


# --------------------------------------------------------------------------- #
# tokens.ts — reconstruct the cssVariables() projection from the TS literals   #
# --------------------------------------------------------------------------- #
def _object_body(text: str, header: str) -> str:
    """Return the `{ ... }` body that follows `header` up to the first `}`.

    Safe for these token objects because none nests braces (values are strings
    with parens at most). `header` is a literal fragment like 'export const space ='.
    """
    start = text.find(header)
    if start < 0:
        raise ParityError(f"tokens.ts: could not find `{header}`")
    brace = text.find("{", start)
    end = text.find("}", brace)
    if brace < 0 or end < 0:
        raise ParityError(f"tokens.ts: malformed object after `{header}`")
    return text[brace + 1 : end]


def _pairs(body: str) -> dict[str, str]:
    """`key: 'value'` pairs from an object body (keys may be bare or numeric)."""
    out: dict[str, str] = {}
    for key, val in re.findall(r"([A-Za-z0-9_]+)\s*:\s*'([^']*)'", body):
        out[key] = val
    return out


def _scalar(text: str, name: str) -> str:
    """A single `name: 'value'` scalar anywhere in the file (e.g. fontSans)."""
    m = re.search(rf"{name}\s*:\s*'([^']*)'", text)
    if not m:
        raise ParityError(f"tokens.ts: could not find scalar `{name}`")
    return m.group(1)


def ts_variables(ts_text: str) -> tuple[dict[str, str], dict[str, str], frozenset[str]]:
    """Reconstruct (light, dark, color-var-names) as cssVariables() would emit.

    The third value is the set of color `--menq-*` names; the dark stylesheet
    block overrides only those (non-color vars cascade from `:root`), so the dark
    comparison is scoped to them.
    """
    space = _pairs(_object_body(ts_text, "export const space ="))
    radius = _pairs(_object_body(ts_text, "export const radius ="))
    shadow = _pairs(_object_body(ts_text, "export const shadow ="))
    motion = _pairs(_object_body(ts_text, "export const motion ="))
    light_colors = _pairs(_object_body(ts_text, "export const lightColors"))
    dark_colors = _pairs(_object_body(ts_text, "export const darkColors"))
    color_var = _pairs(_object_body(ts_text, "const COLOR_VAR"))

    font_sans = _scalar(ts_text, "fontSans")
    font_mono = _scalar(ts_text, "fontMono")

    def non_color() -> dict[str, str]:
        out: dict[str, str] = {}
        for k, v in space.items():
            out[f"--menq-space-{k}"] = v
        for k in ("sm", "md", "card", "pill"):
            _require(k in radius, f"tokens.ts: radius.{k} missing")
            out[f"--menq-radius-{k}"] = radius[k]
        out["--menq-font-sans"] = font_sans
        out["--menq-font-mono"] = font_mono
        for k in ("1", "2"):
            _require(k in shadow, f"tokens.ts: shadow.{k} missing")
            out[f"--menq-shadow-{k}"] = shadow[k]
        out["--menq-motion-fast"] = motion["fast"]
        out["--menq-motion-med"] = motion["med"]
        out["--menq-motion-slow"] = motion["slow"]
        out["--menq-motion-easing"] = motion["easing"]
        return out

    def colors(palette: dict[str, str], where: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for key, var in color_var.items():
            _require(key in palette, f"tokens.ts: {where} missing color '{key}'")
            out[var] = palette[key]
        return out

    _require(bool(color_var), "tokens.ts: COLOR_VAR map is empty")
    light = {**colors(light_colors, "lightColors"), **non_color()}
    dark = {**colors(dark_colors, "darkColors"), **non_color()}
    return light, dark, frozenset(color_var.values())


# --------------------------------------------------------------------------- #
# tokens.css — parse the light (:root) and dark blocks                          #
# --------------------------------------------------------------------------- #
_DARK_RE = re.compile(r':root\[data-theme="dark"\]\s*\{(.*?)\}', re.DOTALL)
_VAR_RE = re.compile(r"(--menq-[A-Za-z0-9-]+)\s*:\s*([^;]+);")


def _menq_vars(block: str) -> dict[str, str]:
    return {name: value.strip() for name, value in _VAR_RE.findall(block)}


def css_variables(css_text: str) -> tuple[dict[str, str], dict[str, str]]:
    """(light, dark) `--menq-*` maps. Light = every --menq-* outside the dark block."""
    dark_match = _DARK_RE.search(css_text)
    _require(dark_match is not None, 'tokens.css: no :root[data-theme="dark"] block')
    dark = _menq_vars(dark_match.group(1))
    light = _menq_vars(css_text[: dark_match.start()] + css_text[dark_match.end() :])
    _require(bool(light), "tokens.css: no --menq-* variables in :root")
    return light, dark


# --------------------------------------------------------------------------- #
# Comparison                                                                   #
# --------------------------------------------------------------------------- #
def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ParityError(msg)


def diff(theme: str, ts: dict[str, str], css: dict[str, str], ts_only_ok: frozenset[str]) -> list[str]:
    """Report drift for one theme: value mismatches + one-sided variables."""
    problems: list[str] = []
    for var, css_val in sorted(css.items()):
        if var not in ts:
            problems.append(f"  XX {theme:<5} {var}: in tokens.css but not projected by tokens.ts")
        elif ts[var] != css_val:
            problems.append(
                f"  XX {theme:<5} {var}: tokens.ts={ts[var]!r} != tokens.css={css_val!r}"
            )
    for var in sorted(ts):
        if var not in css and var not in ts_only_ok:
            problems.append(f"  XX {theme:<5} {var}: projected by tokens.ts but absent from tokens.css")
    return problems


def evaluate(ts_text: str, css_text: str) -> list[str]:
    ts_light, ts_dark, color_vars = ts_variables(ts_text)
    css_light, css_dark = css_variables(css_text)
    problems = diff("light", ts_light, css_light, TS_ONLY_LIGHT)
    # The dark block overrides colors only; the non-color vars cascade from
    # :root, so every non-color dark var is legitimately absent from the block.
    # Scope the dark check to the color vars: values must agree, no color may be
    # missing, and no stray --menq-* may appear in the block.
    dark_only_ok = frozenset(ts_dark) - color_vars
    problems += diff("dark", ts_dark, css_dark, ts_only_ok=dark_only_ok)
    return problems


def _read(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ParityError(f"cannot read {path}: {exc}") from exc


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Design-token drift gate (tokens.ts vs tokens.css).")
    ap.add_argument("--ts", type=pathlib.Path, default=DEFAULT_TS)
    ap.add_argument("--css", type=pathlib.Path, default=DEFAULT_CSS)
    args = ap.parse_args(argv)

    try:
        problems = evaluate(_read(args.ts), _read(args.css))
    except ParityError as exc:
        print(f"RED: {exc}", file=sys.stderr)
        return 1

    if problems:
        print(f"RED: {len(problems)} token drift(s) between tokens.ts and tokens.css:", file=sys.stderr)
        for line in problems:
            print(line, file=sys.stderr)
        return 1

    print("GREEN: tokens.ts and tokens.css agree on every --menq-* variable in both themes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
