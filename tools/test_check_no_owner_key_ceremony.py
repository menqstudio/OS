"""Self-tests for check_no_owner_key_ceremony. Each case builds a throwaway git tree.

This file is also the gate's CONTROL: it names forbidden tokens (win_gen_root, sign_manifest.py,
BROPS_MANIFEST_SIG_IN) and is exempt by path, so the real sweep must find them here or go red.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_no_owner_key_ceremony as gate  # noqa: E402


class Tree:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        # The control must exist in every tree, or "control matched" fails before anything else.
        self.write(gate.CONTROL, "names win_gen_root on purpose\n")

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", rel], check=True)

    def close(self):
        self._tmp.cleanup()


class GateTests(unittest.TestCase):
    def setUp(self):
        self.t = Tree()
        self.addCleanup(self.t.close)

    def test_a_clean_tree_is_green(self):
        self.t.write("docs/README.md", "the install mints trust\n")
        problems, control = gate.check(self.t.root)
        self.assertEqual(problems, [])
        self.assertTrue(control)

    def test_a_removed_path_coming_back_is_red(self):
        self.t.write("engine/ci/live/sign_manifest.py", "print('hi')\n")
        problems, _ = gate.check(self.t.root)
        self.assertTrue(any("sign_manifest.py exists" in p for p in problems), problems)

    def test_a_document_naming_a_ceremony_tool_is_red(self):
        self.t.write("docs/HOWTO.md", "export BROPS_MANIFEST_SIG_IN=/media/x\n")
        problems, _ = gate.check(self.t.root)
        self.assertTrue(any(p.startswith("docs/HOWTO.md names BROPS_MANIFEST_SIG_IN") for p in problems),
                        problems)

    def test_history_is_exempt(self):
        self.t.write("docs/archive/OLD.md", "win_gen_root --out root.private.seed\n")
        self.t.write("apps/desktop/AUDIT/2026-08-06-x.md", "sign_manifest.py\n")
        problems, _ = gate.check(self.t.root)
        self.assertEqual(problems, [])

    def test_a_sweep_that_misses_its_control_is_red(self):
        # Overwrite the control so it names nothing: the walk can no longer prove it matched.
        self.t.write(gate.CONTROL, "nothing here\n")
        _, control = gate.check(self.t.root)
        self.assertFalse(control)


if __name__ == "__main__":
    unittest.main()
