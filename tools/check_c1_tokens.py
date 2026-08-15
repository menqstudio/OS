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


def root_blocks(css: str) -> list[dict[str, str]]:
    """EVERY `:root` block's declarations, base first. Pure/testable.

    Reading only the first block was a hole big enough to drive the bug through. The stylesheet has
    three `:root`s — the base and two overrides — and 17 of the 42 §C.1 tokens are redeclared after
    the first, so an override could change `--azure` to red, or `--s4` to 99px, and the gate stayed
    GREEN. The fifth audit demonstrated exactly that (A-04). The base block still decides §C.1
    parity, because an override is a responsive tier and not the token's declared value; the
    overrides are checked for internal consistency instead.
    """
    blocks = [
        # `body + ";"` because the LAST declaration in a block is usually written without a
        # trailing semicolon, and the closing brace has already been eaten by the block pattern.
        # Without it `:root{ --s5:16px; --s10:30px }` silently loses `--s10` — which is the rung
        # the phone tier had wrong, so the check would have missed the very thing it was added for.
        {k: v.strip() for k, v in re.findall(r"(--[a-zA-Z0-9-]+)\s*:\s*([^;}]+);", body + ";")}
        for body in re.findall(r":root[^{]*\{(.*?)\}", css, re.S)
    ]
    if not blocks:
        raise ValueError("aios.css has no :root block")
    return blocks


def root_declarations(css: str) -> dict[str, str]:
    """The BASE `:root` — the block §C.1 parity is measured against. Pure/testable."""
    return root_blocks(css)[0]


def ladder_monotonic(blocks: list[dict[str, str]], names: list[str]) -> list[str]:
    """The spacing ladder must not run backwards in ANY tier. Pure/testable.

    `--s1..--s10` is an ordered scale, and code picks a rung by meaning — `--s7` is "more than
    `--s6`, less than `--s8`". A tier that tightens some rungs and not others breaks that promise
    silently: the phone tier dropped `--s8` to 24px while `--s7` stayed at 28px, so a panel using
    `padding:var(--s7) var(--s5)` kept desktop-tier vertical padding on a phone while its
    horizontal padding tightened. Nothing renders wrong enough to notice; it is simply wrong.
    """
    failures = []
    for index, block in enumerate(blocks):
        # A block that touches NO rung cannot make the ladder inconsistent, so it is skipped. One
        # that touches a SINGLE rung very much can — the partial tier is the dangerous shape,
        # because it looks harmless and is compared against nothing. The first version required
        # two rungs in the block itself and therefore missed exactly that case.
        if index > 0 and not any(n in block for n in names):
            continue
        # An override tier need not restate every rung; the ones it DOES restate are compared
        # against the effective value, base-then-override, so a partial tier is still checked.
        effective = dict(blocks[0])
        for earlier in blocks[1:index + 1]:
            effective.update(earlier)
        values = []
        for name in names:
            raw = effective.get(name)
            if raw is None:
                continue
            match = re.fullmatch(r"(\d+(?:\.\d+)?)px", raw.strip())
            if not match:
                failures.append(f":root block {index}: {name} = {raw!r} is not a px length")
                continue
            values.append((name, float(match.group(1))))
        for (a_name, a), (b_name, b) in zip(values, values[1:]):
            if b < a:
                failures.append(
                    f":root block {index}: the spacing ladder runs backwards — {a_name}={a:g}px "
                    f"but {b_name}={b:g}px. A tier that tightens some rungs and not others makes "
                    f"'one step larger' false for whoever picked the token by meaning.")
    return failures


def referenced_tokens(texts: dict[str, str]) -> dict[str, list[str]]:
    """token -> the files that say `var(--token)` WITH NO FALLBACK. Pure/testable.

    `var(--x, 12px)` is not a bug and never was: an undeclared `--x` there resolves to the
    fallback and the declaration stands. Only the bare `var(--x)` takes the whole declaration
    down with it. A gate that flagged both would be reporting a style choice as a defect, and
    would be ignored within a week — which is the failure mode that matters most for a new check.

    A NESTED fallback — `var(--a, var(--b))` — does report `--b`, and that is deliberate rather
    than an oversight: `--b` is the last resort, so if nothing declares it the declaration still
    drops when `--a` is absent. The repository has exactly one such site today
    (`var(--k, var(--ink-muted))`) and it passes because `--ink-muted` is declared, which is the
    behaviour worth keeping.

    KNOWN LIMITS, stated rather than implied. Uppercase is matched now (`--Foo` used to slip past
    a lowercase-only class), and comments are stripped on both sides. What this cannot do is
    SCOPE: a token declared on `.a` in one file satisfies a bare reference on `.b` in another,
    because a custom property inherits and this check has no cascade. Narrowing it to same-file
    would be wrong — half this app's tokens are set from React inline styles in a different file
    from the CSS that reads them.
    """
    refs: dict[str, list[str]] = {}
    for label, text in texts.items():
        # Comments are prose, not code. `/* glows are rgb(var(--x-rgb)/a) */` documents a NAMING
        # CONVENTION; reading it as a reference reports the documentation as the defect.
        live = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
        for name in set(re.findall(r"var\(\s*(--[a-zA-Z0-9-]+)\s*\)", live)):
            refs.setdefault(name, []).append(label)
    return refs


