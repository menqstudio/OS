"""Tests for tools/check_repo_state.py — the live-GitHub EXACT-HEAD verifier's pure functions.

Covers the Owner's required regressions: merge-of-carrier -> main-push must be GREEN (no self-red),
exact-head drift must be RED, event base/head/number mismatch must be RED, merged-called-open RED.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_repo_state as rs  # noqa: E402

HEAD_31 = "6ebeca88627640eef8effe576b3d388417cb4949"
HEAD_32 = "0e7ee1af0b96ca768cabe43c71d9caec30230430"
MAIN = "df3c0aca80cbe4a5537a9fdd53e16e26541c9c19"
NEWMAIN = "1111111111111111111111111111111111111111"


CARRIER_HEAD = "2222222222222222222222222222222222222222"


def _snapshot():
    # NOTE: the carrier PR (#33) is deliberately NOT in prs[] — only durable project PRs.
    return {
        "sync": {"baseline_main_head_at_sync": MAIN},
        "current_workflow_pr": {"number": 33, "branch": "chore/phase0-repository-truth",
                                "base": "main", "head": CARRIER_HEAD},
        "carrier_transition": {
            "carrier_pr": 33,
            "pre_merge": {"gate": "PR33_REAUDIT", "carrier_state": "open", "phase_0": "in_progress"},
            "post_merge": {"gate": "REBASE_PR31", "carrier_state": "merged", "phase_0": "done"},
        },
        "prs": [
            {"number": 31, "branch": "feat/wave-3b1-isolated-signer", "base": "main",
             "draft": False, "merge_state": "open", "head": HEAD_31},
            {"number": 32, "branch": "impl/wave-3b1b-execution-binding",
             "base": "feat/wave-3b1-isolated-signer", "draft": True, "merge_state": "open", "head": HEAD_32},
        ],
    }


def _live_ok():
    return {
        31: {"state": "OPEN", "isDraft": False, "headRefName": "feat/wave-3b1-isolated-signer",
             "baseRefName": "main", "headRefOid": HEAD_31},
        32: {"state": "OPEN", "isDraft": True, "headRefName": "impl/wave-3b1b-execution-binding",
             "baseRefName": "feat/wave-3b1-isolated-signer", "headRefOid": HEAD_32},
    }


class ExternalPrTests(unittest.TestCase):
    def test_exact_match_passes(self):
        self.assertEqual(rs.compare_external_prs(_snapshot(), _live_ok()), [])

    def test_merged_called_open_fails(self):
        live = _live_ok(); live[31]["state"] = "MERGED"
        self.assertTrue(any("PR #31" in p and "MERGED" in p for p in rs.compare_external_prs(_snapshot(), live)))

    def test_exact_head_drift_is_now_a_failure(self):
        live = _live_ok(); live[31]["headRefOid"] = NEWMAIN  # head advanced
        f = rs.compare_external_prs(_snapshot(), live)
        self.assertTrue(any("PR #31" in p and "exact-head drift" in p for p in f))

    def test_draft_mismatch_fails(self):
        live = _live_ok(); live[32]["isDraft"] = False
        self.assertTrue(any("PR #32" in p and "draft" in p for p in rs.compare_external_prs(_snapshot(), live)))

    def test_base_mismatch_fails(self):
        live = _live_ok(); live[32]["baseRefName"] = "main"
        self.assertTrue(any("PR #32" in p and "base" in p for p in rs.compare_external_prs(_snapshot(), live)))

    def test_unresolvable_fails_closed(self):
        live = _live_ok(); live[31] = None
        self.assertTrue(any("PR #31" in p and "unresolved" in p for p in rs.compare_external_prs(_snapshot(), live)))

    def test_non_sha_head_fails(self):
        snap = _snapshot(); snap["prs"][0]["head"] = "PENDING"
        self.assertTrue(any("PR #31" in p and "40-hex" in p for p in rs.compare_external_prs(snap, _live_ok())))

    # --- P1: malformed / missing live metadata must be RED (no skip-on-falsy fail-open) -------------
    def test_null_live_head_fails_closed(self):
        live = _live_ok(); live[31]["headRefOid"] = None
        self.assertTrue(any("PR #31" in p and "headRefOid" in p for p in rs.compare_external_prs(_snapshot(), live)))

    def test_missing_live_head_branch_fails_closed(self):
        live = _live_ok(); live[31]["headRefName"] = ""
        self.assertTrue(any("PR #31" in p and "headRefName" in p for p in rs.compare_external_prs(_snapshot(), live)))

    def test_missing_live_base_fails_closed(self):
        live = _live_ok(); del live[32]["baseRefName"]
        self.assertTrue(any("PR #32" in p and "baseRefName" in p for p in rs.compare_external_prs(_snapshot(), live)))

    def test_null_live_state_fails_closed(self):
        live = _live_ok(); live[31]["state"] = None
        self.assertTrue(any("PR #31" in p and "state missing/unknown" in p for p in rs.compare_external_prs(_snapshot(), live)))

    def test_unknown_live_state_fails_closed(self):
        live = _live_ok(); live[31]["state"] = "LOCKED"
        self.assertTrue(any("PR #31" in p and "state missing/unknown" in p for p in rs.compare_external_prs(_snapshot(), live)))

    def test_null_live_isdraft_fails_closed(self):
        live = _live_ok(); live[32]["isDraft"] = None
        self.assertTrue(any("PR #32" in p and "isDraft" in p for p in rs.compare_external_prs(_snapshot(), live)))


class PrEventTests(unittest.TestCase):
    def _event(self, base_sha=MAIN, base_ref="main", head_ref="chore/phase0-repository-truth",
               number=33, head_sha=CARRIER_HEAD):
        return {"pull_request": {"number": number, "base": {"ref": base_ref, "sha": base_sha},
                                 "head": {"ref": head_ref, "sha": head_sha}}}

    def test_ok_event_passes(self):
        self.assertEqual(rs.verify_pr_event(self._event(), _snapshot()), [])

    def test_stale_baseline_vs_pr_base_fails(self):
        f = rs.verify_pr_event(self._event(base_sha=NEWMAIN), _snapshot())
        self.assertTrue(any("stale vs its base" in p for p in f))

    def test_wrong_current_pr_number_fails(self):
        f = rs.verify_pr_event(self._event(number=99), _snapshot())
        self.assertTrue(any("!= snapshot current_workflow_pr #33" in p for p in f))

    def test_wrong_head_branch_fails(self):
        f = rs.verify_pr_event(self._event(head_ref="some/other"), _snapshot())
        self.assertTrue(any("head branch" in p for p in f))


class CarrierExactHeadTests(unittest.TestCase):
    def test_exact_triple_equality_passes(self):
        self.assertEqual(rs.verify_carrier_exact_head(CARRIER_HEAD, CARRIER_HEAD, CARRIER_HEAD), [])

    def test_descendant_with_old_marker_fails(self):
        # a new commit advances the event/live head; the PR-body marker is still the old sha -> RED.
        f = rs.verify_carrier_exact_head(NEWMAIN, NEWMAIN, CARRIER_HEAD)
        self.assertTrue(any("AUDIT_CANDIDATE_HEAD" in p for p in f))

    def test_event_differs_from_live_fails(self):
        f = rs.verify_carrier_exact_head(CARRIER_HEAD, NEWMAIN, CARRIER_HEAD)
        self.assertTrue(any("live GitHub head" in p for p in f))

    def test_missing_event_head_fails(self):
        self.assertTrue(any("event PR head" in p for p in rs.verify_carrier_exact_head(None, CARRIER_HEAD, CARRIER_HEAD)))

    def test_non_hex_event_head_fails(self):
        self.assertTrue(any("event PR head" in p for p in rs.verify_carrier_exact_head("abc", CARRIER_HEAD, CARRIER_HEAD)))

    def test_missing_body_marker_fails(self):
        self.assertTrue(any("AUDIT_CANDIDATE_HEAD marker missing" in p
                            for p in rs.verify_carrier_exact_head(CARRIER_HEAD, CARRIER_HEAD, None)))

    def test_unresolved_live_head_fails(self):
        self.assertTrue(any("live GitHub carrier head" in p
                            for p in rs.verify_carrier_exact_head(CARRIER_HEAD, None, CARRIER_HEAD)))

    def test_parse_marker(self):
        self.assertEqual(rs.parse_audit_candidate(f"body\nAUDIT_CANDIDATE_HEAD: {CARRIER_HEAD}\nmore"), CARRIER_HEAD)
        self.assertIsNone(rs.parse_audit_candidate("no marker here"))

    # --- P0-2: parse_audit_candidate must fail closed on zero / duplicate / malformed markers -------
    def test_parse_duplicate_marker_fails_closed(self):
        body = f"AUDIT_CANDIDATE_HEAD: {CARRIER_HEAD}\nsome text\nAUDIT_CANDIDATE_HEAD: {NEWMAIN}"
        self.assertIsNone(rs.parse_audit_candidate(body))  # ambiguous: never silently pick one

    def test_parse_malformed_marker_fails_closed(self):
        self.assertIsNone(rs.parse_audit_candidate("AUDIT_CANDIDATE_HEAD: not-a-40-hex-sha"))

    def test_parse_zero_marker_is_none(self):
        self.assertIsNone(rs.parse_audit_candidate("release notes with no marker at all"))

    def test_duplicate_marker_makes_exact_head_red(self):
        # a duplicate marker -> parse None -> the exact-head anchor is RED.
        marker = rs.parse_audit_candidate(f"AUDIT_CANDIDATE_HEAD: {CARRIER_HEAD}\nAUDIT_CANDIDATE_HEAD: {CARRIER_HEAD}")
        self.assertTrue(any("AUDIT_CANDIDATE_HEAD" in p
                            for p in rs.verify_carrier_exact_head(CARRIER_HEAD, CARRIER_HEAD, marker)))


class ExternalPrAnchorTests(unittest.TestCase):
    """fifth audit, A-05: the docstring claimed four anchors and delivered one.

    `branch`, `base` and `draft` were each checked only *if the snapshot bothered to state them*,
    so an entry of `{number, merge_state, head}` satisfied "anchored to an exact live head, branch,
    base and draft flag" while anchoring only the head. Omission is now a failure, which is what
    makes the sentence true.
    """
    def _live(self):
        return {112: {"state": "OPEN", "isDraft": False, "headRefName": "design/floor-writer",
                      "baseRefName": "main", "headRefOid": HEAD_31}}

    def _entry(self, **over):
        e = {"number": 112, "branch": "design/floor-writer", "base": "main",
             "draft": False, "merge_state": "open", "head": HEAD_31}
        e.update(over)
        return e

    def test_a_complete_entry_passes(self):
        self.assertEqual(rs.compare_external_prs({"prs": [self._entry()]}, self._live()), [])

    def test_head_only_entry_is_REFUSED(self):
        thin = {"number": 112, "merge_state": "open", "head": HEAD_31}
        f = rs.compare_external_prs({"prs": [thin]}, self._live())
        self.assertTrue(any("omits `branch`" in p for p in f), f)
        self.assertTrue(any("omits `base`" in p for p in f), f)
        self.assertTrue(any("omits `draft`" in p for p in f), f)

    def test_each_omission_is_reported_on_its_own(self):
        for field, needle in (("branch", "omits `branch`"), ("base", "omits `base`"),
                              ("draft", "omits `draft`")):
            entry = self._entry()
            del entry[field]
            f = rs.compare_external_prs({"prs": [entry]}, self._live())
            self.assertTrue(any(needle in p for p in f), (field, f))

    def test_a_stated_but_wrong_value_still_fails(self):
        f = rs.compare_external_prs({"prs": [self._entry(branch="wrong")]}, self._live())
        self.assertTrue(any("but GitHub head branch" in p for p in f), f)


class CarrierPostMergeTests(unittest.TestCase):
    def test_merged_with_correct_post_merge_is_green(self):
        snap = _snapshot()
        snap["product_roadmap"] = {"phase_0": {"if_carrier_open": "in_progress", "if_carrier_merged": "done"}}
        snap["next_action_by_carrier"] = {"open": "x", "merged": "y"}
        self.assertEqual(rs.verify_carrier_post_merge({"state": "MERGED"}, snap), [])

    def test_merged_with_empty_gate_fails(self):
        # gate NAME is snapshot-declared (generic); an EMPTY/missing post_merge gate is RED.
        snap = _snapshot(); snap["next_action_by_carrier"] = {"open": "x", "merged": "y"}
        snap["carrier_transition"]["post_merge"]["gate"] = ""
        f = rs.verify_carrier_post_merge({"state": "MERGED"}, snap)
        self.assertTrue(any("post_merge.gate is missing/empty" in p for p in f))

    def test_merged_self_stale_carrier_state_fails(self):
        # anti-self-stale: live-MERGED but the snapshot still says the carrier is not merged -> RED.
        snap = _snapshot(); snap["next_action_by_carrier"] = {"open": "x", "merged": "y"}
        snap["carrier_transition"]["post_merge"]["carrier_state"] = "open"
        f = rs.verify_carrier_post_merge({"state": "MERGED"}, snap)
        self.assertTrue(any("self-stale main" in p for p in f))

    def test_merged_missing_merged_next_action_fails(self):
        snap = _snapshot(); snap["next_action_by_carrier"] = {"open": "x"}  # no merged
        self.assertTrue(any("next_action_by_carrier.merged is missing" in p
                            for p in rs.verify_carrier_post_merge({"state": "MERGED"}, snap)))

    def test_unresolvable_carrier_fails_closed(self):
        # P0-3: None must be a FAILURE, not a no-op.
        self.assertTrue(any("could not be resolved" in p for p in rs.verify_carrier_post_merge(None, _snapshot())))

    def test_open_carrier_is_noop(self):
        self.assertEqual(rs.verify_carrier_post_merge({"state": "OPEN"}, _snapshot()), [])


class SettledSnapshotTests(unittest.TestCase):
    """The carrier stopped being OPEN. What must the snapshot then say?

    The third arm of this rule used to demand that the carrier itself still be open, which is
    unsatisfiable once a second pull request is parked open across a merge (main RED -> the repair PR
    must self-carry -> merging it re-creates the condition). These tests pin BOTH halves: an open PR
    named nowhere is still RED, and an open PR named in prs[] is GREEN.
    """
    def _snap(self, prs=None):
        snap = _snapshot()
        snap["settled_at_main_head"] = MAIN
        snap["prs"] = prs if prs is not None else []
        return snap

    def _yes(self, a, b):  # is_ancestor stub: settled is on main
        return True

    #: A carrier merge commit whose FIRST PARENT is the settled head these fixtures record.
    #: Supplied to every call, because as of the sixth audit's A-11 the pin FAILS CLOSED: a
    #: missing mergeCommit or an unresolvable parent is a refusal, not a skip. Before that they
    #: were silently skipped, and the auditor measured the repository's own first commit passing.
    MERGE = "f" * 40

    def _parent(self, sha):  # first_parent stub: the merge landed on MAIN
        return MAIN if sha == self.MERGE else None

    def test_open_carrier_is_noop(self):
        self.assertEqual(rs.verify_settled_snapshot(33, "OPEN", self._snap(), {33}, MAIN, self._yes), [])

    # --- seventh audit, G-05: the fifth door, and the test that pinned it open -----------------
    #
    # This was `test_unresolvable_state_is_noop`, asserting `[]` for an empty carrier state — three
    # lines above the two tests `A-11` rewrote for saying exactly the same thing in different
    # words. `A-11`'s own sentence applies: *"a check that could not run has not passed."*
    # `_is_noop` in the name is what stopped anyone noticing, including the round that rewrote its
    # neighbours.
    #
    # An empty state short-circuits ALL FOUR of `A-11`'s doors before any is reached, so this was
    # the largest fail-open in the function and the only one with a test defending it.

    def test_an_unreadable_carrier_state_REFUSES_rather_than_skipping(self):
        f = rs.verify_settled_snapshot(33, "", self._snap(), {33}, MAIN, self._yes,
                                       self.MERGE, self._parent)
        self.assertTrue(any("could not be read" in p for p in f), f)

    def test_an_unreadable_state_does_not_let_a_missing_settled_head_through(self):
        # What the fail-open actually cost: with no settled_at_main_head at all, it returned clean.
        snap = self._snap()
        del snap["settled_at_main_head"]
        self.assertNotEqual(
            rs.verify_settled_snapshot(33, "", snap, {33}, MAIN, self._yes, self.MERGE, self._parent),
            [])

    def test_an_OPEN_carrier_is_still_a_legitimate_skip(self):
        # The half of the old guard that was right, kept separate so the two cannot be confused
        # again — and note it needs no live measurements at all, which is why it is a skip.
        self.assertEqual(
            rs.verify_settled_snapshot(33, "OPEN", self._snap(), {33}, MAIN, self._yes,
                                       self.MERGE, self._parent), [])

    def test_merged_without_settled_head_is_red(self):
        snap = self._snap(); snap.pop("settled_at_main_head")
        self.assertTrue(any("records no settled_at_main_head" in p
                            for p in rs.verify_settled_snapshot(33, "MERGED", snap, set(), MAIN, self._yes, self.MERGE, self._parent)))

    def test_settled_head_not_on_main_is_red(self):
        f = rs.verify_settled_snapshot(33, "MERGED", self._snap(), set(), NEWMAIN, lambda a, b: False, self.MERGE, self._parent)
        self.assertTrue(any("is not an ancestor of live main" in p for p in f))

    def test_merged_with_nothing_open_is_green(self):
        self.assertEqual(rs.verify_settled_snapshot(33, "MERGED", self._snap(), set(), MAIN,
                                                    self._yes, self.MERGE, self._parent), [])

    def test_open_pr_named_nowhere_is_red(self):
        # the staleness the rule exists for: #112 is open and this file mentions it nowhere.
        f = rs.verify_settled_snapshot(113, "MERGED", self._snap(), {112}, MAIN, self._yes, self.MERGE, self._parent)
        self.assertTrue(any("#112 is open and unnamed" in p for p in f), f)

    def test_every_unnamed_open_pr_is_listed(self):
        f = rs.verify_settled_snapshot(113, "MERGED", self._snap(), {112, 120}, MAIN, self._yes, self.MERGE, self._parent)
        self.assertTrue(any("#112, #120 are open and unnamed" in p for p in f), f)

    def test_open_pr_carried_in_prs_is_green(self):
        # THE DEADLOCK REGRESSION. A parked PR recorded in prs[] is named, so main is not RED —
        # and it is not a free pass either: compare_external_prs anchors it to an exact live head.
        snap = self._snap([{"number": 112, "branch": "design/floor-writer", "base": "main",
                            "draft": False, "merge_state": "open", "head": HEAD_31}])
        self.assertEqual(rs.verify_settled_snapshot(113, "MERGED", snap, {112}, MAIN, self._yes, self.MERGE, self._parent), [])

    def test_repair_pr_cannot_be_forced_to_carry_the_parked_pr(self):
        # The other half of the deadlock, stated as a test: the repair PR self-carries (#114) while
        # #112 stays parked in prs[]. Under the old rule this was RED with no legal way out.
        snap = self._snap([{"number": 112, "branch": "design/floor-writer", "base": "main",
                            "draft": False, "merge_state": "open", "head": HEAD_31}])
        self.assertEqual(rs.verify_settled_snapshot(114, "MERGED", snap, {112}, MAIN, self._yes, self.MERGE, self._parent), [])

    # --- fifth audit, A-05: the safety net was a fail-open --------------------------------------
    def test_unknown_open_set_REFUSES_rather_than_assuming_nothing_is_open(self):
        # open_prs_now() used to return an empty set when gh failed, and an empty set is the most
        # PERMISSIVE answer this rule can receive — "no pull requests are open" — returned exactly
        # when the truth is unknown. None now means unknown, and unknown is a refusal.
        f = rs.verify_settled_snapshot(118, "MERGED", self._snap(), None, MAIN, self._yes, self.MERGE, self._parent)
        self.assertTrue(any("could not be determined" in p for p in f), f)

    def test_the_refusal_does_not_fire_while_the_carrier_is_still_open(self):
        self.assertEqual(rs.verify_settled_snapshot(118, "OPEN", self._snap(), None, MAIN, self._yes), [])

    # --- fifth audit, A-07: an ancestor check alone can never go stale --------------------------
    # `settled_at_main_head` means "the main this carrier merged into", which is EXACTLY the merge
    # commit's first parent. The audit's own suggestion — "settled must be at or after the merge
    # commit" — is unsatisfiable for a self-carrier, because the snapshot is written inside the
    # pull request, before the merge it would have to postdate. That version went red on main
    # within a minute of shipping; these tests pin the version that is both exact and satisfiable.
    def test_settled_that_is_not_the_mains_the_carrier_merged_into_is_red(self):
        f = rs.verify_settled_snapshot(118, "MERGED", self._snap(), set(), MAIN, self._yes,
                                       carrier_merge_commit=NEWMAIN,
                                       first_parent=lambda _: "9" * 40)
        self.assertTrue(any("is not the main that carrier" in p for p in f), f)

    def test_settled_equal_to_the_merges_first_parent_is_green(self):
        self.assertEqual(
            rs.verify_settled_snapshot(118, "MERGED", self._snap(), set(), MAIN, self._yes,
                                       carrier_merge_commit=NEWMAIN,
                                       first_parent=lambda _: MAIN), [])

    def test_a_self_carrier_written_before_its_own_merge_is_SATISFIABLE(self):
        # The regression that matters: the snapshot records the main it branched from, the merge
        # lands on that same commit, and this must be GREEN. The first version of the rule made
        # this state impossible to reach and turned main red on every merge.
        snap = self._snap(); snap["settled_at_main_head"] = MAIN
        self.assertEqual(
            rs.verify_settled_snapshot(118, "MERGED", snap, set(), NEWMAIN, self._yes,
                                       carrier_merge_commit=NEWMAIN,
                                       first_parent=lambda _: MAIN), [])

    # --- sixth audit, A-11: the two fail-opens BESIDE the one that was fixed --------------------
    #
    # These two tests used to be named `…_does_not_invent_a_failure` and asserted `[]`. That is the
    # defect, encoded as intent: the auditor measured `settled_at_main_head` set to the
    # REPOSITORY'S OWN FIRST COMMIT passing, because a missing `mergeCommit` or an unresolvable
    # first parent skipped the pin entirely and nothing was logged.
    #
    # "Does not invent a failure" was the wrong frame. A check that could not run has not passed —
    # and the auditor's aside is the sharp part: these are exactly the paths a `gh`-less
    # environment takes, so the environment least able to verify anything was the one that
    # verified least and said so least. `open_prs_now()` was given this same treatment for the
    # fifth audit's `A-05`; these two sat beside it, quiet.

    def test_an_unresolvable_first_parent_REFUSES_rather_than_skipping(self):
        f = rs.verify_settled_snapshot(118, "MERGED", self._snap(), set(), MAIN, self._yes,
                                       carrier_merge_commit=NEWMAIN,
                                       first_parent=lambda _: None)
        self.assertTrue(any("could not be resolved" in p for p in f), f)

    def test_no_merge_commit_available_REFUSES_rather_than_skipping(self):
        f = rs.verify_settled_snapshot(118, "MERGED", self._snap(), set(), MAIN, self._yes,
                                       carrier_merge_commit=None, first_parent=self._parent)
        self.assertTrue(any("no mergeCommit" in p for p in f), f)

    def test_no_first_parent_RESOLVER_refuses_too(self):
        # The third door into the same room: a caller that simply does not supply the resolver.
        f = rs.verify_settled_snapshot(118, "MERGED", self._snap(), set(), MAIN, self._yes,
                                       carrier_merge_commit=NEWMAIN)
        self.assertTrue(any("no first-parent resolver" in p for p in f), f)

    def test_the_first_commit_ever_made_no_longer_passes_through_a_skipped_pin(self):
        # The auditor's own measurement, as a regression. With the pin skipped this was GREEN.
        snap = self._snap()
        snap["settled_at_main_head"] = "0" * 40
        for kwargs in ({"carrier_merge_commit": None, "first_parent": self._parent},
                       {"carrier_merge_commit": NEWMAIN, "first_parent": lambda _: None},
                       {"carrier_merge_commit": NEWMAIN}):
            f = rs.verify_settled_snapshot(118, "MERGED", snap, set(), MAIN, self._yes, **kwargs)
            self.assertTrue(f, f"a skipped pin must not pass: {kwargs}")

    def test_malformed_prs_entries_do_not_launder_an_open_pr(self):
        # a non-dict, a null number and a string number must NOT count as "named".
        snap = self._snap(["112", {"number": None}, {"number": "112"}])
        self.assertTrue(any("#112 is open and unnamed" in p
                            for p in rs.verify_settled_snapshot(113, "MERGED", snap, {112}, MAIN, self._yes, self.MERGE, self._parent)))


class CarrierStateTests(unittest.TestCase):
    """P1: the carrier's live state is explicitly enumerated; unresolved/unknown => RED; OPEN validates
    the pre_merge branch, MERGED the post_merge branch."""
    def _snap_full(self):
        snap = _snapshot()
        snap["product_roadmap"] = {"phase_0": {"if_carrier_open": "in_progress", "if_carrier_merged": "done"}}
        snap["next_action_by_carrier"] = {"open": "x", "merged": "y"}
        return snap

    def test_open_correct_pre_merge_is_green(self):
        self.assertEqual(rs.verify_carrier_state({"state": "OPEN"}, self._snap_full()), [])

    def test_open_empty_pre_merge_gate_fails(self):
        snap = self._snap_full(); snap["carrier_transition"]["pre_merge"]["gate"] = ""
        self.assertTrue(any("pre_merge.gate is missing/empty" in p for p in rs.verify_carrier_state({"state": "OPEN"}, snap)))

    def test_open_any_declared_gate_ok(self):
        # a design-audit carrier declares its OWN gate name (not the Phase-0 value) — must pass.
        snap = self._snap_full(); snap["carrier_transition"]["pre_merge"]["gate"] = "PR31_DESIGN_AUDIT"
        self.assertEqual(rs.verify_carrier_state({"state": "OPEN"}, snap), [])

    def test_unresolved_carrier_state_fails_closed(self):
        self.assertTrue(any("unresolved/missing" in p for p in rs.verify_carrier_state(None, self._snap_full())))
        self.assertTrue(any("unresolved/missing" in p for p in rs.verify_carrier_state({"state": None}, self._snap_full())))

    def test_unknown_carrier_state_fails_closed(self):
        f = rs.verify_carrier_state({"state": "CLOSED"}, self._snap_full())
        self.assertTrue(any("not an allowed carrier state" in p for p in f))

    def test_merged_delegates_to_post_merge_green(self):
        self.assertEqual(rs.verify_carrier_state({"state": "MERGED"}, self._snap_full()), [])

    def test_merged_delegates_to_post_merge_red(self):
        snap = self._snap_full(); snap["carrier_transition"]["post_merge"]["gate"] = ""
        self.assertTrue(any("post_merge.gate is missing/empty" in p for p in rs.verify_carrier_state({"state": "MERGED"}, snap)))


class WorkflowTriggerTests(unittest.TestCase):
    """P0-2: prove `edited` (and the other required types) stay in the real pull_request trigger, so a
    PR-body AUDIT_CANDIDATE_HEAD edit starts a fresh repo-state run; plus the pure-parser forms."""
    def _real_yaml(self):
        return (pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    def test_required_types_present_in_real_workflow(self):
        types = rs.pull_request_trigger_types(self._real_yaml())
        for required in ("opened", "reopened", "synchronize", "edited", "ready_for_review"):
            self.assertIn(required, types, f"pull_request trigger is missing '{required}'")

    def test_parser_block_list_form(self):
        y = "on:\n  pull_request:\n    types:\n      - opened\n      - edited\n"
        self.assertEqual(rs.pull_request_trigger_types(y), {"opened", "edited"})

    def test_parser_inline_list_form(self):
        y = "on:\n  pull_request:\n    types: [opened, edited, synchronize]\n"
        self.assertEqual(rs.pull_request_trigger_types(y), {"opened", "edited", "synchronize"})

    def test_parser_detects_missing_edited(self):
        y = "on:\n  pull_request:\n    types:\n      - opened\n      - synchronize\n\npermissions:\n  contents: read\n"
        self.assertNotIn("edited", rs.pull_request_trigger_types(y))


class MainPushTests(unittest.TestCase):
    def test_merge_of_carrier_then_main_push_is_green(self):
        # THE self-red guard: baseline is an ancestor of the post-merge main HEAD -> GREEN.
        self.assertEqual(rs.verify_main_push(NEWMAIN, MAIN, is_ancestor=lambda a, b: True), [])

    def test_baseline_equal_pushed_is_green(self):
        self.assertEqual(rs.verify_main_push(MAIN, MAIN, is_ancestor=lambda a, b: False), [])

    def test_baseline_not_ancestor_fails(self):
        f = rs.verify_main_push(NEWMAIN, MAIN, is_ancestor=lambda a, b: False)
        self.assertTrue(any("not an ancestor" in p for p in f))


if __name__ == "__main__":
    unittest.main()


class RestSecondRoad(unittest.TestCase):
    """The REST fallback — eighth audit `H-05`, and the first tests it has ever had.

    `grep -c "_rest_" tools/test_check_repo_state.py` returned **0** when the audit ran. This is the
    one piece of code the seventh round added that no gate covered, written during a live GitHub
    outage and merged the same day, and it sits behind a REQUIRED status check.
    """

    def setUp(self):
        rs._REPO_SLUG_CACHE = None
        self.addCleanup(setattr, rs, "_REPO_SLUG_CACHE", None)

    def _gh(self, mapping, default=None):
        """Patch `subprocess.run` in the module under test; dispatch on the joined argv."""
        class R:
            def __init__(self, rc, out, err=""):
                self.returncode, self.stdout, self.stderr = rc, out, err

        def run(cmd, **_kw):
            key = " ".join(cmd)
            for needle, value in mapping.items():
                if needle in key:
                    if isinstance(value, Exception):
                        raise value
                    return R(*value)
            if default is None:
                raise AssertionError("unexpected subprocess call: " + key)
            return R(*default)

        real = rs.subprocess.run
        rs.subprocess.run = run
        self.addCleanup(setattr, rs.subprocess, "run", real)

    # ---- the slug the REST road addresses -----------------------------------------------------

    def test_the_slug_comes_from_gh_not_from_a_literal(self):
        self._gh({"repo view": (0, '{"nameWithOwner":"someone/fork"}')})
        self.assertEqual(rs._repo_slug(), "someone/fork")

    def test_the_slug_is_resolved_once_and_cached(self):
        calls = []

        class R:
            returncode, stdout, stderr = 0, '{"nameWithOwner":"a/b"}', ""

        def run(cmd, **_kw):
            calls.append(cmd)
            return R()

        real = rs.subprocess.run
        rs.subprocess.run = run
        self.addCleanup(setattr, rs.subprocess, "run", real)
        self.assertEqual(rs._repo_slug(), "a/b")
        self.assertEqual(rs._repo_slug(), "a/b")
        self.assertEqual(len(calls), 1, "resolved once per process, not per REST call")

    def test_an_unresolvable_slug_REFUSES_rather_than_guessing(self):
        # The whole point of H-05: in a fork, guessing `menqstudio/OS` answers about a DIFFERENT
        # repository than the GraphQL road did, and nothing downstream could tell.
        for reply in [(1, "", "gh: not a repository"), (0, ""), (0, "not json"),
                      (0, '{"nameWithOwner":null}'), (0, '{"nameWithOwner":"no-slash"}'),
                      (0, '{"nameWithOwner":"https://github.com/a/b"}')]:
            with self.subTest(reply=reply):
                rs._REPO_SLUG_CACHE = None
                self._gh({"repo view": reply})
                self.assertIsNone(rs._repo_slug())
        rs._REPO_SLUG_CACHE = None
        self._gh({"repo view": OSError("gh not installed")})
        self.assertIsNone(rs._repo_slug())

    def test_a_failed_slug_makes_every_REST_road_refuse(self):
        rs._REPO_SLUG_CACHE = False
        self._gh({})                      # any REST call at all would raise AssertionError
        self.assertIsNone(rs._rest_pull(153))
        self.assertIsNone(rs._rest_open_prs())
        data, why = rs._live_protection()
        self.assertIsNone(data)
        self.assertIn("slug unresolved", why)

    # ---- _rest_pull ---------------------------------------------------------------------------

    def test_rest_pull_maps_RESTs_merged_vocabulary_to_GraphQLs(self):
        # REST says `state:"closed"` + `merged:true`; GraphQL says `MERGED`. Mapping a merged PR to
        # CLOSED would tell verify_settled_snapshot the wrong story about the settle.
        rs._REPO_SLUG_CACHE = "a/b"
        self._gh({"pulls/9": (0, '{"state":"closed","merged":true,"draft":false,'
                                 '"head":{"ref":"h","sha":"' + MAIN + '"},"base":{"ref":"main"},'
                                 '"merge_commit_sha":"' + NEWMAIN + '","body":"b"}')})
        pr = rs._rest_pull(9)
        self.assertEqual(pr["state"], "MERGED")
        self.assertEqual(pr["mergeCommit"], {"oid": NEWMAIN})
        self.assertEqual(pr["headRefOid"], MAIN)
        self.assertEqual(pr["baseRefName"], "main")

    def test_rest_pull_uppercases_the_unmerged_states(self):
        for rest_state, expected in [("open", "OPEN"), ("closed", "CLOSED")]:
            with self.subTest(rest_state=rest_state):
                rs._REPO_SLUG_CACHE = "a/b"
                self._gh({"pulls/9": (0, '{"state":"' + rest_state + '","merged":false,'
                                         '"head":{},"base":{}}')})
                self.assertEqual(rs._rest_pull(9)["state"], expected)

    def test_rest_pull_with_no_merge_commit_reports_None_not_a_fake_oid(self):
        rs._REPO_SLUG_CACHE = "a/b"
        self._gh({"pulls/9": (0, '{"state":"open","merged":false,"head":{},"base":{},'
                                 '"merge_commit_sha":null}')})
        self.assertIsNone(rs._rest_pull(9)["mergeCommit"])

    def test_rest_pull_refuses_a_reply_with_no_state(self):
        # A reply with no `state` must fail closed rather than becoming the empty string, which
        # would uppercase to '' and compare unequal to every real state — a silent permanent
        # mismatch that reads as drift instead of as an unanswered read.
        rs._REPO_SLUG_CACHE = "a/b"
        for body in ['{"merged":false}', '[]', 'null', '"a string"']:
            with self.subTest(body=body):
                self._gh({"pulls/9": (0, body)})
                self.assertIsNone(rs._rest_pull(9))

    def test_rest_pull_returns_None_when_the_SECOND_road_fails_too(self):
        rs._REPO_SLUG_CACHE = "a/b"
        self._gh({"pulls/9": rs.subprocess.CalledProcessError(1, "gh")})
        self.assertIsNone(rs._rest_pull(9))
        self._gh({"pulls/9": (0, "{not json")})
        self.assertIsNone(rs._rest_pull(9))

    # ---- _rest_open_prs -----------------------------------------------------------------------

    def test_rest_open_prs_reads_the_shape_gh_ACTUALLY_emits(self):
        # MEASURED against gh 2.97.0 on 2026-08-18: `--paginate` over a genuinely two-page result
        # returns ONE merged array — zero newlines, zero `][`. This is the shape that must work.
        rs._REPO_SLUG_CACHE = "a/b"
        self._gh({"--paginate": (0, '[{"number":153},{"number":112}]')})
        self.assertEqual(rs._rest_open_prs(), {153, 112})

    def test_rest_open_prs_also_reads_the_two_shapes_the_normalisation_defends(self):
        # Neither is emitted by gh 2.97.0 — both have been emitted by other versions, which is why
        # the branches are kept. Pinned so a future tidy-up cannot remove them silently.
        rs._REPO_SLUG_CACHE = "a/b"
        self._gh({"--paginate": (0, '[{"number":1}][{"number":2}]')})
        self.assertEqual(rs._rest_open_prs(), {1, 2}, "concatenated arrays")
        self._gh({"--paginate": (0, '[{"number":3}]\n[{"number":4}]\n')})
        self.assertEqual(rs._rest_open_prs(), {3, 4}, "newline-delimited pages")

    def test_rest_open_prs_never_truncates_a_multi_page_answer(self):
        rs._REPO_SLUG_CACHE = "a/b"
        every = list(range(1, 251))
        body = "[" + ",".join('{"number":' + str(n) + '}' for n in every) + "]"
        self._gh({"--paginate": (0, body)})
        self.assertEqual(rs._rest_open_prs(), set(every))

    def test_rest_open_prs_refuses_rather_than_returning_the_empty_set(self):
        # An empty set is the MOST PERMISSIVE answer available ("nothing is open"), returned exactly
        # when the truth is unknown. That was A-05 in the fifth audit; None is the honest answer.
        rs._REPO_SLUG_CACHE = "a/b"
        for reply in [(1, "", "503"), (0, ""), (0, "   "), (0, "[{not json")]:
            with self.subTest(reply=reply):
                self._gh({"--paginate": reply})
                self.assertIsNone(rs._rest_open_prs())
        self._gh({"--paginate": OSError("gh vanished")})
        self.assertIsNone(rs._rest_open_prs())

    def test_an_empty_open_set_is_distinguishable_from_a_failure(self):
        rs._REPO_SLUG_CACHE = "a/b"
        self._gh({"--paginate": (0, "[]")})
        self.assertEqual(rs._rest_open_prs(), set(), "genuinely no open PRs is a SET, not None")
