#!/usr/bin/env python3
"""Roadmap order, enforced -- a session may only work the FIRST phase that is not done.

MASTER_EXECUTION_ROADMAP.md §A already states the law: "Find the **first phase**
whose *Definition of Done* is not fully checked ... take the **first unchecked
task**." It was prose, so it was ignored: Phase-10 work happened for three days
while Phase 1 stood open and the roadmap was never opened once.

TWO PARTS
  1. STRUCTURAL (CI, no session): the roadmap's own two statements of completion
     must agree. A phase's Definition-of-Done checkboxes and its row in the Phase
     status board are independent surfaces, and a phase counts as complete only
     when BOTH say so. Disagreement is RED and names the phase.
  2. SESSION (hook): the session must DECLARE which phase it is working, and the
     declaration must be the first open phase. Declaring N+1 while N is open is
     refused, by name, before the session may edit anything.

THE COMPLETION SIGNAL, HONESTLY
  There was no machine-readable one. config/current_state.json's status_tokens
  carry wave/task state, not per-phase completion; the roadmap's DoD checkboxes
  are the only per-phase signal that exists. So the smallest honest signal is the
  one already written down -- and it IS "a string someone can edit". The Owner
  said not to invent a completion signal settable by editing a string unless the
  string is itself gate-checked. So it is gate-checked, in three ways:

    * a checkbox flip alone turns this gate RED, because the status board still
      disagrees; the lie has to be told twice, in two places, consistently;
    * both edits land in the diff of a commit, where a reviewer sees them;
    * the same commit is subject to check_canonical_sync, so "quietly close a
      phase" cannot be a silent one-character change.

  That is a speed bump with a paper trail, not a proof. A session determined to
  lie can still flip both. It is stated here so nobody mistakes this for custody.

OUT-OF-ORDER WORK
  Sometimes legitimate (a security fix in a later phase, tooling). The escape is
  NOT a session-local flag: it is an entry in config/roadmap-order-exemptions.json
  -- committed, diff-visible, needing a named approver and a real reason. A
  session can write that file itself; it cannot do so invisibly.

  `meta` is a declarable non-phase for repository governance/tooling work (this
  gate is itself meta work). It is path-scoped: a meta session may not edit
  implementation code. See META_ALLOWED_PREFIXES, and the report's honest note
  that scope is enforced on the edit tools, not on shell redirection.

Usage:
  python tools/check_roadmap_order.py                      # structural (CI)
  python tools/check_roadmap_order.py --declare 1 --note "..."
  python tools/check_roadmap_order.py --declare meta --note "..."
  python tools/check_roadmap_order.py --verify             # session declaration
  python tools/check_roadmap_order.py --scope tools/x.py   # path allowed?
Exit 0 + "GREEN: ..." / exit 1 + the problems.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import time

import check_read_receipt as receipt_store

ROADMAP = "MASTER_EXECUTION_ROADMAP.md"
EXEMPTIONS = "config/roadmap-order-exemptions.json"
META = "meta"
MIN_REASON_CHARS = 60

# A meta session works the repository's own governance surface. It may not touch
# product code -- otherwise "meta" becomes the universal way around phase order.
META_ALLOWED_PREFIXES = (
    "tools/", ".claude/", "config/", "docs/", ".github/",
)
META_ALLOWED_SUFFIXES = (".md",)

_PHASE_RE = re.compile(r"(?m)^##\s+Phase\s+(\d+)\s*[-—–]")
_DOD_RE = re.compile(r"(?m)^\*\*Definition of Done\.\*\*")
_NEXT_BLOCK_RE = re.compile(r"(?m)^(\*\*[A-Z][^*]*\.\*\*|##\s|---\s*$)")
_CHECKBOX_RE = re.compile(r"(?m)^\s*[-*]\s+\[( |x|X)\]")
_BOARD_HEADING_RE = re.compile(r"(?m)^#{2,4}\s+Phase status board\b")
_BOARD_END_RE = re.compile(r"(?m)^#{1,3}\s+(?!#)")
# Exactly three cells: | N | Name | Status |. The roadmap holds other numbered tables
# (the 22-page index, the ownership matrix); scoping to the board SECTION and to a
# three-column shape keeps them from being read as phases.
_BOARD_ROW_RE = re.compile(r"(?m)^\|\s*(\d+)\s*\|([^|]*)\|([^|]*)\|\s*$")
#: The FIRST `n/m` in a board cell -- the row's headline count (ninth audit `I-07`).
_FRACTION_RE = re.compile(r"\b(\d+)/(\d+)\b")


class RoadmapError(RuntimeError):
    """The roadmap cannot be parsed into phases at all."""


def _text(root: pathlib.Path) -> str:
    """The whole roadmap, assembled from the main file plus docs/roadmap/phase-N.md."""
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    try:
        import roadmap_source
        return roadmap_source.roadmap_text(root)
    except OSError as exc:
        raise RoadmapError(f"{ROADMAP} is unreadable: {exc}") from exc


def dod_state(root: pathlib.Path) -> dict[int, dict]:
    """{phase: {'total': n, 'unchecked': n, 'complete': bool}} from the DoD blocks."""
    text = _text(root)
    starts = [(int(m.group(1)), m.start()) for m in _PHASE_RE.finditer(text)]
    if not starts:
        raise RoadmapError(f"{ROADMAP} contains no '## Phase N' sections")
    state: dict[int, dict] = {}
    for index, (number, start) in enumerate(starts):
        end = starts[index + 1][1] if index + 1 < len(starts) else len(text)
        section = text[start:end]
        dod = _DOD_RE.search(section)
        if not dod:
            state[number] = {"total": 0, "unchecked": 0, "complete": False,
                             "problem": "has no '**Definition of Done.**' block"}
            continue
        after = section[dod.end():]
        stop = _NEXT_BLOCK_RE.search(after)
        block = after[:stop.start()] if stop else after
        boxes = _CHECKBOX_RE.findall(block)
        unchecked = sum(1 for box in boxes if box == " ")
        state[number] = {
            "total": len(boxes),
            "unchecked": unchecked,
            # Zero DoD items is NOT complete. An empty checklist would otherwise be
            # the cheapest way to declare a phase done: delete the boxes.
            "complete": bool(boxes) and unchecked == 0,
            "problem": "" if boxes else "'**Definition of Done.**' block has no checkboxes",
        }
    return state


def board_section(root: pathlib.Path) -> str:
    """The text of the 'Phase status board' section only.

    A duplicate board is a real historical failure here: a superseded copy of the
    same ten rows sat a dozen lines below the corrected one until 2026-08-09. So the
    section is located by its heading and ends at the next heading -- and if the
    heading is missing the gate says so rather than scanning the whole document and
    picking up whichever numbered table it meets first.
    """
    text = _text(root)
    start = _BOARD_HEADING_RE.search(text)
    if not start:
        raise RoadmapError(f"{ROADMAP} has no '### Phase status board' heading, so phase "
                           "completion has only one surface and cannot be cross-checked")
    rest = text[start.end():]
    end = _BOARD_END_RE.search(rest)
    return rest[:end.start()] if end else rest


def board_state(root: pathlib.Path) -> dict[int, dict]:
    """{phase: {'cell': str, 'complete': bool}} from the Phase status board table."""
    board: dict[int, dict] = {}
    for match in _BOARD_ROW_RE.finditer(board_section(root)):
        number = int(match.group(1))
        cell = match.group(3).strip()
        if number in board:
            continue  # first row wins; a duplicate row is caught by the count check
        board[number] = {"cell": cell, "complete": "✅" in cell}
    return board


def phase_checkbox_counts(root: pathlib.Path) -> dict[int, tuple[int, int]]:
    """{phase: (checked, total)} over EVERY checkbox in the phase section, not just the DoD block.

    The board rows print this fraction, and until the ninth audit nothing compared the two. `I-07`:
    Phase 8's row said 8/10 and Phase 9's said 8/9 while their sections held 7/9 and 7/9. Phases 3-7
    matched exactly, which is what established that the fraction is meant to be countable rather
    than editorial -- five rows agreeing by coincidence is not a thing that happens.
    """
    text = _text(root)
    starts = [(int(m.group(1)), m.start()) for m in _PHASE_RE.finditer(text)]
    counts: dict[int, tuple[int, int]] = {}
    for index, (number, start) in enumerate(starts):
        end = starts[index + 1][1] if index + 1 < len(starts) else len(text)
        boxes = _CHECKBOX_RE.findall(text[start:end])
        counts[number] = (sum(1 for b in boxes if b != " "), len(boxes))
    return counts


def fraction_problems(root: pathlib.Path) -> list[str]:
    """A board row that prints `n/m` must print the fraction its own section counts.

    Only the FIRST fraction in a row is read. A corrected row keeps the superseded number in a
    parenthetical -- that is how this repository records a correction rather than erasing it -- and
    a check that read every fraction would make writing the history down a failure.
    """
    problems: list[str] = []
    counts = phase_checkbox_counts(root)
    for number, detail in board_state(root).items():
        match = _FRACTION_RE.search(detail["cell"])
        if not match:
            continue                  # a row may say nothing; it may not say a wrong thing
        printed = (int(match.group(1)), int(match.group(2)))
        counted = counts.get(number)
        if counted is None:
            continue                  # orphan rows are reported by structural_problems
        if printed != counted:
            problems.append(
                f"Phase {number}: the status board prints {printed[0]}/{printed[1]} but its own "
                f"section counts {counted[0]}/{counted[1]} checkboxes. The fraction is a count, "
                "not a summary -- correct the row or tick the box")
    return problems


def structural_problems(root: pathlib.Path) -> list[str]:
    """The roadmap's two completion surfaces must agree, phase by phase."""
    problems: list[str] = []
    dod = dod_state(root)
    board = board_state(root)
    for number in sorted(dod):
        detail = dod[number]
        if detail["problem"]:
            problems.append(f"Phase {number} {detail['problem']} -- completion is unreadable, "
                            "so the order rule cannot be enforced for it")
            continue
        if number not in board:
            problems.append(f"Phase {number} has a section but no row in the Phase status board")
            continue
        if detail["complete"] != board[number]["complete"]:
            claim = "complete" if detail["complete"] else "open"
            other = "complete" if board[number]["complete"] else "open"
            problems.append(
                f"Phase {number}: Definition of Done says {claim} "
                f"({detail['total'] - detail['unchecked']}/{detail['total']} checked) but the "
                f"status board says {other} ({board[number]['cell'][:60]!r}). Completion must be "
                "stated the same way in both places or neither is trustworthy")
    orphans = sorted(set(board) - set(dod))
    if orphans:
        problems.append(f"status board rows with no matching phase section: {orphans}")
    # Ninth audit `I-07`: this gate compared completeness as a BOOLEAN and never read the printed
    # fractions, so a row could say 8/10 over a section counting 7/9 and stay green for two rounds.
    problems.extend(fraction_problems(root))
    return problems


