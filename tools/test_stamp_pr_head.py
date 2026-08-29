"""Tests for tools/stamp_pr_head.py — the AUDIT_CANDIDATE_HEAD marker writer.

Two things this file is here to hold:

  * exactly ONE marker survives a restamp. `check_repo_state.py` is exact-head fail-closed and
    reads a single marker; a body carrying two is the same red as a body carrying none.
  * the body is written over REST. `gh pr edit` resolves the pull request through GraphQL and
    asks for `repository.pullRequest.projectCards`, which GitHub sunset with Projects (classic);
    on gh 2.46.0 it fails before writing anything, so the marker stays stale and the next push
    goes red for a reason unrelated to the push.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import stamp_pr_head as st  # noqa: E402

SHA = "9431b0674fb87f14d6398746cb48ed149b24b581"
OTHER = "3c9a5cf00000000000000000000000000000beef"


class RestampTests(unittest.TestCase):
    def test_adds_the_marker_when_the_body_has_none(self):
        out = st.restamp("A settle.\n\nWhy it is one.", SHA)
        self.assertEqual([m.strip() for m in st.MARKER.findall(out)],
                         [f"AUDIT_CANDIDATE_HEAD: {SHA}"])
        self.assertTrue(out.startswith("A settle.\n\nWhy it is one."))

    def test_replaces_rather_than_appends(self):
        once = st.restamp("Body.", OTHER)
        twice = st.restamp(once, SHA)
        self.assertEqual(len(st.MARKER.findall(twice)), 1)
        self.assertIn(SHA, twice)
        self.assertNotIn(OTHER, twice)

    def test_strips_every_stale_marker_not_just_the_last(self):
        messy = f"Body.\n\nAUDIT_CANDIDATE_HEAD: {OTHER}\n\nmore\n\nAUDIT_CANDIDATE_HEAD: {OTHER}\n"
        self.assertEqual(len(st.MARKER.findall(st.restamp(messy, SHA))), 1)

    def test_is_idempotent(self):
        once = st.restamp("Body.", SHA)
        self.assertEqual(st.restamp(once, SHA), once)

    def test_keeps_the_prose(self):
        body = "Line one.\n\n    git diff --numstat 5cf9b8c..40be210\n\nLine two."
        self.assertIn("git diff --numstat 5cf9b8c..40be210", st.restamp(body, SHA))


class PatchCommandTests(unittest.TestCase):
    def test_writes_over_rest(self):
        argv = st.patch_command("menqstudio/OS", 183)
        self.assertEqual(argv[:5], ["gh", "api", "-X", "PATCH", "repos/menqstudio/OS/pulls/183"])

    def test_never_uses_gh_pr_edit(self):
        # The regression: gh 2.46.0's `pr edit` dies on the deprecated projectCards GraphQL field.
        argv = st.patch_command("menqstudio/OS", 183)
        self.assertNotIn("edit", argv)
        self.assertNotEqual(argv[1], "pr")

    def test_reads_the_body_from_stdin(self):
        # --input - keeps a long body out of argv, where it would hit the length limit.
        self.assertEqual(st.patch_command("menqstudio/OS", 1)[-2:], ["--input", "-"])


if __name__ == "__main__":
    unittest.main()
