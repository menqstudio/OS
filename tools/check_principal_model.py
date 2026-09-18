#!/usr/bin/env python3
"""The principal model says SEVEN in five documents. This checks the code still says seven — and which seven.

**Why this gate exists (C7).** `WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md` §2.6 is normative and
says *"The SEVEN runtime service UIDs"*. `docs/SECURITY_MODEL.md` §1.3a repeats it and then makes
a claim ON it: that the Floor Writer adds no member to `RUNTIME_PRINCIPALS` and changes no arm of
`verify_distinct_principals()`, so §2.6 stays true as written. That is exactly the kind of
sentence this repository has repeatedly found to be true when written and false when read.

What the type system already does, and what it does not:

* `pub const RUNTIME_PRINCIPALS: [Principal; 7]` pins the COUNT — an eighth entry is a compile
  error while the 7 stands. It pins nothing about **which** seven, and a rename plus an addition
  keeps the count while changing the model;
* nothing at all pins the `enum Principal` variants to the array. A variant added to the enum and
  omitted from the array compiles, and `verify_distinct_principals()` — which iterates the ARRAY —
  then never asks about it. That principal would be outside the distinctness rule while looking
  like it is inside it;
* and no test compares any of it with the number the documents say.

So this reads the Rust source and requires three things to agree: the enum's variants, the array's
members, and the frozen normative set. Then it requires every document that states the number to
state seven. An eighth principal is not forbidden — it is an AMENDMENT to a normative clause, and
this gate makes it arrive as one: the refusal names §2.6 and says who must ratify it.

stdlib only, no network. Run: `python3 tools/check_principal_model.py`
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "apps/desktop/src-tauri/core/src/windows_broker.rs"

#: §2.6, NORMATIVE. The order is the array's own, which `verify_distinct_principals` relies on for
#: a deterministic verdict, so this is a list and not a set.
NORMATIVE_PRINCIPALS = [
    "Broker", "Authority", "Sidecar", "Supervisor", "Recorder", "Executor", "Signer",
]

#: Documents that state the count. Each must say seven, in the spelling it uses.
COUNT_CLAIMS = {
    "docs/SECURITY_MODEL.md": ("seven", "SEVEN"),
    "docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md": ("SEVEN",),
    "docs/design/FLOOR_WRITER_SERVICE_DESIGN.md": ("SEVEN",),
}

_ENUM = re.compile(r"pub enum Principal\s*\{(?P<body>.*?)\}", re.S)
_ARRAY = re.compile(
    r"pub const RUNTIME_PRINCIPALS:\s*\[Principal;\s*(?P<count>\d+)\]\s*=\s*\[(?P<body>.*?)\];",
    re.S)
_VARIANT = re.compile(r"^\s*([A-Z][A-Za-z0-9]*)\s*,", re.M)
_MEMBER = re.compile(r"Principal::([A-Z][A-Za-z0-9]*)")
#: A count claim only counts when it is about the runtime service UIDs, not about seven of
#: anything else. The word alone would match prose that has nothing to do with the model.
_UID_CLAIM = re.compile(r"(seven|SEVEN)\s+runtime\s+service\s+UIDs", re.I)


def _strip_comments(text: str) -> str:
    """A principal named only in a comment is not a principal. Doc comments in this file describe
    each variant on its own line, and counting those would count the description twice."""
    return re.sub(r"//[^\n]*", "", text)


def read_model(source: str):
    enum = _ENUM.search(source)
    array = _ARRAY.search(source)
    if enum is None:
        return None, None, None, "no `pub enum Principal` in the source"
    if array is None:
        return None, None, None, "no `pub const RUNTIME_PRINCIPALS: [Principal; N]` in the source"
    variants = _VARIANT.findall(_strip_comments(enum.group("body")))
    members = _MEMBER.findall(array.group("body"))
    return variants, members, int(array.group("count")), None


def main() -> int:
    problems = []
    try:
        source = SOURCE.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"RED: cannot read {SOURCE.relative_to(ROOT)}: {exc}")
        return 1

    variants, members, declared, failure = read_model(source)
    if failure:
        print(f"RED: {failure}")
        return 1

    extra = [v for v in variants if v not in NORMATIVE_PRINCIPALS]
    missing = [v for v in NORMATIVE_PRINCIPALS if v not in variants]
    if extra or missing:
        problems.append(
            f"`enum Principal` is not the normative set: extra {extra or '[]'}, missing "
            f"{missing or '[]'}. §2.6 of WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md is NORMATIVE and "
            "says SEVEN runtime service UIDs; changing the set is an AMENDMENT to that clause, "
            "ratifiable only by the Architect, and docs/SECURITY_MODEL.md §1.3a states in as many "
            "words that the Floor Writer slice does not make it")
    if members != NORMATIVE_PRINCIPALS:
        problems.append(
            f"RUNTIME_PRINCIPALS is {members}, not the normative order {NORMATIVE_PRINCIPALS}. "
            "verify_distinct_principals() iterates THIS array, so a principal missing from it is "
            "outside the pairwise-distinctness rule while appearing to be inside it")
    if declared != len(NORMATIVE_PRINCIPALS):
        problems.append(
            f"RUNTIME_PRINCIPALS is declared [Principal; {declared}] and the normative count is "
            f"{len(NORMATIVE_PRINCIPALS)}")
    if len(variants) != len(members):
        problems.append(
            f"the enum has {len(variants)} variant(s) and the array {len(members)} member(s). A "
            "variant the array omits compiles and is then never asked about")

    for relative, spellings in COUNT_CLAIMS.items():
        path = ROOT / relative
        if not path.exists():
            problems.append(f"{relative} is named as stating the count and does not exist")
            continue
        text = path.read_text(encoding="utf-8")
        claims = _UID_CLAIM.findall(text)
        if not claims:
            problems.append(
                f"{relative} states no '<n> runtime service UIDs' claim; this gate is declared to "
                "hold it to one, so either the document changed or this list is stale")
            continue
        for word in claims:
            if word.lower() != "seven":
                problems.append(
                    f"{relative} says '{word} runtime service UIDs' while the code carries "
                    f"{len(members)}")
        del spellings

    if problems:
        print("RED: the principal model and the documents that describe it disagree —")
        for problem in problems:
            print(f"  - {problem}")
        print(f"\n{len(problems)} problem(s).")
        return 1

    print(f"GREEN: the principal model is one model — {len(members)} principals "
          f"({', '.join(members)}); the enum, RUNTIME_PRINCIPALS and its declared length agree, "
          f"and {len(COUNT_CLAIMS)} document(s) state the same count.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
