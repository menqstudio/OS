#!/usr/bin/env python3
"""WCAG contrast gate for the BroPS design tokens.

The design system ships two palettes (light + dark). A token color edit that
looks fine in one theme can silently drop text below the WCAG AA contrast floor
in the other. This gate makes that a fail-closed CI wall: it parses the
foreground/background *text* intents declared in

    apps/desktop/src/theme/contrast-pairs.json

resolves each pair against BOTH the light and the dark palette, computes the
WCAG 2.x contrast ratio, and fails if any text pair is below its AA threshold
(4.5:1 normal, 3.0:1 large) in EITHER theme.

Pure Python standard library only — no numpy, no third-party color libs — so it
runs on the same stdlib-only gate runners as the other tools/ checks.

Usage:  python tools/check_contrast.py [--manifest PATH]
Exit 0 + "GREEN: ..." when every pair passes in both themes; exit 1 + the
offending pairs otherwise. Malformed / missing manifest also fails closed.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import NamedTuple

# Repo-relative default so the gate can be invoked as `python tools/check_contrast.py`
# from the repository root (same convention as the other tools/ gates).
DEFAULT_MANIFEST = pathlib.Path("apps/desktop/src/theme/contrast-pairs.json")

# WCAG-mandated coefficients / offsets. Kept as named constants, not magic numbers.
_LUMA = (0.2126, 0.7152, 0.0722)
_SRGB_KNEE = 0.03928
_CONTRAST_OFFSET = 0.05


class ContrastError(Exception):
    """Raised for a structurally invalid manifest (fail-closed, never a pass)."""


# --------------------------------------------------------------------------- #
# Color math (WCAG 2.x relative luminance + contrast ratio)                    #
# --------------------------------------------------------------------------- #
def parse_hex(value: str) -> tuple[int, int, int]:
    """`#rgb` or `#rrggbb` (any case) -> (r, g, b) in 0..255."""
    if not isinstance(value, str):
        raise ContrastError(f"color must be a string, got {value!r}")
    h = value.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ContrastError(f"invalid hex color: {value!r}")
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError as exc:
        raise ContrastError(f"invalid hex color: {value!r}") from exc


def _srgb_to_linear(channel_8bit: int) -> float:
    """One 0..255 sRGB channel -> linear-light 0..1 (WCAG piecewise transfer)."""
    c = channel_8bit / 255.0
    if c <= _SRGB_KNEE:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance (0 = black, 1 = white)."""
    r, g, b = parse_hex(hex_color)
    lr, lg, lb = _srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)
    return _LUMA[0] * lr + _LUMA[1] * lg + _LUMA[2] * lb


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG contrast ratio in [1, 21]. Order-independent."""
    l1 = relative_luminance(fg)
    l2 = relative_luminance(bg)
    lighter, darker = (l1, l2) if l1 >= l2 else (l2, l1)
    return (lighter + _CONTRAST_OFFSET) / (darker + _CONTRAST_OFFSET)


# --------------------------------------------------------------------------- #
# Manifest evaluation                                                         #
# --------------------------------------------------------------------------- #
class Result(NamedTuple):
    pair_id: str
    theme: str
    fg: str
    bg: str
    size: str
    ratio: float
    threshold: float
    passed: bool


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ContrastError(msg)


def evaluate(manifest: dict) -> list[Result]:
    """Resolve every declared pair against every palette and score it.

    Raises ContrastError (fail-closed) on any structural problem: unknown token,
    unknown size, missing threshold, empty pair list — none of which may be
    treated as a silent pass.
    """
    _require(isinstance(manifest, dict), "manifest must be a JSON object")

    thresholds = manifest.get("thresholds")
    _require(isinstance(thresholds, dict), "manifest.thresholds must be an object")
    for key in ("normal", "large"):
        _require(
            isinstance(thresholds.get(key), (int, float)),
            f"manifest.thresholds.{key} must be a number",
        )

    palettes = manifest.get("palettes")
    _require(
        isinstance(palettes, dict) and palettes,
        "manifest.palettes must be a non-empty object",
    )

    pairs = manifest.get("pairs")
    _require(isinstance(pairs, list) and pairs, "manifest.pairs must be a non-empty array")

    results: list[Result] = []
    for i, pair in enumerate(pairs):
        _require(isinstance(pair, dict), f"pairs[{i}] must be an object")
        pid = pair.get("id", f"pairs[{i}]")
        fg = pair.get("fg")
        bg = pair.get("bg")
        size = pair.get("size", "normal")
        _require(isinstance(fg, str), f"{pid}: 'fg' must be a token name")
        _require(isinstance(bg, str), f"{pid}: 'bg' must be a token name")
        _require(
            size in thresholds,
            f"{pid}: size {size!r} has no matching threshold (have {sorted(thresholds)})",
        )
        threshold = float(thresholds[size])

        for theme, palette in palettes.items():
            _require(isinstance(palette, dict), f"palette {theme!r} must be an object")
            _require(fg in palette, f"{pid}: token {fg!r} not in {theme!r} palette")
            _require(bg in palette, f"{pid}: token {bg!r} not in {theme!r} palette")
            fg_hex, bg_hex = palette[fg], palette[bg]
            ratio = contrast_ratio(fg_hex, bg_hex)
            results.append(
                Result(
                    pair_id=pid,
                    theme=theme,
                    fg=fg_hex,
                    bg=bg_hex,
                    size=size,
                    # NINTH AUDIT. This used to compare `round(ratio, 2) >= threshold`, with the
                    # reasoning "so a printed 4.50 is never reported as a failure". It is the wrong
                    # way round: it made the gate PASS two pairs WCAG fails. `info-on-selected` was
                    # 4.4996 and `danger-on-selected` 4.4995 -- both below AA, both printing 4.50,
                    # and both pairs the previous change had just added. A gate that rounds toward
                    # passing is a gate that reports the number it wants.
                    #
                    # The comparison is on the RAW ratio now. The displayed value keeps 2dp, and
                    # gains a third when the extra digit is what decides -- so a reader can see WHY
                    # a 4.50 failed instead of doubting the gate.
                    ratio=round(ratio, 4) if abs(ratio - threshold) < 0.01 else round(ratio, 2),
                    threshold=threshold,
                    passed=ratio >= threshold,
                )
            )
    return results


def failures(results: list[Result]) -> list[Result]:
    return [r for r in results if not r.passed]


def load_manifest(path: pathlib.Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContrastError(f"cannot read manifest {path}: {exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContrastError(f"manifest {path} is not valid JSON: {exc}") from exc


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #
def _format(r: Result) -> str:
    mark = "ok " if r.passed else "XX "
    return (
        f"  {mark}{r.pair_id:<24} {r.theme:<5} "
        # Print every digit that was stored. When the gate rounded to 2dp AND compared on the
        # rounded value, a 4.4996 failure printed as "4.50" and read as a bug in the gate.
        f"{r.fg} on {r.bg}  {r.ratio:>7g}:1  "
        f"(need {r.threshold:.1f} · {r.size})"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="WCAG AA contrast gate for design tokens.")
    ap.add_argument("--manifest", type=pathlib.Path, default=DEFAULT_MANIFEST)
    ap.add_argument("-v", "--verbose", action="store_true", help="print every pair, not only failures")
    args = ap.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
        results = evaluate(manifest)
    except ContrastError as exc:
        print(f"RED: {exc}", file=sys.stderr)
        return 1

    bad = failures(results)
    if args.verbose:
        for r in results:
            print(_format(r))
    if bad:
        print(f"RED: {len(bad)} text pair(s) below WCAG AA:", file=sys.stderr)
        for r in bad:
            print(_format(r), file=sys.stderr)
        return 1

    print(f"GREEN: {len(results)} token text pairs pass WCAG AA in every theme.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
