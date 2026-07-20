import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_analytics import AnalyticsError, validate_analytics


class AnalyticsTests(unittest.TestCase):
    def test_analytics_catalogs_are_valid(self):
        result = validate_analytics(ROOT)
        self.assertEqual(result["metrics"], 12)
        self.assertEqual(result["dashboards"], 4)

    def test_unknown_status_is_not_green_by_contract(self):
        import json
        registry = json.loads((ROOT / "analytics" / "registry.json").read_text(encoding="utf-8"))
        self.assertTrue(registry["rules"]["unknown_status_is_not_green"])


if __name__ == "__main__":
    unittest.main()
