"""Review-mode containment: the wall must deny shell/command tools in review.

Security remediation, blocker 1 (audit finding: review-mode file deletion and
workspace escape). Shell arguments are not parsed, so `find . -delete` classifies
as a READ_LOCAL read and `cat /etc/passwd` reads outside the workspace — both
slipped past review mode's read-only gate. The fix restricts review to structured
read tools (Read/Glob/Grep) only; every shell/command tool is denied.

These are regression tests for the exact reproduced bypasses: they must be DENY.
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_authorization import classify_tool_action
from bro_policy import REVIEW_READ_TOOLS, State, authorize_classified_action

REVIEW = State("review", "specialist", "sess-review", "agt-p01-r02")
REVIEW_CONDUCTOR = State("review", "bro", "sess-review", "bro-000")


def _c(tool, value):
    return classify_tool_action(tool, value, ROOT)


class ReviewContainmentTests(unittest.TestCase):
    def test_reproduced_shell_bypasses_are_denied(self):
        # the exact commands the audit probe reported as ALLOWED
        for command in ("cat /etc/passwd", "find . -delete", "git -C /tmp status", "cat x"):
            allowed, reason = authorize_classified_action(REVIEW, _c("Bash", {"command": command}), {})
            self.assertFalse(allowed, f"review must deny shell: {command!r} -> {reason}")
            self.assertIn("review mode allows only structured read tools", reason)

    def test_all_shell_resolver_tools_are_denied_in_review(self):
        for tool, value in (("Bash", {"command": "ls"}),
                            ("Shell", {"command": "ls"}),
                            ("PowerShell", {"command": "gci"})):
            allowed, _ = authorize_classified_action(REVIEW, _c(tool, value), {})
            self.assertFalse(allowed, f"{tool} must be denied in review")
        # also denied for the canonical conductor: review restricts everyone
        allowed, _ = authorize_classified_action(REVIEW_CONDUCTOR, _c("Bash", {"command": "cat x"}), {})
        self.assertFalse(allowed)

    def test_structured_reads_still_allowed_in_review(self):
        for tool, value in (("Read", {"file_path": "README.md"}),
                            ("Glob", {"pattern": "**/*.py"}),
                            ("Grep", {"pattern": "def "})):
            allowed, reason = authorize_classified_action(REVIEW, _c(tool, value), {})
            self.assertTrue(allowed, f"review must allow {tool}: {reason}")
        self.assertEqual(REVIEW_READ_TOOLS, frozenset({"Read", "Glob", "Grep"}))

    def test_glob_pattern_is_a_containment_target(self):
        # Glob's path-glob pattern must be a target so the workspace gate can
        # contain it; Grep's pattern is a regex and must NOT become a path target.
        self.assertIn("/etc/**", _c("Glob", {"pattern": "/etc/**"}).targets)
        self.assertIn("../../**", _c("Glob", {"pattern": "../../**"}).targets)
        self.assertEqual(_c("Grep", {"pattern": "def ", "path": "runtime"}).targets, ("runtime",))

    def test_review_still_denies_mutation_before_the_tool_gate(self):
        # a write is denied as mutating, not merely as a non-read tool
        allowed, reason = authorize_classified_action(REVIEW, _c("Write", {"file_path": "docs/x.md"}), {})
        self.assertFalse(allowed)
        self.assertIn("read-only", reason)


if __name__ == "__main__":
    unittest.main()
