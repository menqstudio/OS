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
    three `:root`s — the base, a theme and a responsive tier — and 17 of the 42 §C.1 tokens are
    redeclared after the first, so an override could change `--azure` to red, or `--s4` to 99px,
    and the gate stayed GREEN. The fifth audit demonstrated exactly that (its `A-04`).

    **This docstring then claimed both halves were closed, and only one was.** The sixth
    independent audit's `A-10` measured the other: `--azure:#FF0000` in a new `@media :root` and in
    `:root[data-theme="light"]` were both still GREEN — the example named here by hand. `--s4` was
    covered because `ladder_monotonic` happened to see it; nothing looked at colours at all.

    Both are covered now, by two different rules, because they are two different questions:

      * `ladder_monotonic` asks whether an ORDERED SCALE still runs the way the base declares it —
        applied to spacing, the type scale and the radii, which is where `--t-body:99px` and
        `--r-pill:0px` were also green;
      * `override_scope` asks whether a block is entitled to touch that family of token AT ALL —
        a theme may restate colours, a responsive tier may restate geometry, and neither may do
        the other's job.

    The base block still decides §C.1 parity, because an override is a tier and not the token's
    declared value.
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


def root_block_kinds(css: str) -> list[str]:
    """What KIND each `:root` block is, in the same order as `root_blocks`. Pure/testable.

    `base` | `theme` (a `[data-theme=…]` attribute selector) | `responsive` (inside an `@media`).
    A block that is neither is `other`, and `override_scope()` refuses those rather than guessing
    what they are entitled to change.
    """
    kinds: list[str] = []
    for m in re.finditer(r"(:root[^{]*)\{", css):
        selector = m.group(1)
        before = css[:m.start()]
        # Inside an @media? Count braces since the last @media opener: still open means inside.
        in_media = False
        last = None
        for med in re.finditer(r"@media[^{]*\{", before):
            last = med
        if last is not None:
            tail = css[last.end():m.start()]
            if tail.count("{") - tail.count("}") >= 0:
                in_media = True
        themed = "[data-theme" in selector
        # BOTH IS NOT THEME — seventh independent audit, `G-11(b)`. This tested `[data-theme` FIRST
        # and returned, so `@media (max-width:560px){:root[data-theme="dark"]{--azure:#FF0000}}`
        # classified as a theme and colour was permitted — while the rule's own justification is
        # *"a surface does not become a different colour at 560px"*, which is exactly what that
        # passes. A viewport-conditional colour change escaped by adding a theme attribute.
        #
        # A block that is both is held to the INTERSECTION: it may restate neither. That is the
        # honest reading — it is making a claim conditional on the viewport AND on the theme, and
        # neither of the two justifications covers the other's half.
        if themed and in_media:
            kinds.append("responsive-theme")
        elif themed:
            kinds.append("theme")
        elif in_media:
            kinds.append("responsive")
        elif not kinds:
            kinds.append("base")
        else:
            kinds.append("other")
    return kinds


#: Which §C.1 tokens are COLOUR and which are GEOMETRY. A token whose declared value is a hex
#: colour is a colour; everything else in §C.1 is a length, a duration or an easing curve.
def token_kinds(expected: dict[str, str]) -> dict[str, str]:
    """`{token: 'colour' | 'geometry'}` from §C.1's own declared values. Pure/testable."""
    return {name: ("colour" if value.strip().startswith("#") else "geometry")
            for name, value in expected.items()}


