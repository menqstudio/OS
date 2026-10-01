"""Tests for tools/check_audit_reports.py — sixth independent audit, `A-06`.

The gate exists because the fifth round's report was never filed, and the two documents that
disagreed about it went on disagreeing for a whole round. Each test below is one of the three ways
that can happen, plus the controls that keep the gate from being red for the wrong reason.

The mutation discipline this repository uses applies to the gate itself: every rule here is proved
by building the broken repository it is supposed to refuse, not by asserting the real one passes.
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_audit_reports as m  # noqa: E402


LEDGER_HEAD = """# Ledger

**Authoritative current assessment:** [`{report}`](./{report})
— the **{ordinal}** independent audit.
"""

OWNER_HEAD = """# Owner action required

> **{ordinal} AUDIT, 2026-08-17 — RED.** Filed at
> [`{report}`](../apps/desktop/AUDIT/{report}).
"""


def build(reports: list[str], ledger_report: str, ledger_ordinal: str,
          owner_report: str | None = None, owner_ordinal: str | None = None) -> pathlib.Path:
    """A miniature repository with the same shape as the real one."""
    root = pathlib.Path(tempfile.mkdtemp())
    audit = root / m.AUDIT_DIR
    audit.mkdir(parents=True)
    # Above MIN_REPORT_BYTES. The gate gained a size floor for the seventh audit's `G-03` — it
    # passed a zero-byte report cited by all three documents, because "openable" was implemented as
    # `.exists()`. These fixtures are testing the OTHER rules, so they must clear that floor rather
    # than trip it; the floor has its own cases below.
    for name in reports:
        (audit / name).write_text("# report\n" + ("body line\n" * 300), encoding="utf-8")
    (audit / "AUDIT_LEDGER.md").write_text(
        LEDGER_HEAD.format(report=ledger_report, ordinal=ledger_ordinal.upper()), encoding="utf-8")
    if owner_report is not None:
        docs = root / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "OWNER_ACTION_REQUIRED.md").write_text(
            OWNER_HEAD.format(report=owner_report, ordinal=(owner_ordinal or ledger_ordinal).upper()),
            encoding="utf-8")
    return root


SIXTH = "2026-08-17-sixth-audit-b16e572.md"
FIFTH = "2026-08-16-fifth-audit-5fe4740.md"
FOURTH = "2026-08-15-zero-trust-reaudit-0a9a1af.md"
#: A fourth-round report filed under the naming rule check 3b reads (`-fourth-`). FOURTH above
#: is the real file's name and does NOT carry its ordinal, which is why every fixture built on
#: it also trips 3b -- and why three tests below used to pass for a reason other than their own.
FOURTH_NAMED = "2026-08-15-fourth-audit-0a9a1af.md"


def failures_of(root: pathlib.Path) -> tuple[int, list[str], str]:
    """Run the gate; return its exit code, each failure line it printed, and its stdout."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = m.main(["--root", str(root)])
    lines = [ln[4:] for ln in err.getvalue().splitlines() if ln.startswith("  - ")]
    return code, lines, out.getvalue()


class PureFunctionTests(unittest.TestCase):
    def test_relative_links_ignores_urls_and_bare_anchors(self):
        text = "[a](./x.md) [b](https://example.com/y.md) [c](#section) [d](./z.md#frag)"
        self.assertEqual(m.relative_links(text), ["./x.md", "./z.md"])

    def test_audit_links_normalises_dot_dot(self):
        got = m.audit_links("[r](../apps/desktop/AUDIT/r.md)", pathlib.PurePosixPath("docs"))
        self.assertEqual(got, ["apps/desktop/AUDIT/r.md"])

    def test_audit_links_ignores_links_outside_the_audit_directory(self):
        self.assertEqual(m.audit_links("[t](../TASKS.md)", pathlib.PurePosixPath("docs")), [])

    def test_newest_report_reads_the_date_prefix(self):
        self.assertEqual(m.newest_report([FOURTH, SIXTH, FIFTH]), SIXTH)

    def test_newest_report_ignores_undated_files(self):
        self.assertEqual(m.newest_report(["index.md", "notes.md"]), None)

    def test_authoritative_link_reads_the_banner(self):
        self.assertEqual(
            m.authoritative_link(LEDGER_HEAD.format(report=SIXTH, ordinal="SIXTH")), SIXTH)

    def test_ordinal_reads_the_FIRST_occurrence(self):
        # Both documents lead with the current round and then describe older ones. A gate reading
        # the last mention would pass whenever the history section was longest.
        text = "> **SIXTH AUDIT** … later: the **fourth** independent audit and the **third**."
        self.assertEqual(m.ordinal_of(text), "sixth")


