import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_policy import State, authorize_tool


class PolicyTests(unittest.TestCase):
    def test_review_denies_write(self):
        ok, _ = authorize_tool(State("review", "bro", "s"), "Write", {"file_path": "x"})
        self.assertFalse(ok)

    def test_review_allows_read(self):
        ok, _ = authorize_tool(State("review", "bro", "s"), "Read", {"file_path": "x"})
        self.assertTrue(ok)

    def test_work_denies_push(self):
        ok, _ = authorize_tool(State("work", "specialist", "s"), "Bash", {"command": "git push origin x"})
        self.assertFalse(ok)

    def test_release_denies_wrong_role(self):
        os.environ["BRO_EXTERNAL_RELEASE_BOUNDARY"] = "confirmed"
        ok, _ = authorize_tool(State("release", "release-verifier", "s"), "Bash", {"command": "git push origin x"})
        self.assertFalse(ok)

    def test_release_push_executor_with_boundary(self):
        os.environ["BRO_EXTERNAL_RELEASE_BOUNDARY"] = "confirmed"
        ok, _ = authorize_tool(State("release", "push-executor", "s"), "Bash", {"command": "git push origin x"})
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
