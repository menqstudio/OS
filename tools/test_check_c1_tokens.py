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


class OverrideBlockTests(unittest.TestCase):
    """fifth audit, A-04: the gate read the FIRST `:root` and nothing else.

    17 of the 42 §C.1 tokens are redeclared after the first block, so a responsive tier could set
    `--azure` to red or `--s4` to 99px and the gate stayed GREEN. Worse, the tier that exists to
    tighten spacing tightened some rungs and not the two added this round, so the ladder ran
    backwards on a phone.
    """
    CSS = (":root{\n  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:20px;\n"
           "  --s6:24px; --s7:28px; --s8:32px; --s9:36px; --s10:40px;\n}\n"
           "@media (max-width:560px){ :root{ --s5:16px; --s6:18px; --s7:21px;"
           " --s8:24px; --s9:27px; --s10:30px } }\n")
    NAMES = ["--s%d" % i for i in range(1, 11)]

    def test_every_root_block_is_read_not_only_the_first(self):
        blocks = c1.root_blocks(self.CSS)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["--s5"], "20px")
        self.assertEqual(blocks[1]["--s5"], "16px")

    def test_a_consistent_tier_is_green(self):
        self.assertEqual(c1.ladder_monotonic(c1.root_blocks(self.CSS), self.NAMES), [])

    def test_the_ORIGINAL_bug_a_tier_that_skips_two_rungs_is_red(self):
        # --s7 left at 28px while --s8 drops to 24px: 'one step larger' becomes false.
        broken = self.CSS.replace(" --s7:21px;", "").replace(" --s9:27px;", "")
        f = c1.ladder_monotonic(c1.root_blocks(broken), self.NAMES)
        self.assertTrue(any("reorders itself" in p for p in f), f)
        self.assertTrue(any("--s7" in p for p in f), f)

    def test_a_partial_tier_is_checked_against_the_effective_value(self):
        # A tier need not restate every rung; what it does restate is compared to base+override.
        partial = self.CSS.replace("@media (max-width:560px){ :root{ --s5:16px; --s6:18px; --s7:21px;"
                                   " --s8:24px; --s9:27px; --s10:30px } }",
                                   "@media (max-width:560px){ :root{ --s10:2px } }")
        f = c1.ladder_monotonic(c1.root_blocks(partial), self.NAMES)
        self.assertTrue(any("reorders itself" in p for p in f), f)

    def test_a_non_px_rung_is_reported_rather_than_skipped(self):
        odd = self.CSS.replace("--s4:16px", "--s4:1rem")
        f = c1.ladder_monotonic(c1.root_blocks(odd), self.NAMES)
        self.assertTrue(any("is not a px length" in p for p in f), f)


class GateEvasionTests(unittest.TestCase):
    """fifth audit, A-09: the undeclared-var() half was defeated four ways."""
    def test_a_declaration_inside_a_COMMENT_does_not_count(self):
        # Comments were stripped on the reference side and not on the declaring side.
        refs = c1.referenced_tokens({"a.css": ".x{padding:var(--gone)}"})
        self.assertTrue(c1.undeclared_references(refs, set(), local_ok=set()))

    def test_uppercase_tokens_are_matched(self):
        refs = c1.referenced_tokens({"a.css": ".x{color:var(--Brand)}"})
        self.assertIn("--Brand", refs)
        self.assertTrue(any("--Brand" in p
                            for p in c1.undeclared_references(refs, set(), local_ok=set())))

    def test_a_nested_fallback_reports_the_LAST_resort(self):
        # var(--a, var(--b)): if --a is absent the value is var(--b), so an undeclared --b still
        # drops the declaration. Reporting --b is correct, and is stated in the docstring.
        refs = c1.referenced_tokens({"a.css": ".x{color:var(--a, var(--b))}"})
        self.assertIn("--b", refs)
        self.assertNotIn("--a", refs)