def override_scope(blocks: list[dict[str, str]], kinds: list[str],
                   kinds_by_token: dict[str, str]) -> list[str]:
    """What each `:root` override is ENTITLED to change — sixth independent audit, `A-10`.

    `root_blocks`'s docstring claimed the closed hole was that *"an override could change
    `--azure` to red, or `--s4` to 99px, and the gate stayed GREEN."* Only the `--s4` half was
    closed, by `ladder_monotonic`. The auditor measured the other: `--azure:#FF0000` in a new
    `@media :root`, and again in `:root[data-theme="light"]`, both **GREEN** — the docstring's own
    hand-picked example, still open.

    Forbidding colour overrides outright would have been the wrong fix, and is why this took a
    rule rather than a patch: `:root[data-theme="light"]` redeclares 42 colour tokens and that is
    exactly what a theme IS. What each kind of block may change is different:

      * a **theme** block exists to restate colours. Geometry has no theme — a light layout and a
        dark layout are the same layout — so a theme that moves the spacing ladder or the type
        scale is changing something no reader asked it to.
      * a **responsive** block exists to restate geometry. A colour has no responsive meaning: a
        surface does not become a different colour at 560px, and a rule that says it does is
        either a mistake or a defect hidden where nobody reads.

    So the check is per-kind, and each direction is a real failure rather than a stylistic one.
    Ordering within a scale is still `ladder_monotonic`'s job; this is about which scales a block
    is allowed to touch at all.
    """
    # A `responsive-theme` block - one inside an `@media` that ALSO carries
    # `[data-theme]` - may restate NEITHER family. See `root_block_kinds()` for
    # why (seventh independent audit, `G-11(b)`).
    allowed = {"theme": "colour", "responsive": "geometry", "responsive-theme": None}
    failures: list[str] = []
    for index, (block, kind) in enumerate(zip(blocks, kinds)):
        if kind == "base":
            continue
        if kind == "other":
            failures.append(
                f":root block {index} is neither the base, a [data-theme=…] theme nor a responsive "
                f"@media tier. This gate cannot say what it is entitled to change, and a block "
                f"nobody can classify is where a token change hides. Give it one of those shapes.")
            continue
        may = allowed[kind]
        for name in sorted(block):
            token_kind = kinds_by_token.get(name)
            if token_kind is None or token_kind == may:
                continue
            if may is None:
                failures.append(
                    f":root block {index} is inside an @media AND carries [data-theme], and "
                    f"redeclares `{name}`. A block conditional on BOTH the viewport and the theme "
                    f"may restate neither family: the theme justification (a light layout and a "
                    f"dark layout are the same layout) does not cover the viewport half, and the "
                    f"responsive justification (a surface does not become a different colour at a "
                    f"narrower viewport) does not cover the theme half. Split it into two blocks.")
                continue
            failures.append(
                f":root block {index} ({kind}) redeclares `{name}`, which is a {token_kind} token. "
                f"A {kind} block may only restate {may}: "
                + ("a light layout and a dark layout are the same layout."
                   if kind == "theme" else
                   "a surface does not become a different colour at a narrower viewport."))
    return failures


