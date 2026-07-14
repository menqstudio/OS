import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class SSTRegistryTests(unittest.TestCase):
    def test_every_domain_has_one_existing_sst_and_validator(self):
        registry = json.loads((ROOT / "config" / "sst-registry.json").read_text(encoding="utf-8"))
        domains = registry["domains"]
        names = [item["domain"] for item in domains]
        sources = [item["sst"] for item in domains]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(sources), len(set(sources)))
        for item in domains:
            self.assertTrue((ROOT / item["sst"]).is_file(), item["sst"])
            self.assertTrue((ROOT / item["validator"]).is_file(), item["validator"])

    def test_duplicate_truth_is_forbidden(self):
        registry = json.loads((ROOT / "config" / "sst-registry.json").read_text(encoding="utf-8"))
        self.assertTrue(registry["duplicate_truth_is_error"])
        self.assertTrue(registry["generated_files_must_declare_source"])


if __name__ == "__main__":
    unittest.main()
