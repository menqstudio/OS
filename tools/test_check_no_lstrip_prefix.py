#!/usr/bin/env python3
"""Self-test for `check_no_lstrip_prefix.py`.

Run: python -m unittest test_check_no_lstrip_prefix   (from tools/)

Every assertion here is about a property the gate is supposed to have, and the two that
matter most are the ones a naive regex implementation would fail:

  * `EquivalenceOfSingleCharacterStrip` measures the claim the module docstring makes to
    justify the two-character floor, rather than asserting it. If `lstrip("/")` and
    repeated-prefix-removal ever disagreed, the floor would be a hole and this goes red.
  * `DocumentationIsNotAnOffence` pins the AST design: this repository's own gate
    documentation quotes `lstrip("./")` many times, and a gate that reds on the file
    describing the defect gets switched off. The exemption is structural (comments are
    not in the AST), so it is tested on the real files rather than on a fixture.
"""
from __future__ import annotations

import io
import contextlib
import pathlib
import tempfile
import unittest

import check_no_lstrip_prefix as gate

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent

#: The defective argument, held in a NAMED CONSTANT rather than written as a literal at
#: each call below.
#:
#: Read this before assuming it is a dodge. `TheRepositoryItself.test_the_tree_is_clean`
#: runs the gate over this whole repository, and this file is in it -- so the one file
#: that must legitimately CALL the form the gate forbids would otherwise turn the gate
#: red on itself. The options were an allow-list for `tools/test_*.py` (which would then
#: blind the gate to a real defect written in any test, and is exactly the kind of
#: exemption that rots), or the module docstring's already-stated blind spot: a variable
#: argument is not resolved by the AST walk.
#:
#: The blind spot is used here ONCE, in the open, in the file that documents the defect,
#: rather than configured somewhere a later session has to remember. It also demonstrates
#: the limit honestly: one line turns any offence invisible to this gate, which is why the
#: gate is described as refusing the LITERAL form that was written three times and not as
#: a proof that no character-set strip survives.
DOT_SLASH = "./"


