#!/usr/bin/env python3
"""Every declared CSS custom property is read by something — the reverse of `check_c1_tokens`.

`check_c1_tokens.py` asserts the FORWARD direction: every `var(--x)` resolves to a declaration, so a
rule cannot reference a token nobody defined. That is the direction that produces a visible defect —
Phase 3 shipped two empty states with no padding because `--s7` was referenced and never declared.

Nothing asserted the reverse, and the reverse is where residue accumulates. `T-033` deleted 1 185
unreachable CSS rules; the custom properties those rules read survived the deletion, because nothing
counts a declaration nobody reads. `T-042` found `--hi` by hand while writing a contrast pair for a
background no page paints, and only then did anyone look: **20 of 149 custom properties were declared
and never referenced.**

TWO REASONS A DECLARATION MAY SURVIVE UNREAD, and both are checked rather than assumed:

  * **§C.1 pins it.** The roadmap's design-token specification names 42 tokens by value, and
    `check_c1_tokens.py` requires every one of them to exist in `aios.css`. Nine of the twenty are
    in that list — `--hi`, `--s1`, `--s8`, `--s9`, `--s10`, `--t-hero`, `--t-ui`, `--azure-hover`,
    `--info`. A specification the repository holds itself to is a reason, and it is read FROM the
    roadmap rather than copied here, so the exemption cannot drift from the spec.
  * **It is part of the typed token API.** `tokens.css` declares the `--menq-*`/`--brops-*` surface
    that `tokens.ts` mirrors and `check_token_parity.py` gates. Those are a published contract, not
    internal styling, and a contract may legitimately carry an entry the app has not used yet. Each
    one is listed in `ALLOWED` **by name with its reason** — never by prefix, because a prefix rule
    would exempt every future `--menq-*` token silently, which is the hole this gate exists to close.

Anything else that is declared and unread is residue and should be deleted.

MEASURING IT CORRECTLY MATTERS, and the naive rule gets it wrong. `(--[a-z0-9-]+)\\s*:` counts
`.btn--primary:hover` as declaring `--primary`, because a BEM class name contains a double dash and a
pseudo-class contains a colon. The first scan of this repository reported **24** dead tokens; four of
them were `.dt-row--action`, `.file-row--dir`, `.tile--link` and `.btn--primary`. A declaration is a
`--name:` whose `--` is not preceded by an identifier character.

Usage:  python tools/check_dead_tokens.py [--root DIR]
Exit 0 + "GREEN: ..." / exit 1 + every unread declaration and where it lives.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

SRC = pathlib.Path("apps/desktop/src")
ROADMAP = pathlib.Path("MASTER_EXECUTION_ROADMAP.md")

#: A declaration: `--name:` NOT preceded by an identifier character. The lookbehind is the whole
#: correctness of this gate — without it, every `--modifier:hover` in a BEM stylesheet is a token.
_DECL = re.compile(r"(?<![A-Za-z0-9_-])(--[a-z0-9-]+)\s*:")
#: A reference. `var()` is the only way a custom property is ever read.
_REF = re.compile(r"var\(\s*(--[a-z0-9-]+)")
#: TSX sets custom properties through inline style objects: `{ '--tone': value }`.
_INLINE = re.compile(r"['\"](--[a-z0-9-]+)['\"]\s*:")

_SOURCE_SUFFIXES = (".css", ".ts", ".tsx")

#: Declared, unread, and kept ON PURPOSE — by name, with the reason. Never by prefix: a prefix rule
#: would exempt every future token in the family silently, which is the hole this gate closes.
ALLOWED: dict[str, str] = {
    "--menq-color-accent-text": (
        "published token API, mirrored in tokens.ts and gated by check_token_parity. The button that "
        "would read it uses `--brops-accent-text` instead, which is a separate literal; aligning the "
        "two is a design decision about what 'accent text' means and is not made by a cleanup."
    ),
    "--menq-shadow-1": "published token API (tokens.ts `shadow.sm`); no rule has needed the small shadow yet.",
    "--menq-space-1": "published token API (tokens.ts `space[1]`); the 4px step is unused so far.",
    "--brops-command-surface": (
        "published alias for the command surface, kept alongside the other `--brops-*` aliases so the "
        "family is complete for a consumer reading the stylesheet."
    ),
    "--brops-agent-card-radius": "published alias for the agent-card radius, same reason.",
}


def _read(root: pathlib.Path) -> dict[pathlib.Path, str]:
    src = root / SRC
    if not src.is_dir():
        raise SystemExit(f"RED: {SRC} is not a directory; nothing to scan")
    return {
        p: p.read_text(encoding="utf-8", errors="replace")
        for p in sorted(src.rglob("*"))
        if p.is_file() and p.suffix in _SOURCE_SUFFIXES
    }


def declarations(files: dict[pathlib.Path, str]) -> dict[str, set[str]]:
    """token -> the file names that declare it, from CSS rules and TSX inline style objects."""
    out: dict[str, set[str]] = {}
    for path, text in files.items():
        found = _DECL.finditer(text) if path.suffix == ".css" else _INLINE.finditer(text)
        for match in found:
            out.setdefault(match.group(1), set()).add(path.name)
    return out


def references(files: dict[pathlib.Path, str]) -> set[str]:
    return {m.group(1) for text in files.values() for m in _REF.finditer(text)}


def spec_tokens(root: pathlib.Path) -> set[str]:
    """The tokens §C.1 pins, read FROM the roadmap so the exemption cannot drift from the spec."""
    sys.path.insert(0, str((root / "tools").resolve()))
    try:
        import check_c1_tokens  # noqa: PLC0415  (imported here so the gate has no import-time cost)
        return set(check_c1_tokens.parse_c1((root / ROADMAP).read_text(encoding="utf-8")))
    except Exception as exc:  # a missing/renamed spec must fail closed, not silently exempt nothing
        raise SystemExit(f"RED: could not read the §C.1 token list from {ROADMAP}: {exc}") from exc


def check(root: pathlib.Path, pinned: set[str] | None = None) -> list[str]:
    """Every unread declaration, unless §C.1 pins it or `ALLOWED` names it.

    `pinned` is injected only by the unit tests, whose synthetic trees have no roadmap to read. The
    default — and every real invocation, including `main` — reads it from `MASTER_EXECUTION_ROADMAP.md`
    and fails closed if it cannot, so the exemption cannot drift from the specification. The
    roadmap-reading path is exercised against the shipping tree in `RealRepositoryTests`.
    """
    files = _read(root)
    declared = declarations(files)
    used = references(files)
    pinned = spec_tokens(root) if pinned is None else pinned

    problems: list[str] = []
    for token in sorted(set(declared) - used):
        if token in pinned or token in ALLOWED:
            continue
        where = ", ".join(sorted(declared[token]))
        problems.append(
            f"{token} is declared in {where} and read by nothing. Delete it, or — if it is kept on "
            f"purpose — add it to ALLOWED in {pathlib.Path(__file__).name} with the reason"
        )

    for token in sorted(ALLOWED):
        if token not in declared:
            problems.append(
                f"ALLOWED names {token}, which is declared nowhere. An exemption for a token that "
                f"does not exist is a note nobody will delete"
            )
        elif token in used:
            problems.append(
                f"ALLOWED names {token}, but something reads it now. Remove the exemption — an "
                f"allowlist that outlives its reason is how the next dead token hides"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root)

    problems = check(root)
    if problems:
        print("RED: declared custom properties that nothing reads —", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(f"\n{len(problems)} problem(s).", file=sys.stderr)
        return 1

    files = _read(root)
    declared = declarations(files)
    used = references(files)
    pinned = sorted(set(declared) - used - set(ALLOWED))
    print(
        f"GREEN: {len(declared)} custom properties declared; {len(set(declared) & used)} read by a "
        f"var(); {len(pinned)} unread and pinned by §C.1; {len(ALLOWED)} unread and allowed by name."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