class GateTests(unittest.TestCase):
    def test_a_consistent_repository_is_green(self):
        root = build([FOURTH, SIXTH], SIXTH, "sixth", SIXTH, "sixth")
        self.assertEqual(m.main(["--root", str(root)]), 0)

    # --- the three ways A-06 happened ---------------------------------------------------
    #
    # Each fixture trips EXACTLY ONE rule and the test reads that rule's own message. These
    # three asserted only `main() == 1`, on fixtures that also tripped check 3b (FOURTH's
    # filename has no `-fourth-` in it) -- so checks 1, 2 and 3 could all be deleted from the
    # gate and every test here stayed green. "Every rule here is proved by building the broken
    # repository it is supposed to refuse" was true of the repositories and not of the rules.
    def only(self, root: pathlib.Path, needle: str) -> None:
        code, failures, _ = failures_of(root)
        self.assertEqual(code, 1)
        self.assertEqual(len(failures), 1, failures)
        self.assertIn(needle, failures[0])

    def test_a_citation_that_does_not_open_is_red(self):
        # THE FINDING (check 1). The ledger is otherwise in order -- authoritative link, round and
        # newest report all agree -- and it also links a report that was never filed.
        root = build([FOURTH_NAMED, SIXTH], SIXTH, "sixth", SIXTH, "sixth")
        ledger = root / m.LEDGER
        ledger.write_text(ledger.read_text(encoding="utf-8")
                          + f"\nEarlier: [`{FIFTH}`](./{FIFTH}).\n", encoding="utf-8")
        self.only(root, f"links to `{m.AUDIT_DIR}/{FIFTH}`, which does not exist")

    def test_a_ledger_that_was_not_repointed_is_red(self):
        # Check 2. A newer report is on disk, the banners already name its round, and the
        # ledger's authoritative LINK still points at the older file -- the state this
        # repository was in for a whole round.
        root = build([FOURTH_NAMED, SIXTH], FOURTH_NAMED, "sixth", SIXTH, "sixth")
        self.only(root, f"calls `{FOURTH_NAMED}` authoritative, but the newest report filed is "
                        f"`{SIXTH}`")

    def test_the_two_documents_disagreeing_about_the_round_is_red(self):
        # Check 3, the literal symptom: the ledger on the sixth, the OWNER page on the fourth.
        root = build([FOURTH_NAMED, SIXTH], SIXTH, "sixth", SIXTH, "fourth")
        self.only(root, "leads with the SIXTH round and docs/OWNER_ACTION_REQUIRED.md leads with "
                        "the FOURTH")

    def test_a_round_announced_behind_the_newest_report_is_red(self):
        # Check 3b, second arm: the banner still says FOURTH, its report is filed, and a newer
        # report is on disk. Either a round happened and the banners did not move, or a report
        # was filed under the wrong ordinal.
        root = build([FOURTH_NAMED, SIXTH], SIXTH, "fourth")
        self.only(root, f"announces the FOURTH round, whose newest report is `{FOURTH_NAMED}`, "
                        f"but `{SIXTH}` is newer")

    def test_a_round_cited_in_a_source_comment_with_no_report_is_red(self):
        # Check 3d (`H-02`): nothing ANNOUNCES a seventh round, and a comment cites one.
        root = build([FOURTH_NAMED, SIXTH], SIXTH, "sixth", SIXTH, "sixth")
        (root / "docs" / "NOTES.md").write_text("Closed by (G-05, seventh audit).\n",
                                                encoding="utf-8")
        self.only(root, "`docs/NOTES.md` cites the SEVENTH round and no report")

    def test_a_document_that_announces_no_round_is_red_not_skipped(self):
        """The comparison was `if led and own and led != own`: a banner the gate could not
        read made the check vanish, and the GREEN line still said both pages "lead with" the
        newest report."""
        root = build([FOURTH_NAMED, SIXTH], SIXTH, "sixth", SIXTH, "sixth")
        owner = root / m.OWNER
        owner.write_text(owner.read_text(encoding="utf-8").replace("**SIXTH AUDIT", "**AUDIT"),
                         encoding="utf-8")
        self.only(root, "docs/OWNER_ACTION_REQUIRED.md announces no round this gate can read")

        root = build([FOURTH_NAMED, SIXTH], SIXTH, "sixth", SIXTH, "sixth")
        ledger = root / m.LEDGER
        ledger.write_text(ledger.read_text(encoding="utf-8").replace("**SIXTH**", "the current"),
                          encoding="utf-8")
        code, failures, _ = failures_of(root)
        self.assertEqual(code, 1)
        self.assertTrue(any("AUDIT_LEDGER.md announces no round" in f for f in failures), failures)

    def test_a_ledger_with_no_authoritative_link_is_red(self):
        # Check 2's other arm: nothing says which report is in force, so there is nothing to
        # compare with the newest one. Not a pass.
        root = build([FOURTH_NAMED, SIXTH], SIXTH, "sixth", SIXTH, "sixth")
        (root / m.LEDGER).write_text("# Ledger\n\nThe **SIXTH** independent audit is current.\n",
                                     encoding="utf-8")
        self.only(root, "has no '**Authoritative current assessment:**' link")

    def test_the_green_line_says_what_was_compared(self):
        _, _, out = failures_of(build([FOURTH_NAMED, SIXTH], SIXTH, "sixth", SIXTH, "sixth"))
        self.assertIn(f"calls `{SIXTH}` authoritative and it is the newest report filed", out)
        self.assertIn("docs/OWNER_ACTION_REQUIRED.md announces the same round (SIXTH)", out)
        self.assertNotIn("both lead", out)
        # ... and with no OWNER page it does not claim the page agreed.
        _, _, out = failures_of(build([SIXTH], SIXTH, "sixth"))
        self.assertIn("docs/OWNER_ACTION_REQUIRED.md is absent, so no second document was "
                      "compared", out)

    # --- controls: not red for the wrong reason ----------------------------------------
    def test_no_owner_page_is_not_a_failure_of_this_gate(self):
        root = build([SIXTH], SIXTH, "sixth")
        self.assertEqual(m.main(["--root", str(root)]), 0)

    def test_a_missing_ledger_is_red_and_says_so(self):
        root = pathlib.Path(tempfile.mkdtemp())
        (root / m.AUDIT_DIR).mkdir(parents=True)
        self.assertEqual(m.main(["--root", str(root)]), 1)