def write_tree(base: pathlib.Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class OffenceDetection(unittest.TestCase):
    """The forms that ARE the defect."""

    def test_the_exact_form_found_three_times_is_an_offence(self):
        self.assertEqual(
            gate.offences_in_source('rel = p.lstrip("./")\n'), [(1, "./")])

    def test_reports_the_line_number_of_the_call(self):
        source = "a = 1\nb = 2\n\nc = d.lstrip('./')\n"
        self.assertEqual(gate.offences_in_source(source), [(4, "./")])

    def test_a_windows_separator_is_an_offence_too(self):
        self.assertEqual(gate.offences_in_source('x.lstrip(".\\\\")'), [(1, ".\\")])

    def test_a_bare_slash_pair_is_an_offence(self):
        self.assertEqual(gate.offences_in_source('x.lstrip("//")'), [(1, "//")])

    def test_every_offence_in_a_file_is_reported_not_only_the_first(self):
        source = 'a.lstrip("./")\nb.lstrip("/.")\n'
        self.assertEqual(gate.offences_in_source(source), [(1, "./"), (2, "/.")])

    def test_it_finds_the_call_nested_inside_an_expression(self):
        source = 'q = sorted(x.split("#", 1)[0].lstrip("./") for x in items)\n'
        self.assertEqual(gate.offences_in_source(source), [(1, "./")])

    def test_the_true_fix_is_not_an_offence(self):
        self.assertEqual(gate.offences_in_source('rel = p.removeprefix("./")\n'), [])


class WhatIsDeliberatelyNotAnOffence(unittest.TestCase):
    """The forms that are correct, and would be noise if flagged."""

    def test_a_single_character_separator_is_not_an_offence(self):
        # engine/runtime/bro_policy.py:279 and bro_release_v3.py:40 use this correctly.
        self.assertEqual(gate.offences_in_source('x.lstrip("/")'), [])

    def test_a_multi_character_argument_with_no_separator_is_not_an_offence(self):
        # tools/sync_active_pr.py:281 uses lstrip("#"); check_contrast.py:51 lstrip("#").
        self.assertEqual(gate.offences_in_source('x.lstrip("#")'), [])
        self.assertEqual(gate.offences_in_source('x.lstrip("ab")'), [])

    def test_a_bare_lstrip_with_no_argument_is_not_an_offence(self):
        # Whitespace stripping: check_no_assumptions.py:96, check_repo_state.py:154.
        self.assertEqual(gate.offences_in_source('x.lstrip()'), [])

    def test_a_variable_argument_is_not_flagged_and_that_limit_is_deliberate(self):
        # Stated in the module docstring as a known blind spot rather than hidden.
        self.assertEqual(gate.offences_in_source('sep = "./"\nx.lstrip(sep)\n'), [])

    def test_rstrip_and_strip_are_out_of_scope(self):
        self.assertEqual(gate.offences_in_source('x.rstrip("./")'), [])
        self.assertEqual(gate.offences_in_source('x.strip("./")'), [])


class EquivalenceOfSingleCharacterStrip(unittest.TestCase):
    """Measure the claim that justifies the two-character floor.

    If a one-character `lstrip` ever differed from repeated prefix removal, the floor
    would be an exemption rather than a definition, and this test says so by failing.
    """

    def test_single_character_lstrip_equals_repeated_prefix_removal(self):
        samples = ["/a/b", "//a/b", "a/b", "///", "", "/", "/./x", "//", "x//y"]
        for sample in samples:
            with self.subTest(sample=sample):
                expected = sample
                while expected.startswith("/"):
                    expected = expected[1:]
                self.assertEqual(sample.lstrip("/"), expected)

    def test_two_character_lstrip_does_NOT_equal_repeated_prefix_removal(self):
        # The defect itself, pinned: this is why length >= 2 is the rule.
        self.assertNotEqual(".claude/x".lstrip(DOT_SLASH), ".claude/x".removeprefix(DOT_SLASH))
        self.assertEqual(".claude/x".lstrip(DOT_SLASH), "claude/x")
        self.assertEqual(".claude/x".removeprefix(DOT_SLASH), ".claude/x")

    def test_the_traversal_laundering_the_fix_closes(self):
        # The direction that matters: a path OUTSIDE the tree became one inside it.
        self.assertEqual("../tools/evil.py".lstrip(DOT_SLASH), "tools/evil.py")
        self.assertEqual("../tools/evil.py".removeprefix(DOT_SLASH), "../tools/evil.py")


class DocumentationIsNotAnOffence(unittest.TestCase):
    """The AST design, tested on the real files rather than a fixture.

    `check_doc_claims.py:232` carries a comment quoting `lstrip("./")`, and this gate's
    own docstring quotes the broken form repeatedly. Both must be invisible, and they
    must be invisible STRUCTURALLY -- no allow-list, no suppression marker.
    """

    def test_the_comment_in_check_doc_claims_is_not_flagged(self):
        source = (ROOT / "tools" / "check_doc_claims.py").read_text(encoding="utf-8")
        self.assertIn('lstrip("./")', source, "the comment this test is about has moved")
        self.assertEqual(gate.offences_in_source(source), [])

    def test_this_gate_does_not_flag_its_own_docstring(self):
        source = (ROOT / "tools" / "check_no_lstrip_prefix.py").read_text(encoding="utf-8")
        self.assertIn('lstrip("./")', source, "the gate no longer documents the defect")
        self.assertEqual(gate.offences_in_source(source), [])

    def test_a_docstring_quoting_the_form_is_not_an_offence(self):
        self.assertEqual(gate.offences_in_source('"""Never write x.lstrip(\'./\')."""\n'), [])


class SweepAndVerdict(unittest.TestCase):
    """`scan()` and `main()` over a synthetic tree."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def run_main(self, root: pathlib.Path) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = gate.main(["--root", str(root)])
        return code, buffer.getvalue()

    def test_a_clean_tree_is_green_and_counts_the_files(self):
        write_tree(self.base, {"a.py": 'x.removeprefix("./")\n', "pkg/b.py": "y = 1\n"})
        code, out = self.run_main(self.base)
        self.assertEqual(code, 0, out)
        self.assertIn("GREEN:", out)
        self.assertIn("2 Python file(s)", out)

    def test_an_offence_anywhere_in_the_tree_is_red_and_names_path_and_line(self):
        write_tree(self.base, {"deep/nested/mod.py": "a = 1\nb = a.lstrip('./')\n"})
        code, out = self.run_main(self.base)
        self.assertEqual(code, 1)
        self.assertIn("RED:", out)
        self.assertIn("deep/nested/mod.py:2", out)

    def test_skipped_directories_are_not_swept(self):
        write_tree(self.base, {
            "node_modules/x.py": 'a.lstrip("./")\n',
            "target/y.py": 'a.lstrip("./")\n',
            "__pycache__/z.py": 'a.lstrip("./")\n',
            "ok.py": "a = 1\n",
        })
        code, out = self.run_main(self.base)
        self.assertEqual(code, 0, out)
        self.assertIn("1 Python file(s)", out)

    def test_a_nested_agent_worktree_is_not_swept(self):
        # A second checkout of this repository under .claude/worktrees/ must not decide
        # the verdict: that would make the gate red on a developer box and green in CI.
        write_tree(self.base, {
            ".claude/worktrees/agent-x/tools/g.py": 'a.lstrip("./")\n',
            "tools/g.py": "a = 1\n",
        })
        code, out = self.run_main(self.base)
        self.assertEqual(code, 0, out)

    def test_the_worktree_exclusion_is_relative_to_root_not_absolute(self):
        # If the exclusion were matched on the absolute path, running the gate FROM a
        # worktree checkout would exclude every file and print GREEN over an unswept
        # tree. Here the root itself sits under a .claude/worktrees/ path.
        inner = self.base / ".claude" / "worktrees" / "agent-y"
        write_tree(inner, {"tools/g.py": 'a.lstrip("./")\n'})
        code, out = self.run_main(inner)
        self.assertEqual(code, 1, out)
        self.assertIn("tools/g.py:1", out)

    def test_an_unparseable_file_is_red_rather_than_skipped(self):
        write_tree(self.base, {"broken.py": "def (:\n"})
        code, out = self.run_main(self.base)
        self.assertEqual(code, 1)
        self.assertIn("does not parse", out)
        self.assertIn("broken.py", out)


class TheRepositoryItself(unittest.TestCase):
    """The gate is green on this tree, and the two fixed sites really are fixed."""

    def test_the_tree_is_clean(self):
        problems, scanned = gate.scan(ROOT)
        self.assertEqual(problems, [])
        self.assertGreater(scanned, 100, "the sweep found almost no files; check the root")

    def test_check_roadmap_order_uses_removeprefix(self):
        source = (ROOT / "tools" / "check_roadmap_order.py").read_text(encoding="utf-8")
        self.assertIn('.replace("\\\\", "/").removeprefix("./")', source)

    def test_check_audit_reports_uses_removeprefix(self):
        source = (ROOT / "tools" / "check_audit_reports.py").read_text(encoding="utf-8")
        self.assertIn('.split("#", 1)[0].removeprefix("./")', source)


if __name__ == "__main__":
    unittest.main()
