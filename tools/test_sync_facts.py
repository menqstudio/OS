#!/usr/bin/env python3
"""Tests for sync_facts.py: every refusal by name, and every mode against a real tree."""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sync_facts as m  # noqa: E402


def tree(cfg, files):
    root = pathlib.Path(tempfile.mkdtemp(prefix="facts-"))
    (root / "config").mkdir()
    (root / "config" / "doc-facts.json").write_text(json.dumps(cfg), encoding="utf-8")
    for rel, text in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        # Bytes, not text mode: on Windows `write_text` turns every "\n" into "\r\n", so a fixture
        # that already says "\r\n" arrived as "\r\r\n" and two tests failed on the fixture.
        f.write_bytes(text.encode("utf-8"))
    return root


def run(root, mode):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = m.main([mode, "--root", str(root)])
    return code, out.getvalue()


BASE = {"facts": {"round": {"source": {"value": "eleventh"}}}, "documents": ["*.md"]}


class Modes(unittest.TestCase):
    def test_a_current_span_is_green_and_a_stale_one_is_red_without_writing(self):
        root = tree(BASE, {"A.md": "the <!-- fact:round -->eleventh<!-- /fact --> round\n"})
        self.assertEqual(run(root, "--check")[0], 0)
        (root / "A.md").write_text("the <!-- fact:round -->tenth<!-- /fact --> round\n")
        code, out = run(root, "--check")
        self.assertEqual(code, 1)
        self.assertIn("A.md:1: `round` says `tenth`, the source says `eleventh`", out)
        self.assertIn("tenth", (root / "A.md").read_text(), "--check must not write")

    def test_write_brings_every_use_to_the_source_and_leaves_the_rest_alone(self):
        text = ("# t\nthe <!-- fact:round -->tenth<!-- /fact --> and "
                "<!-- fact:round|upper -->TENTH<!-- /fact -->\nuntouched tenth\n")
        root = tree(BASE, {"A.md": text, "sub/B.md": "x <!-- fact:round|title -->Old<!-- /fact -->\n"})
        cfg = dict(BASE, documents=["*.md", "sub/*.md"])
        (root / "config" / "doc-facts.json").write_text(json.dumps(cfg))
        self.assertEqual(run(root, "--write")[0], 0)
        self.assertEqual((root / "A.md").read_text(),
                         "# t\nthe <!-- fact:round -->eleventh<!-- /fact --> and "
                         "<!-- fact:round|upper -->ELEVENTH<!-- /fact -->\nuntouched tenth\n")
        self.assertIn(">Eleventh<", (root / "sub/B.md").read_text())
        self.assertEqual(run(root, "--check")[0], 0)

    def test_crlf_and_a_missing_final_newline_survive_a_write(self):
        root = tree(BASE, {"A.md": "a\r\n<!-- fact:round -->x<!-- /fact -->\r\nend"})
        self.assertEqual(run(root, "--write")[0], 0)
        self.assertEqual((root / "A.md").read_bytes(),
                         b"a\r\n<!-- fact:round -->eleventh<!-- /fact -->\r\nend")


