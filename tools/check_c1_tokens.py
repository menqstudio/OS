#!/usr/bin/env python3
"""§C.1 is the design system's specification. This makes it a check instead of a promise.

`MASTER_EXECUTION_ROADMAP.md` §C.1 names every design token by value — the brand and semantic
colours, the type scale, the radii, the spacing ladder, the motion durations. Phase 3's Definition
of Done says *"design-token stylesheet reproducing §C.1"*. Nothing verified it. `check_token_parity`
compares `tokens.ts` against `tokens.css` for the `--menq-*` variables, which is a different pair of
files and a different set of names; the `--azure`/`--s4`/`--t-body` ladder the whole cockpit is
actually built on had no gate at all.

Two failures follow from that, and this file refuses both.

1. DRIFT. A token whose value in `aios.css` stops matching the value §C.1 states. The roadmap is the
   spec, so the roadmap wins, and the diff is printed both ways round.

2. A REFERENCE TO A TOKEN THAT DOES NOT EXIST — which is how this gate was born. `--s7` and `--s9`
   were absent from a ladder documented as `--s1..--s10`, and `padding:var(--s7) var(--s5)` shipped
   on the Agents and Automations empty states. An undeclared custom property does not fall back to
   nothing sensible: the *whole declaration* becomes invalid at computed-value time, so those panels
   had no padding. Nothing broke loudly, no test failed, and the roadmap's own §C.1 listed eight
   values for a ten-name range, so the gap looked deliberate to anyone who checked.

   This is the class of bug a stylesheet cannot report on itself, and it is exactly what a machine
   should be reading for.

Run:  python tools/check_c1_tokens.py
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "MASTER_EXECUTION_ROADMAP.md"
AIOS_CSS = ROOT / "apps" / "desktop" / "src" / "theme" / "aios.css"
#: Where a `var(--token)` reference may appear. The page stylesheets live inside the .tsx files as
#: template literals, which is why this is not a *.css-only sweep.
SOURCE_GLOBS = ("apps/desktop/src/**/*.css", "apps/desktop/src/**/*.tsx", "apps/desktop/src/**/*.ts")

#: Token families §C.1 states positionally rather than as `--name value` pairs. Each maps the
#: roadmap row label to the token names, in the order the row lists its values.
POSITIONAL = {
    "Type scale": ["--t-hero", "--t-h1", "--t-h2", "--t-body", "--t-ui", "--t-small", "--t-micro"],
    "Radii": ["--r-sm", "--r", "--r-lg", "--r-xl", "--r-pill"],
    "Spacing": ["--s%d" % i for i in range(1, 11)],
}


def parse_c1(markdown: str) -> dict[str, str]:
    """Every token §C.1 pins, as name -> expected value. Pure/testable.

    Two shapes are read. Inline pairs — `` `--azure #0A84FF` `` — carry their own name. Positional
    rows — ``hero 32 · h1 24 · … (px)`` — carry a list of numbers whose names come from POSITIONAL,
    matched by ORDER, which is why a row with the wrong number of values is an error rather than a
    silent partial read: that mismatch is precisely the §C.1 spacing bug.
    """
    section = re.search(r"^### C\.1 .*?$(.*?)^### ", markdown, re.S | re.M)
    if not section:
        raise ValueError("could not locate the '### C.1' section in the roadmap")
    body = section.group(1)
    expected: dict[str, str] = {}

    for name, value in re.findall(r"`(--[a-z0-9-]+)\s+([^`]+)`", body):
        expected[name] = value.strip()

    for row_label, names in POSITIONAL.items():
        row = re.search(r"^\|\s*\*\*%s\*\*\s*\|(.+?)\|\s*$" % re.escape(row_label), body, re.M)
        if not row:
            raise ValueError("§C.1 has no '%s' row" % row_label)
        cell = row.group(1)
        numbers = re.findall(r"(?<![\w.-])(\d+)(?![\w.])", cell.split("—")[0])
        if len(numbers) != len(names):
            raise ValueError(
                "§C.1 '%s' lists %d values for %d token names (%s..%s) — the row and the names "
                "must agree, or a reader cannot tell which token a number belongs to"
                % (row_label, len(numbers), len(names), names[0], names[-1]))
        for name, number in zip(names, numbers):
            expected[name] = number + "px"
    return expected


def root_declarations(css: str) -> dict[str, str]:
    """Every custom property declared in the FIRST `:root` block. Pure/testable.

    The first block only: later `:root` blocks in this stylesheet are responsive overrides inside
    `@media`, and a phone-tier override of `--s5` is not the token's declared value.
    """
    block = re.search(r":root\s*\{(.*?)\n\}", css, re.S)
    if not block:
        raise ValueError("aios.css has no :root block")
    return {k: v.strip() for k, v in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;}]+)[;}]", block.group(1))}


def referenced_tokens(texts: dict[str, str]) -> dict[str, list[str]]:
    """token -> the files that say `var(--token)` WITH NO FALLBACK. Pure/testable.

    `var(--x, 12px)` is not a bug and never was: an undeclared `--x` there resolves to the
    fallback and the declaration stands. Only the bare `var(--x)` takes the whole declaration
    down with it. A gate that flagged both would be reporting a style choice as a defect, and
    would be ignored within a week — which is the failure mode that matters most for a new check.
    """
    refs: dict[str, list[str]] = {}
    for label, text in texts.items():
        # Comments are prose, not code. `/* glows are rgb(var(--x-rgb)/a) */` documents a NAMING
        # CONVENTION; reading it as a reference reports the documentation as the defect.
        live = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
        for name in set(re.findall(r"var\(\s*(--[a-z0-9-]+)\s*\)", live)):
            refs.setdefault(name, []).append(label)
    return refs


def compare(expected: dict[str, str], declared: dict[str, str]) -> list[str]:
    """§C.1 against the stylesheet. Pure/testable.

    A duration in §C.1 (`--fast 130ms`) is a PREFIX claim, not the whole value: the stylesheet adds
    the easing curve (`130ms cubic-bezier(.2,.6,.2,1)`), which §C.1 deliberately does not spell out
    per-token. Demanding equality there would force the spec to carry implementation detail; the
    first whitespace-separated token is the part §C.1 is actually asserting.
    """
    failures: list[str] = []
    for name, want in sorted(expected.items()):
        got = declared.get(name)
        if got is None:
            failures.append(f"§C.1 pins {name} = {want!r}, but aios.css :root does not declare it")
            continue
        got_norm = re.sub(r"\s+", " ", got).strip()
        if got_norm == want or got_norm.split(" ")[0] == want:
            continue
        failures.append(f"{name}: §C.1 says {want!r}, aios.css says {got_norm!r}")
    return failures


def undeclared_references(refs: dict[str, list[str]], declared, local_ok: set[str]) -> list[str]:
    """`var(--x)` where nothing declares `--x`. Pure/testable.

    `local_ok` are properties a component sets on itself (`--i`, `--tone-rgb`, …) rather than
    inheriting from `:root`; they are legitimately absent from the root block. Everything else that
    is referenced and never declared anywhere is a dropped declaration at runtime.
    """
    failures = []
    for name, where in sorted(refs.items()):
        if name in declared or name in local_ok:
            continue
        files = ", ".join(sorted(set(where))[:4])
        failures.append(
            f"var({name}) is used in {files} but {name} is declared nowhere — the whole "
            f"declaration containing it is invalid at computed-value time and is dropped")
    return failures


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root)

    markdown = (root / "MASTER_EXECUTION_ROADMAP.md").read_text(encoding="utf-8")
    css_path = root / "apps" / "desktop" / "src" / "theme" / "aios.css"
    css = css_path.read_text(encoding="utf-8")

    expected = parse_c1(markdown)
    declared = root_declarations(css)

    texts: dict[str, str] = {}
    for pattern in SOURCE_GLOBS:
        for path in root.glob(pattern):
            texts[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8", errors="replace")
    # Anything SET anywhere in the tree counts as declared for the reference check; only the §C.1
    # comparison insists on the root block. "Set" has to include the React inline-style form —
    # `style={{ ['--i']: index }}` is how every staggered list in this app passes its index to CSS,
    # and a scan that only understood `--i: 0;` would report all of them as broken. The looser
    # pattern is deliberate: this check exists to find tokens NOTHING sets, so it must err toward
    # believing a token is set.
    declared_anywhere = set(declared)
    for text in texts.values():
        declared_anywhere |= set(re.findall(r"""['"\[\s]*(--[a-z0-9-]+)['"\]\s]*:""", text))
        declared_anywhere |= set(re.findall(r"""setProperty\(\s*['"](--[a-z0-9-]+)['"]""", text))

    failures = compare(expected, declared)
    failures += undeclared_references(referenced_tokens(texts), declared_anywhere, local_ok=set())

    if failures:
        print("RED: §C.1 design tokens —", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print(f"\n{len(failures)} problem(s). §C.1 is the spec; aios.css must reproduce it.", file=sys.stderr)
        return 1
    print(f"GREEN: aios.css :root reproduces all {len(expected)} §C.1 tokens, and every var(--x) "
          f"in apps/desktop/src resolves to a declaration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
