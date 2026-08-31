"""An assumption may not enter the record dressed as a fact.

The Owner's words, and he is right: *"ԴՈՒ ԵՐԲԵՔ ՉՊԵՏՔԱ ԵՆԹԱԴՐԵՍ"* — never assume. The
session that wrote this file had just written, about a number it had put into a committed
config, *"I guessed it rather than reading it"* — and only found out it was wrong when a
gate it had also written went red.

**Be honest about what this can and cannot do.** No gate can stop a mind from assuming.
What it can stop is an assumption being **written into the record as though it were
measured**, which is the part that costs the next session three days — because the next
session cannot tell the difference, and reasonably believes what the document says.

So the rule is not "never write an uncertain thing". Uncertainty is real and hiding it is
worse. The rule is:

    An uncertain statement in a canonical document must SAY it is uncertain, in a form a
    machine can find, together with what would settle it.

Two ways to satisfy this gate, and the second is the point:

  1. **Settle it.** Run the command, read the file, and write what it printed. The sentence
     then names its own evidence — `measured`, `ran`, `printed`, `verified`, `read at`,
     `git show`, a test count, a file:line — and the gate is satisfied because the hedge is
     no longer doing any work.
  2. **Mark it.** `<!-- UNVERIFIED: what would settle this -->` on the line, or the same in
     an `UNVERIFIED:` prefix. The claim survives, flagged, with the experiment named. The
     next session then knows exactly which sentences to distrust — which is worth more than
     a document with no hedges in it and no honesty either.

What is NOT flagged: normative "shall" and "should" (a specification says what a system
should do, which is not a guess), and anything inside a code fence.

Runs over the canonical read set only. A hedge in an archive is history; a hedge in the
canon is an instruction.

Stdlib only, offline, fail-closed. Exit 0 GREEN, 1 RED.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST_REL = "config/canonical-read-manifest.json"

# First-person epistemic hedges and explicit assumption words, English and Armenian.
# Deliberately NOT "should"/"shall" on their own: a specification legitimately says what a
# system should do, and a rule that cannot tell that from a guess is a rule people disable.
HEDGES = [
    r"\bI (?:assume|assumed|think|thought|believe|guess|guessed)\b",
    r"\bassum(?:e|ed|ing|ption)\b",
    r"\bpresumably\b",
    r"\bprobably\b",
    r"\blikely\b",
    r"\bmy guess\b",
    # "guessed" as a VERB the writer is doing, not "a guess" as a noun the writer is warning
    # about. All three of this gate's first-run hits were the second kind — "treat every head
    # on this page as a date-stamped guess", "a guess that reads like a measurement" — which
    # is a document being honest, exactly the behaviour this gate exists to encourage.
    r"\b(?:I|we) guess(?:ed)?\b",
    r"\bjust guess(?:ed|ing)\b",
    r"\bseems? to (?:be|have)\b",
    r"\bappears? to (?:be|have)\b",
    r"\bshould be fine\b",
    r"\bpresumed\b",
    r"\bենթադր\w*",
    r"\bհավանաբար\b",
]
HEDGE = re.compile("|".join(HEDGES), re.IGNORECASE)

# The sentence names its own evidence, so the hedge is describing a past uncertainty rather
# than asserting a present one.
EVIDENCE = re.compile(
    r"\b(?:measured|measure|ran|runs|printed|prints|verified|verify|checked|observed|"
    r"reproduc|mutat|git show|git log|rev-parse|cat-file|:\d+\b|\d+\s*(?:tests?|OK|passed|"
    r"bytes|lines))\b", re.IGNORECASE)

MARKED = re.compile(r"<!--\s*UNVERIFIED:|^\s*>?\s*UNVERIFIED:", re.IGNORECASE)

# A sentence ABOUT assuming is not an assumption. "the chain node is earned, never assumed",
# "probed rather than assumed", "not a REUSE assumption" are the repository asserting the
# opposite of a guess, and flagging them teaches a reader that the gate does not understand
# what it reads — after which nobody reads its output. Detected by the negation or contrast
# that precedes the hedge, within a short window.
NEGATED = re.compile(
    r"(?:\bnot\b|\bnever\b|\bno\b|\bwithout\b|\brather than\b|\binstead of\b|"
    r"\bearned\b|\bproven\b|\bprobed\b|\bmeasured\b)[^.;]{0,60}$", re.IGNORECASE)


def offending_lines(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    in_fence = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not HEDGE.search(line):
            continue
        if MARKED.search(line) or EVIDENCE.search(line):
            continue
        m = HEDGE.search(line)
        if m and NEGATED.search(line[:m.start()]):
            continue
        out.append((n, line.strip()))
    return out


def main(root: pathlib.Path = ROOT) -> int:
    try:
        paths = json.loads((root / MANIFEST_REL).read_text(encoding="utf-8"))["paths"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"RED: cannot read {MANIFEST_REL}: {exc}")
        return 1

    problems: list[str] = []
    scanned = 0
    for rel in paths:
        path = root / rel
        if not path.is_file():
            continue
        scanned += 1
        for n, line in offending_lines(path.read_text(encoding="utf-8", errors="ignore")):
            problems.append(f"{rel}:{n}  {line[:150]}")

    if problems:
        print("RED: canonical documents carry unmarked guesses\n")
        for p in problems:
            print(f"  - {p}")
        print("\nEach of these hedges without saying how it could be settled. Two ways out, "
              "and the second is not a defeat:\n"
              "  1. Settle it — run the thing, read the file, and write what it PRINTED.\n"
              "  2. Mark it — `<!-- UNVERIFIED: what would settle this -->` on the line.\n"
              "An honest 'I could not check this, and here is the experiment' is worth more "
              "to the next session than a confident sentence nobody tested. What costs three "
              "days is a guess that reads like a measurement.")
        return 1

    print(f"GREEN: no unmarked guess in the canonical read set; files={scanned}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
