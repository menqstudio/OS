"""Tests for tools/check_audit_reports.py — sixth independent audit, `A-06`.

The gate exists because the fifth round's report was never filed, and the two documents that
disagreed about it went on disagreeing for a whole round. Each test below is one of the three ways
that can happen, plus the controls that keep the gate from being red for the wrong reason.

The mutation discipline this repository uses applies to the gate itself: every rule here is proved
by building the broken repository it is supposed to refuse, not by asserting the real one passes.
"""
from __future__ import annotations

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
    def test_a_citation_that_does_not_open_is_red(self):
        # THE FINDING. The ledger names a report that was never filed.
        root = build([FOURTH], FIFTH, "fifth")
        self.assertEqual(m.main(["--root", str(root)]), 1)

    def test_a_ledger_that_was_not_repointed_is_red(self):
        # A newer report is on disk and the ledger still calls the older one current — the state
        # this repository was in for a whole round.
        root = build([FOURTH, SIXTH], FOURTH, "fourth", FOURTH, "fourth")
        self.assertEqual(m.main(["--root", str(root)]), 1)

    def test_the_two_documents_disagreeing_about_the_round_is_red(self):
        # The literal symptom: the OWNER page on the fifth, the ledger on the fourth.
        root = build([FOURTH, SIXTH], SIXTH, "fourth", SIXTH, "sixth")
        self.assertEqual(m.main(["--root", str(root)]), 1)

    # --- controls: not red for the wrong reason ----------------------------------------
    def test_no_owner_page_is_not_a_failure_of_this_gate(self):
        root = build([SIXTH], SIXTH, "sixth")
        self.assertEqual(m.main(["--root", str(root)]), 0)

    def test_a_missing_ledger_is_red_and_says_so(self):
        root = pathlib.Path(tempfile.mkdtemp())
        (root / m.AUDIT_DIR).mkdir(parents=True)
        self.assertEqual(m.main(["--root", str(root)]), 1)


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
