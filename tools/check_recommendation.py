"""Options without a recommendation are not analysis, they are a decision passed upward.

The Owner's rule: *"ուզում եմ որ մի քանի տարբերակի դեպքում առաջարկես քո ռեքը ՊԱՐՏԱԴԻՐ, ու
քո ռեքը լինի ոչ թե արագ ու հեշտը այլ ՄԵՆԱԼԱՎՆ ՈՒ ՃԻՇՏԸ"* — where there are options, name
the one you recommend, and let it be the best and most correct one rather than the quick
and easy one.

Presenting three options and stopping looks careful and is not. It moves the hardest part
of the work — the judgement — onto the person who has least context, and it does so while
appearing thorough. Whoever laid out the options knows which is strongest; withholding that
is the omission this refuses.

**Be exact about what this catches.** It reads documents. It cannot read a conversation, so
the rule in `config/owner-contract.md` is what governs a reply, and that contract is
injected on every message rather than at session start. This gate covers the half that can
be mechanised: a canonical document that lays out alternatives must say which one it
recommends and why.

The wording matters and is checked: a recommendation has to be attached to a REASON. "Option
B (recommended)" with nothing after it is a preference. "Option B, because it is the only
one that leaves the audited security code untouched" is a recommendation.

What is NOT flagged: a list of steps, a table of files, an enumeration of findings. Only
lists that present ALTERNATIVES — the shape where a choice is being handed over.

Stdlib only, offline, fail-closed. Exit 0 GREEN, 1 RED.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST_REL = "config/canonical-read-manifest.json"

# The shapes this repository actually writes alternatives in.
# Inline (?m)/(?im) flags are illegal anywhere but the start of a pattern, so the flags go
# on the compile call. This exact slip was made twice while writing these gates -- once here
# and once in check_no_assumptions.py -- which is the kind of thing worth writing down rather
# than quietly fixing.
# Sibling list items, each one alternative. TWO are required: a single item reading
# "- **Option 1 / Option 2 / T-005** — subtree+skip-guard vs submodule" is a GLOSSARY
# defining what those names mean, not a choice being handed over, and the gate's first run
# flagged exactly that. One item is a definition; two are a decision.
OPTION_ITEM = re.compile(
    r"^\s*[-*]\s*\*\*(?:Option\s*)?[A-D0-9]\s*[·:.—-]", re.MULTILINE | re.IGNORECASE)
# Or the document says outright that it is offering a choice.
OPTION_PHRASE = re.compile(
    r"\b(?:two|three|four)\s+options\b|\boptions\s*:|"
    r"\b(?:երկու|երեք|չորս)\s+տարբերակ", re.IGNORECASE)


def presents_alternatives(body: str) -> bool:
    return len(OPTION_ITEM.findall(body)) >= 2 or bool(OPTION_PHRASE.search(body))

# A recommendation, and it must carry a reason: the marker plus a because-clause somewhere
# in the same section.
RECOMMEND = re.compile(
    r"\b(?:recommend(?:ed|ation|s)?|the answer is|the right (?:one|answer|choice)|"
    r"decision \(standing\)|\*\*decision|standing decision|chosen|we take|take option|"
    r"առաջարկ\w*|ռեկոմենդաց\w*|ճիշտ[ըն])", re.IGNORECASE)
REASON = re.compile(
    r"\b(?:because|since|so that|the reason|which is why|it is the only|"
    r"leaves .* untouched|որովհետև|պատճառ\w*|քանի որ)", re.IGNORECASE)

HEADING = re.compile(r"^#{1,6} ", re.MULTILINE)


def sections(text: str) -> list[tuple[str, str]]:
    """(heading, body) for every heading in the document, plus a leading preamble."""
    marks = list(HEADING.finditer(text))
    out: list[tuple[str, str]] = []
    if not marks:
        return [("(document)", text)]
    if marks[0].start() > 0:
        out.append(("(preamble)", text[: marks[0].start()]))
    for i, m in enumerate(marks):
        stop = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        block = text[m.start(): stop]
        out.append((block.splitlines()[0].strip()[:90], block))
    return out


def strip_fences(text: str) -> str:
    return re.sub(r"(?s)```.*?```", "", text)


def main(root: pathlib.Path = ROOT) -> int:
    try:
        paths = json.loads((root / MANIFEST_REL).read_text(encoding="utf-8"))["paths"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"RED: cannot read {MANIFEST_REL}: {exc}")
        return 1

    problems: list[str] = []
    checked = 0
    for rel in paths:
        path = root / rel
        if not path.is_file():
            continue
        for heading, body in sections(strip_fences(path.read_text(encoding="utf-8", errors="ignore"))):
            if not presents_alternatives(body):
                continue
            checked += 1
            if not RECOMMEND.search(body):
                problems.append(
                    f"{rel} — {heading}: lays out alternatives and recommends none. Name the "
                    f"one you would take.")
            elif not REASON.search(body):
                problems.append(
                    f"{rel} — {heading}: names a recommendation with no reason attached. A "
                    f"preference is not a recommendation; say what makes it the strongest.")

    if problems:
        print("RED: alternatives are presented without a recommendation\n")
        for p in problems:
            print(f"  - {p}")
        print("\nWhoever wrote the options knows which is strongest. Withholding that moves "
              "the judgement onto the reader with the least context, while looking thorough.\n"
              "And the recommendation is the BEST and most correct option — not the quickest "
              "one, and not the one that avoids touching something difficult. If the strongest "
              "option is also the expensive one, recommend it and say what it costs.")
        return 1

    print(f"GREEN: every set of alternatives carries a reasoned recommendation; "
          f"sections with options={checked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
