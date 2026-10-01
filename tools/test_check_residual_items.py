"""Self-tests for the residual-items (O-1..O-5) inventory gate.

A gate is only worth its GREEN if it is proven to go RED. These drive `check()` against
synthetic trees reproducing each way the inventory could quietly stop being true:

  * an item disappears from the inventory;
  * an item is present but never says what closes it;
  * a severity is downgraded in one document and not the other — the mechanism by which an
    accepted HIGH stops blocking a release;
  * an item is flipped to CLOSED / OWNER-DEFERRED with no named sign-off;
  * the inventory cites engine code that does not exist, which reads as verified and is not.

They also assert the real repository passes, with all five still OPEN.
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest

from check_residual_items import (ITEMS, check, declared_severities, parse_inventory,
                                  summary_owner_secret)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

_SEVERITIES = {"O-1": "HIGH", "O-2": "MEDIUM", "O-3": "MEDIUM", "O-4": "LOW", "O-5": "LOW"}


def _section(item: str, severity: str, status: str = "OPEN", extra: str = "",
             cite: str = "engine/runtime/x.py", owner: str = "no") -> str:
    return (
        f"### {item} · a title\n\n"
        f"- **Severity:** {severity}\n"
        f"- **Status:** {status}\n"
        f"- **Owner secret needed:** {owner}\n"
        f"- **Engine code:** `{cite}`\n"
        f"- **Closure requires:** do the audited thing\n"
        f"{extra}\n\n"
    )


def _summary(owner: dict[str, str] | None = None, skip: str | None = None) -> str:
    """The §0 summary table. Its `Needs an Owner secret?` column must agree with each section."""
    owner = owner or {}
    rows = ["| Item | Engine ticket | Severity | Status | Needs an Owner secret? | One-line defect |",
            "|---|---|---|---|---|---|"]
    for item, sev in _SEVERITIES.items():
        if item == skip:
            continue
        rows.append(f"| **{item}** | `T-{item}` | {sev} | OPEN | {owner.get(item, 'no')} | a defect |")
    return "\n".join(rows) + "\n\n"


def _canonical(severities: dict[str, str]) -> str:
    return "\n".join(
        f"  - **{item} ({sev})** one-line summary." for item, sev in severities.items()
    )


def _tree(inventory: str, claude: str | None = None, security: str | None = None) -> pathlib.Path:
    root = pathlib.Path(tempfile.mkdtemp())
    (root / "docs").mkdir()
    (root / "docs" / "PHASE_10_PRODUCTION_ITEMS.md").write_text(inventory, encoding="utf-8")
    (root / "CLAUDE.md").write_text(claude or _canonical(_SEVERITIES), encoding="utf-8")
    (root / "docs" / "SECURITY_MODEL.md").write_text(
        security or _canonical(_SEVERITIES), encoding="utf-8"
    )
    (root / "engine" / "runtime").mkdir(parents=True)
    (root / "engine" / "runtime" / "x.py").write_text("# stub\n", encoding="utf-8")
    return root


def _full_inventory(summary: str | None = None, **overrides: str) -> str:
    parts = []
    for item, sev in _SEVERITIES.items():
        if item in overrides:
            parts.append(overrides[item])
        else:
            parts.append(_section(item, sev))
    head = "# inventory\n\n## 0. Summary\n\n" + (summary if summary is not None else _summary())
    return head + "".join(parts)


class InventoryGateTests(unittest.TestCase):
    def test_a_complete_inventory_passes(self):
        self.assertEqual(check(_tree(_full_inventory())), [])

    def test_a_missing_item_is_RED(self):
        text = _full_inventory()
        text = text.replace(_section("O-2", "MEDIUM"), "")
        problems = check(_tree(text))
        self.assertTrue(any("O-2" in p and "no `### O-2" in p for p in problems), problems)

    def test_an_item_with_no_closure_statement_is_RED(self):
        stripped = _section("O-3", "MEDIUM").replace(
            "- **Closure requires:** do the audited thing\n", ""
        )
        problems = check(_tree(_full_inventory(**{"O-3": stripped})))
        self.assertTrue(any("Closure requires" in p for p in problems), problems)

    def test_severity_drift_against_CLAUDE_md_is_RED(self):
        """The failure mode: an accepted HIGH quietly becomes a LOW in one document."""
        downgraded = dict(_SEVERITIES, **{"O-1": "LOW"})
        problems = check(_tree(_full_inventory(), claude=_canonical(downgraded)))
        self.assertTrue(any("severity drift for O-1" in p for p in problems), problems)

    def test_severity_drift_against_SECURITY_MODEL_is_RED(self):
        downgraded = dict(_SEVERITIES, **{"O-3": "LOW"})
        problems = check(_tree(_full_inventory(), security=_canonical(downgraded)))
        self.assertTrue(any("severity drift for O-3" in p for p in problems), problems)

    def test_a_downgrade_in_ONE_of_two_statements_of_the_list_is_RED(self):
        """CLAUDE.md carries the list twice -- English, then Armenian. The gate kept only the
        last occurrence, so a downgrade in the first was invisible: the second still said
        HIGH, the comparison passed, and the document a reader opens first said LOW."""
        downgraded = dict(_SEVERITIES, **{"O-1": "LOW"})
        for label, text in (
            ("first", _canonical(downgraded) + "\n\n# Հայերեն\n\n" + _canonical(_SEVERITIES)),
            ("second", _canonical(_SEVERITIES) + "\n\n# Հայերեն\n\n" + _canonical(downgraded)),
        ):
            with self.subTest(downgraded=label):
                problems = check(_tree(_full_inventory(), claude=text))
                self.assertIn(
                    "severity drift for O-1: CLAUDE.md says LOW, "
                    "docs/PHASE_10_PRODUCTION_ITEMS.md says HIGH", " ".join(problems))
                self.assertTrue(any("CLAUDE.md disagrees with itself — it says HIGH and LOW" in p
                                    for p in problems), problems)

    def test_a_list_stated_twice_the_same_way_is_green(self):
        """The control: stating it twice is not the defect; stating it two ways is."""
        twice = _canonical(_SEVERITIES) + "\n\n# Հայերեն\n\n" + _canonical(_SEVERITIES)
        self.assertEqual(check(_tree(_full_inventory(), claude=twice, security=twice)), [])

    def test_a_canonical_doc_that_stops_naming_an_item_is_RED(self):
        partial = {k: v for k, v in _SEVERITIES.items() if k != "O-5"}
        problems = check(_tree(_full_inventory(), claude=_canonical(partial)))
        self.assertTrue(any("no severity asserted for O-5" in p for p in problems), problems)

    def test_CLOSED_without_a_sign_off_is_RED(self):
        closed = _section("O-4", "LOW", status="CLOSED")
        problems = check(_tree(_full_inventory(**{"O-4": closed})))
        self.assertTrue(any("no `**Sign-off:**`" in p for p in problems), problems)

    def test_OWNER_DEFERRED_without_a_sign_off_is_RED(self):
        deferred = _section("O-5", "LOW", status="OWNER-DEFERRED")
        problems = check(_tree(_full_inventory(**{"O-5": deferred})))
        self.assertTrue(any("no `**Sign-off:**`" in p for p in problems), problems)

    def test_CLOSED_with_a_sign_off_passes(self):
        closed = _section(
            "O-4", "LOW", status="CLOSED", extra="- **Sign-off:** Owner, PR #99, head abc1234\n"
        )
        self.assertEqual(check(_tree(_full_inventory(**{"O-4": closed}))), [])

    def test_an_unknown_status_is_RED(self):
        weird = _section("O-2", "MEDIUM", status="MOSTLY-FINE")
        problems = check(_tree(_full_inventory(**{"O-2": weird})))
        self.assertTrue(any("MOSTLY-FINE" in p for p in problems), problems)

    def test_a_citation_of_absent_engine_code_is_RED(self):
        ghost = _section("O-1", "HIGH", cite="engine/runtime/bro_deleted_module.py")
        problems = check(_tree(_full_inventory(**{"O-1": ghost})))
        self.assertTrue(any("bro_deleted_module.py" in p for p in problems), problems)

    def test_summary_table_contradicting_a_section_is_RED(self):
        """The exact drift found on 2026-08-09: the table said one thing, §1 said the other.

        `docs/SECURITY_MODEL.md` §4 said a third. The gate stayed GREEN through all of it, because
        it validated the FIELD's shape and never the summary table above it -- the part of the file
        a reader actually reads.
        """
        problems = check(_tree(_full_inventory(summary=_summary({"O-3": "yes"}))))
        self.assertTrue(any("owner-secret drift for O-3" in p for p in problems), problems)

    def test_an_item_absent_from_the_summary_table_is_RED(self):
        problems = check(_tree(_full_inventory(summary=_summary(skip="O-5"))))
        self.assertTrue(any("O-5" in p and "summary table" in p for p in problems), problems)

    def test_summary_and_section_agreeing_on_yes_passes(self):
        yes = _section("O-2", "MEDIUM", owner="yes — an operator-signed artifact")
        self.assertEqual(
            check(_tree(_full_inventory(summary=_summary({"O-2": "yes"}), **{"O-2": yes}))), [])

    def test_an_unreadable_summary_cell_is_RED(self):
        problems = check(_tree(_full_inventory(summary=_summary({"O-1": "maybe"}))))
        self.assertTrue(any("neither yes nor no" in p for p in problems), problems)

    def test_a_missing_inventory_file_is_RED(self):
        root = pathlib.Path(tempfile.mkdtemp())
        problems = check(root)
        self.assertTrue(any("missing" in p for p in problems), problems)


class ParsingTests(unittest.TestCase):
    def test_the_summary_column_is_read_from_the_right_cell(self):
        table = ("| Item | Ticket | Severity | Status | Needs an Owner secret? | Defect |\n"
                 "|---|---|---|---|---|---|\n"
                 "| **O-1** | `L-6` | HIGH | OPEN | no | the read half |\n"
                 "| **O-3** | `M-4` | MEDIUM | OPEN | **yes** (an artifact) | the token |\n")
        self.assertEqual(summary_owner_secret(table), {"O-1": "no", "O-3": "yes"})

    def test_combined_severity_lines_are_understood(self):
        """CLAUDE.md writes `**O-4 / O-5 (LOW)**` on one line."""
        found = declared_severities("  - **O-4 / O-5 (LOW)** control-room actor …")
        self.assertEqual(found, {"O-4": {"LOW"}, "O-5": {"LOW"}})

    def test_MED_is_normalised_to_MEDIUM(self):
        self.assertEqual(declared_severities("**O-2 (MED)** …"), {"O-2": {"MEDIUM"}})

    def test_every_occurrence_is_kept_not_only_the_last(self):
        text = "**O-1 (LOW)** … later … **O-1 (HIGH)** … and **O-2 (MED)** … **O-2 (MEDIUM)**"
        self.assertEqual(declared_severities(text),
                         {"O-1": {"LOW", "HIGH"}, "O-2": {"MEDIUM"}})


class LiveRepositoryTests(unittest.TestCase):
    def test_the_repository_passes_with_all_five_open(self):
        problems = check(REPO_ROOT)
        self.assertEqual(problems, [], "\n".join(problems))
        sections = parse_inventory(
            (REPO_ROOT / "docs" / "PHASE_10_PRODUCTION_ITEMS.md").read_text(encoding="utf-8")
        )
        self.assertEqual(sorted(sections), sorted(ITEMS))
        for item in ITEMS:
            self.assertEqual(sections[item]["Status"].upper(), "OPEN", item)

    def test_the_inventory_records_which_items_need_the_owner(self):
        """Every item answers yes-or-no, and today every answer is `no`.

        The history of this docstring is the reason for its shape. It first pinned "O-3 is the
        only item needing an Owner secret". Then it said the O-2 and O-5 work had put an
        audit-anchor signer and an evidence-floor anchor on the same list, and argued against pinning any membership at all. That conclusion was
        reversed by a DECISION, not by a finding: Owner decision #78 (2026-08-09) -- no person
        holds a key; the install mints trust. The inventory's five rows all read `no`, and
        CLAUDE.md §6 says none needs an Owner-minted artifact.

        So the membership is asserted again, on purpose. A `yes` reappearing here is not
        "someone learned something": it is an inventory asking a person to mint, hold or sign
        with a key, against a recorded decision, and that should go red until the decision
        itself is changed by the Owner. The old `if answer == "yes"` arm, which only asked that
        a `yes` name its artifact, had nothing left to run on and is gone.
        """
        text = (REPO_ROOT / "docs" / "PHASE_10_PRODUCTION_ITEMS.md").read_text(encoding="utf-8")
        sections = parse_inventory(text)
        for item in ITEMS:
            answer = sections[item]["Owner secret needed"].strip().lower()
            self.assertEqual(
                answer, "no",
                f"{item}: the inventory says an Owner secret is needed ({answer!r}). Owner "
                f"decision #78: no person holds a key. That is a decision for the Owner to "
                f"reverse, not a cell to edit.")


if __name__ == "__main__":
    unittest.main()
