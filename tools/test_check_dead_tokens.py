"""Tests for tools/check_dead_tokens.py — the declared-but-never-read custom property gate.

Offline and stdlib-only. Most tests build a small fake `apps/desktop/src` tree; the ones that need
the §C.1 spec use the real repository, because the exemption is read FROM the roadmap on purpose.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_dead_tokens as dt  # noqa: E402

#: CI runs these with `working-directory: tools`, so a repo-relative path resolves to the wrong
#: place. The same trap `test_check_contrast.py` records.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _tree(css: str, tsx: str = "") -> pathlib.Path:
    d = tempfile.TemporaryDirectory()
    _tree.keep.append(d)
    root = pathlib.Path(d.name)
    src = root / dt.SRC
    src.mkdir(parents=True)
    (src / "app.css").write_text(css, encoding="utf-8")
    if tsx:
        (src / "App.tsx").write_text(tsx, encoding="utf-8")
    return root


_tree.keep = []


class ScannerTests(unittest.TestCase):
    """The parsing, which is where this gate is easiest to get wrong."""

    def test_a_bem_class_is_not_a_declaration(self):
        # The first scan of the real repository reported 24 dead tokens; four were
        # `.dt-row--action`, `.file-row--dir`, `.tile--link` and `.btn--primary`. A BEM class name
        # contains a double dash and a pseudo-class contains a colon, so the naive
        # `(--[a-z0-9-]+)\\s*:` rule reads them as token declarations.
        css = ".btn--primary:hover { color: red; }\n.tile--link:focus { color: blue; }\n"
        found = dt.declarations({pathlib.Path("a.css"): css})
        self.assertEqual(found, {}, f"a BEM modifier is not a token: {sorted(found)}")

    def test_a_real_declaration_is_found(self):
        found = dt.declarations({pathlib.Path("a.css"): ":root { --brand: #fff; }"})
        self.assertEqual(sorted(found), ["--brand"])

    def test_a_declaration_after_a_semicolon_is_found(self):
        found = dt.declarations({pathlib.Path("a.css"): ":root{--a:1;--b:2}"})
        self.assertEqual(sorted(found), ["--a", "--b"])

    def test_an_inline_style_object_declares_a_token(self):
        # TSX sets custom properties as object keys: `style={{ '--tone': value }}`.
        found = dt.declarations({pathlib.Path("A.tsx"): "style={{ '--tone': m.tone }}"})
        self.assertEqual(sorted(found), ["--tone"])

    def test_only_var_counts_as_a_reference(self):
        # A token named in a comment or a string is not read. `var()` is the only way.
        refs = dt.references({pathlib.Path("a.css"): "/* --brand is nice */ .x{color:var(--other)}"})
        self.assertEqual(refs, {"--other"})


class GateTests(unittest.TestCase):
    # `pinned=set()` throughout: a synthetic tree has no roadmap to read, and these tests are about
    # the scanner and the allowlist rather than about the §C.1 exemption. The roadmap-reading path is
    # exercised against the shipping tree in `RealRepositoryTests`.
    def test_a_token_nothing_reads_is_red(self):
        root = _tree(":root { --used: 1; --dead: 2; }\n.x { width: var(--used); }\n")
        problems = dt.check(root, pinned=set())
        self.assertTrue(any("--dead" in p for p in problems), problems)
        self.assertFalse(any("--used" in p for p in problems), problems)

    def test_a_token_read_from_tsx_is_not_dead(self):
        root = _tree(":root { --tone: red; }", "const s = { color: 'var(--tone)' };")
        self.assertEqual([p for p in dt.check(root, pinned=set()) if "--tone" in p], [])

    def test_a_token_declared_in_tsx_and_read_in_css_is_not_dead(self):
        # The real pattern: the page sets `--st-rgb` inline and the stylesheet reads it.
        root = _tree(".led { color: rgb(var(--st-rgb)); }", "style={{ '--st-rgb': m.tone }}")
        self.assertEqual([p for p in dt.check(root, pinned=set()) if "--st-rgb" in p], [])

    def test_the_exemption_is_BY_NAME_and_not_by_prefix(self):
        # The property that keeps the allowlist reviewable, and it was asserted nowhere until a
        # mutant said so: replacing `token in ALLOWED` with `token.startswith(('--menq-','--brops-'))`
        # left every test green. A prefix rule exempts every FUTURE token in the family silently,
        # which is the hole this gate exists to close — so an unread `--menq-*` that nobody listed
        # must still be reported.
        root = _tree(":root { --menq-color-invented: #123; --other: 1; } .x{color:var(--other)}")
        problems = dt.check(root, pinned=set())
        self.assertTrue(any("--menq-color-invented" in p for p in problems),
                        f"an unlisted --menq-* token must still be reported: {problems}")

    def test_the_allowlist_must_not_outlive_its_reason(self):
        # An exemption for a token something now reads is a note nobody will delete.
        root = _tree(":root { --menq-shadow-1: 0 1px 2px #000; }\n.x { box-shadow: var(--menq-shadow-1); }")
        self.assertTrue(any("--menq-shadow-1" in p and "reads it now" in p for p in dt.check(root, pinned=set())))

    def test_the_allowlist_must_not_name_a_token_that_does_not_exist(self):
        root = _tree(":root { --other: 1; }\n.x{color:var(--other)}")
        problems = dt.check(root, pinned=set())
        self.assertTrue(any("declared nowhere" in p for p in problems), problems)


class RealRepositoryTests(unittest.TestCase):
    """Against the shipping tree, because the §C.1 exemption is read from the real roadmap."""

    def test_the_repository_is_green_today(self):
        self.assertEqual(dt.check(REPO_ROOT), [])

    def test_the_c1_tokens_are_exempt_and_there_really_are_some(self):
        # Nine tokens are declared, unread, and pinned by §C.1 — `--hi` among them, which is the one
        # `T-042` found by hand. Without this exemption the gate would demand deleting tokens the
        # roadmap requires to exist, and the exemption is read FROM the roadmap so it cannot drift.
        pinned = dt.spec_tokens(REPO_ROOT)
        files = dt._read(REPO_ROOT)
        unread = set(dt.declarations(files)) - dt.references(files)
        self.assertIn("--hi", pinned)
        self.assertIn("--hi", unread, "--hi is still declared and still read by nothing")
        self.assertGreaterEqual(len(unread & pinned), 5)

    def test_every_allowlisted_token_carries_a_real_reason(self):
        # An allowlist whose entries say nothing is a list of exemptions nobody can review.
        for token, why in dt.ALLOWED.items():
            self.assertGreater(len(why), 40, f"{token}: the reason is too short to be one")


if __name__ == "__main__":
    unittest.main()
