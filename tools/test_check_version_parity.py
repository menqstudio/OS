"""Tests for tools/check_version_parity.py — the desktop app-version parity gate.

Offline and stdlib-only: every test synthesises a whole fake `apps/desktop` tree in a temp dir,
so nothing here depends on the real one. That matters more than usual for this gate — the real
tree is GREEN and has been since the app existed, so a test that read it would pass forever
without exercising a single refusal.

Every test is a single mutation of a GREEN tree, and each names the mutant of the GATE that it
kills, because a test that goes green when its check is deleted is the defect START_HERE.md
counts four of.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_version_parity as vp  # noqa: E402


class VersionParityTests(unittest.TestCase):
    def _tree(self, version: str = "0.1.0") -> pathlib.Path:
        """A repository in which the gate is GREEN. Every test breaks exactly one thing."""
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        root = pathlib.Path(d.name)
        (root / "apps" / "desktop" / "src-tauri").mkdir(parents=True)

        (root / vp.PACKAGE_JSON).write_text(
            json.dumps({"name": "brops", "version": version, "private": True}, indent=2),
            encoding="utf-8",
        )
        (root / vp.TAURI_CONF).write_text(
            json.dumps(
                {"$schema": "../node_modules/@tauri-apps/cli/config.schema.json",
                 "productName": "BroPS", "version": version, "identifier": "studio.menq.brops"},
                indent=2,
            ),
            encoding="utf-8",
        )
        # A manifest shaped like the real one: [workspace] first, then [package], then a
        # [build-dependencies] table that ALSO carries a key spelled `version`.
        (root / vp.CARGO_TOML).write_text(
            '[workspace]\n'
            'members = ["core"]\n'
            '\n'
            '[package]\n'
            'name = "brops"\n'
            f'version = "{version}"\n'
            'edition = "2021"\n'
            '\n'
            '[build-dependencies]\n'
            'tauri-build = { version = "2", features = [] }\n',
            encoding="utf-8",
        )
        (root / vp.PACKAGE_LOCK).write_text(
            json.dumps(
                {"name": "brops", "version": version, "lockfileVersion": 3,
                 "packages": {"": {"name": "brops", "version": version}}},
                indent=2,
            ),
            encoding="utf-8",
        )
        return root

    def _set_json(self, root: pathlib.Path, rel: str, mutate) -> None:
        path = root / rel
        doc = json.loads(path.read_text(encoding="utf-8"))
        mutate(doc)
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    # --- the tree the mutations start from -----------------------------------------------
    def test_a_tree_where_every_declaration_agrees_is_green(self):
        self.assertEqual(vp.check(self._tree()), [])

    def test_the_green_tree_reads_all_five_declarations(self):
        """If a source silently failed to parse, every disagreement test below would still
        pass — on four sources instead of five — and the gate would be weaker than its tests
        claim. So the population is asserted, not assumed."""
        problems: list[str] = []
        found = vp.declared_versions(self._tree(), problems)
        self.assertEqual(problems, [])
        self.assertEqual(sorted(found), [
            f'{vp.PACKAGE_LOCK} .packages[""].version',
            f"{vp.PACKAGE_LOCK} .version",
            f"{vp.PACKAGE_JSON} .version",
            f"{vp.CARGO_TOML} [package] version",
            f"{vp.TAURI_CONF} .version",
        ])
        self.assertEqual(set(found.values()), {"0.1.0"})

    # --- the whole point: a disagreement is RED and NAMES the file --------------------------
    def test_package_json_alone_disagreeing_is_red_and_names_it(self):
        """Mutant: drop the `len(distinct) > 1` arm ⇒ green."""
        root = self._tree()
        self._set_json(root, vp.PACKAGE_JSON, lambda d: d.update(version="0.2.0"))
        problems = vp.check(root)
        self.assertTrue(problems, "a disagreement must be RED")
        self.assertTrue(any(vp.PACKAGE_JSON in p for p in problems), problems)
        self.assertTrue(any("'0.2.0'" in p for p in problems), problems)
        self.assertTrue(any("'0.1.0'" in p for p in problems), problems)

    def test_tauri_conf_alone_disagreeing_is_red_and_names_it(self):
        """The installer's version is the one a user sees; it must be nameable on its own."""
        root = self._tree()
        self._set_json(root, vp.TAURI_CONF, lambda d: d.update(version="1.0.0"))
        problems = vp.check(root)
        # Exactly one problem, and its SUBJECT is the file that disagrees. The other four are
        # named inside it as the majority it disagrees with, which is a different role: a
        # message that accused all five would tell a reader nothing about where to look.
        self.assertEqual(len(problems), 1, problems)
        self.assertTrue(problems[0].startswith(f"{vp.TAURI_CONF} .version says '1.0.0'"), problems)

    def test_cargo_toml_alone_disagreeing_is_red_and_names_it(self):
        root = self._tree()
        path = root / vp.CARGO_TOML
        path.write_text(path.read_text(encoding="utf-8").replace(
            'version = "0.1.0"', 'version = "0.3.1"'), encoding="utf-8")
        problems = vp.check(root)
        self.assertTrue(any(vp.CARGO_TOML in p and "'0.3.1'" in p for p in problems), problems)

    def test_the_lockfile_alone_disagreeing_is_red(self):
        """`npm ci` does not catch this — measured, and written into the gate's docstring:
        a probe with package.json at 9.9.9 and its lock at 0.1.0 exited 0."""
        root = self._tree()
        self._set_json(root, vp.PACKAGE_LOCK, lambda d: d["packages"][""].update(version="0.9.0"))
        problems = vp.check(root)
        self.assertTrue(any('packages[""].version' in p and "'0.9.0'" in p for p in problems),
                        problems)

    def test_the_message_reports_against_the_majority_not_the_first_file(self):
        """Three files bumped and one forgotten is the realistic drift, and the message has to
        accuse the ONE, not the three. Mutant: report against an arbitrary element of `distinct`
        ⇒ this goes red about half the time, which is why the tie-break is deterministic."""
        root = self._tree("0.2.0")
        self._set_json(root, vp.CARGO_TOML.replace(vp.CARGO_TOML, vp.PACKAGE_JSON),
                       lambda d: d.update(version="0.2.0"))
        path = root / vp.CARGO_TOML
        path.write_text(path.read_text(encoding="utf-8").replace(
            'version = "0.2.0"', 'version = "0.1.0"'), encoding="utf-8")
        problems = vp.check(root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn(vp.CARGO_TOML, problems[0])
        self.assertIn("'0.1.0'", problems[0])
        self.assertIn("'0.2.0'", problems[0])

    def test_two_runs_on_the_same_broken_tree_print_the_same_thing(self):
        """A verdict that changes between runs on an unchanged tree teaches a reader to skim it."""
        root = self._tree()
        self._set_json(root, vp.PACKAGE_JSON, lambda d: d.update(version="2.0.0"))
        self._set_json(root, vp.TAURI_CONF, lambda d: d.update(version="3.0.0"))
        self.assertEqual(vp.check(root), vp.check(root))

    # --- the Cargo manifest is read from the RIGHT table ------------------------------------
    def test_the_build_dependency_version_is_not_mistaken_for_the_package_version(self):
        """`[build-dependencies] tauri-build = { version = "2" }` is in every real manifest here.
        Mutant: anchor the regex to `version` alone instead of the [package] table ⇒ the gate
        reads "2" and reports four sources disagreeing with a version nobody wrote."""
        root = self._tree()
        problems: list[str] = []
        found = vp.declared_versions(root, problems)
        self.assertEqual(found[f"{vp.CARGO_TOML} [package] version"], "0.1.0")
        self.assertEqual(problems, [])

    def test_a_cargo_manifest_with_no_package_version_is_red(self):
        """Mutant: treat a missing [package] version as "agrees" ⇒ green, and CARGO_PKG_VERSION
        would compile nothing into the host binary."""
        root = self._tree()
        path = root / vp.CARGO_TOML
        path.write_text(path.read_text(encoding="utf-8").replace('version = "0.1.0"\n', ""),
                        encoding="utf-8")
        problems = vp.check(root)
        self.assertTrue(any("[package] table" in p for p in problems), problems)

    # --- absence is not agreement ------------------------------------------------------------
    def test_a_missing_file_is_red_rather_than_silently_skipped(self):
        """Mutant: `return {}` instead of appending a problem when a file is absent ⇒ green on a
        tree with no tauri.conf.json at all. A file that is not there does not agree with anything."""
        root = self._tree()
        (root / vp.TAURI_CONF).unlink()
        problems = vp.check(root)
        self.assertTrue(any(vp.TAURI_CONF in p and "missing" in p for p in problems), problems)

    def test_tauri_conf_without_a_version_field_is_red_and_says_why(self):
        """Tauri's documented fallback to Cargo.toml is legal and is the real remedy — but
        arriving at it by DELETING the field is an accident, not a decision. Mutant: accept the
        absence ⇒ green, and the bundle's version silently changes source."""
        root = self._tree()
        self._set_json(root, vp.TAURI_CONF, lambda d: d.pop("version"))
        problems = vp.check(root)
        self.assertTrue(any(vp.TAURI_CONF in p for p in problems), problems)
        self.assertTrue(any("fall back" in p for p in problems), problems)

    def test_unparseable_json_is_red_not_an_exception(self):
        root = self._tree()
        (root / vp.PACKAGE_JSON).write_text("{ not json", encoding="utf-8")
        problems = vp.check(root)
        self.assertTrue(any("does not parse" in p for p in problems), problems)

    # --- the shape of the string --------------------------------------------------------------
    def test_a_prerelease_suffix_is_red_on_every_source(self):
        """Mutant: drop the `_SEMVER_CORE` arm ⇒ green. The MSI product version and
        CFBundleShortVersionString are numeric triples; the bundler rewrites a suffix, so the
        sources stop meaning one thing again while agreeing byte-for-byte."""
        root = self._tree("0.2.0-rc.1")
        problems = vp.check(root)
        self.assertEqual(len(problems), 5, problems)
        self.assertTrue(all("MAJOR.MINOR.PATCH" in p for p in problems), problems)

    def test_a_four_component_version_is_red(self):
        root = self._tree("0.1.0.4")
        self.assertTrue(any("MAJOR.MINOR.PATCH" in p for p in vp.check(root)), vp.check(root))

    def test_a_two_component_version_is_red(self):
        root = self._tree("1.0")
        self.assertTrue(any("MAJOR.MINOR.PATCH" in p for p in vp.check(root)), vp.check(root))

    def test_a_multi_digit_version_is_green(self):
        """The shape check must not become a version-number opinion: 12.30.400 is fine."""
        self.assertEqual(vp.check(self._tree("12.30.400")), [])

    # --- exit codes --------------------------------------------------------------------------
    def test_main_returns_zero_on_a_green_tree(self):
        self.assertEqual(vp.main(["--root", str(self._tree())]), 0)

    def test_main_returns_one_on_a_disagreeing_tree(self):
        root = self._tree()
        self._set_json(root, vp.PACKAGE_JSON, lambda d: d.update(version="0.4.0"))
        self.assertEqual(vp.main(["--root", str(root)]), 1)

    # --- the real repository -------------------------------------------------------------------
    def test_the_real_repository_is_green(self):
        """The invariant this gate was written to hold is TRUE at this head — the point was
        that nothing held it. If this goes red, the tree drifted, not the test."""
        self.assertEqual(vp.check(pathlib.Path(__file__).resolve().parents[1]), [])


if __name__ == "__main__":
    unittest.main()
