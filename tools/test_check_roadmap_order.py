"""Self-tests for the roadmap-order rule.

A gate is only worth its GREEN if it is proven to go RED. These cover the two
halves separately: the STRUCTURAL cross-check (Definition of Done vs the status
board -- the thing that makes a one-character checkbox flip insufficient), and the
SESSION declaration (working phase N+1 while N is open is refused by name).
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest

import check_read_receipt as receipts
import check_roadmap_order as order

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
NOTE = "closing the last open Definition-of-Done item for this phase, with evidence"


def _phase(number: int, dod: list[bool]) -> str:
    boxes = "\n".join(f"- [{'x' if done else ' '}] item {i}" for i, done in enumerate(dod))
    return (f"## Phase {number} — Name\n\n**Objective.** words.\n\n"
            f"**Definition of Done.**\n{boxes}\n\n"
            "**Task checklist.**\n- [ ] something else entirely\n\n---\n\n")


def _board(rows: dict[int, bool]) -> str:
    lines = ["### Phase status board", "", "| Phase | Name | Status |", "|---|---|---|"]
    for number, done in sorted(rows.items()):
        lines.append(f"| {number} | Name | {'✅ **Locked (done)**' if done else '🔨 In progress'} |")
    return "\n".join(lines) + "\n\n## Phases\n\n"


def _tree(dod: dict[int, list[bool]], board: dict[int, bool] | None = None,
          exemptions: dict | None = None) -> pathlib.Path:
    root = pathlib.Path(tempfile.mkdtemp()) / "repo"
    (root / "config").mkdir(parents=True)
    board = board if board is not None else {n: all(v) and bool(v) for n, v in dod.items()}
    text = "# Roadmap\n\n" + _board(board) + "".join(_phase(n, v) for n, v in sorted(dod.items()))
    (root / order.ROADMAP).write_text(text, encoding="utf-8")
    (root / receipts.MANIFEST).write_text(
        json.dumps({"paths": [order.ROADMAP]}), encoding="utf-8")
    if exemptions is not None:
        (root / order.EXEMPTIONS).write_text(
            json.dumps({"exemptions": exemptions}), encoding="utf-8")
    return root


class StructuralTests(unittest.TestCase):
    def test_agreeing_surfaces_are_green(self):
        self.assertEqual(order.structural_problems(_tree({0: [True], 1: [False]})), [])

    def test_first_open_phase_is_the_lowest_incomplete_one(self):
        self.assertEqual(order.first_open_phase(_tree({0: [True], 1: [False], 2: [False]})), 1)

    def test_all_complete_returns_none(self):
        self.assertIsNone(order.first_open_phase(_tree({0: [True], 1: [True]})))

    def test_flipping_only_the_checkboxes_is_refused(self):
        """The anti-string-edit measure: the lie has to be told twice, consistently."""
        problems = order.structural_problems(_tree({0: [True], 1: [True]}, board={0: True, 1: False}))
        self.assertEqual(len(problems), 1)
        self.assertIn("Phase 1", problems[0])
        self.assertIn("status board says open", problems[0])

    def test_flipping_only_the_board_is_refused(self):
        problems = order.structural_problems(_tree({0: [True], 1: [False]}, board={0: True, 1: True}))
        self.assertEqual(len(problems), 1)
        self.assertIn("Definition of Done says open", problems[0])

    def test_deleting_every_checkbox_does_not_complete_a_phase(self):
        """An empty checklist would otherwise be the cheapest way to declare done."""
        root = _tree({0: [True], 1: []}, board={0: True, 1: True})
        self.assertFalse(order.dod_state(root)[1]["complete"])
        self.assertTrue(order.structural_problems(root))

    def test_a_phase_missing_from_the_board_is_refused(self):
        problems = order.structural_problems(_tree({0: [True], 1: [False]}, board={0: True}))
        self.assertIn("no row in the Phase status board", problems[0])

    def test_a_roadmap_without_a_board_heading_is_refused(self):
        root = _tree({0: [True]})
        (root / order.ROADMAP).write_text("# Roadmap\n\n" + _phase(0, [True]), encoding="utf-8")
        with self.assertRaises(order.RoadmapError):
            order.board_state(root)

    def test_the_real_roadmap_is_self_consistent(self):
        self.assertEqual(order.structural_problems(REPO_ROOT), [])

    def test_the_real_roadmap_first_open_phase_is_readable(self):
        self.assertIsInstance(order.first_open_phase(REPO_ROOT), int)


class DeclarationTests(unittest.TestCase):
    def setUp(self):
        self.store = pathlib.Path(tempfile.mkdtemp())
        os.environ["BRO_RECEIPT_DIR"] = str(self.store)
        self.addCleanup(os.environ.pop, "BRO_RECEIPT_DIR", None)
        self.root = _tree({0: [True], 1: [False], 2: [False]})
        receipts.record(self.root, "s1")

    def test_undeclared_is_refused_and_names_the_open_phase(self):
        ok, why = order.verify_declaration(self.root, "s1")
        self.assertFalse(ok)
        self.assertIn("has not declared", why)
        self.assertIn("Phase 1", why)

    def test_declaring_the_open_phase_is_allowed(self):
        ok, why = order.declare(self.root, "s1", 1, NOTE)
        self.assertTrue(ok, why)

    def test_declaring_a_later_phase_is_refused_by_name(self):
        ok, why = order.declare(self.root, "s1", 2, NOTE)
        self.assertFalse(ok)
        self.assertIn("declared Phase 2 while Phase 1 is still open", why)
        self.assertIn(order.EXEMPTIONS, why)

    def test_declaring_a_completed_phase_is_refused(self):
        ok, why = order.declare(self.root, "s1", 0, NOTE)
        self.assertFalse(ok)
        self.assertIn("already complete", why)

    def test_a_committed_exemption_permits_working_ahead(self):
        root = _tree({0: [True], 1: [False], 2: [False]}, exemptions={
            "2": {"reason": "a security fix in phase 2 that cannot wait for phase 1 to close, "
                            "approved out of band by the Owner",
                  "approved_by": "Gev"}})
        receipts.record(root, "s1")
        ok, why = order.declare(root, "s1", 2, NOTE)
        self.assertTrue(ok, why)
        self.assertIn("committed exemption", why)

    def test_an_exemption_without_an_approver_does_not_count(self):
        root = _tree({0: [True], 1: [False], 2: [False]}, exemptions={
            "2": {"reason": "a security fix in phase 2 that cannot wait for phase 1 to close, "
                            "approved out of band by nobody in particular"}})
        receipts.record(root, "s1")
        ok, why = order.declare(root, "s1", 2, NOTE)
        self.assertFalse(ok)
        self.assertIn("names no approver", why)

    def test_an_exemption_with_a_placeholder_reason_does_not_count(self):
        root = _tree({0: [True], 1: [False], 2: [False]},
                     exemptions={"2": {"reason": "needed", "approved_by": "Gev"}})
        receipts.record(root, "s1")
        ok, why = order.declare(root, "s1", 2, NOTE)
        self.assertFalse(ok)
        self.assertIn("no real reason", why)

    def test_an_expired_exemption_does_not_count(self):
        root = _tree({0: [True], 1: [False], 2: [False]}, exemptions={
            "2": {"reason": "a security fix in phase 2 that cannot wait for phase 1 to close, "
                            "approved out of band by the Owner",
                  "approved_by": "Gev", "expires_at_epoch": 1}})
        receipts.record(root, "s1")
        ok, why = order.declare(root, "s1", 2, NOTE)
        self.assertFalse(ok)
        self.assertIn("expired", why)

    def test_declaring_without_a_read_receipt_is_refused(self):
        (self.root / order.ROADMAP).write_text("# changed\n\n" + _board({0: True}), encoding="utf-8")
        ok, why = order.declare(self.root, "s1", 1, NOTE)
        self.assertFalse(ok)
        self.assertIn("full read", why)

    def test_a_declaration_note_must_say_something(self):
        ok, why = order.declare(self.root, "s1", 1, "wip")
        self.assertFalse(ok)
        self.assertIn("--note", why)

    def test_a_declaration_stops_being_valid_when_the_phase_closes(self):
        """Re-derived every call, never trusted from the receipt."""
        self.assertTrue(order.declare(self.root, "s1", 1, NOTE)[0])
        closed = _tree({0: [True], 1: [True], 2: [False]})
        receipts.record(closed, "s1")
        document = receipts.load(closed, "s1")
        document["declared_phase"] = 1
        receipts.write_receipt(closed, "s1", document)
        ok, why = order.verify_declaration(closed, "s1")
        self.assertFalse(ok)
        self.assertIn("already complete", why)

    def test_meta_is_allowed_and_path_scoped(self):
        ok, why = order.declare(self.root, "s1", order.META, NOTE)
        self.assertTrue(ok, why)
        self.assertIsNone(order.scope_problem(self.root, "s1", "tools/check_x.py"))
        self.assertIsNone(order.scope_problem(self.root, "s1", "README.md"))
        problem = order.scope_problem(self.root, "s1", "apps/desktop/src/App.tsx")
        self.assertIsNotNone(problem)
        self.assertIn("may not edit", problem)

    def test_a_numbered_phase_has_no_path_scope(self):
        """Stated rather than faked: a phase's scope is prose, and inventing a path
        list for it would be a check that pretends to know something it does not."""
        self.assertTrue(order.declare(self.root, "s1", 1, NOTE)[0])
        self.assertIsNone(order.scope_problem(self.root, "s1", "apps/desktop/src/App.tsx"))

    def test_an_inconsistent_roadmap_blocks_declaration_entirely(self):
        root = _tree({0: [True], 1: [True]}, board={0: True, 1: False})
        receipts.record(root, "s1")
        ok, why = order.verify_declaration(root, "s1")
        self.assertFalse(ok)
        self.assertIn("self-inconsistent", why)


if __name__ == "__main__":
    unittest.main()


class RefusedDeclarationRollbackTests(unittest.TestCase):
    """A refused declaration must leave no trace.

    Found by driving the wall on a throwaway copy: an attempt to declare Phase 10
    was correctly refused and then PERSISTED, so every later edit was denied for a
    phase the session had never been allowed to claim. A gate that punishes the
    attempt to obey it is a gate people route around.
    """

    def setUp(self):
        self.store = pathlib.Path(tempfile.mkdtemp())
        os.environ["BRO_RECEIPT_DIR"] = str(self.store)
        self.addCleanup(os.environ.pop, "BRO_RECEIPT_DIR", None)
        self.root = _tree({0: [True], 1: [False], 2: [False]})
        receipts.record(self.root, "s1")

    def test_a_refused_declaration_does_not_persist(self):
        self.assertFalse(order.declare(self.root, "s1", 2, NOTE)[0])
        self.assertIsNone(receipts.load(self.root, "s1")["declared_phase"])

    def test_a_refused_declaration_does_not_overwrite_a_good_one(self):
        self.assertTrue(order.declare(self.root, "s1", 1, NOTE)[0])
        self.assertFalse(order.declare(self.root, "s1", 2, NOTE)[0])
        self.assertEqual(receipts.load(self.root, "s1")["declared_phase"], 1)
        self.assertTrue(order.verify_declaration(self.root, "s1")[0])