def ladder_monotonic(blocks: list[dict[str, str]], names: list[str],
                     scale: str = "spacing ladder") -> list[str]:
    """An ordered scale must not reorder itself in ANY tier. Pure/testable.

    `--s1..--s10` is an ordered scale, and code picks a rung by meaning — `--s7` is "more than
    `--s6`, less than `--s8`". A tier that tightens some rungs and not others breaks that promise
    silently: the phone tier dropped `--s8` to 24px while `--s7` stayed at 28px, so a panel using
    `padding:var(--s7) var(--s5)` kept desktop-tier vertical padding on a phone while its
    horizontal padding tightened. Nothing renders wrong enough to notice; it is simply wrong.

    **The DIRECTION is read from the base block rather than assumed.** This applies to the type
    scale and the radii too (`A-10`: `--t-body:99px` and `--r-pill:0px` in a later override were
    both measured GREEN), and the type scale runs the other way — `--t-hero` 32px down to
    `--t-micro` 10px. An ascending-only check reported the correct base type scale as six
    failures the first time it was pointed at it, which is how a gate gets switched off rather
    than fixed. The invariant is not "increasing"; it is "the order the base declares still
    holds".
    """
    def read(block: dict[str, str], on_error: list[str] | None, index: int) -> list[tuple[str, float]]:
        out = []
        for name in names:
            raw = block.get(name)
            if raw is None:
                continue
            match = re.fullmatch(r"(\d+(?:\.\d+)?)px", raw.strip())
            if not match:
                if on_error is not None:
                    on_error.append(f":root block {index}: {name} = {raw!r} is not a px length")
                continue
            out.append((name, float(match.group(1))))
        return out

    failures: list[str] = []
    base_values = read(blocks[0], failures, 0)
    ups = sum(1 for (_, a), (_, b) in zip(base_values, base_values[1:]) if b > a)
    downs = sum(1 for (_, a), (_, b) in zip(base_values, base_values[1:]) if b < a)
    if ups and downs:
        failures.append(
            f"the base {scale} is not ordered at all — it rises {ups} time(s) and falls {downs}. "
            f"Nothing downstream can be checked against a scale that has no direction.")
        return failures
    ascending = ups >= downs
    _ = ascending  # direction is applied below
    failures_local = []
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
        values = read(effective, failures_local if index else None, index)
        for (a_name, a), (b_name, b) in zip(values, values[1:]):
            if (b < a) if ascending else (b > a):
                way = "larger" if ascending else "smaller"
                failures_local.append(
                    f":root block {index}: the {scale} reorders itself — {a_name}={a:g}px but "
                    f"{b_name}={b:g}px, and the base declares this scale getting {way} along its "
                    f"length. A tier that reorders some rungs and not others makes 'one step "
                    f"{way}' false for whoever picked the token by meaning.")
    return failures + failures_local


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


#: Seeds only. The real set is DERIVED from the stylesheet by `entrance_classes()` below.
#:
#: This used to be the whole list, and the sixth independent audit's `A-04` measured the cost:
#: the check knew two entrance classes while **fourteen** rules in the tree declare `opacity:0`
#: together with an animation and are equally invisible-until-animated — `.chat-typing span`,
#: `.strip--sweeping .strip-sweep`, `.shimmer`, `.sigil::before`, `.spark .fill`, `.spark .end`,
#: `.v-agents .lat-links .ll`, `.v-analytics .an-fill`, `.v-analytics .an-emk`, `.v-files .slab`,
#: `.v-home .wf-fill`, `.v-notifications .band`. A hand-maintained list of the dangerous shapes is
#: only ever as current as the last person who remembered it.
ENTRANCE_CLASSES = {"reveal": "reveal", "rise": "reveal"}

#: Words the `animation` shorthand can contain that are NOT keyframe names.
#:
#: `A-04`'s latent third finding: the name harvest takes every identifier out of the shorthand, so
#: a keyframe called `forwards`, `infinite` or `both` would make every declaration containing that
#: word "self-sufficient" and switch the whole check off. No such collision exists among the
#: tree's 163 keyframe names today — `keyframe_name_collisions()` is what keeps it that way.
ANIMATION_KEYWORDS = {
    "normal", "reverse", "alternate", "alternate-reverse",
    "none", "forwards", "backwards", "both",
    "running", "paused", "infinite",
    "linear", "ease", "ease-in", "ease-out", "ease-in-out", "step-start", "step-end",
    "steps", "cubic-bezier", "var", "s", "ms", "initial", "inherit", "unset", "revert",
}