class AnimationClobberTests(unittest.TestCase):
    """fifth audit, A-01, turned into a check — and A-01's real lesson is in §E of that report:
    no test in this repository ever loads a stylesheet (`css: false`), so 652 unit tests and the
    whole axe suite run against a DOM with no CSS. A class name in a className was assertable; the
    paint was not. This is the static substitute."""
    TSX = ('const x = <div className={`mani surface reveal ${on ? " sigbreathe" : ""}`} />;\n'
           'const CSS = `\n'
           '.v-security .mani.sigbreathe { animation: sigbreathe 2.6s infinite; }\n'
           '`;')
    GROUPS = [{"mani", "surface", "reveal", "sigbreathe"}]

    def test_a_shorthand_that_drops_the_entrance_is_reported(self):
        f = c1.animation_clobber({"Security.tsx": self.TSX}, self.GROUPS)
        self.assertEqual(len(f), 1, f)
        self.assertIn(".mani.sigbreathe", f[0])
        self.assertIn("never becomes visible", f[0])

    def test_keeping_the_entrance_in_the_list_is_green(self):
        ok = self.TSX.replace("animation: sigbreathe 2.6s infinite;",
                              "animation: reveal var(--enter) forwards, sigbreathe 2.6s infinite;")
        self.assertEqual(c1.animation_clobber({"Security.tsx": ok}, self.GROUPS), [])

    def test_a_replacement_that_ENDS_VISIBLE_is_legitimate(self):
        # dec-reveal ends at opacity:1, so it does the entrance's job and must not be reported.
        css = ('const x = <div className="led rise" />;\n'
               'const CSS = `\n'
               '@keyframes dec-reveal { from { opacity: 0; } to { opacity: 1; transform: none; } }\n'
               '.v-decisions .led { animation: dec-reveal .3s ease both; }\n`;')
        self.assertEqual(c1.animation_clobber({"Decisions.tsx": css}, [{"led", "rise"}]), [])

    def test_but_a_final_keyframe_that_OMITS_opacity_is_reported(self):
        # THE SECOND REAL BUG this check found: an implicit 100% is built from the underlying
        # value, which is the entrance class's opacity:0 — so the row faded back out.
        css = ('const x = <div className="led rise" />;\n'
               'const CSS = `\n'
               '@keyframes dec-stamp { 0% { opacity: 0; } 60% { opacity: 1; } 100% { transform: none; } }\n'
               '.v-decisions .led.dec-stamp { animation: dec-stamp .4s both; }\n`;')
        f = c1.animation_clobber({"Decisions.tsx": css}, [{"led", "rise", "dec-stamp"}])
        self.assertTrue(any("dec-stamp" in p for p in f), f)

    def test_a_pseudo_element_is_a_different_box(self):
        css = ('const x = <div className="surface reveal" />;\n'
               'const CSS = `.surface:hover::after { animation: spin 1s infinite; }`;')
        self.assertEqual(c1.animation_clobber({"a.tsx": css}, [{"surface", "reveal"}]), [])

    def test_reduced_motion_may_kill_the_animation(self):
        css = ('const x = <div className="mani reveal sigbreathe" />;\n'
               'const CSS = `\n@media (prefers-reduced-motion: reduce) {\n'
               '  .mani.sigbreathe { animation: none; }\n}\n`;')
        self.assertEqual(c1.animation_clobber({"a.tsx": css}, [{"mani", "reveal", "sigbreathe"}]), [])

    def test_an_unmatched_selector_is_skipped_rather_than_guessed_at(self):
        css = 'const CSS = `.nothing-renders-this { animation: spin 1s; }`;'
        self.assertEqual(c1.animation_clobber({"a.tsx": css}, self.GROUPS), [])

    def test_only_the_SUBJECT_compound_is_matched_against_an_element(self):
        # `.v-security` is an ancestor and never shares a className with `.mani`. Requiring the
        # whole selector to be in one group is why the first version missed the rule it was for.
        groups = c1.classname_groups({
            "a.tsx": 'const x = <div className={`mani surface reveal ${on ? " sigbreathe" : ""}`} />;'})
        self.assertTrue(any({"mani", "sigbreathe", "reveal"} <= g for g in groups), groups)

    def test_a_conditional_class_is_collected_from_the_interpolation(self):
        groups = c1.classname_groups({
            "a.tsx": 'const x = <div className={`a b ${flag ? " lit" : ""}`} />;'})
        self.assertTrue(any("lit" in g for g in groups), groups)


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


