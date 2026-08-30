#!/usr/bin/env python3
"""`lstrip("./")` strips CHARACTERS, not a prefix -- and it was written three times.

THE DEFECT. `str.lstrip(chars)` takes a CHARACTER SET. It removes leading characters
while each one is a member of that set; it does NOT remove a prefix. So::

    ".claude/settings.json".lstrip("./")  -> "claude/settings.json"     WRONG
    ".github/x".lstrip("./")              -> "github/x"                 WRONG
    "../tools/x.py".lstrip("./")          -> "tools/x.py"               WRONG, AND WORSE
    ".claude/settings.json".removeprefix("./") -> ".claude/settings.json"   right

The form reads exactly like "drop a leading ./" and behaves like "drop every leading
dot and slash", so every path under a DOTTED directory silently loses its dot. Both
failure directions are real:

  * TOO STRICT -- a reference to `.claude/x` or `.github/x` became `claude/x` /
    `github/x`, matched nothing, and produced a false refusal.
  * TOO PERMISSIVE -- `../tools/x.py` and `..///.././tools/evil.py` were both laundered
    into `tools/x.py` / `tools/evil.py`, so a parent-directory traversal ARRIVED inside
    an allow-listed prefix. That is the direction that matters: the buggy form let a
    path escape the tree and then pass a scope check.

FOUND THREE TIMES BEFORE THIS GATE EXISTED.

  1. `tools/check_doc_claims.py` hit it on its own first run and fixed it inline with
     `target[2:] if target.startswith("./")`, leaving a comment at `:232` describing it.
     Nothing generalised the lesson, so the comment was the only record.
  2. `tools/check_roadmap_order.py:373` carried it live: `scope_problem` mangled every
     path before comparing it with `META_ALLOWED_PREFIXES`, two of which are `.claude/`
     and `.github/`. A `meta` session -- the declaration whose entire purpose is
     governance and tooling work -- could therefore never edit either directory. Worse
     for a subagent: an agent working inside `.claude/worktrees/<id>/` had EVERY path
     mangled, so the root wall denied every Edit/Write it attempted and its only way to
     write anything at all was the ungated Bash path.
  3. `tools/check_audit_reports.py:119` carried the identical line in
     `authoritative_link`, and nobody had noticed. It has not fired only because no
     audit report has ever lived under a dotted directory -- it was found by sweeping
     for the FORM, not by a RED.

Two of them were live at the same head. That is the argument for a gate rather than a
third careful fix: a defect that recurs across files is a defect the build should refuse,
because the next person to write it will also be writing something that reads correctly.

WHAT IS FLAGGED, AND WHY EXACTLY THIS RULE
  A call `<anything>.lstrip(<string literal>)` where the literal CONTAINS a path
  separator (`/` or `\\`) AND is at least two characters long.

  The two-character floor is not a softening, it is the definition of the bug. A
  ONE-character argument cannot exhibit the character-set surprise: `s.lstrip("/")` means
  "remove leading `/` characters", and repeated-prefix-removal of a single character is
  the same operation -- there is no second reading for it to be confused with. Verified
  exhaustively in `test_check_no_lstrip_prefix.py`. Three call sites in this tree use
  that form correctly (`check_audit_reports.py:84`, `engine/runtime/bro_release_v3.py:40`,
  `engine/runtime/bro_policy.py:279`), all of them normalising leading slashes, and
  flagging them would either force churn through the `engine/` subtree -- a security
  perimeter vendored from `menqstudio/Bro` -- or force an allow-list, and an allow-list is
  the thing that rots.

WHY AN AST WALK AND NOT A REGEX -- this is the load-bearing design choice
  The gate parses each file and inspects CALL nodes. A comment is not in the AST at all,
  and neither is a docstring's prose. So `check_doc_claims.py:232`, which describes this
  exact defect in a comment, and this file's own docstring above, which quotes the broken
  form four times, are invisible to the gate BY CONSTRUCTION -- not by an exception, not
  by a suppression marker, not by a path allow-list that some later session has to
  remember to maintain. A regex would have needed all three, and the first thing a
  maintainer does with a gate that reds on its own documentation is switch it off.

  The cost is stated rather than hidden: an AST walk sees only what the parser sees.
  `getattr(s, "lstrip")("./")`, `s.lstrip(sep)` where `sep` is a variable, and a call
  assembled through `eval` are all invisible. This gate refuses the LITERAL form that was
  actually written three times; it is not a proof that no character-set strip survives
  anywhere.

  A file that does not parse is RED, not skipped. A gate that silently skips what it
  cannot read reports green over the one file most likely to be wrong. Measured at the
  head that added this gate: 270 Python files, 0 unparseable.

Usage:
  python tools/check_no_lstrip_prefix.py [--root DIR]
Exit 0 + "GREEN: ..."; exit 1 listing every offending `path:line`.
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import sys

#: Directories never swept. `.claude/worktrees/` is excluded for the reason
#: `check_doc_claims.py:246` names: the Agent tool checks a whole second copy of this
#: repository out there so a subagent cannot collide with the session, and a gate that
#: counted that copy would be RED on a developer box and GREEN in CI -- a verdict that
#: depends on the machine rather than the tree. The exclusion is matched on the path
#: RELATIVE to --root, never the absolute one: a checkout that IS a worktree would
#: otherwise exclude itself entirely and sweep nothing while printing GREEN.
SKIP_DIR_NAMES = frozenset({
    ".git", "node_modules", "target", "dist", "build", "__pycache__", ".venv", "venv",
})
SKIP_REL_PREFIXES = (".claude/worktrees/",)

#: What makes an argument a PATH strip rather than an ordinary character strip.
PATH_SEPARATORS = ("/", "\\")

#: The method whose character-set semantics were mistaken for prefix semantics.
METHOD = "lstrip"


def is_defective_argument(value: object) -> bool:
    """True for the exact form that was written three times.

    A string constant that contains a path separator and is longer than one character.
    Length 1 is excluded on purpose -- see the module docstring: with a single character
    the character-set reading and the prefix reading coincide, so there is no defect to
    find and three correct call sites would become noise.
    """
    if not isinstance(value, str):
        return False
    if len(value) < 2:
        return False
    return any(sep in value for sep in PATH_SEPARATORS)


def offences_in_source(source: str) -> list[tuple[int, str]]:
    """`(lineno, literal)` for each defective `.lstrip("...")` call. Pure/testable.

    Raises SyntaxError when the source does not parse; the caller turns that into RED.
    """
    tree = ast.parse(source)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != METHOD:
            continue
        if len(node.args) != 1:
            continue
        argument = node.args[0]
        if not isinstance(argument, ast.Constant):
            continue
        if is_defective_argument(argument.value):
            found.append((node.lineno, argument.value))
    return found


def python_files(root: pathlib.Path) -> list[pathlib.Path]:
    out = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if set(pathlib.PurePosixPath(rel).parts) & SKIP_DIR_NAMES:
            continue
        if rel.startswith(SKIP_REL_PREFIXES):
            continue
        out.append(path)
    return sorted(out)


def scan(root: pathlib.Path) -> tuple[list[str], int]:
    """`(problems, files_scanned)`."""
    problems: list[str] = []
    files = python_files(root)
    for path in files:
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            offences = offences_in_source(text)
        except SyntaxError as exc:
            problems.append(f"{rel}:{exc.lineno or 0}: does not parse ({exc.msg}); this gate "
                            f"cannot vouch for a file it cannot read, so it refuses instead "
                            f"of skipping")
            continue
        for lineno, literal in offences:
            problems.append(
                f"{rel}:{lineno}: .lstrip({literal!r}) strips CHARACTERS, not a prefix -- "
                f"{literal!r} is a character SET here, so a leading dot or slash of any "
                f"length is eaten. Use .removeprefix({literal!r}) if you mean the prefix, or "
                f"pathlib if you mean path normalisation.")
    return problems, len(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[1]))
    args = parser.parse_args(argv)
    root = pathlib.Path(args.root).resolve()

    problems, scanned = scan(root)
    if not problems:
        print(f"GREEN: no `.lstrip()` with a multi-character path-separator argument; "
              f"{scanned} Python file(s) parsed and swept under {root.name}/")
        return 0
    print(f"RED: `lstrip` used as a prefix strip -- {len(problems)} occurrence(s)\n")
    for problem in problems:
        print(f"  - {problem}")
    print(
        "\n`str.lstrip(chars)` removes leading characters that are MEMBERS of `chars`. It is\n"
        "not a prefix removal, and it reads exactly like one. The two ways it goes wrong are\n"
        "opposite: `.claude/x` becomes `claude/x` and matches nothing (a false refusal), and\n"
        "`../tools/x` becomes `tools/x` and matches an allow-listed prefix it should never\n"
        "have reached (a traversal laundered into scope). This form was written three times\n"
        "in this repository before the gate existed; see the module docstring."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
