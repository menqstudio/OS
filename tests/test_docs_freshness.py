import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from bro_docs_freshness import validate_docs


class DocsFreshnessTests(unittest.TestCase):
    def test_every_document_is_registered_and_reviewed(self):
        self.assertGreaterEqual(validate_docs(ROOT), 59)


if __name__ == "__main__":
    unittest.main()
