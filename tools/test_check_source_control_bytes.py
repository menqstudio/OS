"""Self-tests for `check_source_control_bytes.py` — one case per rule, plus this repository today.

Each case builds a throwaway git tree. None of them edits this repository: a self-test that plants a
control byte in a real source file and restores it is one interrupted run away from leaving the byte
behind, which is the exact defect the gate exists to refuse.

The last two cases are the ones that keep the gate honest over time: the rule must SURVIVE CONTACT
(tab, CR and LF are text, or the gate goes red on every indented file and is switched off within a
day), and a declaration must not outlive the fixture it excuses.
"""

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "check_source_control_bytes.py"

NUL = b"\x00"
BS = b"\x08"
BEL = b"\x07"
DEL = b"\x7f"


#: The gate's own declared fixture. Every tree below carries it unless a case is ABOUT declarations,
#: so each case exercises one rule instead of also tripping "a declaration names a file that is not
#: there" — the isolation failure that made a first draft of these tests red for the wrong reason.
FIXTURE_REL = "engine/tests/test_one_standard_pins.py"
FIXTURE_BYTES = b'row = {"ctl": "' + b"\x01" + b'"}\n'


class _Tree:
    """A tracked git tree, written from a {relative path: bytes} map."""

    def __init__(self, files: dict, with_fixture: bool = True):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="control-bytes-"))
        files = dict(files)
        if with_fixture:
            files.setdefault(FIXTURE_REL, FIXTURE_BYTES)
        for rel, data in files.items():
            p = self.dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        self._git("init", "-q")
        self._git("add", "-A")

    def _git(self, *args):
        subprocess.run(["git", *args], cwd=self.dir, capture_output=True, check=False)

    def run(self):
        out = subprocess.run([sys.executable, str(GATE), str(self.dir)], capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             env={**os.environ, "PYTHONUTF8": "1"})
        return out.returncode, out.stdout + out.stderr

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class ACleanTree(unittest.TestCase):
    def test_a_tree_with_no_control_bytes_is_green_and_says_what_it_read(self):
        tree = _Tree({"src/a.ts": b"const x = 1;\n", "docs/b.md": b"# fine\n"})
        try:
            code, out = tree.run()
            self.assertEqual(code, 0, out)
            self.assertIn("GREEN", out)
            # "zero is a measurement" — the count has to be in the verdict or a reader cannot tell
            # the rule ran at all.
            # Three: the two written here plus the declared fixture every tree carries.
            self.assertRegex(out, r"\b3 tracked text files\b")
            self.assertIn("0 undeclared found", out)
        finally:
            tree.close()

    def test_tab_cr_and_lf_are_text_and_are_not_flagged(self):
        """A rule that called these control characters would be switched off within a day."""
        tree = _Tree({"src/a.ts": b"if (x) {\n\treturn 1;\r\n}\r\n"})
        try:
            code, out = tree.run()
            self.assertEqual(code, 0, out)
        finally:
            tree.close()

    def test_a_binary_file_is_not_swept_so_its_bytes_are_not_a_finding(self):
        tree = _Tree({"assets/logo.png": NUL + b"\x89PNG" + NUL, "src/a.ts": b"ok\n"})
        try:
            code, out = tree.run()
            self.assertEqual(code, 0, out)
        finally:
            tree.close()


class TheGateRefuses(unittest.TestCase):
    def _red(self, files, *expect):
        tree = _Tree(files)
        try:
            code, out = tree.run()
            self.assertEqual(code, 1, out)
            for fragment in expect:
                self.assertIn(fragment, out)
            return out
        finally:
            tree.close()

    def test_a_nul_in_a_source_file_is_refused_with_its_file_line_and_byte(self):
        """The `writeRecord.tsx` defect: ripgrep calls the file binary and prints no match."""
        out = self._red(
            {"src/writeRecord.tsx": b"const a = 1;\nexport const K = '" + NUL + b"sentinel';\n"},
            "src/writeRecord.tsx:2", "0x00")
        self.assertIn("<0x00>", out, "the report must render the byte, or nobody can see what is wrong")
        self.assertIn("u0000", out, "the remedy has to be in the message")

    def test_a_backspace_in_a_source_file_is_refused(self):
        """The honesty-test defect: `/\\bverified\\b/i` became a regex for a literal backspace."""
        self._red(
            {"src/honesty.test.tsx": b"const F = [/" + BS + b"verified" + BS + b"/i];\n"},
            "src/honesty.test.tsx:1", "0x08")

    def test_every_control_byte_below_space_is_refused_not_just_the_two_that_bit_us(self):
        """A gate that only knew about 0x00 and 0x08 would be a fix with a gate-shaped name."""
        self._red({"src/a.ts": b"x" + BEL + b"y\n"}, "0x07")
        self._red({"src/a.ts": b"x" + DEL + b"y\n"}, "0x7f")

    def test_each_occurrence_is_reported_so_the_second_byte_survives_no_fix(self):
        out = self._red({"src/a.ts": b"a" + BEL + b"b\n", "src/b.ts": b"c" + BS + b"d\n"},
                        "src/a.ts:1", "src/b.ts:1")
        self.assertIn("2 problem(s)", out)

    def test_the_line_number_is_the_line_the_byte_is_on(self):
        out = self._red({"src/a.ts": b"one\ntwo\nthree" + BS + b"\nfour\n"}, "src/a.ts:3")
        self.assertNotIn("src/a.ts:1", out)

    def test_a_tree_git_cannot_list_is_refused_rather_than_swept_emptily(self):
        tree = _Tree({"src/a.ts": b"ok\n"})
        try:
            shutil.rmtree(tree.dir / ".git", ignore_errors=True)
            code, out = tree.run()
            self.assertEqual(code, 1, out)
            self.assertIn("proves nothing", out)
        finally:
            tree.close()


