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


class MarkerReadBackTests(unittest.TestCase):
    """The read-back compares what GitHub returns, which is not byte-identical to what was sent."""

    def test_crlf_read_back_matches_the_lf_body_that_was_sent(self):
        body = st.restamp("Body.", SHA)
        self.assertEqual(st.markers(body.replace("\n", "\r\n")), st.markers(body))

    def test_a_different_sha_still_mismatches(self):
        self.assertNotEqual(st.markers(st.restamp("Body.", OTHER)), st.markers(st.restamp("Body.", SHA)))

    def test_a_dropped_marker_mismatches(self):
        self.assertNotEqual(st.markers("Body with no marker."), st.markers(st.restamp("Body.", SHA)))


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


class StampedShaTests(unittest.TestCase):
    """What the body is ALREADY stamped at — the question the write decision turns on."""

    def test_reads_a_crlf_body_the_way_github_returns_one(self):
        self.assertEqual(st.stamped_sha(f"Body.\r\n\r\nAUDIT_CANDIDATE_HEAD: {SHA}\r\n"), SHA)

    def test_reads_an_lf_body_the_same(self):
        self.assertEqual(st.stamped_sha(st.restamp("Body.", SHA)), SHA)

    def test_extra_space_after_the_colon_still_reads(self):
        self.assertEqual(st.stamped_sha(f"AUDIT_CANDIDATE_HEAD:   {SHA}\r\n"), SHA)

    def test_no_marker_is_not_stamped(self):
        self.assertIsNone(st.stamped_sha("Body with no marker.\r\n"))

    def test_two_markers_is_not_stamped(self):
        # check_repo_state.py refuses two exactly as it refuses none, so neither is "already".
        body = f"a\r\nAUDIT_CANDIDATE_HEAD: {SHA}\r\nb\r\nAUDIT_CANDIDATE_HEAD: {SHA}\r\n"
        self.assertIsNone(st.stamped_sha(body))

    def test_a_stale_sha_reads_as_itself_not_as_the_wanted_one(self):
        self.assertEqual(st.stamped_sha(f"AUDIT_CANDIDATE_HEAD: {OTHER}\r\n"), OTHER)


#: The attribution line every pull request in this repository ends with — AFTER the marker. This
#: constant is the whole point of `MarkerPositionTests`: `restamp()` used to relocate the marker
#: past it, so a body that already named the pushed head came back different and got written.
FOOTER = "\n\n\U0001f916 Generated with [Claude Code](https://claude.com/claude-code)\n"


class MarkerPositionTests(unittest.TestCase):
    """A correct marker stays where it is, even when something follows it.

    The measured defect: `restamp()` stripped every marker and re-appended at the end, so a body
    whose marker was already right but not LAST came back reordered. The caller then wrote it, and a
    write fires `pull_request: edited`, which ci.yml subscribes to by design — all 22 jobs restart
    and the run in flight is cancelled. 2026-09-19: 26 `ci` pull-request runs over 11 heads, 19
    cancelled, every head with more than one run.
    """

    def test_a_correct_marker_with_a_footer_after_it_is_left_alone(self):
        body = f"## T\n\nProse.\n\nAUDIT_CANDIDATE_HEAD: {SHA}{FOOTER}"
        self.assertEqual(st.restamp(body, SHA), body)

    def test_a_correct_marker_that_is_last_is_left_alone(self):
        body = f"## T\n\nProse.\n\nAUDIT_CANDIDATE_HEAD: {SHA}\n"
        self.assertEqual(st.restamp(body, SHA), body)

    def test_a_stale_marker_with_a_footer_is_replaced_and_still_ends_up_unique(self):
        body = f"## T\n\nProse.\n\nAUDIT_CANDIDATE_HEAD: {OTHER}{FOOTER}"
        out = st.restamp(body, SHA)
        self.assertNotEqual(out, body)
        self.assertEqual(st.stamped_sha(out), SHA)
        self.assertEqual(len(st.MARKER.findall(out)), 1)

    def test_prose_that_merely_mentions_the_marker_name_is_not_a_marker(self):
        """For THIS tool only: a mention is not a marker, so it still stamps such a body.

        `check_repo_state.py` is deliberately stricter and counts the KEYWORD across the whole body,
        fail-closing on more than one occurrence so nobody can append a second marker to smuggle a
        head. So a pull request description must not name the keyword in prose at all — measured the
        hard way on this very pull request, whose first description did and went RED with
        "marker missing/not 40-hex: None". These two rules are not in conflict: the writer refuses to
        guess which of several markers is real, and the verifier refuses to guess at all.
        """
        body = f"anchored in the body as the audited-head marker\n\nAUDIT_CANDIDATE_HEAD: {SHA}\n"
        self.assertEqual(st.stamped_sha(body), SHA)


