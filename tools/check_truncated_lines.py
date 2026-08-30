#!/usr/bin/env python3
"""No canonical line may end mid-sentence.

THE DEFECT, 2026-08-30. Eleven of the thirteen Definition-of-Done and Task-checklist rows in
`docs/roadmap/phase-1.md` end in the middle of a clause:

    - [ ] One governed round-trip proven end-to-end. **Still open, and an independent auditor has now
    - [x] `task-request` + `bridge-result` contracts defined and tested — **but only `task-request` is

They have read that way since commit `8e446d4` (2026-08-10), which rewrote those rows; the split
into `docs/roadmap/` carried the halves over unchanged, and `tools/fixtures/roadmap-pre-split.md`
preserves them, so the fixture agrees with the file and the byte-identity test stays green over
text that says nothing. `check_roadmap_order.py` reads these very rows to decide which phase a
session may work, and `git show c82f06a:MASTER_EXECUTION_ROADMAP.md` shows the round-trip row at
363 characters before that commit and 98 after.

Thirty gates and not one of them looked. That is not an oversight so much as a category: every
other gate judges content that is PRESENT -- is the file too big, does this path resolve, is this
number measured, is this claim marked. A truncated line passes all of them, because what is wrong
with it is the part that is not there.

WHAT COUNTS AS TRUNCATED. A markdown list row or table cell that ends without terminal
punctuation. The rule has to tolerate the ways a complete line legitimately ends -- a closing
backtick, a bold marker, a bracket, a colon introducing a block -- so it looks only at the last
non-decoration character and asks whether the line ends on a word or a comma with no terminator.

Exit 0 GREEN, 1 RED.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Where a cut-off line does real damage: the roadmap rows that gate which phase may be worked.
SCANNED_GLOBS = ("docs/roadmap/phase-*.md",)

#: A CHECKBOX row -- `- [ ] …` or `- [x] …`. Scoped there deliberately, and the scope is the
#: argument, not an exemption: these are the rows `tools/check_roadmap_order.py` parses to decide
#: which phase a session may work, so a half-sentence here is a phase CONDITION that no reader can
#: evaluate and no session can satisfy. A descriptive bullet ending without a full stop is prose.
#:
#: Measured 2026-08-30 over `docs/roadmap/`: 16 checkbox rows truncated, and 22 descriptive
#: bullets (mostly `Components: …` lists in the UI/UX sections of phases 2-6) that are cut the
#: same way. The 22 are a real defect and are NOT covered here -- they are recorded on the board
#: rather than quietly folded into a gate that would then be red for two different reasons.
LIST_ROW = re.compile(r"^\s*[-*+]\s\[[ xX]\]\s")

#: Trailing decoration that is not the sentence: emphasis, code fences, quotes.
#:
#: Brackets are NOT stripped, and that distinction cost a false positive on the first run:
#: `docs/roadmap/phase-10.md:20` ends "(keyboard-complete, AA contrast, live regions, HY SR
#: labels)" -- a closed parenthesis is a finished thought, and stripping it to judge the word
#: inside called a complete bullet truncated.
DECORATION = re.compile(r"[*_`~\"'>»]+$")

#: A line that ends a sentence or a clause a reader can act on. Brackets are deliberately NOT
#: listed: the final test is `last.isalnum()`, which already passes anything that is not a word
#: character, so `)` here would be a second guard over the same case -- and two guards over one
#: rule is how both go untested (each mutation is masked by the other). One authority.
TERMINATORS = ".!?:;|։՞՜"


def is_truncated(line: str) -> bool:
    """True when this list row stops in the middle of a clause."""
    body = line.rstrip()
    if not LIST_ROW.match(body):
        return False
    stripped = DECORATION.sub("", body).rstrip()
    if not stripped:
        return False
    last = stripped[-1]
    if last in TERMINATORS:
        return False
    # An em dash or comma at the end is a clause that was going somewhere and did not arrive.
    if last in ",—-–":
        return True
    # Otherwise it ends on a word character: a sentence with no full stop.
    return last.isalnum()


def scan(root: pathlib.Path) -> list[tuple[str, int, str]]:
    problems: list[tuple[str, int, str]] = []
    for glob in SCANNED_GLOBS:
        for path in sorted(root.glob(glob)):
            rel = path.relative_to(root).as_posix()
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if is_truncated(line):
                    problems.append((rel, n, line.strip()))
    return problems


def main() -> int:
    problems = scan(ROOT)
    if not problems:
        counted = sum(len(list(ROOT.glob(g))) for g in SCANNED_GLOBS)
        print(f"GREEN: no roadmap Definition-of-Done row ends mid-sentence; files={counted}")
        return 0
    print("RED: canonical lines end in the middle of a clause\n")
    for rel, n, text in problems[:20]:
        print(f"  - {rel}:{n}")
        print(f"      …{text[-72:]}")
    if len(problems) > 20:
        print(f"  … and {len(problems) - 20} more")
    print(
        "\nA row that stops mid-clause is not a short row: it is a claim whose condition was\n"
        "lost. Finish the sentence from the code, or from the pre-truncation text in git --\n"
        "never by deleting the row, which throws away the half that survived."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