def entrance_classes(all_css: str) -> dict[str, str]:
    """Every class whose element is INVISIBLE until its own animation runs. Pure/testable.

    Derived from the stylesheet rather than listed by hand (`A-04`). A rule that declares
    `opacity: 0` and an animation in the same body is making the animation load-bearing: the
    element does not paint until it runs, so anything that later replaces the animation list on
    that element deletes its only path to being visible. That is `A-01`, and it is a property of
    the rule, not of a name someone remembered to add here.

    The SUBJECT compound is what gets recorded — for `.spark .fill` that is `fill` — because that
    is the element the animation is on and the element another rule would clobber.

    Conservative in the direction that matters: a rule with no class in its subject contributes
    nothing, and a keyframe that cannot be named is skipped rather than guessed at. The result
    only ever makes the clobber check consider MORE elements, and every one it reports is printed
    with its selector.
    """
    found = dict(ENTRANCE_CLASSES)
    live = re.sub(r"/\*.*?\*/", " ", all_css, flags=re.S)
    for selector, body in re.findall(r"([^{}@;]+)\{([^{}]*)\}", live):
        if not re.search(r"(?<![-\w])opacity\s*:\s*0\s*(?:[;}]|$)", body + ";"):
            continue
        decl = re.search(r"(?<![-\w])animation(?:-name)?\s*:\s*([^;}]+)", body)
        if not decl:
            continue
        names = [n for n in re.findall(r"[a-zA-Z][\w-]*", decl.group(1))
                 if n not in ANIMATION_KEYWORDS]
        if not names:
            continue
        for part in selector.split(","):
            subject = re.split(r"[\s>+~]+", part.strip())[-1]
            # A pseudo-element is a different box and cannot be clobbered by a class rule on the
            # element itself, so `.sigil::before` contributes nothing here.
            if re.search(r"::[a-zA-Z-]+", subject):
                continue
            for cls in re.findall(r"\.([a-zA-Z][\w-]*)", subject):
                found.setdefault(cls, names[0])
    return found


def all_source_css(texts: dict[str, str]) -> str:
    """Every source file's text, comments stripped — the surface `animation_clobber` actually reads.

    Seventh independent audit, `G-13`: `keyframe_name_collisions` was called with `aios.css` alone
    while the check it guards builds its keyframe set from every file in `SOURCE_GLOBS`, so a
    keyword-named `@keyframes` in any other stylesheet — or in one of the 28 in-component `<style>`
    template literals — was invisible to the guard.

    The auditor was scrupulous about the severity and so is this note: **they could not turn it
    into an escape.** `ANIMATION_KEYWORDS` is subtracted from `names` inside `animation_clobber`
    regardless of where the keyframe was defined, so `names & self_sufficient` cannot be satisfied
    by a keyword-named keyframe. What remains is the reverse — a legitimate rule using one would
    compute `names = {}` and be falsely reported. That is noise, not silence, and it is fixed as
    the lesser thing it is: an inconsistency between a guard and its subject.
    """
    return "\n".join(re.sub(r"/\*.*?\*/", " ", t, flags=re.S) for t in texts.values())


def keyframe_name_collisions(all_css: str) -> list[str]:
    """A keyframe named after an `animation` keyword — the latent hole in `A-04`. Pure/testable."""
    return sorted({
        name for name in re.findall(r"@keyframes\s+([\w-]+)", all_css)
        if name in ANIMATION_KEYWORDS
    })