class Sources(unittest.TestCase):
    def test_json_regex_and_command_sources_resolve(self):
        cfg = {"facts": {
            "n": {"source": {"json": {"file": "c.json", "path": "claims.rust.0.value"}}},
            "r": {"source": {"regex": {"file": "L.md", "pattern": r"the \*\*([A-Z]+)\*\* audit"}}},
            "c": {"source": {"command": [sys.executable, "-c", "print('abc1234')"]}}},
            "documents": ["A.md"]}
        root = tree(cfg, {"c.json": json.dumps({"claims": {"rust": [{"value": 1434}]}}),
                          "L.md": "is the **ELEVENTH** audit\n",
                          "A.md": "<!-- fact:n|comma -->0<!-- /fact --> <!-- fact:r|lower -->x<!-- /fact --> "
                                  "<!-- fact:c -->x<!-- /fact -->\n"})
        self.assertEqual(run(root, "--write")[0], 0)
        self.assertEqual((root / "A.md").read_text(),
                         "<!-- fact:n|comma -->1,434<!-- /fact --> <!-- fact:r|lower -->eleventh<!-- /fact --> "
                         "<!-- fact:c -->abc1234<!-- /fact -->\n")

    def test_a_json_source_whose_path_or_file_is_not_there_is_refused_by_name(self):
        for path, files, needle in (("claims.nope.value", {"c.json": '{"claims": {}}'}, "does not resolve (stopped at `nope`)"),
                                    ("claims.0", {"c.json": '{"claims": []}'}, "does not resolve (stopped at `0`)"),
                                    ("a", {}, "c.json does not exist")):
            cfg = {"facts": {"n": {"source": {"json": {"file": "c.json", "path": path}}}}, "documents": ["A.md"]}
            root = tree(cfg, dict(files, **{"A.md": "<!-- fact:n -->x<!-- /fact -->\n"}))
            code, out = run(root, "--write")
            self.assertEqual((code, needle in out), (2, True), out)

    def test_a_regex_source_must_match_exactly_once(self):
        for body, n in (("nothing here\n", 0), ("**A** audit and **B** audit\n", 2)):
            cfg = {"facts": {"r": {"source": {"regex": {"file": "L.md", "pattern": r"\*\*([A-Z]+)\*\* audit"}}}},
                   "documents": ["A.md"]}
            root = tree(cfg, {"L.md": body, "A.md": "<!-- fact:r -->x<!-- /fact -->\n"})
            code, out = run(root, "--write")
            self.assertEqual(code, 2)
            self.assertIn(f"matches {n} time(s)", out)
            self.assertIn(">x<", (root / "A.md").read_text())

    def test_a_command_is_argv_and_a_failing_one_is_refused(self):
        for spec, needle in (("git rev-parse HEAD", "never a shell string"),
                             ([sys.executable, "-c", "raise SystemExit(3)"], "exited 3"),
                             (["no-such-program-zz"], "did not run")):
            root = tree({"facts": {"c": {"source": {"command": spec}}}, "documents": ["A.md"]},
                        {"A.md": "<!-- fact:c -->x<!-- /fact -->\n"})
            code, out = run(root, "--check")
            self.assertEqual(code, 2, out)
            self.assertIn(needle, out)

    def test_an_empty_multiline_or_comment_closing_value_is_refused(self):
        for value in ("", "  ", "a\nb", "x --> y", True, 1.5, None, ["a"]):
            root = tree({"facts": {"v": {"source": {"value": value}}}, "documents": ["A.md"]},
                        {"A.md": "<!-- fact:v -->x<!-- /fact -->\n"})
            self.assertEqual(run(root, "--write")[0], 2, repr(value))
            self.assertIn(">x<", (root / "A.md").read_text())


class Refusals(unittest.TestCase):
    def refused(self, cfg, files, needle):
        root = tree(cfg, files)
        before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
        code, out = run(root, "--write")
        self.assertEqual(code, 2, out)
        self.assertIn(needle, out)
        self.assertEqual(before, {p: p.read_bytes() for p in root.rglob("*") if p.is_file()},
                         "a refusal must write nothing")

    def test_an_undeclared_fact_in_a_marker(self):
        self.refused(BASE, {"A.md": "<!-- fact:round -->x<!-- /fact --> <!-- fact:nope -->x<!-- /fact -->\n"},
                     "A.md:1: marker names `nope`")

    def test_an_unknown_filter_and_one_that_cannot_apply(self):
        self.refused(BASE, {"A.md": "<!-- fact:round|shout -->x<!-- /fact -->\n"}, "unknown filter `shout`")
        self.refused(BASE, {"A.md": "<!-- fact:round|comma -->x<!-- /fact -->\n"}, "cannot be applied")

    def test_a_marker_that_does_not_close_on_its_line(self):
        self.refused(BASE, {"A.md": "ok <!-- fact:round -->x<!-- /fact -->\nbad <!-- fact:round -->x\n<!-- /fact -->\n"},
                     "A.md:2: a fact marker opens and does not close")

    def test_a_declared_fact_nothing_uses(self):
        cfg = {"facts": {"round": {"source": {"value": "a"}}, "orphan": {"source": {"value": "b"}}},
               "documents": ["A.md"]}
        self.refused(cfg, {"A.md": "<!-- fact:round -->x<!-- /fact -->\n"}, "declares `orphan` and nothing uses it")

    def test_a_listed_document_that_is_not_there_and_no_config_and_no_facts(self):
        self.refused(dict(BASE, documents=["A.md", "MISSING.md"]),
                     {"A.md": "<!-- fact:round -->x<!-- /fact -->\n"}, "`MISSING.md` matches no file")
        self.refused({"facts": {}, "documents": ["A.md"]}, {"A.md": "x\n"}, "declares no facts")
        root = pathlib.Path(tempfile.mkdtemp(prefix="facts-"))
        self.assertEqual(run(root, "--check")[0], 2)

    def test_a_source_with_two_kinds_or_an_unknown_kind(self):
        self.refused({"facts": {"v": {"source": {"value": "a", "json": {}}}}, "documents": ["A.md"]},
                     {"A.md": "<!-- fact:v -->x<!-- /fact -->\n"}, "exactly one of")
        self.refused({"facts": {"v": {"source": {"shell": "date"}}}, "documents": ["A.md"]},
                     {"A.md": "<!-- fact:v -->x<!-- /fact -->\n"}, "unknown source kind `shell`")


