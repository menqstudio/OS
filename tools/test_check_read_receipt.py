"""Self-tests for the canonical full-read receipt.

A gate is only worth its GREEN if it is proven to go RED. These drive the receipt
against every way a session could hold a proof it has not earned: a receipt for a
document that has since changed, one recorded against a different tree, one whose
manifest was redefined underneath it, one whose digest was hand-edited, and one
stored where it could be committed and inherited.
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest

import check_read_receipt as receipts

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _tree(paths=("A.md", "B.md"), extra_manifest=()) -> pathlib.Path:
    root = pathlib.Path(tempfile.mkdtemp()) / "repo"
    (root / "config").mkdir(parents=True)
    for name in paths:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"content of {name}\n", encoding="utf-8")
    (root / receipts.MANIFEST).write_text(
        json.dumps({"paths": list(paths) + list(extra_manifest)}), encoding="utf-8")
    return root


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.store = pathlib.Path(tempfile.mkdtemp())
        os.environ["BRO_RECEIPT_DIR"] = str(self.store)
        self.addCleanup(os.environ.pop, "BRO_RECEIPT_DIR", None)

    def test_no_receipt_is_red(self):
        ok, why = receipts.verify(_tree(), "s1")
        self.assertFalse(ok)
        self.assertIn("no full-read receipt", why)

    def test_recorded_receipt_verifies(self):
        root = _tree()
        receipts.record(root, "s1")
        ok, why = receipts.verify(root, "s1")
        self.assertTrue(ok, why)

    def test_a_changed_canonical_file_voids_the_receipt(self):
        """The whole point: the digest, not the filename list."""
        root = _tree()
        receipts.record(root, "s1")
        (root / "B.md").write_text("edited\n", encoding="utf-8")
        ok, why = receipts.verify(root, "s1")
        self.assertFalse(ok)
        self.assertIn("B.md", why)
        self.assertIn("changed after the full-read receipt", why)

    def test_a_touched_but_identical_file_does_not_void_it(self):
        """Content-bound, not mtime-bound: rewriting the same bytes is not a change."""
        root = _tree()
        receipts.record(root, "s1")
        (root / "B.md").write_text("content of B.md\n", encoding="utf-8")
        self.assertTrue(receipts.verify(root, "s1")[0])

    def test_redefining_the_manifest_voids_the_receipt(self):
        root = _tree()
        receipts.record(root, "s1")
        (root / receipts.MANIFEST).write_text(json.dumps({"paths": ["A.md"]}), encoding="utf-8")
        ok, why = receipts.verify(root, "s1")
        self.assertFalse(ok)
        self.assertIn("canonical set itself was redefined", why)

    def test_a_new_canonical_file_is_not_covered(self):
        """Manifest hash equal but a path added would be a hole; the manifest hash
        catches it, and so does the per-path set comparison if it ever did not."""
        root = _tree()
        receipts.record(root, "s1")
        document = receipts.load(root, "s1")
        document["manifest_sha256"] = receipts.sha256_file(root / receipts.MANIFEST)
        del document["paths"]["B.md"]
        receipts.write_receipt(root, "s1", document)
        ok, why = receipts.verify(root, "s1")
        self.assertFalse(ok)
        self.assertIn("not covered by the receipt", why)

    def test_a_receipt_from_another_repository_is_refused(self):
        root_a, root_b = _tree(), _tree()
        receipts.record(root_a, "s1")
        document = receipts.load(root_a, "s1")
        document["repo_root"] = str(root_b.resolve())
        receipts.write_receipt(root_a, "s1", document)
        ok, why = receipts.verify(root_a, "s1")
        self.assertFalse(ok)
        self.assertIn("different repository root", why)

    def test_a_hand_edited_digest_is_refused(self):
        root = _tree()
        receipts.record(root, "s1")
        document = receipts.load(root, "s1")
        document["canonical_digest"] = "0" * 64
        receipts.write_receipt(root, "s1", document)
        ok, why = receipts.verify(root, "s1")
        self.assertFalse(ok)
        self.assertIn("does not match its own hashes", why)

    def test_receipts_are_per_session(self):
        root = _tree()
        receipts.record(root, "s1")
        self.assertTrue(receipts.verify(root, "s1")[0])
        self.assertFalse(receipts.verify(root, "s2")[0])

    def test_a_missing_canonical_file_cannot_be_recorded(self):
        root = _tree(extra_manifest=("GONE.md",))
        with self.assertRaises(receipts.ReceiptError) as caught:
            receipts.record(root, "s1")
        self.assertIn("GONE.md", str(caught.exception))

    def test_a_receipt_store_inside_the_repository_is_refused(self):
        """A committed receipt is a reusable one -- the next clone would inherit a
        proof it never earned."""
        root = _tree()
        os.environ["BRO_RECEIPT_DIR"] = str(root / ".receipts")
        with self.assertRaises(receipts.ReceiptError) as caught:
            receipts.receipt_dir(root)
        self.assertIn("inside the repository", str(caught.exception))

    def test_declarations_survive_a_refresh(self):
        """Re-reading changed documents must not wipe what the session declared."""
        root = _tree()
        receipts.record(root, "s1")
        document = receipts.load(root, "s1")
        document["declared_phase"] = 3
        document["prior_art"] = [{"target": "x.py"}]
        receipts.write_receipt(root, "s1", document)
        (root / "B.md").write_text("edited\n", encoding="utf-8")
        refreshed = receipts.record(root, "s1")
        self.assertEqual(refreshed["declared_phase"], 3)
        self.assertEqual(refreshed["prior_art"], [{"target": "x.py"}])

    def test_the_real_repository_canonical_set_hashes(self):
        hashes = receipts.canonical_hashes(REPO_ROOT)
        self.assertEqual(len(hashes), len(receipts.manifest_paths(REPO_ROOT)))
        self.assertIn("MASTER_EXECUTION_ROADMAP.md", hashes)


if __name__ == "__main__":
    unittest.main()