def classname_groups(texts: dict[str, str]) -> list[set[str]]:
    """Every set of class tokens that appear together in one `className`. Pure/testable.

    Template interpolations are dropped rather than guessed at: `sec-int--${integrity}` contributes
    nothing, which is the safe direction — this feeds a check that must not invent a rule match.
    """
    groups: list[set[str]] = []
    for text in texts.values():
        # `class=` TOO — seventh independent audit, `G-12`. `markdown.tsx:33` emits
        # `<span class="muted">` into `dangerouslySetInnerHTML`, and that is the form the entire
        # Markdown surface — the body of every agent reply in the product — is written in. The one
        # instance in the tree is styled, so nothing was broken; the harvest simply could not see
        # the shape.
        for match in re.finditer(r"\b(?:className|class)=", text):
            i = match.end()
            if i >= len(text):
                continue
            plain = False
            if text[i] in "\"'":                      # className="a b c"
                end = text.find(text[i], i + 1)
                region = text[i + 1:end] if end != -1 else ""
                plain = True
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
            # `[A-Za-z]`, not `[a-z]`. The sixth audit's `A-04` measured the lowercase-only filter
            # as a blind spot: a class token starting with a capital was dropped, so any clobber
            # applied through one was invisible. CSS class names are case-sensitive and nothing
            # forbids a capital.
            tokens: set[str] = set()
            # THE PLAIN FORM, WHICH THIS FUNCTION HAD NEVER READ. For `className="a b c"` the
            # region is `a b c` — no quotes and no backticks inside it — so both harvest loops
            # below found nothing and the group was dropped. Every plain string className in the
            # app has been invisible to the clobber check since it was written, which is a larger
            # hole than any of the three the sixth audit reported and was found only by
            # mutation-testing its A-04 case with a plain attribute.
            if plain:
                tokens |= {t for t in region.split() if re.fullmatch(r"[A-Za-z][\w-]*", t)}
            for literal in re.findall(r"['\"]([^'\"\n]*)['\"]", region):
                tokens |= {t for t in literal.split() if re.fullmatch(r"[A-Za-z][\w-]*", t)}
            for literal in re.findall(r"`([^`]*)`", region):
                stripped = re.sub(r"\$\{[^{}]*\}", " ", literal)
                tokens |= {t for t in stripped.split() if re.fullmatch(r"[A-Za-z][\w-]*", t)}
            if tokens:
                groups.append(tokens)
    return groups


