"""Self-tests for the prior-art rule.

A gate is only worth its GREEN if it is proven to go RED. These cover exactly the
mechanical parts and no more: an undeclared new file, an empty declaration, a name
collision the declaration never mentions, and a new gate reading an existing gate's
inputs. The judgement -- "is this really a duplicate?" -- is recorded, never
decided, and there is deliberately no test asserting the gate can tell.
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest

import check_prior_art as prior_art
import check_read_receipt as receipts

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SEARCHED = "grepped tools/ for check_*, listed config/, read docs/ARCHITECTURE.md"
DECISION_NEW = "new: nothing in the tree reads the canonical read manifest for a session receipt"


def _tree(files: dict[str, str] | None = None) -> pathlib.Path:
    root = pathlib.Path(tempfile.mkdtemp()) / "repo"
    (root / "config").mkdir(parents=True)
    (root / receipts.MANIFEST).write_text(json.dumps({"paths": ["A.md"]}), encoding="utf-8")
    (root / "A.md").write_text("canon\n", encoding="utf-8")
    for name, text in (files or {}).items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


class PriorArtTests(unittest.TestCase):
    def setUp(self):
        self.store = pathlib.Path(tempfile.mkdtemp())
        os.environ["BRO_RECEIPT_DIR"] = str(self.store)
        self.addCleanup(os.environ.pop, "BRO_RECEIPT_DIR", None)

    def test_an_undeclared_new_file_is_refused(self):
        root = _tree()
        receipts.record(root, "s1")
        ok, why = prior_art.verify(root, "s1", "tools/new_thing.py")
        self.assertFalse(ok)
        self.assertIn("recorded no prior-art search", why)
        self.assertIn("--declare", why)

    def test_a_recorded_search_permits_the_new_file(self):
        root = _tree()
        receipts.record(root, "s1")
        self.assertTrue(prior_art.declare(
            root, "s1", "tools/new_thing.py", SEARCHED, "nothing", DECISION_NEW)[0])
        ok, why = prior_art.verify(root, "s1", "tools/new_thing.py")
        self.assertTrue(ok, why)

    def test_a_declaration_without_a_real_search_is_refused(self):
        root = _tree()
        receipts.record(root, "s1")
        ok, why = prior_art.declare(root, "s1", "tools/x.py", "looked", "", DECISION_NEW)
        self.assertFalse(ok)
        self.assertIn("--searched", why)

    def test_a_decision_must_be_extend_or_new(self):
        root = _tree()
        receipts.record(root, "s1")
        ok, why = prior_art.declare(root, "s1", "tools/x.py", SEARCHED, "", "seems fine to me")
        self.assertFalse(ok)
        self.assertIn("'extend:' or 'new:'", why)

    def test_a_bare_new_with_no_justification_is_refused(self):
        root = _tree()
        receipts.record(root, "s1")
        ok, why = prior_art.declare(root, "s1", "tools/x.py", SEARCHED, "", "new: because")
        self.assertFalse(ok)
        self.assertIn("real justification", why)

    def test_a_name_collision_the_declaration_ignores_is_refused(self):
        """The provision_custody case, reduced to something a machine can see."""
        root = _tree({"apps/desktop/src-tauri/win-live/src/provision_custody.rs": "// exists\n"})
        receipts.record(root, "s1")
        prior_art.declare(root, "s1", "engine/runtime/provision_custody.py",
                          SEARCHED, "nothing", DECISION_NEW)
        ok, why = prior_art.verify(root, "s1", "engine/runtime/provision_custody.py")
        self.assertFalse(ok)
        self.assertIn("collides by name", why)
        self.assertIn("provision_custody.rs", why)

    def test_naming_the_collision_clears_it(self):
        root = _tree({"apps/desktop/src-tauri/win-live/src/provision_custody.rs": "// exists\n"})
        receipts.record(root, "s1")
        prior_art.declare(
            root, "s1", "engine/runtime/provision_custody.py", SEARCHED,
            "apps/desktop/src-tauri/win-live/src/provision_custody.rs builds the DACL on Windows",
            "new: the POSIX side has no equivalent and the Rust one cannot be called from python")
        ok, why = prior_art.verify(root, "s1", "engine/runtime/provision_custody.py")
        self.assertTrue(ok, why)

    def test_a_new_gate_over_an_existing_gates_inputs_is_refused(self):
        root = _tree({
            "tools/check_old.py": "PATH = 'config/current_state.json'\nDOC = 'docs/design/x.md'\n",
            "tools/check_new.py": "SAME = 'config/current_state.json'\n",
        })
        receipts.record(root, "s1")
        prior_art.declare(root, "s1", "tools/check_new.py", SEARCHED, "nothing", DECISION_NEW)
        ok, why = prior_art.verify(root, "s1", "tools/check_new.py")
        self.assertFalse(ok)
        self.assertIn("check_old.py", why)
        self.assertIn("same inputs", why)

    def test_naming_the_overlapping_gate_clears_it(self):
        root = _tree({
            "tools/check_old.py": "PATH = 'config/current_state.json'\n",
            "tools/check_new.py": "SAME = 'config/current_state.json'\n",
        })
        receipts.record(root, "s1")
        prior_art.declare(
            root, "s1", "tools/check_new.py", SEARCHED,
            "tools/check_old.py reads the same file but validates a different property",
            "new: check_old validates structure, this validates freshness against a receipt")
        self.assertTrue(prior_art.verify(root, "s1", "tools/check_new.py")[0])

    def test_a_declaration_needs_a_valid_read_receipt(self):
        root = _tree()
        ok, why = prior_art.declare(root, "s1", "tools/x.py", SEARCHED, "", DECISION_NEW)
        self.assertFalse(ok)
        self.assertIn("no full-read receipt", why)

    def test_declarations_are_per_target(self):
        root = _tree()
        receipts.record(root, "s1")
        prior_art.declare(root, "s1", "tools/a.py", SEARCHED, "", DECISION_NEW)
        self.assertTrue(prior_art.verify(root, "s1", "tools/a.py")[0])
        self.assertFalse(prior_art.verify(root, "s1", "tools/b.py")[0])

    def test_the_real_repository_gate_overlap_scan_runs(self):
        overlaps = prior_art.gate_overlaps(REPO_ROOT, "tools/check_canonical_sync.py")
        self.assertIsInstance(overlaps, dict)


if __name__ == "__main__":
    unittest.main()
