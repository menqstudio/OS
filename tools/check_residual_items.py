#!/usr/bin/env python3
"""Fail-closed CI gate: the residual engine items O-1..O-5 have a real, non-drifting inventory.

**Why this exists.** `MASTER_EXECUTION_ROADMAP.md` §Phase-10 makes *"O-1..O-5 closed or
owner-signed-deferred (each audited)"* an exit criterion, and `docs/SECURITY_MODEL.md` §5 makes
it a precondition for flipping the production `trusted_verified` gate. Yet before
`docs/PHASE_10_PRODUCTION_ITEMS.md` existed, the five items were only one-line summaries
duplicated across four documents — no file said what any of them *required*, one of them is an
accepted HIGH, and the independent audit's own check recorded
`no evidence found — grep for O-1/O-5 matched only [prose]`. An accepted HIGH cannot be tracked
by prose that drifts, and a duplicated one-liner drifts by construction.

This gate makes the inventory a checked claim rather than a description:

  1. `docs/PHASE_10_PRODUCTION_ITEMS.md` carries exactly one section per item O-1..O-5.
  2. Each section declares Severity, Status, `Owner secret needed`, `Engine code` and
     `Closure requires` — so "what is O-2?" always has an answer in one place.
  3. Declared severities MATCH what `CLAUDE.md` §6 and `docs/SECURITY_MODEL.md` §4 assert. A
     severity silently downgraded in one document turns this RED.
  4. Every `engine/...` path cited by an item EXISTS. An inventory that points at deleted code
     is worse than none — it reads as verified.
  5. A status may not leave `OPEN` without a `Sign-off:` line. `CLOSED` and `OWNER-DEFERRED`
     are audited verdicts; neither may be asserted by editing a word.

Exit 0 = pass. Exit 1 = a violation. No other outcome.
"""

from __future__ import annotations

import pathlib
import re
import sys

INVENTORY = "docs/PHASE_10_PRODUCTION_ITEMS.md"
ITEMS = ("O-1", "O-2", "O-3", "O-4", "O-5")

VALID_SEVERITIES = {"HIGH", "MEDIUM", "LOW"}
VALID_STATUSES = {"OPEN", "CLOSED", "OWNER-DEFERRED"}
#: A status other than OPEN is an audited verdict and needs named evidence.
NEEDS_SIGN_OFF = {"CLOSED", "OWNER-DEFERRED"}

REQUIRED_FIELDS = ("Severity", "Status", "Owner secret needed", "Engine code", "Closure requires")

#: `MED` is the abbreviation both CLAUDE.md and SECURITY_MODEL.md use for MEDIUM.
_SEVERITY_ALIASES = {"MED": "MEDIUM", "MEDIUM": "MEDIUM", "HIGH": "HIGH", "LOW": "LOW"}

_SECTION_RE = re.compile(r"^###\s+(O-[1-5])\s+·\s+(.+?)\s*$", re.MULTILINE)
_FIELD_RE = re.compile(r"^-\s+\*\*(?P<label>[^*]+?):\*\*\s*(?P<value>.*)$", re.MULTILINE)
#: `engine/a/b.py`, with or without a `:line` suffix, inside backticks or bare.
_ENGINE_PATH_RE = re.compile(r"(engine/[A-Za-z0-9_./-]+\.(?:py|json|md|yml|toml))")


def _read(root: pathlib.Path, rel: str, problems: list[str]) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8")
    except OSError as exc:
        problems.append(f"{rel}: unreadable ({exc})")
        return ""


def parse_inventory(text: str) -> dict[str, dict[str, str]]:
    """Return {item: {field label: value}} for every `### O-N · title` section."""
    sections: dict[str, dict[str, str]] = {}
    matches = list(_SECTION_RE.finditer(text))
    for index, match in enumerate(matches):
        item = match.group(1)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end(): end]
        fields = {m.group("label").strip(): m.group("value").strip() for m in _FIELD_RE.finditer(body)}
        fields["__body__"] = body
        fields["__title__"] = match.group(2)
        sections[item] = fields
    return sections


def declared_severities(text: str) -> dict[str, str]:
    """Severities a canonical doc asserts, e.g. `**O-1 (HIGH)**` or `**O-4 / O-5 (LOW)**`."""
    found: dict[str, str] = {}
    for match in re.finditer(r"\*\*((?:O-[1-5])(?:\s*/\s*O-[1-5])*)\s*\((HIGH|MED|MEDIUM|LOW)\)\*\*", text):
        severity = _SEVERITY_ALIASES[match.group(2).upper()]
        for item in re.findall(r"O-[1-5]", match.group(1)):
            found[item] = severity
    return found


