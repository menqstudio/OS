"""The derived session-read manifest follows OS's two read configs and the tracked Markdown."""

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import sync_session_read_manifest as sync  # noqa: E402


def _git(root: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _tree() -> pathlib.Path:
    root = pathlib.Path(tempfile.mkdtemp())
    (root / "config").mkdir()
    (root / "docs" / "deep").mkdir(parents=True)
    (root / "NEXT.md").write_text("# next\n", encoding="utf-8")
    (root / "STATE.json").write_text("{}\n", encoding="utf-8")
    (root / "README.md").write_text("# readme\n", encoding="utf-8")
    (root / "docs" / "GUIDE.md").write_text("# guide\n", encoding="utf-8")
    (root / "docs" / "deep" / "NOTE.MD").write_text("# note\n", encoding="utf-8")
    (root / "docs" / "data.json").write_text("{}\n", encoding="utf-8")
    (root / sync.READ_MANIFEST_REL).write_text(
        json.dumps({"paths": ["NEXT.md", "STATE.json"]}), encoding="utf-8")
    (root / sync.BUDGET_REL).write_text(json.dumps({
        "total_bytes_max": 5000,
        "per_file_bytes": {"NEXT.md": 3000, "STATE.json": 2000},
        "rationale": {"NEXT.md": "A handoff is the head and the next action. It was long once."},
    }), encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    return root


class DeriveTests(unittest.TestCase):
    def setUp(self):
        self.root = _tree()

    def test_the_core_is_the_read_order_with_its_ceilings(self):
        data = sync.derive(self.root)
        self.assertEqual([e["path"] for e in data["core"]], ["NEXT.md", "STATE.json"])
        self.assertEqual([e["bytes_max"] for e in data["core"]], [3000, 2000])
        self.assertEqual(data["total_bytes_max"], 5000)
        self.assertEqual(data["schema_version"], 1)

    def test_why_is_the_first_sentence_of_the_rationale_or_says_where_it_is(self):
        core = sync.derive(self.root)["core"]
        self.assertEqual(core[0]["why"], "A handoff is the head and the next action.")
        self.assertEqual(core[1]["why"], sync.NO_RATIONALE)

    def test_a_long_rationale_is_bounded(self):
        self.assertLessEqual(len(sync.first_sentence("word " * 200)), sync.WHY_MAX)

    def test_areas_hold_every_tracked_markdown_file_outside_the_core_by_directory(self):
        areas = sync.derive(self.root)["areas"]
        self.assertEqual(areas, {
            ".": ["README.md"],
            "docs": ["docs/GUIDE.md"],
            "docs/deep": ["docs/deep/NOTE.MD"],
        })

    def test_an_untracked_markdown_file_is_not_an_area_file(self):
        (self.root / "docs" / "DRAFT.md").write_text("# draft\n", encoding="utf-8")
        self.assertEqual(sync.derive(self.root)["areas"]["docs"], ["docs/GUIDE.md"])

    def test_a_core_file_without_a_ceiling_is_refused(self):
        budget = json.loads((self.root / sync.BUDGET_REL).read_text(encoding="utf-8"))
        del budget["per_file_bytes"]["STATE.json"]
        (self.root / sync.BUDGET_REL).write_text(json.dumps(budget), encoding="utf-8")
        with self.assertRaises(sync.Refusal) as caught:
            sync.derive(self.root)
        self.assertIn("STATE.json", str(caught.exception))

    def test_a_total_that_is_not_a_positive_integer_is_refused(self):
        for bad in (0, -1, True, "5000", None):
            with self.subTest(total=bad):
                budget = json.loads((self.root / sync.BUDGET_REL).read_text(encoding="utf-8"))
                budget["total_bytes_max"] = bad
                (self.root / sync.BUDGET_REL).write_text(json.dumps(budget), encoding="utf-8")
                with self.assertRaises(sync.Refusal):
                    sync.derive(self.root)


class CheckAndWriteTests(unittest.TestCase):
    def setUp(self):
        self.root = _tree()
        self.args = ["--root", str(self.root)]

    def test_check_is_red_until_written_and_green_after(self):
        self.assertEqual(sync.main(["--check", *self.args]), 1)
        self.assertEqual(sync.main(["--write", *self.args]), 0)
        self.assertEqual(sync.main(["--check", *self.args]), 0)

    def test_a_new_tracked_markdown_file_makes_the_check_red(self):
        sync.main(["--write", *self.args])
        (self.root / "docs" / "NEW.md").write_text("# new\n", encoding="utf-8")
        _git(self.root, "add", "-A")
        self.assertEqual(sync.main(["--check", *self.args]), 1)

    def test_a_changed_ceiling_makes_the_check_red(self):
        sync.main(["--write", *self.args])
        budget = json.loads((self.root / sync.BUDGET_REL).read_text(encoding="utf-8"))
        budget["per_file_bytes"]["NEXT.md"] = 3001
        (self.root / sync.BUDGET_REL).write_text(json.dumps(budget), encoding="utf-8")
        self.assertEqual(sync.main(["--check", *self.args]), 1)

    def test_a_hand_edit_of_the_derived_file_makes_the_check_red(self):
        sync.main(["--write", *self.args])
        output = self.root / sync.OUTPUT_REL
        data = json.loads(output.read_text(encoding="utf-8"))
        data["total_bytes_max"] = 999999
        output.write_text(sync.rendered(data), encoding="utf-8")
        self.assertEqual(sync.main(["--check", *self.args]), 1)

    def test_a_crlf_checkout_of_the_derived_file_is_still_green(self):
        sync.main(["--write", *self.args])
        output = self.root / sync.OUTPUT_REL
        output.write_bytes(output.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(sync.main(["--check", *self.args]), 0)

    def test_a_refused_derivation_is_red_not_a_crash(self):
        (self.root / sync.BUDGET_REL).write_text("{", encoding="utf-8")
        self.assertEqual(sync.main(["--check", *self.args]), 1)


if __name__ == "__main__":
    unittest.main()
