"""Tests for tools/check_bundle_budget.py — the bundle-size performance-budget gate.

Offline and stdlib-only: each test synthesises a fake `apps/desktop` tree (budget +
Vite manifest + built asset bytes) in a temp dir, so no real Vite build is needed.
"""
from __future__ import annotations

import gzip
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_bundle_budget as cb  # noqa: E402


def _bytes_for_gzip_kb(target_kb: float) -> bytes:
    """Return incompressible bytes whose gzip size is ~target_kb.

    Uses a deterministic PRNG stream — random bytes barely compress, so gzip
    length tracks raw length closely, letting a test pin a payload just over or
    under a KB budget.
    """
    import random

    rng = random.Random(1234)
    raw = bytes(rng.randrange(256) for _ in range(int(target_kb * 1024)))
    return raw


class CheckBundleBudgetTests(unittest.TestCase):
    def _tmp(self) -> pathlib.Path:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return pathlib.Path(d.name)

    def _write(
        self,
        root: pathlib.Path,
        budget: dict,
        manifest: dict,
        files: dict[str, bytes],
    ) -> None:
        desktop = root / cb.DESKTOP
        dist = root / cb.DIST
        (dist / ".vite").mkdir(parents=True, exist_ok=True)
        (desktop / "perf-budget.json").write_text(json.dumps(budget, indent=2), encoding="utf-8")
        (dist / ".vite" / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        for rel, data in files.items():
            p = dist / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

    # --- helpers to build a realistic single-entry manifest -------------------
    def _single_entry(self, js: bytes, css: bytes):
        manifest = {
            "index.html": {
                "file": "assets/index-abc123.js",
                "name": "index",
                "src": "index.html",
                "isEntry": True,
                "css": ["assets/index-def456.css"],
            }
        }
        files = {"assets/index-abc123.js": js, "assets/index-def456.css": css}
        return manifest, files

    def _gz(self, data: bytes) -> int:
        return len(gzip.compress(data, compresslevel=9, mtime=0))

    def test_within_budget_is_green(self):
        root = self._tmp()
        js = _bytes_for_gzip_kb(80)
        css = _bytes_for_gzip_kb(5)
        manifest, files = self._single_entry(js, css)
        total_kb = (self._gz(js) + self._gz(css)) / 1024
        budget = {"entries": {"index": {"max_gzip_kb": total_kb + 20}}}
        self._write(root, budget, manifest, files)
        self.assertEqual(cb.check(root), [])

    def test_over_budget_fails(self):
        root = self._tmp()
        js = _bytes_for_gzip_kb(120)
        css = _bytes_for_gzip_kb(5)
        manifest, files = self._single_entry(js, css)
        total_kb = (self._gz(js) + self._gz(css)) / 1024
        budget = {"entries": {"index": {"max_gzip_kb": total_kb - 10}}}
        self._write(root, budget, manifest, files)
        problems = cb.check(root)
        self.assertTrue(any("exceeds budget" in p and "index" in p for p in problems), problems)

    def test_css_counts_toward_entry_payload(self):
        # JS alone fits; JS+CSS blows the budget. Proves CSS is aggregated.
        root = self._tmp()
        js = _bytes_for_gzip_kb(80)
        css = _bytes_for_gzip_kb(30)
        manifest, files = self._single_entry(js, css)
        js_only_kb = self._gz(js) / 1024
        budget = {"entries": {"index": {"max_gzip_kb": js_only_kb + 5}}}
        self._write(root, budget, manifest, files)
        problems = cb.check(root)
        self.assertTrue(any("index" in p and "exceeds budget" in p for p in problems), problems)

    def test_imported_chunk_counts_toward_payload(self):
        # Entry statically imports a shared chunk; the shared chunk's bytes count.
        root = self._tmp()
        entry_js = _bytes_for_gzip_kb(40)
        shared_js = _bytes_for_gzip_kb(60)
        manifest = {
            "index.html": {
                "file": "assets/index-abc.js",
                "name": "index",
                "src": "index.html",
                "isEntry": True,
                "imports": ["_shared-xyz.js"],
            },
            "_shared-xyz.js": {
                "file": "assets/shared-xyz.js",
            },
        }
        files = {"assets/index-abc.js": entry_js, "assets/shared-xyz.js": shared_js}
        entry_only_kb = self._gz(entry_js) / 1024
        budget = {"entries": {"index": {"max_gzip_kb": entry_only_kb + 5}}}
        self._write(root, budget, manifest, files)
        problems = cb.check(root)
        self.assertTrue(any("index" in p and "exceeds budget" in p for p in problems), problems)

    def test_unbudgeted_entry_fails(self):
        root = self._tmp()
        js = _bytes_for_gzip_kb(10)
        css = _bytes_for_gzip_kb(2)
        manifest, files = self._single_entry(js, css)
        budget = {"entries": {"somethingelse": {"max_gzip_kb": 500}}}
        self._write(root, budget, manifest, files)
        problems = cb.check(root)
        self.assertTrue(any("index" in p and "no budget" in p for p in problems), problems)
        self.assertTrue(any("somethingelse" in p and "no such entry" in p for p in problems), problems)

    def test_stale_budget_entry_fails(self):
        root = self._tmp()
        js = _bytes_for_gzip_kb(10)
        css = _bytes_for_gzip_kb(2)
        manifest, files = self._single_entry(js, css)
        budget = {"entries": {"index": {"max_gzip_kb": 500}, "ghost": {"max_gzip_kb": 500}}}
        self._write(root, budget, manifest, files)
        problems = cb.check(root)
        self.assertTrue(any("ghost" in p and "no such entry" in p for p in problems), problems)

    def test_missing_budget_file_raises(self):
        root = self._tmp()
        js = _bytes_for_gzip_kb(10)
        css = _bytes_for_gzip_kb(2)
        manifest, files = self._single_entry(js, css)
        # Write manifest + assets but no perf-budget.json.
        dist = root / cb.DIST
        (dist / ".vite").mkdir(parents=True, exist_ok=True)
        (dist / ".vite" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        for rel, data in files.items():
            p = dist / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        with self.assertRaises(SystemExit):
            cb.check(root)

    def test_missing_manifest_raises(self):
        root = self._tmp()
        desktop = root / cb.DESKTOP
        desktop.mkdir(parents=True, exist_ok=True)
        (desktop / "perf-budget.json").write_text(
            json.dumps({"entries": {"index": {"max_gzip_kb": 100}}}), encoding="utf-8"
        )
        with self.assertRaises(SystemExit):
            cb.check(root)

    def test_malformed_budget_raises(self):
        root = self._tmp()
        js = _bytes_for_gzip_kb(10)
        css = _bytes_for_gzip_kb(2)
        manifest, files = self._single_entry(js, css)
        bad = {"entries": {"index": {"max_gzip_kb": -5}}}
        self._write(root, bad, manifest, files)
        with self.assertRaises(SystemExit):
            cb.check(root)


if __name__ == "__main__":
    unittest.main()
