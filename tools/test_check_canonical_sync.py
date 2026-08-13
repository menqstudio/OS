"""Self-tests for the canonical update law.

A gate is only worth its GREEN if it is proven to go RED. These drive `check()`
against literal changed-file lists -- no git, because the law is a function of
"what changed", and taking that as data is what makes it testable at all three
points it runs (pre-commit, CI, here).
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from check_canonical_sync import LAW, check, load_law

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

_LAW = {
    "schema": 1,
    "substantive_globs": ["engine/*", "tools/*", "*.rs"],
    "exempt_globs": ["*/tests/*", "tools/test_*"],
    "required_docs": ["NEXT_CHAT.md", "PROJECT_STATE.md", "config/current_state.json"],
}


def _tree(law: dict | None = None) -> pathlib.Path:
    root = pathlib.Path(tempfile.mkdtemp())
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / LAW).write_text(json.dumps(law if law is not None else _LAW), encoding="utf-8")
    return root


class UpdateLawTests(unittest.TestCase):
    def test_code_change_without_the_docs_is_refused(self):
        problems = check(_tree(), ["engine/runtime/bro_policy.py"])
        self.assertEqual(len(problems), 1)
        self.assertIn("NEXT_CHAT.md", problems[0])
        self.assertIn("PROJECT_STATE.md", problems[0])

    def test_code_change_with_every_required_doc_passes(self):
        self.assertEqual(check(_tree(), [
            "engine/runtime/bro_policy.py", "NEXT_CHAT.md", "PROJECT_STATE.md",
            "config/current_state.json",
        ]), [])

    def test_any_one_doc_is_not_enough(self):
        """The whole point of this gate over the existing PR-level check: ALL, not ANY."""
        problems = check(_tree(), ["engine/runtime/bro_policy.py", "PROJECT_STATE.md"])
        self.assertEqual(len(problems), 1)
        # The "does not update [...]" list is the missing set; the doc that WAS
        # touched must not be in it (it still appears later, in the full roll-call).
        missing = problems[0].split("does not update ")[1].split("] in the same commit")[0]
        self.assertIn("NEXT_CHAT.md", missing)
        self.assertIn("config/current_state.json", missing)
        self.assertNotIn("PROJECT_STATE.md", missing)

    def test_docs_only_change_is_lawful(self):
        self.assertEqual(check(_tree(), ["README.md"]), [])

    def test_empty_change_is_lawful(self):
        self.assertEqual(check(_tree(), []), [])

    def test_exempt_paths_do_not_trigger_the_law(self):
        self.assertEqual(check(_tree(), ["engine/tests/test_x.py", "tools/test_check_x.py"]), [])

    def test_globs_match_at_any_depth(self):
        self.assertTrue(check(_tree(), ["apps/desktop/src-tauri/src/lib.rs"]))

    def test_windows_separators_are_normalised(self):
        self.assertTrue(check(_tree(), ["engine\\runtime\\x.py"]))
        self.assertEqual(check(_tree(), [
            "engine\\runtime\\x.py", "NEXT_CHAT.md", "PROJECT_STATE.md",
            "config/current_state.json"]), [])

    def test_empty_required_docs_is_refused_rather_than_vacuously_green(self):
        law = dict(_LAW, required_docs=[])
        with self.assertRaises(ValueError):
            load_law(_tree(law))

    def test_malformed_law_is_refused(self):
        law = dict(_LAW, substantive_globs="engine/*")
        with self.assertRaises(ValueError):
            load_law(_tree(law))

    def test_the_real_repository_law_file_loads(self):
        law = load_law(REPO_ROOT)
        self.assertIn("NEXT_CHAT.md", law["required_docs"])
        self.assertIn("config/current_state.json", law["required_docs"])

    def test_the_real_law_refuses_an_engine_only_commit(self):
        self.assertTrue(check(REPO_ROOT, ["engine/runtime/bro_policy.py"]))


if __name__ == "__main__":
    unittest.main()