def first_open_phase(root: pathlib.Path) -> int | None:
    """Lowest phase not complete on BOTH surfaces. None when every phase is done."""
    dod = dod_state(root)
    board = board_state(root)
    for number in sorted(dod):
        if not (dod[number]["complete"] and board.get(number, {}).get("complete")):
            return number
    return None


def load_exemptions(root: pathlib.Path) -> dict:
    try:
        document = json.loads((root / EXEMPTIONS).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entries = document.get("exemptions")
    return entries if isinstance(entries, dict) else {}


def exemption_problem(root: pathlib.Path, phase: int) -> str | None:
    """None when a usable exemption exists; otherwise why it does not count."""
    entry = load_exemptions(root).get(str(phase))
    if not isinstance(entry, dict):
        return f"no entry for phase {phase} in {EXEMPTIONS}"
    reason = str(entry.get("reason") or "")
    approved_by = str(entry.get("approved_by") or "")
    if len(reason.strip()) < MIN_REASON_CHARS:
        return (f"the {EXEMPTIONS} entry for phase {phase} has no real reason "
                f"(under {MIN_REASON_CHARS} characters)")
    if not approved_by.strip():
        return f"the {EXEMPTIONS} entry for phase {phase} names no approver"
    expires = entry.get("expires_at_epoch")
    if isinstance(expires, int) and expires <= int(time.time()):
        return f"the {EXEMPTIONS} entry for phase {phase} expired"
    return None


def parse_declaration(value: str) -> int | str:
    if str(value).strip().lower() == META:
        return META
    try:
        return int(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"phase must be an integer or {META!r}, got {value!r}") from exc


def declare(root: pathlib.Path, sid: str, phase: int | str, note: str) -> tuple[bool, str]:
    """Record the declaration in the session receipt. Refused without a valid receipt:
    a session cannot name the phase it is working before it has read the roadmap."""
    ok, why = receipt_store.verify(root, sid)
    if not ok:
        return False, (f"cannot declare a phase: {why}. Complete the canonical full read first "
                       "(python tools/check_read_receipt.py --record).")
    if len(note.strip()) < MIN_REASON_CHARS:
        return False, (f"--note must say what this session is doing in this phase "
                       f"(at least {MIN_REASON_CHARS} characters)")
    document = receipt_store.load(root, sid) or {}
    # Snapshot, write, verify, ROLL BACK on refusal. A refused declaration must leave no
    # trace: found by driving the wall on a throwaway copy, where an attempt to declare
    # Phase 10 was correctly refused and then persisted, so every subsequent edit was denied
    # for a phase the session had never been allowed to claim. A gate that punishes the
    # attempt to obey it is a gate people route around.
    previous = {key: document.get(key) for key in
                ("declared_phase", "declared_phase_note", "declared_phase_at_epoch")}
    document["declared_phase"] = phase
    document["declared_phase_note"] = note.strip()
    document["declared_phase_at_epoch"] = int(time.time())
    receipt_store.write_receipt(root, sid, document)
    ok, why = verify_declaration(root, sid)
    if not ok:
        document.update(previous)
        receipt_store.write_receipt(root, sid, document)
    return ok, why


def verify_declaration(root: pathlib.Path, sid: str) -> tuple[bool, str]:
    """(ok, reason) for the session's declared phase against the live roadmap.

    Re-derived from the roadmap on EVERY call, never trusted from the receipt: a
    phase that closes or opens mid-session changes the answer, and a declaration
    recorded when it was true must stop being usable when it stops being true.
    """
    problems = structural_problems(root)
    if problems:
        return False, ("the roadmap's completion state is self-inconsistent, so phase order "
                       "cannot be enforced: " + "; ".join(problems[:3]))
    document = receipt_store.load(root, sid)
    if document is None:
        return False, "no session receipt, so no phase declaration"
    declared = document.get("declared_phase")
    if declared is None:
        open_phase = first_open_phase(root)
        return False, (
            "this session has not declared which roadmap phase it is working. The first phase "
            f"whose Definition of Done is not fully checked is Phase {open_phase}. Declare it: "
            f"python tools/check_roadmap_order.py --declare {open_phase} --note \"<what you are "
            "doing>\"  (or --declare meta for repository governance/tooling work).")
    if declared == META:
        return True, ("declared meta (repository governance/tooling); phase order does not apply, "
                      f"edits are scoped to {', '.join(META_ALLOWED_PREFIXES)} and *.md")
    if not isinstance(declared, int):
        return False, f"declared phase {declared!r} is neither an integer nor {META!r}"
    open_phase = first_open_phase(root)
    if open_phase is None:
        return True, f"declared Phase {declared}; every phase is complete"
    if declared == open_phase:
        return True, f"declared Phase {declared}, which is the first phase not yet complete"
    if declared < open_phase:
        return False, (f"declared Phase {declared}, which is already complete. The first open "
                       f"phase is Phase {open_phase}.")
    problem = exemption_problem(root, declared)
    if problem is None:
        return True, (f"declared Phase {declared} ahead of the open Phase {open_phase}, permitted "
                      f"by a committed exemption in {EXEMPTIONS}")
    return False, (
        f"REFUSED: this session declared Phase {declared} while Phase {open_phase} is still open. "
        f"Close Phase {open_phase} before starting Phase {declared} -- {problem}. Working ahead "
        f"requires a committed, reviewable exemption: add an entry keyed \"{declared}\" to "
        f"{EXEMPTIONS} with a reason of at least {MIN_REASON_CHARS} characters and a named "
        "approver, and commit it.")


def scope_problem(root: pathlib.Path, sid: str, rel_path: str) -> str | None:
    """None when the declared phase permits editing this path.

    Scope is enforced ONLY for `meta`. A numbered phase's scope is prose in the
    roadmap ("In: ... Out: ...") and cannot be turned into a path list without
    inventing one, so this gate does not pretend to enforce it.
    """
    document = receipt_store.load(root, sid) or {}
    if document.get("declared_phase") != META:
        return None
    rel = str(rel_path).replace("\\", "/").lstrip("./")
    if rel.startswith(META_ALLOWED_PREFIXES) or rel.endswith(META_ALLOWED_SUFFIXES):
        return None
    return (f"this session declared `meta` (repository governance/tooling), which may not edit "
            f"{rel}. Meta scope is {', '.join(META_ALLOWED_PREFIXES)} and *.md. To change "
            "implementation code, declare the roadmap phase that owns it.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[1]))
    parser.add_argument("--session", default=None)
    parser.add_argument("--declare", default=None, help="phase number, or 'meta'")
    parser.add_argument("--note", default="", help="what this session is doing in that phase")
    parser.add_argument("--verify", action="store_true", help="check the session declaration")
    parser.add_argument("--scope", default=None, help="path to test against the declaration")
    args = parser.parse_args(argv)
    root = pathlib.Path(args.root).resolve()
    sid = receipt_store.session_id(args.session)
    try:
        if args.declare is not None:
            ok, why = declare(root, sid, parse_declaration(args.declare), args.note)
        elif args.scope is not None:
            problem = scope_problem(root, sid, args.scope)
            ok, why = problem is None, problem or f"{args.scope} is within the declared scope"
        elif args.verify:
            ok, why = verify_declaration(root, sid)
        else:
            problems = structural_problems(root)
            if problems:
                print("RED: roadmap completion is self-inconsistent:")
                for problem in problems:
                    print(f"  - {problem}")
                return 1
            open_phase = first_open_phase(root)
            dod = dod_state(root)
            print(f"GREEN: roadmap phases {min(dod)}..{max(dod)} agree between Definition of Done "
                  f"and the status board; first open phase = "
                  f"{'none (all complete)' if open_phase is None else open_phase}")
            return 0
    except (RoadmapError, receipt_store.ReceiptError, ValueError) as exc:
        print(f"RED: {exc}")
        return 1
    print(("GREEN: " if ok else "RED: ") + why)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
