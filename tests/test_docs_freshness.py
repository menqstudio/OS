import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from bro_docs_freshness import DocsError, validate_docs, validate_manifest_metadata


class DocsFreshnessTests(unittest.TestCase):
    def test_every_document_is_registered_and_reviewed(self):
        self.assertGreaterEqual(validate_docs(ROOT), 60)

    def test_post_merge_manifest_metadata_is_exact(self):
        data = json.loads(
            (ROOT / "config" / "documentation-manifest.json").read_text(encoding="utf-8")
        )
        validate_manifest_metadata(data)

    def test_pre_pr4_manifest_metadata_is_denied(self):
        data = json.loads(
            (ROOT / "config" / "documentation-manifest.json").read_text(encoding="utf-8")
        )
        data["merged_pr"] = 3
        data["merge_commit"] = "bec6c77f622065ee302acf23d26d4c73329a400a"
        with self.assertRaises(DocsError):
            validate_manifest_metadata(data)


if __name__ == "__main__":
    unittest.main()