class Targets(unittest.TestCase):
    """A fact reaching text that cannot carry a marker: JSON, a code block, a budgeted file."""
    CFG = {"facts": {"round": {"source": {"value": "eleventh"}}, "n": {"source": {"value": "1434"}}},
           "documents": [], "targets": [
               {"file": "s.json", "fact": "round", "filter": "upper",
                "pattern": r"\"round\": \"([A-Z]+)\""},
               {"file": "C.md", "fact": "n", "pattern": r"cargo test +# (\d+) passed"}]}
    JSON_TEXT = '{"z": "կ",   "audit": {"round": "NINTH"},\n "counts": [3]}\n'
    MD = "```bash\ncargo test   # 1432 passed\n```\n1432 elsewhere\n"

    def test_a_stale_target_is_named_then_written_and_nothing_else_in_the_file_moves(self):
        root = tree(self.CFG, {"s.json": self.JSON_TEXT, "C.md": self.MD})
        code, out = run(root, "--check")
        self.assertEqual(code, 1)
        self.assertIn("s.json:1: `round` says `NINTH`, the source says `ELEVENTH`", out)
        self.assertIn("C.md:2: `n` says `1432`, the source says `1434`", out)
        self.assertEqual((root / "s.json").read_text(encoding="utf-8"), self.JSON_TEXT)
        self.assertEqual(run(root, "--write")[0], 0)
        self.assertEqual((root / "s.json").read_text(encoding="utf-8"),
                         self.JSON_TEXT.replace("NINTH", "ELEVENTH"))
        self.assertEqual((root / "C.md").read_text(),
                         "```bash\ncargo test   # 1434 passed\n```\n1432 elsewhere\n")
        self.assertEqual(run(root, "--check")[0], 0)

    def test_a_target_must_match_exactly_once_and_have_exactly_one_group(self):
        for md, needle in (("no count here\n", "matches 0 time(s)"),
                           (self.MD + "cargo test # 7 passed\n", "matches 2 time(s)")):
            root = tree(self.CFG, {"s.json": self.JSON_TEXT, "C.md": md})
            code, out = run(root, "--write")
            self.assertEqual((code, needle in out), (2, True), out)
            self.assertEqual((root / "s.json").read_text(encoding="utf-8"), self.JSON_TEXT,
                             "a refusal in one file must not write another")
        for pattern, needle in ((r"cargo test +# \d+ passed", "has 0 group(s)"),
                                (r"(cargo) test +# (\d+) passed", "has 2 group(s)"),
                                (r"cargo test +# (\d+ passed", "not a regular expression")):
            cfg = json.loads(json.dumps(self.CFG))
            cfg["targets"][1]["pattern"] = pattern
            root = tree(cfg, {"s.json": self.JSON_TEXT, "C.md": self.MD})
            code, out = run(root, "--write")
            self.assertEqual((code, needle in out), (2, True), out)

    def test_a_target_naming_an_undeclared_fact_or_a_missing_file(self):
        cfg = json.loads(json.dumps(self.CFG))
        cfg["targets"][1]["fact"] = "nope"
        root = tree(cfg, {"s.json": self.JSON_TEXT, "C.md": self.MD})
        self.assertIn("names `nope`", run(root, "--check")[1])
        root = tree(self.CFG, {"s.json": self.JSON_TEXT})
        self.assertIn("target file C.md does not exist", run(root, "--check")[1])

    def test_a_pattern_across_a_line_break_matches_a_crlf_checkout_and_the_file_keeps_its_endings(self):
        cfg = {"facts": {"round": {"source": {"value": "eleventh"}}}, "documents": [],
               "targets": [{"file": "S.md", "fact": "round", "pattern": r"current one is the\n> ([a-z]+),"}]}
        for ending in ("\n", "\r\n"):
            body = f"x{ending}> the current one is the{ending}> tenth, [link]{ending}end"
            root = tree(cfg, {"S.md": body})
            code, out = run(root, "--check")
            self.assertEqual(code, 1, out)
            self.assertIn("S.md:3: `round` says `tenth`", out)
            self.assertEqual(run(root, "--write")[0], 0)
            self.assertEqual((root / "S.md").read_bytes(), body.replace("tenth", "eleventh").encode())

    def test_a_file_that_mixes_line_endings_keeps_every_one_of_them(self):
        cfg = {"facts": {"n": {"source": {"value": "5"}}}, "documents": [],
               "targets": [{"file": "M.md", "fact": "n", "pattern": r"count=(\d+)"}]}
        root = tree(cfg, {"M.md": "a\r\nb\ncount=4\r\nc\n"})
        self.assertEqual(run(root, "--write")[0], 0)
        self.assertEqual((root / "M.md").read_bytes(), b"a\r\nb\ncount=5\r\nc\n")

    def test_markers_and_a_target_in_one_file_are_both_applied(self):
        cfg = {"facts": {"round": {"source": {"value": "eleventh"}}, "n": {"source": {"value": "5"}}},
               "documents": ["A.md"],
               "targets": [{"file": "A.md", "fact": "n", "pattern": r"count=(\d+)"}]}
        root = tree(cfg, {"A.md": "<!-- fact:round -->x<!-- /fact -->\r\ncount=4\r\n"})
        self.assertEqual(run(root, "--write")[0], 0)
        self.assertEqual((root / "A.md").read_bytes(),
                         b"<!-- fact:round -->eleventh<!-- /fact -->\r\ncount=5\r\n")


