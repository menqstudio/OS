"""Tests for tools/check_c1_tokens.py — the §C.1 design-token gate.

The gate exists because of one bug and it is worth naming in the tests: `--s7` and `--s9` were
missing from a spacing ladder documented as `--s1..--s10`, `padding:var(--s7) var(--s5)` shipped on
two empty states, and an undeclared custom property makes the WHOLE declaration invalid at
computed-value time — so those panels had no padding. No test could fail, because nothing read the
stylesheet against its own specification.

Two properties are pinned here, and a third that matters just as much: the gate must not cry wolf.
A `var(--x, fallback)` is legitimate, a token set from a React inline style is legitimate, and a
token named inside a CSS comment is documentation. A gate that reported those would be switched off
within a week, and a gate that is switched off catches nothing.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_c1_tokens as c1  # noqa: E402

ROADMAP = """
### C.1 Design tokens (from the prototype `:root`)
| Group | Tokens |
|---|---|
| **Brand / accent** | `--azure #0A84FF` (primary), `--cyan #38BDF8` |
| **Type scale** | hero 32 · h1 24 · h2 19 · body 15 · ui 14 · small 12 · micro 10 (px) |
| **Radii** | sm 9 · base 12 · lg 18 · xl 26 · pill 999 (px) |
| **Spacing** | 4 · 8 · 12 · 16 · 20 · 24 · 28 · 32 · 36 · 40 (px) — `--s1..--s10` |
| **Motion** | `--fast 130ms`, `--stagger 52ms` |

### C.2 next section
"""


class ParseC1Tests(unittest.TestCase):
    def test_inline_pairs_are_read_with_their_values(self):
        got = c1.parse_c1(ROADMAP)
        self.assertEqual(got["--azure"], "#0A84FF")
        self.assertEqual(got["--cyan"], "#38BDF8")
        self.assertEqual(got["--fast"], "130ms")

    def test_positional_rows_are_matched_by_order(self):
        got = c1.parse_c1(ROADMAP)
        self.assertEqual(got["--t-hero"], "32px")
        self.assertEqual(got["--t-micro"], "10px")
        self.assertEqual(got["--r-sm"], "9px")
        self.assertEqual(got["--r-pill"], "999px")
        self.assertEqual(got["--s1"], "4px")
        self.assertEqual(got["--s7"], "28px")     # the rung that was missing
        self.assertEqual(got["--s10"], "40px")

    def test_a_row_whose_value_count_disagrees_with_its_names_is_an_ERROR(self):
        # THE BUG, as a test. §C.1 listed eight values for --s1..--s10, so the gap read as
        # deliberate. Silently reading the first eight would have re-created exactly that.
        eight = ROADMAP.replace("4 · 8 · 12 · 16 · 20 · 24 · 28 · 32 · 36 · 40",
                                "4 · 8 · 12 · 16 · 20 · 24 · 32 · 40")
        with self.assertRaises(ValueError) as cm:
            c1.parse_c1(eight)
        self.assertIn("Spacing", str(cm.exception))

    def test_a_missing_section_is_an_error_not_an_empty_result(self):
        with self.assertRaises(ValueError):
            c1.parse_c1("# a roadmap with no C.1 at all\n")


class RootDeclarationTests(unittest.TestCase):
    def test_reads_the_first_root_block_only(self):
        css = (":root{\n  --s5:20px; --bg:#05070C;\n}\n"
               "@media (max-width:560px){ :root{ --s5:16px } }\n")
        got = c1.root_declarations(css)
        self.assertEqual(got["--s5"], "20px")   # NOT the phone-tier override
        self.assertEqual(got["--bg"], "#05070C")


class CompareTests(unittest.TestCase):
    def test_matching_values_pass(self):
        self.assertEqual(c1.compare({"--bg": "#05070C"}, {"--bg": "#05070C"}), [])

    def test_drift_is_reported_both_ways_round(self):
        f = c1.compare({"--bg": "#05070C"}, {"--bg": "#000000"})
        self.assertEqual(len(f), 1)
        self.assertIn("#05070C", f[0])
        self.assertIn("#000000", f[0])

    def test_an_undeclared_spec_token_is_reported(self):
        f = c1.compare({"--s7": "28px"}, {})
        self.assertTrue(any("does not declare it" in p for p in f))

    def test_a_duration_spec_is_a_prefix_claim_not_an_equality_one(self):
        # §C.1 says `--fast 130ms`; the stylesheet adds the easing curve. The spec is asserting
        # the duration, and forcing it to carry the curve would put implementation in the spec.
        self.assertEqual(c1.compare({"--fast": "130ms"},
                                    {"--fast": "130ms cubic-bezier(.2,.6,.2,1)"}), [])

    def test_but_a_wrong_duration_still_fails(self):
        self.assertEqual(len(c1.compare({"--fast": "130ms"},
                                        {"--fast": "500ms cubic-bezier(.2,.6,.2,1)"})), 1)


class ReferenceTests(unittest.TestCase):
    def test_a_bare_var_with_nothing_declaring_it_is_reported(self):
        refs = c1.referenced_tokens({"a.css": ".x{padding:var(--s7)}"})
        f = c1.undeclared_references(refs, {"--s5"}, local_ok=set())
        self.assertTrue(any("--s7" in p for p in f), f)

    def test_a_var_WITH_a_fallback_is_not_a_defect(self):
        # It resolves to the fallback and the declaration stands. Reporting it would be noise.
        refs = c1.referenced_tokens({"a.css": ".x{padding:var(--s7, 28px)}"})
        self.assertEqual(refs, {})

    def test_a_token_named_only_inside_a_comment_is_documentation(self):
        refs = c1.referenced_tokens({"a.css": "/* glows are rgb(var(--x-rgb)/a) */\n.y{color:red}"})
        self.assertEqual(refs, {})

    def test_a_declared_token_is_not_reported(self):
        refs = c1.referenced_tokens({"a.css": ".x{padding:var(--s5)}"})
        self.assertEqual(c1.undeclared_references(refs, {"--s5"}, local_ok=set()), [])

    def test_the_reporting_names_the_file_so_the_fix_is_findable(self):
        refs = c1.referenced_tokens({"features/Agents.tsx": ".x{padding:var(--s7)}"})
        f = c1.undeclared_references(refs, set(), local_ok=set())
        self.assertIn("features/Agents.tsx", f[0])


class RealRepositoryTests(unittest.TestCase):
    """The gate against the real files — the regression that keeps the bug closed."""
    def test_the_real_spacing_ladder_is_complete_and_matches_C1(self):
        expected = c1.parse_c1(c1.ROADMAP.read_text(encoding="utf-8"))
        declared = c1.root_declarations(c1.AIOS_CSS.read_text(encoding="utf-8"))
        for i in range(1, 11):
            self.assertIn("--s%d" % i, declared, "--s%d is missing from the ladder again" % i)
        self.assertEqual(c1.compare(expected, declared), [])


if __name__ == "__main__":
    unittest.main()
