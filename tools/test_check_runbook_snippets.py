"""Self-tests for the runbook-snippet gate.

The gate exists because a `python3 -c` snippet in docs/DEBIAN_DEPLOYMENT.md called a function with
the wrong number of arguments and nobody noticed until it failed on a real Debian box, halfway
through a step that had already mounted something. These tests are the mutations that finding
implies, run against fixtures rather than against the live doc.

Two of them guard the gate's own first version, which was wrong in both directions: it matched
snippet text only up to end-of-line (so anything inside a `$(...)` substitution was reported as a
syntax error that did not exist), and an earlier hand-written matcher required a `bp.` prefix, so
it silently examined three of five calls and printed GREEN. A checker that under-reports is more
dangerous than no checker, because it is believed.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_runbook_snippets as gate  # noqa: E402


def doc(body: str) -> pathlib.Path:
    """A throwaway markdown file containing one bash block."""
    tmp = pathlib.Path(tempfile.mkdtemp()) / "runbook.md"
    tmp.write_text("```bash\n" + body + "\n```\n", encoding="utf-8")
    return tmp


class SnippetGate(unittest.TestCase):

    def problems(self, body: str) -> list[str]:
        return gate.check(doc(body))

    # ---------------------------------------------------------------- the shape it must accept
    def test_correct_call_passes(self):
        self.assertEqual([], self.problems(
            'python3 -c "\n'
            'import pathlib\n'
            'import bro_protected as bp\n'
            "root = pathlib.Path('/opt/brops/engine')\n"
            'manifest = bp.load_protected_manifest(root)\n'
            'bp.assert_no_bytecode_shadow(root, manifest)\n'
            '"'))

    def test_from_import_form_is_resolved(self):
        """`from bro_protected import X` then a bare `X(...)` must still be checked."""
        problems = self.problems(
            'python3 -c "\n'
            'from bro_protected import assert_no_bytecode_shadow\n'
            'assert_no_bytecode_shadow(1)\n'
            '"')
        self.assertTrue(any("assert_no_bytecode_shadow" in p for p in problems), problems)

    def test_snippet_inside_command_substitution_is_parsed(self):
        """Regression: the first matcher anchored on end-of-line and mangled this into a
        syntax error, blaming the runbook for a defect in the gate."""
        self.assertEqual([], self.problems(
            'export KEY=$(python3 -c "import json; print(json.load(open(\'k.json\'))[\'public_key\'])")'))

    def test_calls_into_modules_we_do_not_own_are_ignored(self):
        self.assertEqual([], self.problems(
            'python3 -c "import json; json.load(1, 2, 3, 4, 5)"'))

    # ---------------------------------------------------------------- the mutations it must catch
    def test_missing_required_argument(self):
        problems = self.problems(
            'python3 -c "\n'
            'import bro_protected as bp\n'
            'bp.assert_no_bytecode_shadow(root)\n'
            '"')
        self.assertTrue(any("needs 2" in p for p in problems), problems)

    def test_too_many_positional_arguments(self):
        problems = self.problems(
            'python3 -c "\n'
            'import bro_protected as bp\n'
            'bp.assert_no_bytecode_shadow(root, manifest, True)\n'
            '"')
        self.assertTrue(any("at most" in p for p in problems), problems)

    def test_function_that_does_not_exist(self):
        problems = self.problems(
            'python3 -c "\n'
            'import bro_protected as bp\n'
            'bp.load_protected_manifets(root)\n'
            '"')
        self.assertTrue(any("has no load_protected_manifets" in p for p in problems), problems)

    def test_snippet_that_does_not_parse(self):
        problems = self.problems(
            'python3 -c "\n'
            'import bro_protected as bp\n'
            'bp.load_protected_manifest(root\n'
            '"')
        self.assertTrue(any("does not parse" in p for p in problems), problems)

    # ---------------------------------------------------------------- and it must see EVERY call
    def test_every_snippet_in_a_block_is_examined_not_just_the_first(self):
        problems = self.problems(
            'python3 -c "import bro_protected as bp; bp.assert_no_bytecode_shadow(1, 2)"\n'
            'python3 -c "import bro_protected as bp; bp.assert_no_bytecode_shadow(1)"')
        self.assertEqual(1, len(problems), problems)

    def test_a_missing_listed_doc_is_a_failure_not_a_skip(self):
        """A gate that quietly passes when its input vanished is the failure mode this
        repository has spent a week removing."""
        original = gate.DOCS
        try:
            gate.DOCS = ("docs/a-file-that-does-not-exist.md",)
            self.assertEqual(1, gate.main())
        finally:
            gate.DOCS = original

    def test_the_real_runbooks_pass(self):
        self.assertEqual(0, gate.main())


if __name__ == "__main__":
    unittest.main()