class TheRepositoryItLivesIn(unittest.TestCase):
    def test_every_declared_fact_here_equals_its_source(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        if not (root / m.CONFIG).is_file():
            self.skipTest(f"{m.CONFIG} is not present; the tool is being tested on its own")
        code, out = run(root, "--check")
        self.assertEqual(code, 0, out)


class EntryPointTests(unittest.TestCase):
    """`tools/sync_facts.py` is an entry point for the kit's file, not a second copy of it."""

    ENTRY = pathlib.Path(__file__).resolve().parent / "sync_facts.py"
    KIT = pathlib.Path(__file__).resolve().parents[1] / "menq-standard" / "sync_facts.py"

    def test_the_imported_module_is_the_kits_file(self):
        self.assertTrue(self.KIT.is_file(), "the MenQ Standard kit is not in this checkout")
        self.assertEqual(pathlib.Path(m.__file__).resolve(), self.KIT)

    def test_the_entry_point_holds_no_implementation_of_its_own(self):
        text = self.ENTRY.read_text(encoding="utf-8")
        for name in ("def resolve", "def main", "def apply", "argparse"):
            self.assertNotIn(name, text, f"{name!r} is implemented in the entry point again")

    def test_run_as_a_script_it_gives_the_kits_verdict(self):
        import subprocess
        import sys as _sys
        root = self.ENTRY.parents[1]
        via_entry = subprocess.run([_sys.executable, str(self.ENTRY), "--check"], cwd=root, capture_output=True, text=True)
        via_kit = subprocess.run([_sys.executable, str(self.KIT), "--check"], cwd=root, capture_output=True, text=True)
        self.assertEqual((via_entry.returncode, via_entry.stdout), (via_kit.returncode, via_kit.stdout))
        self.assertIn("fact(s)", via_entry.stdout)

    def test_a_missing_kit_file_is_said_plainly(self):
        import importlib.util
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            copy = pathlib.Path(tmp) / "tools" / "sync_facts.py"
            copy.parent.mkdir()
            copy.write_bytes(self.ENTRY.read_bytes())
            spec = importlib.util.spec_from_file_location("sync_facts_without_kit", copy)
            with self.assertRaises(SystemExit) as caught:
                spec.loader.exec_module(importlib.util.module_from_spec(spec))
        self.assertIn("the kit's file is missing", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
