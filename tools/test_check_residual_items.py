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

from check_residual_items import ITEMS, check, declared_severities, parse_inventory

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

_SEVERITIES = {"O-1": "HIGH", "O-2": "MEDIUM", "O-3": "MEDIUM", "O-4": "LOW", "O-5": "LOW"}


def _section(item: str, severity: str, status: str = "OPEN", extra: str = "", cite: str = "engine/runtime/x.py") -> str:
    return (
        f"### {item} · a title\n\n"
        f"- **Severity:** {severity}\n"
        f"- **Status:** {status}\n"
        f"- **Owner secret needed:** no\n"
        f"- **Engine code:** `{cite}`\n"
        f"- **Closure requires:** do the audited thing\n"
        f"{extra}\n\n"
    )


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


def _full_inventory(**overrides: str) -> str:
    parts = []
    for item, sev in _SEVERITIES.items():
        if item in overrides:
            parts.append(overrides[item])
        else:
            parts.append(_section(item, sev))
    return "# inventory\n\n" + "".join(parts)


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

    def test_a_missing_inventory_file_is_RED(self):
        root = pathlib.Path(tempfile.mkdtemp())
        problems = check(root)
        self.assertTrue(any("missing" in p for p in problems), problems)


class ParsingTests(unittest.TestCase):
    def test_combined_severity_lines_are_understood(self):
        """CLAUDE.md writes `**O-4 / O-5 (LOW)**` on one line."""
        found = declared_severities("  - **O-4 / O-5 (LOW)** control-room actor …")
        self.assertEqual(found, {"O-4": "LOW", "O-5": "LOW"})

    def test_MED_is_normalised_to_MEDIUM(self):
        self.assertEqual(declared_severities("**O-2 (MED)** …"), {"O-2": "MEDIUM"})


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
        sections = parse_inventory(
            (REPO_ROOT / "docs" / "PHASE_10_PRODUCTION_ITEMS.md").read_text(encoding="utf-8")
        )
        answers = {i: sections[i]["Owner secret needed"].lower() for i in ITEMS}
        # O-3 is the only residual item whose closure needs something only the Owner can mint.
        self.assertTrue(answers["O-3"].startswith("yes"), answers)
        for item in ("O-1", "O-2", "O-4", "O-5"):
            self.assertTrue(answers[item].startswith("no"), answers)


if __name__ == "__main__":
    unittest.main()