class TheListOfRounds(unittest.TestCase):
    """ORDINALS ended at "tenth" while the standing round was the tenth.

    The round words below are never written next to the word they are filed under: this file
    is itself inside the gate's citation scan (`tools/*.py`), and a literal naming a round that
    has no report would turn the real repository RED -- which it did, on the first run of these
    tests. The gate was right; a fixture is not a citation, so it is assembled.
    """

    NEXT = "eleventh"
    FAR = "sixteenth"
    TENTH = "2026-09-19-tenth-audit-75fca65.md"

    @staticmethod
    def filed(round_word: str, date: str = "2026-10-20") -> str:
        return "-".join((date, round_word, "audit", "abcdef0.md"))

    def setUp(self):
        self.ELEVENTH = self.filed(self.NEXT)

    def test_an_eleventh_round_is_read_as_the_eleventh(self):
        banner = "> **" + self.NEXT.upper() + " " + "AUDIT** … earlier: the **tenth** audit."
        self.assertEqual(m.ordinal_of(banner), self.NEXT)
        self.assertEqual(m.ordinal_of("the **" + self.FAR + "** independent " + "audit"), self.FAR)
        root = build([self.TENTH, self.ELEVENTH], self.ELEVENTH, self.NEXT,
                     self.ELEVENTH, self.NEXT)
        code, failures, _ = failures_of(root)
        self.assertEqual((code, failures), (0, []))

    def test_an_eleventh_banner_with_no_eleventh_report_is_red_for_THAT_reason(self):
        """Before, ELEVENTH did not match at all: the first match fell to an older round and
        the failure named the wrong ordinal."""
        root = build([self.TENTH], self.TENTH, self.NEXT, self.TENTH, self.NEXT)
        _, failures, _ = failures_of(root)
        self.assertTrue(any("announces the ELEVENTH round and no report" in f for f in failures),
                        failures)

    def test_a_report_filed_under_an_ordinal_the_list_lacks_is_red(self):
        beyond = self.filed("twenty-first", "2027-01-05")
        self.assertEqual(m.unknown_ordinal_reports([beyond, self.TENTH, FOURTH,
                                                    "2026-08-06-independent-audit.md",
                                                    "2026-08-06-remediation-audit.md"]),
                         [(beyond, "twenty-first")])
        root = build([self.TENTH, beyond], beyond, "tenth")
        _, failures, _ = failures_of(root)
        self.assertTrue(any("is filed as the `twenty-first` round" in f and "Extend the list" in f
                            for f in failures), failures)

    def test_every_real_report_is_one_the_list_can_rank(self):
        reports = [p.name for p in (m.ROOT / m.AUDIT_DIR).glob("*.md")]
        self.assertEqual(m.unknown_ordinal_reports(reports), [])


