#!/usr/bin/env python3
"""How much of the design system is dead? A MEASUREMENT, and deliberately not a gate.

**This exists because a number had no home — seventh independent audit, `G-15`.** `T-033`,
`T-029` and `AUDIT_LEDGER.md` all quote *"785 of 2 639 class tokens"*, and no committed tool
computed it. The auditor tried twice and got 1 058 of 2 249 and 1 479 of 2 646 with two reasonable
definitions, neither matching. The numerator was defensible — `T-033`'s row states its method is
crude and safe as a lower bound, so a stricter definition SHOULD yield more — but the denominator
was off by 390 and nobody could re-derive either figure.

That is the same defect the same pull request had just corrected in O-2's *"26 tests"*, whose fix
note reads: *"A number with no home is a number nobody can check."* The next line of that PR
introduced this one.

# WHY THIS EXITS 0, ALWAYS

`T-033` argues correctly that a dead-CSS **gate** must come AFTER the deletion pass, not instead of
it: turned on today it needs a ~785-entry baseline, and a baseline that size is the shape six
rounds of audit keep finding defects hidden inside. `check_schema_mirrors`'s `validates()` and
`check_c1_tokens`'s `ENTRANCE_CLASSES` both failed as exactly that shape.

So this reports and returns 0. If someone later wires it into CI with a threshold, they will have
built the thing its own task warns against. The docstring says so here rather than in a ticket.

# THE DEFINITION, stated so the number can be argued with

  * **Denominator** — every class token named by a selector in the app's stylesheets. That means
    `apps/desktop/src/**/*.css` AND the `<style>` template literals inside `.tsx` files, because
    28 pages carry their CSS there. Comments stripped first.
  * **Numerator** — those that appear in no `.ts`/`.tsx` as a word, MINUS any whose family a
    template literal composes (`fs-` from `fs-${tone}`). That subtraction was added on 2026-08-19
    after the deletion pass proved the crude form wrong in a way that mattered: `fs-info` and
    `fs-mint` are applied by `Files.tsx` through a NESTED template literal, appear nowhere as a
    word, were deleted as dead, and the browser suite went red. It only ever makes the number
    smaller.

The numerator test is CRUDE ON PURPOSE: any mention anywhere counts as live, including in a
comment. That makes the count a safe **lower bound** on what is dead and useless as an instruction
to delete anything. `unstyledClasses` in the browser suite is the precise instrument; this is the
scale of the problem, not the list.

Run:  python tools/count_dead_classes.py [--list]
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "apps" / "desktop" / "src"


def selector_class_tokens(css_texts: list[str]) -> set[str]:
    """Every class token named by a selector. Pure/testable."""
    tokens: set[str] = set()
    for text in css_texts:
        live = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
        for m in re.finditer(r"([^{}@;]+)\{", live):
            tokens |= set(re.findall(r"\.(-?[_a-zA-Z][\w-]*)", m.group(1)))
    return tokens


def code_words(code_texts: list[str]) -> set[str]:
    """Every identifier-ish word in the TypeScript. Pure/testable."""
    words: set[str] = set()
    for text in code_texts:
        words |= set(re.findall(r"[-_a-zA-Z][\w-]*", text))
    return words


def style_literals(tsx: str) -> list[str]:
    """The CSS inside a component's `<style>` template literal, or a bare CSS-looking literal."""
    return [m.group(1) for m in re.finditer(r"`([^`]*\{[^`]*\}[^`]*)`", tsx, re.S)]


def composable_prefixes(code_texts: list[str]) -> set[str]:
    """Static runs a template literal completes with an interpolation, e.g. `fs-` in `fs-${tone}`.

    A class built this way appears in no source file as a word and IS applied by the running app.
    `T-036` found the first instance -- `tier-${a.level}` -- reported as an unstyled class when it
    is nothing of the kind. The deletion pass found the second the expensive way: `fs-info` and
    `fs-mint` were called dead, their rules removed, and the browser suite went red on the next run.

    Scanned over the WHOLE file rather than inside matched template literals, because the literal
    that produced them is NESTED -- `fstat${c.tone ? ` fs-${c.tone}` : ''}` -- and a regex that
    matches a literal from backtick to backtick swallows the inner one. Any `prefix-${` anywhere
    disqualifies that family. Deliberately over-broad: it makes the dead count smaller, never larger.
    """
    prefixes: set[str] = set()
    for text in code_texts:
        prefixes |= set(re.findall(r"([A-Za-z][\w-]*-)\$\{", text))
    return prefixes


def unreachable_selectors(css_texts: list[str], dead: set[str]) -> list[str]:
    """Selectors that can never match, by `T-029`'s rule.

    A comma-separated part dies when ANY class in it names a token nothing applies, because an
    element must carry every class in a compound. Two weaker readings were tried in `T-029` and
    both removed nothing.

    This is the instrument the 2026-08-19 deletion pass used to take `aios.css` from 3 194 rules to
    2 009. It reports; it does not delete, and it is not wired into CI -- `T-033` argues correctly
    that a dead-CSS gate needs a baseline the size of whatever is left, which is the shape six
    rounds of audit keep finding defects hidden inside.
    """
    out: list[str] = []
    for text in css_texts:
        live = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
        for m in re.finditer(r"([^{}@;]+)\{", live):
            sel = m.group(1).strip()
            if not sel or sel.startswith("@"):
                continue
            parts = [p.strip() for p in sel.split(",") if p.strip()]
            if parts and all(set(re.findall(r"\.(-?[_a-zA-Z][\w-]*)", p)) & dead for p in parts):
                out.append(sel)
    return out

def measure(root: pathlib.Path) -> tuple[set[str], set[str]]:
    """(all selector class tokens, the dead ones). Pure-ish: reads the tree, computes nothing else."""
    css_texts, code_texts = [], []
    for path in sorted((root / "apps" / "desktop" / "src").rglob("*")):
        if path.suffix == ".css":
            css_texts.append(path.read_text(encoding="utf-8", errors="replace"))
        elif path.suffix in (".ts", ".tsx"):
            text = path.read_text(encoding="utf-8", errors="replace")
            code_texts.append(text)
            css_texts.extend(style_literals(text))
    named = selector_class_tokens(css_texts)
    words = code_words(code_texts)
    prefixes = composable_prefixes(code_texts)
    dead = {n for n in named if n not in words and not any(n.startswith(p) for p in prefixes)}
    return named, dead


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--list", action="store_true", help="print every dead token, not just the count")
    ap.add_argument("--rules", action="store_true",
                    help="print the selectors that can never match, by T-029's compound rule")
    args = ap.parse_args(argv)

    named, dead = measure(pathlib.Path(args.root))
    pct = (100.0 * len(dead) / len(named)) if named else 0.0
    print(f"{len(dead)} of {len(named)} class tokens named by a rule appear in no .ts/.tsx "
          f"({pct:.0f}% of the design system).")
    print("REPORT ONLY — this exits 0 by design. See the docstring, and T-033.")
    if args.list:
        for name in sorted(dead):
            print(f"  {name}")
    if args.rules:
        root = pathlib.Path(args.root)
        css_texts = []
        for path in sorted((root / "apps" / "desktop" / "src").rglob("*")):
            if path.suffix == ".css":
                css_texts.append(path.read_text(encoding="utf-8", errors="replace"))
            elif path.suffix in (".ts", ".tsx"):
                css_texts.extend(style_literals(path.read_text(encoding="utf-8", errors="replace")))
        sels = unreachable_selectors(css_texts, dead)
        print(f"{len(sels)} selector(s) can never match (T-029's compound rule):")
        for sel in sels:
            print(f"  {sel[:110]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
