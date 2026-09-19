#!/usr/bin/env python3
"""Self-tests for `check_artwork_geometry.py`.

Every rule is exercised twice: a synthetic pair that satisfies it, and the same pair with exactly one
property broken. A gate that is only ever run against a repository it passes has been observed, not
tested -- and two of this gate's rules were WRONG on the first run against the real sheets, which is
the whole argument for building the synthetic side.

The real repository gets one test of its own, at the end, and it is deliberately the last: a gate whose
only evidence is "the tree is green today" cannot tell a clean tree from a rule that never fires.
"""
from __future__ import annotations

import importlib.util
import pathlib
import shutil
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent

spec = importlib.util.spec_from_file_location("check_artwork_geometry",
                                              HERE / "check_artwork_geometry.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

#: A whole sheet, small enough to read in a failure message and complete enough to pass every rule.
LIGHT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 200" width="1200" height="200"
     role="img" aria-labelledby="t d" font-family="Inter, sans-serif">
  <title id="t">A sheet</title>
  <desc id="d">light theme. MenQ ground #ffffff.</desc>
  <defs><clipPath id="clip"><rect x="0" y="0" width="1200" height="200"/></clipPath></defs>
  <rect x="0" y="0" width="1200" height="200" fill="#ffffff"/>
  <rect x="40" y="40" width="200" height="40" rx="12" fill="#f5f6f8" clip-path="url(#clip)"/>
  <text x="56" y="64" font-size="11" fill="#10131a">Left column</text>
  <text x="600" y="64" font-size="11" fill="#5b6473">Right column · աջ սյունը</text>
</svg>
"""

#: The same drawing in the other theme. Colour literals only -- that is the property under test.
DARK = (LIGHT
        .replace("light theme. MenQ ground #ffffff.", "dark theme. MenQ ground #0b0d10.")
        .replace('fill="#ffffff"', 'fill="#0b0d10"')
        .replace('fill="#f5f6f8"', 'fill="#14171f"')
        .replace('fill="#10131a"', 'fill="#eef1f6"')
        .replace('fill="#5b6473"', 'fill="#98a2b3"'))

TOKENS = """:root {
  --menq-color-bg: #f5f6f8;
  --menq-color-surface: #ffffff;
  --menq-color-text: #10131a;
  --menq-color-muted: #5b6473;
}
:root[data-theme="dark"] {
  --menq-color-bg: #0c0e13;
  --menq-color-surface: #14171f;
  --menq-color-text: #eef1f6;
  --menq-color-muted: #98a2b3;
}
"""


class ASyntheticPair(unittest.TestCase):
    """One drawing, one theme swap, and one property broken per test."""

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="artwork-geometry-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "apps" / "desktop" / "src" / "theme").mkdir(parents=True)
        (self.root / "apps" / "desktop" / "src" / "theme" / "tokens.css").write_text(
            TOKENS, encoding="utf-8")
        self.sheets = self.root / "docs" / "brand" / "readme"
        self.sheets.mkdir(parents=True)
        self.write("sheet-light.svg", LIGHT)
        self.write("sheet-dark.svg", DARK)
        (self.root / "README.md").write_text(
            "![a](docs/brand/readme/sheet-light.svg) ![b](docs/brand/readme/sheet-dark.svg)\n",
            encoding="utf-8")

    def write(self, name, text):
        (self.sheets / name).write_bytes(text.encode("utf-8"))

    def problems(self):
        return m.check(self.root)[0]

    # -- the control ---------------------------------------------------------------------------
    def test_a_correct_pair_has_no_problem(self):
        """Without this, every test below could be passing for the wrong reason."""
        self.assertEqual(self.problems(), [])

    def test_the_control_counts_what_it_read(self):
        _problems, counted = m.check(self.root)
        self.assertEqual((counted["sheets"], counted["pairs"], counted["runs"]), (2, 1, 4))

    # -- rule 1, parsing ----------------------------------------------------------------------
    def test_a_sheet_that_does_not_parse_is_named(self):
        self.write("sheet-light.svg", LIGHT.replace("</svg>", ""))
        self.assertTrue(any("does not parse" in p for p in self.problems()), self.problems())

    # -- rule 2, canvas -----------------------------------------------------------------------
    def test_a_height_that_disagrees_with_the_viewbox_is_named(self):
        self.write("sheet-light.svg", LIGHT.replace('height="200"\n', 'height="240"\n', 1))
        self.assertTrue(any("do not agree with the viewBox" in p for p in self.problems()),
                        self.problems())

    def test_a_canvas_of_another_width_is_named(self):
        self.write("sheet-light.svg", LIGHT.replace('viewBox="0 0 1200 200" width="1200"',
                                                    'viewBox="0 0 1000 200" width="1000"'))
        self.assertTrue(any("not 1200" in p for p in self.problems()), self.problems())

    # -- rule 3, the twin ---------------------------------------------------------------------
    def test_a_light_sheet_without_its_dark_twin_is_named(self):
        (self.sheets / "sheet-dark.svg").unlink()
        self.assertTrue(any("has no sheet-dark.svg" in p for p in self.problems()), self.problems())

    # -- rule 4, parity -----------------------------------------------------------------------
    def test_a_dark_sheet_that_is_a_second_drawing_is_named(self):
        """The failure mode this rule exists for: a dark sheet that drifted, or was redrawn."""
        self.write("sheet-dark.svg", DARK.replace('x="600"', 'x="620"'))
        self.assertTrue(any("more than colour literals" in p for p in self.problems()),
                        self.problems())

    def test_a_theme_line_may_differ(self):
        """The one line that is ALLOWED to differ, so the rule is not simply byte equality."""
        self.write("sheet-dark.svg", DARK.replace("dark theme. MenQ ground #0b0d10.",
                                                  "dark theme, re-cut for the gallery."))
        self.assertEqual(self.problems(), [])

    # -- rule 5, declared pairs ---------------------------------------------------------------
    def test_a_light_colour_paired_with_an_undeclared_dark_colour_is_named(self):
        """MEASURED on the real sheets: `#f5f6f8` maps to `#14171f` 61 times and to `#1b1f2a` ONCE,
        in one panel of `authority-dark.svg`. Counting found it; looking had not."""
        # `#0c0e13` would NOT do: it is this theme's dark `bg`, so `#f5f6f8 -> #0c0e13` is a
        # declared pair and the mutant would be legal. The dark TEXT colour is on the palette and
        # pairs with nothing light-panel-shaped, which is what makes it a mutation.
        self.write("sheet-dark.svg", DARK.replace('fill="#14171f"', 'fill="#eef1f6"'))
        self.assertTrue(any("is not a declared light/dark pair" in p for p in self.problems()),
                        self.problems())

    def test_a_declared_token_pair_is_allowed_even_when_light_repeats_a_literal(self):
        """The first version of this rule demanded a bijection and was WRONG: a light theme may use
        white for both the ground and an elevated card, and the dark theme then separates them. That
        is the token table working, not a lost distinction, and `architecture-*.svg` does exactly it."""
        light = LIGHT.replace('fill="#f5f6f8"', 'fill="#ffffff"')
        dark = DARK.replace('fill="#14171f"', 'fill="#14171f"')
        self.write("sheet-light.svg", light)
        self.write("sheet-dark.svg", dark)
        self.assertEqual([p for p in self.problems() if "declared" in p], [])

    # -- rule 6, palette ----------------------------------------------------------------------
    def test_a_colour_on_no_token_table_is_named(self):
        self.write("sheet-light.svg", LIGHT.replace('fill="#10131a"', 'fill="#123456"'))
        self.assertTrue(any("on no token table" in p for p in self.problems()), self.problems())

    # -- rule 7, fragments --------------------------------------------------------------------
    def test_a_fragment_reference_to_nothing_is_named(self):
        self.write("sheet-light.svg", LIGHT.replace("url(#clip)", "url(#nope)"))
        self.assertTrue(any("url(#nope)" in p for p in self.problems()), self.problems())

    def test_a_fragment_defined_in_the_same_file_is_not_external(self):
        """My own checker called this a defect in `#247` and it was the checker that was wrong."""
        self.assertEqual([p for p in self.problems() if "url(" in p], [])

    # -- rule 8, the content edge -------------------------------------------------------------
    def test_a_run_past_the_content_edge_is_named(self):
        self.write("sheet-light.svg", LIGHT.replace('<text x="600"', '<text x="1100"'))
        self.assertTrue(any("past the content edge" in p for p in self.problems()), self.problems())

    def test_a_run_past_the_canvas_says_so_as_well(self):
        self.write("sheet-light.svg", LIGHT.replace('<text x="600"', '<text x="1190"'))
        self.assertTrue(any("past the 1200 canvas" in p for p in self.problems()), self.problems())

    # -- rule 9, overlap ----------------------------------------------------------------------
    def test_two_runs_that_overlap_on_one_baseline_are_named(self):
        """The defect the verification sheet was two bound rows away from."""
        self.write("sheet-light.svg", LIGHT.replace('<text x="600"', '<text x="100"'))
        self.assertTrue(any("overlap by" in p for p in self.problems()), self.problems())

    def test_runs_on_different_baselines_may_share_x(self):
        self.write("sheet-light.svg", LIGHT.replace('<text x="600" y="64"', '<text x="56" y="120"'))
        self.assertEqual([p for p in self.problems() if "overlap" in p], [])

    # -- rule 10, bytes -----------------------------------------------------------------------
    def test_crlf_is_named(self):
        (self.sheets / "sheet-light.svg").write_bytes(LIGHT.replace("\n", "\r\n").encode("utf-8"))
        self.assertTrue(any("CRLF" in p for p in self.problems()), self.problems())

    def test_a_control_byte_is_named(self):
        """`TASKS.md` carried a real 0x08 for weeks and no gate refused it."""
        (self.sheets / "sheet-light.svg").write_bytes(
            LIGHT.replace("Left column", "Left\x08column").encode("utf-8"))
        self.assertTrue(any("control byte" in p for p in self.problems()), self.problems())

    def test_a_bom_is_named(self):
        (self.sheets / "sheet-light.svg").write_bytes(b"\xef\xbb\xbf" + LIGHT.encode("utf-8"))
        self.assertTrue(any("BOM" in p for p in self.problems()), self.problems())

    # -- rule 11, orphans ---------------------------------------------------------------------
    def test_a_sheet_the_readme_does_not_show_is_named(self):
        self.write("orphan-light.svg", LIGHT)
        self.write("orphan-dark.svg", DARK)
        self.assertTrue(any("orphan-light.svg: no README.md reference" in p
                            for p in self.problems()), self.problems())


class TheRealRepository(unittest.TestCase):
    """Last, and on purpose: a green tree is not evidence that a rule fires."""

    def test_the_sheets_this_repository_ships_pass_every_rule(self):
        problems, counted = m.check(ROOT)
        self.assertEqual(problems, [], "\n".join(problems))
        self.assertGreaterEqual(counted["sheets"], 14)
        self.assertGreaterEqual(counted["pairs"], 7)

    def test_the_verification_pair_is_the_one_that_taught_this_gate(self):
        """Named, so deleting the sheet that motivated the gate is a failure rather than a silence."""
        names = {p.name for p in (ROOT / m.SHEET_DIR).glob("*.svg")}
        self.assertIn("verification-light.svg", names)
        self.assertIn("verification-dark.svg", names)


if __name__ == "__main__":
    unittest.main()