#: Classes whose ELEMENT IS INVISIBLE until an animation runs. `.reveal`/`.rise` are
#: `opacity:0; transform:translateY(14px); animation:reveal …` — the entrance animation is the
#: only thing that paints them. Anything that overrides `animation` on such an element must keep
#: the entrance in the list.
ENTRANCE_CLASSES = {"reveal": "reveal", "rise": "reveal"}


def classname_groups(texts: dict[str, str]) -> list[set[str]]:
    """Every set of class tokens that appear together in one `className`. Pure/testable.

    Template interpolations are dropped rather than guessed at: `sec-int--${integrity}` contributes
    nothing, which is the safe direction — this feeds a check that must not invent a rule match.
    """
    groups: list[set[str]] = []
    for text in texts.values():
        for match in re.finditer(r"className=", text):
            i = match.end()
            if i >= len(text):
                continue
            if text[i] in "\"'":                      # className="a b c"
                end = text.find(text[i], i + 1)
                region = text[i + 1:end] if end != -1 else ""
            elif text[i] == "{":                      # className={`a ${x} b` : ''} — brace-matched,
                depth, j = 0, i                       # so a conditional class is not truncated at
                while j < len(text):                  # the first quote inside the interpolation.
                    if text[j] == "{":
                        depth += 1
                    elif text[j] == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                region = text[i + 1:j]
            else:
                continue
            # Two passes, because a class can hide in either half of a template literal.
            #  1. Quoted literals ANYWHERE in the attribute, including inside an interpolation —
            #     `integrity === 'checking' ? ' sigbreathe' : ''` is where `sigbreathe` lives, and
            #     dropping interpolations wholesale would lose exactly the conditional classes that
            #     matter most, since those are the ones a reviewer never sees applied.
            #  2. The literal text of the template itself, with interpolations removed.
            # Over-inclusion is the safe direction here: a stray token can only make this check
            # consider MORE rules, and every rule it considers is printed with its selector.
            tokens: set[str] = set()
            for literal in re.findall(r"['\"]([^'\"\n]*)['\"]", region):
                tokens |= {t for t in literal.split() if re.fullmatch(r"[a-z][\w-]*", t)}
            for literal in re.findall(r"`([^`]*)`", region):
                stripped = re.sub(r"\$\{[^{}]*\}", " ", literal)
                tokens |= {t for t in stripped.split() if re.fullmatch(r"[a-z][\w-]*", t)}
            if tokens:
                groups.append(tokens)
    return groups


