#!/usr/bin/env python3
"""Self-tests for the WCAG contrast gate.

Run from tools/:  python -m unittest test_check_contrast

Covers: known-good color math against WCAG reference values, a PASSING manifest
that mirrors the shipping token palette (proves the gate stays GREEN on the real
palette in both themes), and a FAILING manifest (proves the gate actually fails
closed instead of rubber-stamping). Also exercises the real on-disk manifest
when it is present next to the checker, and the structural fail-closed paths.
"""
from __future__ import annotations

import json
import pathlib
import unittest

import check_contrast as cc

HERE = pathlib.Path(__file__).resolve().parent
# The shipping manifest lives in the app theme dir; when the tests run from a
# flat scratch copy it sits beside this file. Try both, skip the on-disk case if
# neither exists so the unit logic tests still run anywhere.
_REPO_MANIFEST = HERE.parent / "apps" / "desktop" / "src" / "theme" / "contrast-pairs.json"
_LOCAL_MANIFEST = HERE / "contrast-pairs.json"


# A minimal, self-contained palette that mirrors the real token values for the
# pairs we assert on. Kept inline so the color-math + evaluate() tests are
# hermetic (no filesystem dependency).
_PASSING_MANIFEST = {
    "thresholds": {"normal": 4.5, "large": 3.0},
    "palettes": {
        "light": {
            "bg": "#f5f6f8",
            "surface": "#ffffff",
            "text": "#10131a",
            "muted": "#5b6473",
            "accent": "#3d5afe",
            "accent-text": "#ffffff",
            "warning": "#c77700",
        },
        "dark": {
            "bg": "#0c0e13",
            "surface": "#14171f",
            "text": "#eef1f6",
            "muted": "#98a2b3",
            "accent": "#7c8dff",
            "accent-text": "#0c0e13",
            "warning": "#f0b23a",
        },
    },
    "pairs": [
        {"id": "body-text-on-bg", "fg": "text", "bg": "bg", "size": "normal"},
        {"id": "muted-on-surface", "fg": "muted", "bg": "surface", "size": "normal"},
        {"id": "primary-button-label", "fg": "accent-text", "bg": "accent", "size": "normal"},
        {"id": "status-warning-label", "fg": "warning", "bg": "surface", "size": "large"},
    ],
}

# Deliberately broken: light-mode "muted" is a pale gray on white (~1.8:1) — far
# below AA normal — and dark-mode text is near-black on near-black. A gate that
# passes this is not a gate.
_FAILING_MANIFEST = {
    "thresholds": {"normal": 4.5, "large": 3.0},
    "palettes": {
        "light": {
            "surface": "#ffffff",
            "muted": "#bfc4cc",   # pale gray on white -> fails AA normal
            "text": "#111111",
        },
        "dark": {
            "surface": "#0c0e13",
            "muted": "#98a2b3",
            "text": "#151821",    # near-black text on near-black surface -> fails
        },
    },
    "pairs": [
        {"id": "muted-on-surface", "fg": "muted", "bg": "surface", "size": "normal"},
        {"id": "body-text-on-surface", "fg": "text", "bg": "surface", "size": "normal"},
    ],
}


class ColorMath(unittest.TestCase):
    def test_luminance_extremes(self):
        self.assertAlmostEqual(cc.relative_luminance("#000000"), 0.0, places=6)
        self.assertAlmostEqual(cc.relative_luminance("#ffffff"), 1.0, places=6)

    def test_black_on_white_is_21(self):
        # WCAG reference: pure black on pure white is exactly 21:1.
        self.assertAlmostEqual(cc.contrast_ratio("#000000", "#ffffff"), 21.0, places=2)

    def test_ratio_is_order_independent(self):
        self.assertAlmostEqual(
            cc.contrast_ratio("#10131a", "#f5f6f8"),
            cc.contrast_ratio("#f5f6f8", "#10131a"),
            places=9,
        )

    def test_shorthand_hex(self):
        self.assertEqual(cc.parse_hex("#fff"), (255, 255, 255))
        self.assertAlmostEqual(
            cc.contrast_ratio("#000", "#fff"),
            cc.contrast_ratio("#000000", "#ffffff"),
            places=9,
        )

    def test_known_midtone_pair(self):
        # #767676 on white is the canonical WCAG "just passes 4.5" gray.
        self.assertGreaterEqual(cc.contrast_ratio("#767676", "#ffffff"), 4.5)


