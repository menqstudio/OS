"""Every field in the machine mirror must be read by something.

`config/current_state.json` is called the machine-readable mirror, and
`tools/check_repo_state.py` genuinely does verify two of its fields against live GitHub:
`settled_at_main_head` and `prs[]`. Those cannot drift.

The other twenty could, and did. The ninth independent audit's `I-06`:

    The machine mirror's prose drifted. `config/current_state.json.purpose` says "main is
    at settled_at_main_head (b3010f6)" while that field is `d0bddc4` ... `check_repo_state.py`
    is GREEN because it reads `settled_at_main_head` and `prs[]` and never these fields.

That is the whole mechanism, and it is not carelessness. **A field nothing reads cannot be
wrong**, so nothing ever corrects it, so it accumulates. `purpose` reached **74,311
characters** — 68% of a file whose own first sentence tells you not to read a commit id out
of it — inside a set every session is required to read.

Deleting the prose does not fix that. Nothing stops the next session writing a new
paragraph into a field no gate looks at, and the same rule that produced 74k characters is
still in force. So this is the rule instead:

    A top-level field of the machine mirror is either READ by a tool or a hook, or it is
    declared unread with a reason. Anything else is RED.

WHAT COUNTS AS A READER, and what stopped counting. The test is textual: the field's name,
quoted, in a file that could be a reader. Two things used to pass it that read nothing:

  * a TEST. `product_roadmap` appeared, quoted, in exactly one file in the tree --
    `tools/test_check_repo_state.py`, a fixture WRITING it -- and the gate printed GREEN on a
    field no tool has read since the rule that read it was removed.
  * a file that never opens the mirror. `"schema"` is a key in a dozen unrelated JSON
    documents and `"_comment"` in as many; each matched somewhere, and none of those files so
    much as names `current_state.json`.

So a reader is now a non-test file that NAMES THE MIRROR and quotes the field. The limit that
buys: a tool that reads the mirror only through another module's loader, and never names the
file itself, is not seen as a reader -- a false RED, with the gate's own message as the way
out. It is still a reference test, not a proof that the reference is correct.

It is the same reverse-direction assertion as `check_dead_tokens.py` (every declared CSS
custom property must be read by something) and `check_canon_budget.py` (the canon must stay
small enough to be read). This repository has never lacked a rule saying *write something
down*; it lacked the rules saying *and it must be reachable, and it must fit*.

The allowlist is checked from both sides: an entry naming a field that no longer exists is
also RED, because an exemption that outlives its reason is where the next dead field hides.

Stdlib only, offline, fail-closed. Exit 0 GREEN, 1 RED.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_REL = "config/current_state.json"
BUDGET_REL = "config/canon-budget.json"

# Where a reader would live. A field is "read" if its name appears as a string in one of
# these — the same crude, honest test check_dead_tokens.py uses on stylesheets: it proves
# a reference exists, not that the reference is correct.
#
# `.github/workflows` is here because the RED message has always said "workflow" and no
# workflow was scanned. `runtime` was here and is gone: there is no `runtime/` at the
# repository root (the engine's is `engine/runtime/`, and nothing in it reads this mirror),
# so the entry scanned nothing and read as coverage.
READER_DIRS = ("tools", ".claude/hooks", "bridge", ".github/workflows")
READER_SUFFIXES = (".py", ".yml", ".yaml", ".rs", ".ts")
#: What a file must mention to be able to be a reader of the mirror at all.
MIRROR_NAME = pathlib.PurePosixPath(STATE_REL).name


def is_test(rel: pathlib.PurePosixPath) -> bool:
    """A test writes fixtures; it does not read the mirror on anyone's behalf."""
    return (rel.name.startswith("test_") or ".test." in rel.name
            or "tests" in rel.parts or "fixtures" in rel.parts)


def reader_files(root: pathlib.Path) -> list[pathlib.Path]:
    """Every file that could be a reader: right place, right suffix, not a test, not this
    checker, and it names the mirror."""
    out: list[pathlib.Path] = []
    for rel in READER_DIRS:
        base = root / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix not in READER_SUFFIXES or not path.is_file():
                continue
            # This checker names every field it validates, in its own docstring and in
            # its messages. Counting itself as a reader would make every field pass.
            if path.resolve() == pathlib.Path(__file__).resolve():
                continue
            if is_test(pathlib.PurePosixPath(path.relative_to(root).as_posix())):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if MIRROR_NAME in text:
                out.append(path)
    return out


def readers_text(root: pathlib.Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8", errors="ignore")
                     for path in reader_files(root))


def main(root: pathlib.Path = ROOT) -> int:
    try:
        state = json.loads((root / STATE_REL).read_text(encoding="utf-8"))
        budget = json.loads((root / BUDGET_REL).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"RED: cannot read the machine mirror or its budget: {exc}")
        return 1
    if not isinstance(state, dict):
        print(f"RED: {STATE_REL} must contain an object")
        return 1

    allowed = budget.get("state_fields_read_by_nothing")
    if not isinstance(allowed, dict):
        print("RED: config/canon-budget.json must carry state_fields_read_by_nothing "
              "(an object mapping each deliberately-unread field to its reason)")
        return 1

    haystack = readers_text(root)
    problems: list[str] = []

    for field in state:
        if f'"{field}"' in haystack or f"'{field}'" in haystack or f"[{field}]" in haystack:
            if field in allowed:
                problems.append(
                    f"`{field}` is declared as read by nothing, but something reads it now. "
                    f"Remove it from state_fields_read_by_nothing — an exemption that "
                    f"outlives its reason is where the next dead field hides")
            continue
        if field not in allowed:
            problems.append(
                f"`{field}` is in {STATE_REL} and NO tool, hook, workflow or module reads "
                f"it (a reader is a non-test file that names {MIRROR_NAME} and quotes the "
                f"field). A field nothing reads cannot be wrong, so nothing corrects it — that "
                f"is how `purpose` reached 74,311 characters. Give it a reader, delete it, "
                f"or declare it in state_fields_read_by_nothing with the reason")

    for field in allowed:
        if field not in state:
            problems.append(
                f"state_fields_read_by_nothing names `{field}`, which is not in {STATE_REL}")

    if problems:
        print(f"RED: the machine mirror carries fields nothing answers for\n")
        for p in problems:
            print(f"  - {p}")
        print("\nThe mirror is checked against live GitHub on exactly two fields. Every other "
              "field is prose until something reads it.")
        return 1

    print(f"GREEN: every field in {STATE_REL} is read by something or declared with a reason; "
          f"fields={len(state)}; declared-unread={len(allowed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