class AnnouncedRoundTests(unittest.TestCase):
    """`G-03` — the gate written to close `A-06` did not detect `A-06`.

    Checks 1-3 compare the ledger, the OWNER page and the directory TO EACH OTHER. The auditor set
    both banners to SEVENTH with no seventh report filed and got GREEN: agreeing with each other is
    not the same as being current. And "openable" was `.exists()` — a zero-byte file cited by all
    three documents also passed.
    """

    def test_an_announced_round_with_no_report_is_red(self):
        # THE FINDING. Ledger and OWNER page both say SEVENTH; only a sixth report exists.
        root = build([FOURTH, SIXTH], SIXTH, "seventh", SIXTH, "seventh")
        f = m.main(["--root", str(root)])
        self.assertEqual(f, 1)

    def test_an_announced_round_with_its_report_is_green(self):
        seventh = "2026-08-18-seventh-audit-491f923.md"
        root = build([SIXTH, seventh], seventh, "seventh", seventh, "seventh")
        self.assertEqual(m.main(["--root", str(root)]), 0)

    def test_a_zero_byte_report_is_not_a_report(self):
        root = build([SIXTH], SIXTH, "sixth", SIXTH, "sixth")
        (root / m.AUDIT_DIR / SIXTH).write_text("", encoding="utf-8")
        self.assertEqual(m.main(["--root", str(root)]), 1)

    def test_the_size_floor_is_a_smoke_check_and_says_so(self):
        # Pinned so nobody later defends it as a guarantee: padding satisfies it, deliberately.
        root = build([SIXTH], SIXTH, "sixth", SIXTH, "sixth")
        (root / m.AUDIT_DIR / SIXTH).write_text("x" * (m.MIN_REPORT_BYTES + 1), encoding="utf-8")
        self.assertEqual(m.main(["--root", str(root)]), 0)