class PassingSet(unittest.TestCase):
    def test_no_failures_in_either_theme(self):
        results = cc.evaluate(_PASSING_MANIFEST)
        # 4 pairs x 2 themes = 8 scored results.
        self.assertEqual(len(results), 8)
        self.assertEqual(cc.failures(results), [])

    def test_every_result_meets_its_threshold(self):
        for r in cc.evaluate(_PASSING_MANIFEST):
            self.assertGreaterEqual(
                r.ratio, r.threshold,
                msg=f"{r.pair_id} [{r.theme}] {r.ratio} < {r.threshold}",
            )


class FailingSet(unittest.TestCase):
    def test_failures_are_detected(self):
        results = cc.evaluate(_FAILING_MANIFEST)
        bad = cc.failures(results)
        self.assertTrue(bad, "expected at least one failing pair")
        ids = {r.pair_id for r in bad}
        self.assertIn("muted-on-surface", ids)      # light pale-gray failure
        self.assertIn("body-text-on-surface", ids)  # dark near-black-on-black failure

    def test_main_returns_nonzero_on_failing_manifest(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(_FAILING_MANIFEST, fh)
            path = fh.name
        self.assertEqual(cc.main(["--manifest", path]), 1)

    def test_main_returns_zero_on_passing_manifest(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(_PASSING_MANIFEST, fh)
            path = fh.name
        self.assertEqual(cc.main(["--manifest", path]), 0)


class FailClosed(unittest.TestCase):
    def test_unknown_token_raises(self):
        m = json.loads(json.dumps(_PASSING_MANIFEST))
        m["pairs"].append({"id": "bad", "fg": "nope", "bg": "bg", "size": "normal"})
        with self.assertRaises(cc.ContrastError):
            cc.evaluate(m)

    def test_unknown_size_raises(self):
        m = json.loads(json.dumps(_PASSING_MANIFEST))
        m["pairs"].append({"id": "bad", "fg": "text", "bg": "bg", "size": "huge"})
        with self.assertRaises(cc.ContrastError):
            cc.evaluate(m)

    def test_empty_pairs_raises(self):
        m = json.loads(json.dumps(_PASSING_MANIFEST))
        m["pairs"] = []
        with self.assertRaises(cc.ContrastError):
            cc.evaluate(m)

    def test_bad_hex_raises(self):
        with self.assertRaises(cc.ContrastError):
            cc.parse_hex("#12xz9q")


class RealManifest(unittest.TestCase):
    def test_shipping_manifest_is_green(self):
        path = _REPO_MANIFEST if _REPO_MANIFEST.exists() else _LOCAL_MANIFEST
        if not path.exists():
            self.skipTest("shipping contrast-pairs.json not present in this layout")
        results = cc.evaluate(cc.load_manifest(path))
        self.assertEqual(
            cc.failures(results), [],
            msg="the real token palette must pass WCAG AA in both themes",
        )



#: The repository root. CI runs these tests with `working-directory: tools`, so a repo-relative
#: path resolves against the wrong directory — which is how the first version of this class failed
#: with FileNotFoundError while the gate it tests was green.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


class PalettesMirrorTokens(unittest.TestCase):
    """The manifest's palettes are a hand-maintained copy of the shipping tokens.

    The file has always SAID they must mirror `tokens.ts`, and until 2026-08-29 nothing checked it.
    A stale copy makes this gate grade colours the app no longer paints and report GREEN about a
    palette that is not on screen — which is the same shape as the ninth audit's `I-12`, one file
    over: a verdict about an artifact nobody verified.
    """

    def test_the_shipping_manifest_mirrors_tokens_ts(self):
        manifest = cc.load_manifest(REPO_ROOT / cc.DEFAULT_MANIFEST)
        cc._require_palettes_mirror_tokens(manifest["palettes"], REPO_ROOT)

    def test_a_drifted_palette_is_refused(self):
        # The mutation the check exists for: a colour edited in the manifest and not in the tokens.
        manifest = cc.load_manifest(REPO_ROOT / cc.DEFAULT_MANIFEST)
        manifest["palettes"]["light"]["warning"] = "#111111"
        with self.assertRaises(cc.ContrastError) as caught:
            cc._require_palettes_mirror_tokens(manifest["palettes"], REPO_ROOT)
        self.assertIn("warning", str(caught.exception))
        self.assertIn("#111111", str(caught.exception))

    def test_selected_is_exempt_because_it_is_a_composite(self):
        # `selected` is an rgba in the tokens and a precomputed opaque composite here, so there is
        # nothing for it to match. Exempt BY NAME, not by pattern — a suffix rule would silently
        # exempt whatever anyone named `*-tint` next, and those ARE real tokens now.
        manifest = cc.load_manifest(REPO_ROOT / cc.DEFAULT_MANIFEST)
        self.assertIn("selected", manifest["palettes"]["light"])
        cc._require_palettes_mirror_tokens(manifest["palettes"], REPO_ROOT)

    def test_the_badge_tints_are_NOT_exempt(self):
        # The `--menq-*` tints became real tokens on 2026-08-29 precisely so the declared pair and
        # the painted background are the same value; exempting them would undo that. The exemption
        # is narrowed to the `aios-*-tint` entries, which are composites with no token behind them —
        # `.pill.info` paints `rgb(var(--cyan-rgb)/.08)` and there is no `--cyan-tint` to mirror.
        manifest = cc.load_manifest(REPO_ROOT / cc.DEFAULT_MANIFEST)
        manifest["palettes"]["light"]["warning-tint"] = "#222222"
        with self.assertRaises(cc.ContrastError):
            cc._require_palettes_mirror_tokens(manifest["palettes"], REPO_ROOT)



class TwoPalettes(unittest.TestCase):
    """There are TWO palettes, and until 2026-08-29 this gate measured one of them.

    `tokens.css`/`tokens.ts` carry the `--menq-*` set. `aios.css` carries `--ink`/`--cyan`/
    `--success`/… and **the pages paint with those**. `T-042` found six light values in the second
    palette below WCAG AA by running a browser — `--cyan-soft` carries `.eyebrow` on nearly every
    page header and measured **1.99:1** — while every declared pair here was green, because none of
    them named it. A running test is not a committed contract; these are.
    """

    def _manifest(self):
        return cc.load_manifest(REPO_ROOT / cc.DEFAULT_MANIFEST)

    def test_both_palettes_are_declared(self):
        pal = self._manifest()["palettes"]["light"]
        self.assertIn("muted", pal, "the --menq-* family must still be here")
        self.assertIn("aios-cyan-soft", pal, "the aios family is the one that was missing")
        self.assertIn("aios-ink-muted", pal)

    def test_the_aios_entries_are_mirrored_against_aios_css_not_tokens_ts(self):
        # The routing IS the point: `aios-cyan-soft` is `#0679ab`, a value that appears in aios.css
        # and nowhere in tokens.ts. Checking it against tokens.ts would refuse a correct manifest.
        manifest = self._manifest()
        cc._require_palettes_mirror_tokens(manifest["palettes"], REPO_ROOT)
        aios = (REPO_ROOT / cc._AIOS_SOURCE).read_text(encoding="utf-8").lower()
        tokens = (REPO_ROOT / cc._TOKENS_SOURCE).read_text(encoding="utf-8").lower()
        value = manifest["palettes"]["light"]["aios-cyan-soft"]
        self.assertIn(value, aios)
        self.assertNotIn(value, tokens)

    def test_a_drifted_aios_entry_is_refused(self):
        manifest = self._manifest()
        manifest["palettes"]["light"]["aios-cyan-soft"] = "#123456"
        with self.assertRaises(cc.ContrastError) as caught:
            cc._require_palettes_mirror_tokens(manifest["palettes"], REPO_ROOT)
        self.assertIn("aios.css", str(caught.exception))

    def test_the_eyebrow_pair_is_declared_and_is_the_one_that_was_failing(self):
        # `--cyan-soft` on `--bg` is `.eyebrow` on the page background: the 1.99:1 that started this.
        manifest = self._manifest()
        ids = {p["id"] for p in manifest["pairs"]}
        self.assertIn("aios-cyan-soft-on-bg", ids)
        pal = manifest["palettes"]["light"]
        self.assertGreaterEqual(
            cc.contrast_ratio(pal["aios-cyan-soft"], pal["aios-bg"]), 4.5,
            "the value that measured 1.99:1 in the browser must now clear AA",
        )

    def test_the_aios_tints_ARE_exempt_because_no_token_backs_them(self):
        # The other half of the rule, so the narrowing is pinned in both directions.
        manifest = self._manifest()
        manifest["palettes"]["light"]["aios-cyan-tint"] = "#010203"
        cc._require_palettes_mirror_tokens(manifest["palettes"], REPO_ROOT)

    def test_no_pair_names_a_background_the_app_never_paints(self):
        # `--hi` is declared in both :root blocks and painted NOWHERE. An early draft of the aios
        # pairs included it and produced a real number about a background no page has — declaring
        # pairs that never occur invents work and teaches the next reader to distrust the gate.
        ids = {p["id"] for p in self._manifest()["pairs"]}
        self.assertFalse([i for i in ids if i.endswith("-on-hi")],
                         "no pair may name --hi until something paints it")


if __name__ == "__main__":
    unittest.main()