class WriteDecisionTests(unittest.TestCase):
    """Whether `main()` WRITES — the layer `test_is_idempotent` does not reach.

    `restamp()` being idempotent on a marker-last body says nothing about the tool leaving a real
    pull request's body alone, and it did not: with the attribution line after the marker the guard
    saw a difference and PATCHed. These tests drive `main()` with `gh` and the writer replaced, and
    assert on the decision rather than on the string.
    """

    def setUp(self):
        self.written = []
        self._run, self._write = st.run, st.write_body
        st.write_body = lambda repo, pr, body: self.written.append((repo, pr, body))
        self.addCleanup(self._restore)

    def _restore(self):
        st.run, st.write_body = self._run, self._write

    def _drive(self, body: str, pushed: str, local: str | None = None):
        """Run main() against a fake GitHub whose body is `body` and whose tip is `pushed`."""
        local = pushed if local is None else local
        import json as _json

        def fake_run(*args: str) -> str:
            if args[:2] == ("gh", "pr"):
                return _json.dumps({"body": body, "headRefName": "some/branch"})
            if args[:2] == ("git", "ls-remote"):
                return f"{pushed}\trefs/heads/some/branch\n"
            if args[:2] == ("git", "rev-parse"):
                return local + "\n"
            raise AssertionError(f"unexpected call: {args}")

        st.run = fake_run
        argv = sys.argv
        sys.argv = ["stamp_pr_head.py", "--pr", "230"]
        try:
            return st.main()
        finally:
            sys.argv = argv

    def test_a_real_pr_body_already_at_the_pushed_sha_is_not_rewritten(self):
        """The regression, in the shape a real pull request has: footer AFTER the marker."""
        body = f"## T\n\nprose\n\nAUDIT_CANDIDATE_HEAD: {SHA}{FOOTER}"
        self.assertEqual(self._drive(body, SHA), 0)
        self.assertEqual(self.written, [], "the body was rewritten though it already named the tip")

    def test_a_marker_last_body_is_not_rewritten(self):
        self.assertEqual(self._drive(st.restamp("prose", SHA), SHA), 0)
        self.assertEqual(self.written, [])

    def test_a_crlf_body_already_at_the_pushed_sha_is_not_rewritten(self):
        """Defensive: no current `gh` read returns CRLF, but #183 recorded one that did."""
        code = self._drive(f"## T\r\n\r\nprose\r\n\r\nAUDIT_CANDIDATE_HEAD: {SHA}\r\n", SHA)
        self.assertEqual(code, 0)
        self.assertEqual(self.written, [])

    def test_a_stale_sha_is_rewritten(self):
        self.assertEqual(self._drive(f"prose\r\n\r\nAUDIT_CANDIDATE_HEAD: {OTHER}\r\n", SHA), 0)
        self.assertEqual(len(self.written), 1)
        self.assertEqual(st.stamped_sha(self.written[0][2]), SHA)

    def test_an_unstamped_body_is_written(self):
        self.assertEqual(self._drive("prose with no marker\r\n", SHA), 0)
        self.assertEqual(len(self.written), 1)

    def test_a_body_with_two_markers_is_rewritten_down_to_one(self):
        body = f"a\r\nAUDIT_CANDIDATE_HEAD: {SHA}\r\nb\r\nAUDIT_CANDIDATE_HEAD: {SHA}\r\n"
        self.assertEqual(self._drive(body, SHA), 0)
        self.assertEqual(len(self.written), 1, "two markers is a red state, not an 'already'")
        self.assertEqual(len(st.markers(self.written[0][2])), 1)

    def test_unpushed_work_refuses_instead_of_stamping(self):
        with self.assertRaises(SystemExit):
            self._drive("prose\r\n", SHA, local=OTHER)
        self.assertEqual(self.written, [])


if __name__ == "__main__":
    unittest.main()
