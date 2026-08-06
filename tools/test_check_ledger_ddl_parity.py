"""Self-tests for the supervisor durable-ledger DDL single-source gate.

The gate exists because the audit's F-01 root cause was a durable state machine nobody
ran; the fix makes SQL the enforcement and two languages load it. These tests drive
``check()`` against synthetic roots, so the gate itself is proven to fail closed rather
than merely proven to print GREEN on the real tree.
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest

from check_ledger_ddl_parity import CANONICAL, MIRROR, REQUIRED_CLAUSES, check

# A minimal DDL body that satisfies every REQUIRED_CLAUSES substring. It is not valid
# standalone SQL — the gate is a text/constraint floor, not a parser — but it lets the
# tests isolate the two failure modes the gate must catch.
GOOD = (
    "PRAGMA foreign_keys = ON;\n"
    "UNIQUE (install_id, request_nonce)\n"
    "UNIQUE (challenge_handle)\n"
    "UNIQUE (execution_attempt_id)\n"
    "idx_governed_turn_acceptance_receipt\n"
    "trg_governed_turn_acceptance_transition\n"
    "RAISE(ABORT, 'illegal acceptance state transition')\n"
    "CREATE TABLE IF NOT EXISTS governed_turn_completion\n"
    "execution_attempt_id        TEXT PRIMARY KEY NOT NULL\n"
    "CREATE TABLE IF NOT EXISTS governed_evidence_head_floor\n"
)


def _root(canonical: str | None, mirror: str | None) -> pathlib.Path:
    root = pathlib.Path(tempfile.mkdtemp())
    if canonical is not None:
        p = root / CANONICAL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(canonical, encoding="utf-8")
    if mirror is not None:
        p = root / MIRROR
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(mirror, encoding="utf-8")
    return root


class LedgerDdlParityGateTests(unittest.TestCase):
    def test_identical_copies_pass(self):
        self.assertEqual(check(_root(GOOD, GOOD)), [])

    def test_divergence_is_reported(self):
        problems = check(_root(GOOD, GOOD + "-- drifted\n"))
        self.assertTrue(any("DIVERGED" in p for p in problems), problems)

    def test_a_single_byte_of_drift_is_caught(self):
        # Whitespace-only drift still means the two halves compiled different text.
        problems = check(_root(GOOD, GOOD + " "))
        self.assertTrue(any("DIVERGED" in p for p in problems), problems)

    def test_missing_canonical_is_red_not_skipped(self):
        problems = check(_root(None, GOOD))
        self.assertTrue(any("missing canonical" in p for p in problems), problems)

    def test_missing_mirror_is_red_not_skipped(self):
        problems = check(_root(GOOD, None))
        self.assertTrue(any("missing mirrored" in p for p in problems), problems)

    def test_both_missing_is_red(self):
        self.assertNotEqual(check(_root(None, None)), [])

    def test_removing_an_enforcement_clause_from_both_copies_is_still_red(self):
        # Byte-equality alone would pass this; the constraint floor is what catches it.
        for clause in REQUIRED_CLAUSES:
            with self.subTest(clause=clause):
                stripped = GOOD.replace(clause, "")
                self.assertNotEqual(stripped, GOOD, f"fixture does not contain {clause!r}")
                problems = check(_root(stripped, stripped))
                self.assertTrue(
                    any(clause in p for p in problems),
                    f"removing {clause!r} from both copies was not caught: {problems}",
                )

    def test_the_real_repository_is_green(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        self.assertEqual(check(root), [])


if __name__ == "__main__":
    unittest.main()