class A03LonghandTests(unittest.TestCase):
    r"""`A-03` — the gate was evaded by the remedy its own error message recommended.

    `animation-name` is list-valued; setting it replaces the list identically. The check matched
    `animation\s*:` only, so an author who tripped it, read "use the animation-* longhands" and did
    exactly that reintroduced the fifth audit's `A-01` byte for byte. Measured in Chromium by the
    auditor: shorthand -> opacity 0, longhand -> opacity 0; gate RED for one and GREEN for the other.
    """

    CSS = ".reveal{opacity:0;animation:reveal var(--enter) forwards}\n@keyframes reveal{to{opacity:1}}\n"
    TSX = 'const x = <div className="reveal hot" />;'

    def clobber(self, rule):
        texts = {"a.css": self.CSS + rule, "x.tsx": self.TSX}
        return c1.animation_clobber(texts, c1.classname_groups(texts))

    def test_the_shorthand_is_caught(self):
        self.assertTrue(self.clobber(".reveal.hot{animation:spin 2s infinite}"))

    def test_the_animation_name_LONGHAND_is_caught_too(self):
        self.assertTrue(self.clobber(".reveal.hot{animation-name:spin;animation-duration:2s}"))

    def test_a_composed_list_is_accepted_in_both_forms(self):
        self.assertEqual(self.clobber(".reveal.hot{animation:reveal var(--enter) forwards,spin 2s}"), [])
        self.assertEqual(self.clobber(".reveal.hot{animation-name:reveal,spin}"), [])

    def test_the_message_no_longer_recommends_the_longhand_on_its_own(self):
        message = self.clobber(".reveal.hot{animation:spin 2s infinite}")[0]
        self.assertIn("Compose the list instead", message)
        self.assertIn("NOT the `animation-name` longhand on its own", message)


class A04EntranceDiscoveryTests(unittest.TestCase):
    """`A-04` — the check knew two entrance classes; the tree had fourteen."""

    def test_an_entrance_class_is_DERIVED_from_opacity_zero_plus_an_animation(self):
        css = ".zzfade{opacity:0;animation:zzin 1s forwards}\n@keyframes zzin{to{opacity:1}}\n"
        self.assertEqual(c1.entrance_classes(css).get("zzfade"), "zzin")

    def test_a_descendant_selector_records_its_SUBJECT_compound(self):
        css = ".spark .fill{opacity:0;animation:draw 1s forwards}\n"
        self.assertIn("fill", c1.entrance_classes(css))
        self.assertNotIn("spark", c1.entrance_classes(css))

    def test_a_pseudo_element_is_not_an_entrance_class_on_its_owner(self):
        css = ".sigil::before{opacity:0;animation:glow 1s forwards}\n"
        self.assertNotIn("sigil", c1.entrance_classes(css))

    def test_a_derived_entrance_class_is_then_protected(self):
        css = (".zzfade{opacity:0;animation:zzin 1s forwards}\n@keyframes zzin{to{opacity:1}}\n"
               ".zzfade.zzhot{animation:spin 2s infinite}\n")
        tsx = 'const x = <div className="zzfade zzhot" />;'
        self.assertTrue(c1.animation_clobber({"a.css": css, "x.tsx": tsx},
                                            c1.classname_groups({"x.tsx": tsx})))

    def test_a_PLAIN_string_className_is_read_at_all(self):
        # The hole found by mutation-testing A-04's own case, and bigger than A-04: for
        # `className="a b"` the region has no quotes or backticks inside it, so both harvest
        # loops found nothing and EVERY plain className in the app was invisible to this check.
        self.assertEqual(c1.classname_groups({"x.tsx": 'x = <b className="alpha beta" />'}),
                         [{"alpha", "beta"}])

    def test_an_UPPERCASE_class_token_is_read(self):
        self.assertEqual(c1.classname_groups({"x.tsx": 'x = <b className="Alpha beta" />'}),
                         [{"Alpha", "beta"}])

    def test_a_keyframe_named_after_an_animation_keyword_is_refused(self):
        self.assertEqual(c1.keyframe_name_collisions("@keyframes forwards{to{opacity:1}}"),
                         ["forwards"])
        self.assertEqual(c1.keyframe_name_collisions("@keyframes reveal{to{opacity:1}}"), [])

    def test_a_test_fixture_is_not_shipped_source(self):
        self.assertTrue(c1.is_test_file("src/test/harness.browser.spec.tsx"))
        self.assertTrue(c1.is_test_file("src/features/Foo.test.tsx"))
        self.assertFalse(c1.is_test_file("src/features/Foo.tsx"))


