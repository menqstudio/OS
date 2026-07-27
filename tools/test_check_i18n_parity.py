"""Tests for tools/check_i18n_parity.py — the en/hy/ru key-parity gate.

Two layers:
  * pure-function tests (offline, no repo) prove that divergence / duplicates / parse
    failures are RED and that an exact match is GREEN;
  * a real-file test proves the checked-in dictionaries are actually in parity, so a
    contributor who adds a key to en.ts but forgets hy.ts/ru.ts fails CI.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_i18n_parity as ip  # noqa: E402


class ExtractKeysTests(unittest.TestCase):
    def test_extracts_keys_in_order(self):
        src = (
            "export const en = {\n"
            "  'app.name': 'BroPS',\n"
            "  'app.tagline': \"Bro's Personal Space\",\n"
            "  'state.loading': 'Loading…',\n"
            "} as const;\n"
        )
        self.assertEqual(ip.extract_keys(src), ["app.name", "app.tagline", "state.loading"])

    def test_value_with_colon_is_not_a_key(self):
        # a value containing ": " must not be mistaken for a key (key is anchored to line start).
        src = "  'top.search': 'Search or: press K',\n"
        self.assertEqual(ip.extract_keys(src), ["top.search"])

    def test_type_and_wrapper_lines_ignored(self):
        src = (
            "import type { DictKey } from './en';\n"
            "export const hy: Record<DictKey, string> = {\n"
            "  'nav.home': 'Գլխավոր',\n"
            "};\n"
            "export type DictKey = keyof typeof en;\n"
        )
        self.assertEqual(ip.extract_keys(src), ["nav.home"])


class ParityTests(unittest.TestCase):
    def _equal(self):
        keys = ["a", "b", "c"]
        return {"en": list(keys), "hy": list(keys), "ru": list(keys)}

    def test_equal_sets_pass(self):
        self.assertEqual(ip.parity_failures(self._equal()), [])

    def test_missing_key_in_hy_fails(self):
        ks = self._equal(); ks["hy"] = ["a", "b"]
        f = ip.parity_failures(ks)
        self.assertTrue(any("hy" in p and "missing key 'c'" in p for p in f))

    def test_extra_key_in_ru_fails(self):
        ks = self._equal(); ks["ru"] = ["a", "b", "c", "d"]
        f = ip.parity_failures(ks)
        self.assertTrue(any("ru" in p and "extra key 'd'" in p for p in f))

    def test_key_only_in_en_flagged_for_both_others(self):
        # the exact drift this gate exists to catch: en gains 'state.loadFailed' alone.
        ks = {"en": ["a", "state.loadFailed"], "hy": ["a"], "ru": ["a"]}
        f = ip.parity_failures(ks)
        self.assertTrue(any("hy" in p and "state.loadFailed" in p for p in f))
        self.assertTrue(any("ru" in p and "state.loadFailed" in p for p in f))

    def test_duplicate_key_fails(self):
        ks = self._equal(); ks["en"] = ["a", "b", "b", "c"]
        f = ip.parity_failures(ks)
        self.assertTrue(any("duplicate key 'b'" in p for p in f))

    def test_empty_language_fails_closed(self):
        ks = self._equal(); ks["ru"] = []
        f = ip.parity_failures(ks)
        self.assertTrue(any("ru" in p and "no keys parsed" in p for p in f))


class RealFileParityTests(unittest.TestCase):
    """The checked-in dictionaries must be in parity right now."""
    def test_repo_dictionaries_are_in_parity(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        keysets = ip.load_keysets(root)
        self.assertEqual(ip.parity_failures(keysets), [])


if __name__ == "__main__":
    unittest.main()
