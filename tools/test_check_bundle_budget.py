"""Tests for tools/check_bundle_budget.py — the bundle-size performance-budget gate.

Offline and stdlib-only: each test synthesises a fake `apps/desktop` tree (budget +
Vite manifest + built asset bytes) in a temp dir, so no real Vite build is needed.
"""
from __future__ import annotations

import gzip
import json
import os
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


class FreshnessTests(unittest.TestCase):
    """The gate must refuse to grade a build older than the tree — ninth audit `I-12`.

    The finding is a measurement, not a theory: the gate reported GREEN at 151.6 KB against a
    `dist/` built BEFORE the deletion whose effect it was being cited to prove, then GREEN again
    at 133.0 KB after a rebuild of the identical tree. Two numbers, one source, both "GREEN".
    """

    def _tree(self, source_offset: float):
        """A complete fake desktop tree; `source_offset` seconds are added to the source mtime."""
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        root = pathlib.Path(d.name)
        desktop, dist = root / cb.DESKTOP, root / cb.DIST
        (dist / "assets").mkdir(parents=True, exist_ok=True)
        (dist / ".vite").mkdir(parents=True, exist_ok=True)
        (desktop / "src" / "features").mkdir(parents=True, exist_ok=True)
        js = _bytes_for_gzip_kb(10)
        (dist / "assets" / "index-abc123.js").write_bytes(js)
        manifest = {"index.html": {"file": "assets/index-abc123.js", "name": "index",
                                   "src": "index.html", "isEntry": True}}
        mpath = dist / ".vite" / "manifest.json"
        mpath.write_text(json.dumps(manifest), encoding="utf-8")
        (desktop / "perf-budget.json").write_text(
            json.dumps({"entries": {"index": {"max_gzip_kb": 500}}}), encoding="utf-8")
        base = mpath.stat().st_mtime
        for name in ("src/features/Home.tsx", "index.html", "vite.config.ts", "package.json"):
            p = desktop / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x", encoding="utf-8")
            os.utime(p, (base + source_offset, base + source_offset))
        return root, desktop, mpath, base

    def test_a_source_newer_than_the_manifest_is_red(self):
        root, _, _, _ = self._tree(source_offset=60)
        problems = cb.check(root)
        self.assertTrue(problems, "a stale build must not be graded")
        self.assertTrue(problems[0].startswith("the build is stale"), problems)

    def test_a_build_newer_than_every_source_is_green(self):
        root, _, _, _ = self._tree(source_offset=-60)
        self.assertEqual(cb.check(root), [])

    def test_editing_a_test_file_does_not_make_the_build_stale(self):
        # A gate that reds when a `.test.tsx` is touched gets switched off within a week, and it
        # would be wrong: no test file is in the bundle it measures.
        root, desktop, mpath, base = self._tree(source_offset=-60)
        for name in ("src/features/Home.test.tsx", "src/features/Home.spec.ts", "src/notes.md"):
            p = desktop / name
            p.write_text("x", encoding="utf-8")
            os.utime(p, (base + 600, base + 600))
        self.assertEqual(cb.check(root), [])

    def test_the_staleness_report_names_the_offending_file(self):
        # A refusal a person cannot act on gets worked around; the message has to say WHICH file.
        root, desktop, mpath, base = self._tree(source_offset=-60)
        p = desktop / "src" / "features" / "Late.tsx"
        p.write_text("x", encoding="utf-8")
        os.utime(p, (base + 600, base + 600))
        problems = cb.check(root)
        self.assertEqual(len(problems), 1)
        self.assertIn("Late.tsx", problems[0])

    def test_staleness_is_reported_instead_of_a_size_verdict_not_beside_it(self):
        # The point of failing first: a precise-looking KB number next to the wrong tree is the
        # thing that made this finding possible, so a stale build reports ONE problem, not two.
        root, desktop, mpath, base = self._tree(source_offset=60)
        (desktop / "perf-budget.json").write_text(
            json.dumps({"entries": {"index": {"max_gzip_kb": 0.001}}}), encoding="utf-8")
        problems = cb.check(root)
        self.assertEqual(len(problems), 1)
        self.assertNotIn("exceeds", problems[0])


if __name__ == "__main__":
    unittest.main()