def animation_clobber(texts: dict[str, str], groups: list[set[str]]) -> list[str]:
    """A rule that REPLACES the animation on an element whose visibility depends on one.

    THIS IS A-01 FROM THE FIFTH AUDIT, TURNED INTO A CHECK. `.v-security .mani.sigbreathe` set the
    `animation` SHORTHAND at specificity (0,3,0) on an element that also carries `.reveal` (0,1,0).
    The shorthand replaces the whole animation list, so `reveal` never ran, and the instrument
    rendered at `opacity:0`, displaced 14px, for the entire state the pulse was added to depict.

    Nothing in this repository could see it. `vitest.config.ts` sets `css: false`, so 652 unit
    tests and the whole axe suite run against a DOM with no stylesheet attached; the test asserted
    that the string `sigbreathe` was in a className, which was true, and said nothing about paint.
    A real browser is the only thing that measures this, and there is none here — so the check is
    static: find rules that set the `animation` shorthand, work out which elements they can match
    from the class sets the components actually render, and require the entrance animation to
    survive in the list.

    Deliberately conservative. A selector is only judged when EVERY class in it appears together
    in some real `className`, so an unmatched or dynamically-composed selector is skipped rather
    than guessed at. It under-reports; it does not invent.
    """
    # A keyframe set whose FINAL state paints the element is a legitimate replacement: the
    # entrance no longer has to run, because this animation does the same job. `dec-reveal`
    # (`to{opacity:1}`) is exactly that and must not be reported. What is NOT legitimate is a
    # final keyframe that omits opacity, because the implicit 100% is then built from the
    # UNDERLYING value — which is the `opacity:0` the entrance class set.
    all_css = "\n".join(re.sub(r"/\*.*?\*/", " ", t, flags=re.S) for t in texts.values())
    self_sufficient = set()
    for name, frames in re.findall(r"@keyframes\s+([\w-]+)\s*\{(.*?)\n?\s*\}\s*(?:\n|$)", all_css, re.S):
        last = re.findall(r"(?:100%|to)\s*\{([^{}]*)\}", frames)
        if last and re.search(r"opacity\s*:\s*(?!0\b)[\d.]+", last[-1]):
            self_sufficient.add(name)

    failures: list[str] = []
    for label, text in texts.items():
        live = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
        # A reduced-motion block is exempt: `aios.css` makes `.reveal`/`.rise` `opacity:1` outright
        # there, so killing the animation is what SHOULD happen and is not a clobber.
        live = re.sub(r"@media[^{]*prefers-reduced-motion[^{]*\{.*?\n\s*\}", " ", live, flags=re.S)
        for selector, body in re.findall(r"([^{}@;]+)\{([^{}]*)\}", live):
            decl = re.search(r"(?<![-\w])animation\s*:\s*([^;}]+)", body)
            if not decl:
                continue
            names = set(re.findall(r"[a-zA-Z][\w-]*", decl.group(1)))
            if names & self_sufficient:
                continue
            for part in selector.split(","):
                # A PSEUDO-ELEMENT is a different box. `.surface:hover::after{animation:…}` animates
                # the generated child, and the element's own `reveal` is untouched — flagging it
                # would be reporting correct CSS as a defect, which is how a new gate gets ignored.
                # Pseudo-CLASSES are NOT exempt: `.a:hover{animation:…}` really does replace it.
                if re.search(r"::[a-zA-Z-]+|:(?:before|after|first-line|first-letter)\b", part):
                    continue
                # ONLY THE SUBJECT COMPOUND. `.v-security .mani.sigbreathe` styles `.mani.sigbreathe`;
                # `.v-security` is an ANCESTOR and never appears in the same className. Matching the
                # whole selector against one element's classes was why the first version of this
                # check could not see the very rule it was written for.
                subject = re.split(r"[\s>+~]+", part.strip())[-1]
                classes = set(re.findall(r"\.([a-zA-Z][\w-]*)", subject))
                if not classes:
                    continue
                for group in groups:
                    if not classes <= group:
                        continue
                    for entrance_class, keyframe in ENTRANCE_CLASSES.items():
                        if entrance_class in group and entrance_class not in classes \
                                and keyframe not in names:
                            failures.append(
                                f"{label}: `{part.strip()}` sets the `animation` shorthand without "
                                f"`{keyframe}`, on an element that also carries `.{entrance_class}` "
                                f"— which is `opacity:0` until `{keyframe}` runs. The shorthand "
                                f"replaces the whole list, so this element never becomes visible. "
                                f"Include `{keyframe}` in the list, or use the animation-* longhands.")
                    break
    return sorted(set(failures))


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
    blocks = root_blocks(css)
    declared = blocks[0]

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
        # Comments are stripped HERE TOO. They were stripped on the reference side and not on the
        # declaring side, so `/* --x: 4px */` in any file silenced a real undeclared `var(--x)`
        # anywhere in the tree — a check defeated by a comment (A-09, fifth audit).
        live = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
        for name, value in re.findall(
                r"""['"\[\s]*(--[a-zA-Z0-9-]+)['"\]\s]*:\s*([^;,}\n]*)""", live):
            # A TYPE ANNOTATION SETS NOTHING. `type T = { '--x': string }` matched the same shape
            # as a real declaration and counted as one. A bare TS primitive on the value side is
            # never a CSS value, so it is the cheap, exact discriminator.
            if value.strip().rstrip("|&?") .strip() in {"string", "number", "boolean", "any", "unknown"}:
                continue
            declared_anywhere.add(name)
        declared_anywhere |= set(re.findall(r"""setProperty\(\s*['"](--[a-zA-Z0-9-]+)['"]""", live))

    failures = compare(expected, declared)
    failures += ladder_monotonic(blocks, POSITIONAL["Spacing"])
    failures += animation_clobber(texts, classname_groups(texts))
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