class DeclarationsAreNotAnEscapeHatch(unittest.TestCase):
    """The allowance exists so a real fixture can live; these keep it from becoming a mute switch."""

    def test_a_declared_site_is_allowed_and_counted(self):
        # The gate's own DECLARED entry, in a tree where that path exists.
        rel = "engine/tests/test_one_standard_pins.py"
        tree = _Tree({rel: b'row = {"ctl": "' + b"\x01" + b'"}\n', "src/a.ts": b"ok\n"})
        try:
            code, out = tree.run()
            self.assertEqual(code, 0, out)
            self.assertIn("1 occurrence(s) of 1 declared fixture(s)", out)
        finally:
            tree.close()

    def test_the_same_byte_in_an_undeclared_file_is_still_refused(self):
        """The declaration is (path, byte), not (byte). Otherwise one fixture would license the byte
        everywhere in the tree, which is how an exception becomes a policy."""
        tree = _Tree({"engine/tests/somewhere_else.py": b'x = "' + b"\x01" + b'"\n'})
        try:
            code, out = tree.run()
            self.assertEqual(code, 1, out)
            self.assertIn("somewhere_else.py:1", out)
        finally:
            tree.close()

    def test_a_declaration_whose_fixture_is_gone_is_refused(self):
        """An exception that outlives the thing it excused reads as a checked case and is none."""
        rel = "engine/tests/test_one_standard_pins.py"
        tree = _Tree({rel: b"row = {}\n"})    # the file exists, the byte does not
        try:
            code, out = tree.run()
            self.assertEqual(code, 1, out)
            self.assertIn("matched nothing", out)
        finally:
            tree.close()

    def test_a_declaration_pointing_at_a_deleted_file_is_refused(self):
        # The one case that must NOT carry the fixture: the point is a declaration with no file.
        tree = _Tree({"src/a.ts": b"ok\n"}, with_fixture=False)
        try:
            code, out = tree.run()
            self.assertEqual(code, 1, out)
            self.assertIn("which is not a file", out)
        finally:
            tree.close()

    def test_every_declared_reason_is_a_reason_and_not_a_placeholder(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("cscb", GATE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertTrue(mod.DECLARED, "an empty DECLARED would make the rule below vacuous")
        for key, reason in mod.DECLARED.items():
            with self.subTest(key=key):
                self.assertGreaterEqual(len(reason.strip()), mod.MIN_REASON, key)


class ThisRepositoryToday(unittest.TestCase):
    def test_no_tracked_text_file_carries_an_undeclared_control_byte(self):
        out = subprocess.run([sys.executable, str(GATE), str(ROOT)], capture_output=True, text=True,
                             encoding="utf-8", errors="replace",
                             env={**os.environ, "PYTHONUTF8": "1"})
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_the_two_repaired_honesty_lists_hold_word_boundaries_and_not_backspaces(self):
        """The regression this gate was written for, asserted directly rather than only via bytes.

        Five entries per list read `/<0x08>word<0x08>/i` and matched no rendered text, so five
        `not.toMatch` assertions per file accepted every input. Injecting `custody` into the rendered
        fixture passed before the repair and failed after it."""
        for rel in ("apps/desktop/src/features/Knowledge.honesty.test.tsx",
                    "apps/desktop/src/features/Memory.honesty.test.tsx"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            with self.subTest(rel=rel):
                for word in ("verified", "trusted", "signed", "receipt", "custody"):
                    self.assertIn(rf"/\b{word}\b/i", text,
                                  f"{rel}: the {word} rule is not a word-boundary regex")
                self.assertNotIn("\x08", text)

    def test_the_gate_is_run_by_a_workflow(self):
        workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        hits = [w.name for w in workflows
                if "check_source_control_bytes.py" in w.read_text(encoding="utf-8")]
        self.assertTrue(hits, "no workflow runs tools/check_source_control_bytes.py")

    def test_the_job_that_runs_it_is_a_required_context(self):
        """A gate whose failure cannot block a merge is the pattern this repository names `T-056`.
        This one is deliberately hosted inside an already-required job so it blocks from its first run
        and adds no dated Owner debt."""
        import json
        contexts = set(json.loads(
            (ROOT / "config" / "required-checks.json").read_text(encoding="utf-8"))["contexts"])
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        # The job whose block contains the gate's invocation.
        blocks = re.split(r"\n  (?=[a-z0-9][a-z0-9-]*:\s*\n)", ci)
        owning = [b for b in blocks if "check_source_control_bytes.py" in b]
        self.assertEqual(len(owning), 1, "the gate should be invoked from exactly one job")
        name = re.search(r"^    name: (.+)$", owning[0], re.M)
        self.assertIsNotNone(name, "the owning job has no name:")
        self.assertIn(name.group(1).strip().strip('"'), contexts,
                      "the job that runs this gate is not a required context")


if __name__ == "__main__":
    unittest.main()