def check(root: pathlib.Path) -> list[str]:
    problems: list[str] = []

    text = _read(root, INVENTORY, problems)
    if not text:
        problems.append(
            f"{INVENTORY}: missing — Phase 10 cannot claim 'O-1..O-5 closed or owner-signed-"
            f"deferred' when no file records what the five items are"
        )
        return problems

    sections = parse_inventory(text)

    # ---- rule 1: completeness ----
    for item in ITEMS:
        if item not in sections:
            problems.append(
                f"{INVENTORY}: no `### {item} · <title>` section — every residual item must be "
                f"answerable from this one file"
            )
    for extra in sorted(set(sections) - set(ITEMS)):
        problems.append(f"{INVENTORY}: unexpected item section {extra}")

    # ---- rules 2, 4, 5 ----
    for item in ITEMS:
        fields = sections.get(item)
        if fields is None:
            continue
        for label in REQUIRED_FIELDS:
            if label not in fields or not fields[label]:
                problems.append(f"{INVENTORY}: {item} does not declare `**{label}:**`")

        severity = fields.get("Severity", "").upper()
        if severity and severity not in VALID_SEVERITIES:
            problems.append(
                f"{INVENTORY}: {item} severity {severity!r} is not one of "
                f"{sorted(VALID_SEVERITIES)}"
            )

        status = fields.get("Status", "").upper()
        if status and status not in VALID_STATUSES:
            problems.append(
                f"{INVENTORY}: {item} status {status!r} is not one of {sorted(VALID_STATUSES)}"
            )
        if status in NEEDS_SIGN_OFF and "Sign-off:" not in fields.get("__body__", ""):
            problems.append(
                f"{INVENTORY}: {item} is marked {status} with no `**Sign-off:**` line — closing "
                f"or deferring a residual security item is an audited verdict, not a word edit"
            )

        owner = fields.get("Owner secret needed", "").lower()
        if owner and not owner.startswith(("yes", "no")):
            problems.append(
                f"{INVENTORY}: {item} `Owner secret needed` must start with yes/no (got "
                f"{owner[:24]!r}) — this is the field that separates 'we can fix it' from "
                f"'only Gev can'"
            )

        # rule 4: every cited engine path must exist.
        for cited in sorted(set(_ENGINE_PATH_RE.findall(fields.get("__body__", "")))):
            if not (root / cited).exists():
                problems.append(
                    f"{INVENTORY}: {item} cites `{cited}`, which does not exist — an inventory "
                    f"pointing at absent code reads as verified and is not"
                )

    # ---- rule 3: severities must agree with the canonical docs ----
    for rel in ("CLAUDE.md", "docs/SECURITY_MODEL.md"):
        doc = _read(root, rel, problems)
        if not doc:
            continue
        asserted = declared_severities(doc)
        missing = [i for i in ITEMS if i not in asserted]
        if missing:
            problems.append(
                f"{rel}: no severity asserted for {', '.join(missing)} — this document is a "
                f"canonical source for the residual items and must keep naming them"
            )
        for item, severity in sorted(asserted.items()):
            declared = sections.get(item, {}).get("Severity", "").upper()
            if declared and declared != severity:
                problems.append(
                    f"severity drift for {item}: {rel} says {severity}, {INVENTORY} says "
                    f"{declared} — one of them is wrong and a downgraded severity is how an "
                    f"accepted HIGH quietly stops blocking a release"
                )

    return problems


def main(argv: list[str] | None = None) -> int:
    root = (
        pathlib.Path(argv[0]).resolve()
        if argv
        else pathlib.Path(__file__).resolve().parents[1]
    )
    problems = check(root)
    if problems:
        print("RED: residual-items inventory gate failed")
        for p in problems:
            print(f"  - {p}")
        return 1
    text = (root / INVENTORY).read_text(encoding="utf-8")
    sections = parse_inventory(text)
    open_items = [i for i in ITEMS if sections[i].get("Status", "").upper() == "OPEN"]
    print(
        f"GREEN: {len(ITEMS)} residual engine items inventoried in {INVENTORY} "
        f"({len(open_items)} OPEN: {', '.join(open_items) or 'none'}); severities agree with "
        f"CLAUDE.md and docs/SECURITY_MODEL.md; every cited engine path exists"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