class StateAnchorTests(unittest.TestCase):
    """Section 4 — the machine-readable anchor, which was carrying the same defect, worse.

    `config/current_state.json` named the `2026-08-06` remediation audit and asserted *"no
    independent audit has been run on any later head"* after four more had run. Five rounds stale,
    in the file `check_coordination.py` makes the human documents agree with.
    """

    def state(self, root: pathlib.Path, sentence: str) -> None:
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / m.STATE).write_text('{"purpose": "%s"}' % sentence, encoding="utf-8")

    def test_a_state_pointer_at_the_newest_report_is_green(self):
        root = build([FOURTH, SIXTH], SIXTH, "sixth", SIXTH, "sixth")
        self.state(root, f"AUDIT POSITION: the last INDEPENDENT audit -- {m.AUDIT_DIR}/{SIXTH} -- returned RED.")
        self.assertEqual(m.main(["--root", str(root)]), 0)

    def test_a_state_pointer_left_behind_is_red(self):
        # THE REAL DEFECT, as a test.
        root = build([FOURTH, SIXTH], SIXTH, "sixth", SIXTH, "sixth")
        self.state(root, f"AUDIT POSITION: the last INDEPENDENT audit -- {m.AUDIT_DIR}/{FOURTH} -- returned RED.")
        self.assertEqual(m.main(["--root", str(root)]), 1)

    def test_a_state_pointer_at_a_report_that_was_never_filed_is_red(self):
        root = build([FOURTH, SIXTH], SIXTH, "sixth", SIXTH, "sixth")
        self.state(root, f"AUDIT POSITION: the last INDEPENDENT audit -- {m.AUDIT_DIR}/{FIFTH} -- returned RED.")
        self.assertEqual(m.main(["--root", str(root)]), 1)

    def test_a_state_file_with_no_audit_position_at_all_is_red(self):
        # Deleting the sentence must not be the cheap way to pass.
        root = build([SIXTH], SIXTH, "sixth", SIXTH, "sixth")
        self.state(root, "no audit position here")
        self.assertEqual(m.main(["--root", str(root)]), 1)

    # --- the pointer as a FIELD (T-045 regression) --------------------------------------
    # `purpose` held the pointer inside 74k characters of prose. Cutting that paragraph
    # deleted the pointer with it and turned this gate RED on a change that had nothing to
    # do with the audit trail. A regex over prose is a pointer a rewrite can lose.

    def field_state(self, root: pathlib.Path, pointer: str | None, purpose: str = "") -> None:
        (root / "config").mkdir(parents=True, exist_ok=True)
        audit: dict[str, str] = {"gate": "ARCHITECT_PENDING"}
        if pointer is not None:
            audit["last_independent_audit"] = pointer
        (root / m.STATE).write_text(
            json.dumps({"purpose": purpose, "code_audit": audit}), encoding="utf-8")

    def test_a_pointer_in_the_code_audit_field_is_green(self):
        root = build([FOURTH, SIXTH], SIXTH, "sixth", SIXTH, "sixth")
        self.field_state(root, f"{m.AUDIT_DIR}/{SIXTH}")
        self.assertEqual(m.main(["--root", str(root)]), 0)

    def test_a_field_pointer_left_behind_is_red(self):
        root = build([FOURTH, SIXTH], SIXTH, "sixth", SIXTH, "sixth")
        self.field_state(root, f"{m.AUDIT_DIR}/{FOURTH}")
        self.assertEqual(m.main(["--root", str(root)]), 1)

    def test_a_field_pointer_at_a_report_never_filed_is_red(self):
        root = build([FOURTH, SIXTH], SIXTH, "sixth", SIXTH, "sixth")
        self.field_state(root, f"{m.AUDIT_DIR}/{FIFTH}")
        self.assertEqual(m.main(["--root", str(root)]), 1)

    def test_the_field_is_authoritative_over_a_stale_sentence(self):
        # Both present and disagreeing: the machine-readable field decides, so a leftover
        # sentence in prose cannot hold the gate green after the field has moved on.
        root = build([FOURTH, SIXTH], SIXTH, "sixth", SIXTH, "sixth")
        self.field_state(
            root, f"{m.AUDIT_DIR}/{FOURTH}",
            purpose=f"AUDIT POSITION: the last INDEPENDENT audit -- {m.AUDIT_DIR}/{SIXTH} -- returned RED.")
        self.assertEqual(m.main(["--root", str(root)]), 1)

    def test_an_empty_field_falls_back_to_the_sentence(self):
        # Deleting the field must not silently disable the prose form older docs still use.
        root = build([FOURTH, SIXTH], SIXTH, "sixth", SIXTH, "sixth")
        self.field_state(
            root, "   ",
            purpose=f"AUDIT POSITION: the last INDEPENDENT audit -- {m.AUDIT_DIR}/{SIXTH} -- returned RED.")
        self.assertEqual(m.main(["--root", str(root)]), 0)

    def test_neither_field_nor_sentence_is_red(self):
        root = build([SIXTH], SIXTH, "sixth", SIXTH, "sixth")
        self.field_state(root, None)
        self.assertEqual(m.main(["--root", str(root)]), 1)

    def test_the_pointer_is_read_from_the_sentence_not_from_any_path(self):
        text = (f"the index is {m.AUDIT_DIR}/AUDIT_LEDGER.md. "
                f"AUDIT POSITION: the last INDEPENDENT audit -- {m.AUDIT_DIR}/{SIXTH} -- returned RED.")
        self.assertEqual(m.state_audit_pointer(text), f"{m.AUDIT_DIR}/{SIXTH}")


class RealRepositoryTests(unittest.TestCase):
    """The regression: the repository as it stands."""

    def test_the_real_audit_trail_opens_today(self):
        self.assertEqual(m.main([]), 0)

    def test_the_sixth_round_report_is_actually_filed(self):
        # Named explicitly rather than left to the generic rule, because this file existing is the
        # remediation of A-06 and a rule can be satisfied by deleting the citation instead.
        self.assertTrue((m.ROOT / m.AUDIT_DIR / SIXTH).exists())


if __name__ == "__main__":
    unittest.main()