def is_test_file(label: str) -> bool:
    """`*.test.*` / `*.spec.*`. Pure/testable.

    Only `animation_clobber` uses this, and only because a test that PROVES a clobber detector
    works has to contain a clobber. `harness.browser.spec.tsx` renders
    `.a01 { animation: spin … }` on a `.reveal` element on purpose, and once this gate learned to
    read plain string classNames it started reporting that fixture as a defect — correctly, and
    uselessly, since nothing in a spec file is shipped.

    Deliberately NOT applied to the reference check. `var(--x)` in a test still has to resolve:
    that check is about a declaration nothing declares, which is a mistake wherever it is written.
    """
    return ".test." in label or ".spec." in label


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

    KNOWN LIMITS, stated rather than implied — every one of these is a shape this check cannot see:

      * **A class list assembled from NON-LITERAL values.** This paragraph used to say a class
        applied through `cx(...)` "never appears in one, so it is invisible here." That is false
        and the seventh audit measured it (`G-12`): `cx('a','b','c')` IS caught, because the
        quoted-literal pass harvests string arguments anywhere in the attribute region. The real
        limit is narrower — a helper called with **variables** or a lookup table, where there is no
        literal to harvest. Wrong in the safe direction, but wrong, and a docstring that overstates
        a hole is the same defect as one that understates a reach (`A-03`). Closing the real limit
        means resolving arbitrary JS, and a resolver that guesses wrong reports correct code as
        broken. What covers it instead is a measurement —
        `apps/desktop/src/features/pages.browser.spec.tsx` renders the real components in real
        Chromium and reads `animation-name` off the real element.
      * **A clobber that only exists at a viewport or in a state this file never reaches.** Same
        answer: the browser suite measures what renders.
      * **Test files.** Excluded on purpose — see `is_test_file`.

    The honest division: this check runs per-commit and catches the author; the browser suite
    measures the result. Neither is a substitute for the other, and this docstring has been wrong
    about its own reach once already (`A-03`), so the reach is written down.
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

    entrances = entrance_classes(all_css)

    failures: list[str] = []
    for label, text in texts.items():
        live = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
        # A reduced-motion block is exempt: `aios.css` makes `.reveal`/`.rise` `opacity:1` outright
        # there, so killing the animation is what SHOULD happen and is not a clobber.
        live = re.sub(r"@media[^{]*prefers-reduced-motion[^{]*\{.*?\n\s*\}", " ", live, flags=re.S)
        for selector, body in re.findall(r"([^{}@;]+)\{([^{}]*)\}", live):
            # `animation-name` TOO — the sixth audit's `A-03`, and the sharpest kind of hole:
            # this check matched the shorthand only, and its own error message recommended "use
            # the animation-* longhands". `animation-name` is itself list-valued, so setting it
            # replaces the list identically. Measured in Chromium: shorthand → opacity 0, longhand
            # → opacity 0, and the gate caught one and passed the other. An author who tripped
            # this gate and followed its advice reintroduced the bug byte for byte.
            decl = re.search(r"(?<![-\w])animation(?:-name)?\s*:\s*([^;}]+)", body)
            if not decl:
                continue
            # Keywords are not keyframe names. Without this, a keyframe called `forwards` would
            # make every `animation: x 1s forwards` look self-sufficient (`A-04`, latent).
            names = {n for n in re.findall(r"[a-zA-Z][\w-]*", decl.group(1))
                     if n not in ANIMATION_KEYWORDS}
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
                # EVERY matching group, not the first — seventh independent audit, `G-04`.
                #
                # This loop used to `break` after the first group that was a superset of the
                # selector's subject classes. If that group lacked the entrance class, nothing was
                # reported and no later group was examined, so **detection depended on the source
                # order of two unrelated JSX elements.** The auditor measured it with the same CSS
                # twice, changing only which component was declared first: non-entrance first →
                # GREEN, entrance first → RED.
                #
                # That is the most natural way this bug arises — the same class pair rendered with
                # the entrance in a detail view and without it in a compact list — and it is
                # fifth-round `A-01`'s exact mechanism. `sorted(set(failures))` already dedupes,
                # and the sets involved are small, so the `break` bought nothing worth that.
                for group in groups:
                    if not classes <= group:
                        continue
                    for entrance_class, keyframe in entrances.items():
                        # NO `entrance_class not in classes` guard. It was there to stop the
                        # entrance rule reporting itself, and it also excused the shape the sixth
                        # audit measured: `.zzfade{opacity:0;animation:zzin}` clobbered by
                        # `.zzfade.zzhot{animation:sigbreathe}` — a MORE SPECIFIC rule on the same
                        # class, which is the most natural way to write the bug and was silently
                        # exempt. The entrance rule still does not report itself, for the honest
                        # reason rather than the accidental one: it declares its own keyframe, so
                        # `keyframe in names` skips it.
                        if entrance_class in group and keyframe not in names:
                            failures.append(
                                f"{label}: `{part.strip()}` replaces the animation list without "
                                f"`{keyframe}`, on an element that also carries `.{entrance_class}` "
                                f"— which is `opacity:0` until `{keyframe}` runs, so this element "
                                f"never becomes visible. Compose the list instead: "
                                f"`animation: {keyframe} var(--enter) forwards, <yours>`. "
                                f"NOT the `animation-name` longhand on its own — it is list-valued "
                                f"and replaces the list identically, which is the same bug (A-03).")
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
    # Every ORDERED scale, not only spacing. `--t-body: 99px` and `--r-pill: 0px` in a later
    # override were both measured GREEN by the sixth audit (`A-10`), and they break the same
    # promise `--s7` does: code picks a rung by meaning, and a tier that reorders the scale makes
    # "one step larger" false for whoever picked it that way.
    for scale in ("Spacing", "Type scale", "Radii"):
        failures += ladder_monotonic(blocks, POSITIONAL[scale], scale.lower())
    failures += override_scope(blocks, root_block_kinds(css), token_kinds(expected))
    failures += [
        f"@keyframes `{name}` is also an `animation` keyword. Every declaration containing that "
        f"word would read as self-sufficient and switch the clobber check off (A-04, latent). "
        f"Rename the keyframes." for name in keyframe_name_collisions(all_source_css(texts))]
    # Shipped source only — see is_test_file(). A spec that proves the clobber detector works has
    # to contain a clobber, and reporting it would train everyone to ignore this gate.
    shipped = {k: v for k, v in texts.items() if not is_test_file(k)}
    failures += animation_clobber(shipped, classname_groups(shipped))
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