class A10OverrideScopeTests(unittest.TestCase):
    """`A-10` — what a `:root` override is entitled to change, per kind of block."""

    KINDS = {"--azure": "colour", "--s4": "geometry", "--t-body": "geometry"}

    def test_block_kinds_are_read_from_the_stylesheet(self):
        css = (':root{--azure:#0A84FF}\n'
               ':root[data-theme="light"]{--azure:#FFFFFF}\n'
               '@media (max-width:560px){:root{--s4:12px}}\n')
        self.assertEqual(c1.root_block_kinds(css), ["base", "theme", "responsive"])

    def test_a_theme_may_restate_colours(self):
        self.assertEqual(
            c1.override_scope([{}, {"--azure": "#fff"}], ["base", "theme"], self.KINDS), [])

    def test_a_theme_may_NOT_move_the_layout(self):
        out = c1.override_scope([{}, {"--s4": "99px"}], ["base", "theme"], self.KINDS)
        self.assertTrue(any("geometry token" in f for f in out), out)

    def test_a_responsive_tier_may_restate_geometry(self):
        self.assertEqual(
            c1.override_scope([{}, {"--s4": "12px"}], ["base", "responsive"], self.KINDS), [])

    def test_a_responsive_tier_may_NOT_repaint(self):
        # THE FINDING, and the docstring's own worked example.
        out = c1.override_scope([{}, {"--azure": "#FF0000"}], ["base", "responsive"], self.KINDS)
        self.assertTrue(any("colour token" in f for f in out), out)

    def test_a_block_nobody_can_classify_is_refused_rather_than_guessed_at(self):
        out = c1.override_scope([{}, {"--azure": "#f00"}], ["base", "other"], self.KINDS)
        self.assertTrue(any("cannot say what it is entitled to change" in f for f in out), out)

    def test_token_kinds_come_from_C1s_own_values(self):
        kinds = c1.token_kinds({"--azure": "#0A84FF", "--s4": "16px", "--enter": "640ms"})
        self.assertEqual(kinds, {"--azure": "colour", "--s4": "geometry", "--enter": "geometry"})


class LadderDirectionTests(unittest.TestCase):
    """The type scale descends. An ascending-only check called the correct base six failures."""

    def test_a_descending_scale_is_accepted(self):
        blocks = [{"--t-hero": "32px", "--t-h1": "24px", "--t-body": "15px"}]
        self.assertEqual(c1.ladder_monotonic(blocks, ["--t-hero", "--t-h1", "--t-body"], "type scale"), [])

    def test_a_tier_that_reorders_a_DESCENDING_scale_is_red(self):
        blocks = [{"--t-hero": "32px", "--t-h1": "24px", "--t-body": "15px"},
                  {"--t-body": "99px"}]
        out = c1.ladder_monotonic(blocks, ["--t-hero", "--t-h1", "--t-body"], "type scale")
        self.assertTrue(any("reorders itself" in f for f in out), out)

    def test_an_ascending_scale_still_works(self):
        blocks = [{"--s1": "4px", "--s2": "8px"}, {"--s2": "2px"}]
        out = c1.ladder_monotonic(blocks, ["--s1", "--s2"], "spacing")
        self.assertTrue(any("reorders itself" in f for f in out), out)

    def test_a_base_with_no_direction_at_all_is_refused(self):
        blocks = [{"--a": "1px", "--b": "9px", "--c": "2px"}]
        out = c1.ladder_monotonic(blocks, ["--a", "--b", "--c"], "made-up scale")
        self.assertTrue(any("no direction" in f for f in out), out)
