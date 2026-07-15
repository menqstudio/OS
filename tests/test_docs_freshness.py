import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from bro_docs_freshness import DocsError, validate_docs, validate_manifest_metadata


class DocsFreshnessTests(unittest.TestCase):
    def test_every_document_is_registered_and_reviewed(self):
        self.assertGreaterEqual(validate_docs(ROOT), 61)

    def test_post_pr6_manifest_metadata_is_exact(self):
        data = json.loads(
            (ROOT / "config" / "documentation-manifest.json").read_text(encoding="utf-8")
        )
        validate_manifest_metadata(data)

    def test_pre_pr6_manifest_metadata_is_denied(self):
        data = json.loads(
            (ROOT / "config" / "documentation-manifest.json").read_text(encoding="utf-8")
        )
        data["merged_pr"] = 4
        data["merge_commit"] = "61bf9bc4a42b512926bf848b79a0cac063196993"
        data["status"] = "orchestration-control-room-v1-contracts-merged-runtime-phase2-next"
        with self.assertRaises(DocsError):
            validate_manifest_metadata(data)


if __name__ == "__main__":
    unittest.main()
