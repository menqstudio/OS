#!/usr/bin/env python3
"""The front page's artwork is checked by a person, and that is the defect.

THE DEFECT, 2026-09-19. `docs/brand/readme/verification-*.svg` draws the negative matrix as a bar
to scale, so its segment edges move every time a row is bound. Two things beside the bar were
positioned FROM those edges, and both broke when `unreviewed` fell to 38:

  * the plate behind the `unreviewed · չստուգված` label was a fixed 200 px centred on the band. At a
    176 px band that is 972..1172 against a band of 984..1160 -- 12 px past the rounded end and 12 px
    into the amber band beside it.
  * the four-line `unreviewed` paragraph was left-aligned at the band's LEFT edge, so its column
    narrowed every time the number it explains improved. Two lines reached x=1204.2 and x=1227.8,
    past the 1200 canvas, and were clipped.

Both were found by a script in a scratchpad directory, which is to say: not found by this
repository. `docs/README_CLAIM_HISTORY.md` section 8 lists nine properties every sheet that landed in
`#247` was checked against -- parse, viewBox, palette, pair parity, colour mapping, id references, two
right edges, byte hygiene -- and every one of those nine was a person running a private tool once. The
older pair predates that pull request, so the text-edge check had never been pointed at it at all, and
one of its lines had been overhanging the content edge since the sheet was drawn.

A picture the front page shows is a claim like any other. This is the gate that reads it.

WHAT IS CHECKED, and why each rule is the rule it is:

  1. every sheet parses as XML -- a sheet GitHub cannot render says nothing at all
  2. `viewBox="0 0 1200 H"` with `width`/`height` that agree, because a mismatch scales every
     coordinate silently and the checks below would then be measuring the wrong canvas
  3. every sheet has its light/dark twin: the README serves them through
     `<source media="(prefers-color-scheme: dark)">`, so a missing twin is a broken theme
  4. the twins are byte-identical apart from colour literals and the one `<desc>` line. This is the
     property that makes a dark sheet a TRANSLATION of a light one rather than a second drawing --
     and it caught a designer claiming to have verified a dark sheet that did not exist
  5. every light->dark colour pair is DECLARED -- one token's two values in `tokens.css`, or one of
     two named exceptions this file states with its reason. The first version of this rule demanded a
     bijection and was wrong: `architecture-*.svg` legitimately uses white for both the ground and an
     elevated card, and the dark theme separates them, which is the token table working. Declared
     pairing catches what the bijection was reaching for and nothing it was wrong about
  6. every colour literal is on the token table, so artwork cannot introduce a brand colour
  7. every `url(#…)` fragment resolves to an `id` defined in the same file
  8. no text run passes x=1160, the content right edge inside a 1200 px canvas
  9. no two text runs sharing a baseline OVERLAP
 10. LF endings, no BOM, no C0 control characters -- `TASKS.md` carried a real 0x08 for weeks
 11. no sheet is an orphan: every file here is referenced by `README.md`

Widths are estimated with a deliberately pessimistic per-character advance table (Armenian counted
wider than Latin, since these sheets are bilingual everywhere and a Latin-only figure would
under-count exactly the lines most at risk). Over-estimating makes a pass a real pass.

THE FLOOR IN RULE 9 IS ZERO, MEASURED. Across the 14 sheets the tightest gap between two runs on one
baseline is 3.9 px -- `MASTER_EXECUTION_ROADMAP.md` beside Armenian prose in the roadmap pair, where
the mono advance is over-estimated most. So any floor above zero would be red on arrival on artwork
nobody has complained about. Overlap is a defect; breathing room is a judgement, and a gate that
argues about judgement gets ignored.

Exit 0 GREEN, 1 RED.
"""
from __future__ import annotations

import pathlib
import re
import sys
import xml.dom.minidom

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The sheets the README shows.
SHEET_DIR = "docs/brand/readme"

#: The canvas, and the content edge inside it. 1200 x H with a 40 px margin each side.
CANVAS_W = 1200
CONTENT_RIGHT = 1160

#: Per-character advances as a fraction of font-size, deliberately high.
#:
#: Armenian is wider than Latin at the same size in Inter and in Noto Sans Armenian, and these sheets
#: are bilingual in every block, so one Latin figure would under-count the lines most at risk.
ADV_LATIN, ADV_ARMENIAN, ADV_MONO, ADV_SPACE = 0.52, 0.58, 0.60, 0.26
BOLD_FACTOR = 1.045

#: Light/dark pairs the sheets use that `tokens.css` does not declare, each with its reason.
#:
#: MEASURED across the 14 sheets: 13 distinct light->dark pairs, 10 of them exactly a token's light
#: and dark value. These are the other two, and they are here because they are the sheets' own
#: decisions rather than because the rule was inconvenient:
#:
#:   #ffffff -> #0b0d10   x51, every pair of sheets. The MenQ grounds, decision `D-025`: eight
#:                        foundation tokens, NO accent hue, grounds white and near-black. The white
#:                        is in `tokens.css`; the near-black is not, because this repository's own
#:                        dark ground is `#0c0e13`. Each dark sheet's `<desc>` line states it.
#:   #f5f6f8 -> #14171f   x61, every pair of sheets. The sheets' panel: in light the app's `bg`
#:                        token reads as a panel over a white ground, and in dark a panel must be
#:                        LIGHTER than the MenQ ground, which the app's dark `bg` is not.
#:
#: The thirteenth pair was `#f5f6f8 -> #1b1f2a`, ONCE, in one panel of `authority-dark.svg` where
#: every other panel in all seven pairs uses `#14171f`. Counting found it; six months of looking at
#: the sheet had not. It is a fix, not an entry here.
ARTWORK_PAIRS = {
    ("#ffffff", "#0b0d10"): "the MenQ grounds, decision D-025",
    ("#f5f6f8", "#14171f"): "the sheets' panel over each theme's ground",
}

TOKEN_FILE = "apps/desktop/src/theme/tokens.css"

TEXT_RE = re.compile(r"<text ([^>]*?)>(.*?)</text>", re.S)
ATTR_RE = re.compile(r'([\w:-]+)="([^"]*)"')
COLOUR_RE = re.compile(r"#[0-9a-fA-F]{6}")
DESC_RE = re.compile(r"<desc[^>]*>.*?</desc>", re.S)
ID_RE = re.compile(r'\sid="([^"]+)"')
URL_RE = re.compile(r"url\(#([^)]+)\)")


def advance(ch: str, size: float, mono: bool) -> float:
    o = ord(ch)
    if mono:
        return size * ADV_MONO
    if 0x530 <= o <= 0x58F or 0xFB13 <= o <= 0xFB17:
        return size * ADV_ARMENIAN
    return size * ADV_SPACE if ch == " " else size * ADV_LATIN


def run_box(attrs: dict, body: str) -> tuple[float, float, float] | None:
    """(baseline, left, right) for one text run, or None when it is not positioned."""
    if "x" not in attrs or "y" not in attrs:
        return None
    body = re.sub(r"<[^>]+>", "", body).strip()
    if not body:
        return None
    size = float(attrs.get("font-size", 16))
    mono = "mono" in attrs.get("font-family", "")
    width = sum(advance(c, size, mono) for c in body)
    if attrs.get("font-weight") in {"700", "bold"}:
        width *= BOLD_FACTOR
    x, anchor = float(attrs["x"]), attrs.get("text-anchor", "start")
    left = x - width if anchor == "end" else x - width / 2 if anchor == "middle" else x
    return float(attrs["y"]), left, left + width


def runs(text: str):
    for raw, body in TEXT_RE.findall(text):
        box = run_box(dict(ATTR_RE.findall(raw)), body)
        if box:
            yield box, re.sub(r"<[^>]+>", "", body).strip()


def declared_pairs(root: pathlib.Path) -> dict[tuple[str, str], str]:
    """Every (light value, dark value) the theme declares for one token, plus the sheets' own two.

    `tokens.css` states the light palette on bare `:root` and overrides it under
    `:root[data-theme="dark"]`, so the pairing is the token NAME -- which is the only thing that knows
    two literals are the same idea in two themes.
    """
    css = (root / TOKEN_FILE).read_text(encoding="utf-8").lower()
    light: dict[str, str] = {}
    dark: dict[str, str] = {}
    for block in re.split(r"\n(?=:root)", css):
        head = block.split("{", 1)[0]
        target = dark if 'data-theme="dark"' in head else light
        for name, value in re.findall(r"(--[\w-]+):\s*(#[0-9a-f]{6})", block):
            target.setdefault(name, value)
    out = {(lv, dark[name]): name for name, lv in light.items() if name in dark}
    out.update(ARTWORK_PAIRS)
    return out


def known_colours(root: pathlib.Path) -> set[str]:
    css = (root / TOKEN_FILE).read_text(encoding="utf-8").lower()
    allowed = set(COLOUR_RE.findall(css))
    for a, b in ARTWORK_PAIRS:
        allowed |= {a, b}
    return allowed


def masked(text: str) -> str:
    """The sheet with every colour literal and the one theme line removed."""
    return DESC_RE.sub("<desc/>", COLOUR_RE.sub("#XXXXXX", text.lower()))


def check(root: pathlib.Path) -> tuple[list[str], dict]:
    problems: list[str] = []
    counted = {"sheets": 0, "pairs": 0, "runs": 0, "colours": 0}
    directory = root / SHEET_DIR
    if not directory.is_dir():
        return [f"{SHEET_DIR}/ is not a directory; the README's figures come from there"], counted

    palette = known_colours(root)
    pairs = declared_pairs(root)
    sheets = sorted(directory.glob("*.svg"))
    readme = (root / "README.md").read_text(encoding="utf-8") if (root / "README.md").exists() else ""
    texts: dict[str, str] = {}

    for path in sheets:
        rel = f"{SHEET_DIR}/{path.name}"
        counted["sheets"] += 1
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        texts[path.name] = text

        # 10. bytes
        if raw.startswith(b"\xef\xbb\xbf"):
            problems.append(f"{rel}: starts with a UTF-8 BOM")
        if b"\r\n" in raw:
            problems.append(f"{rel}: holds CRLF line endings. These files are LF, and "
                            f".gitattributes pins `*.svg text eol=lf` so that is true "
                            f"wherever the tree is checked out -- a Windows runner whose "
                            f"core.autocrlf is `true` converts them otherwise, and this "
                            f"gate would then report git configuration as artwork")
        stray = {b for b in raw if b < 0x20 and b not in (0x09, 0x0A)}
        if stray:
            names = ", ".join(f"0x{b:02x}" for b in sorted(stray))
            problems.append(f"{rel}: holds control byte(s) {names}, which render as nothing in a "
                            f"diff, a terminal and a review")

        # 1. parses
        try:
            xml.dom.minidom.parseString(text)
        except Exception as exc:                                    # noqa: BLE001 - reported, not raised
            problems.append(f"{rel}: does not parse as XML ({exc}); GitHub would show nothing")
            continue

        # 2. canvas
        box = re.search(r'viewBox="0 0 (\d+) (\d+)"', text)
        w = re.search(r'\swidth="(\d+)"', text)
        h = re.search(r'\sheight="(\d+)"', text)
        if not box:
            problems.append(f'{rel}: no viewBox="0 0 W H" on the root element')
        elif int(box.group(1)) != CANVAS_W:
            problems.append(f"{rel}: viewBox is {box.group(1)} px wide, not {CANVAS_W}")
        elif not (w and h) or (int(w.group(1)), int(h.group(1))) != (
                int(box.group(1)), int(box.group(2))):
            problems.append(f"{rel}: width/height do not agree with the viewBox "
                            f"({w.group(1) if w else '-'}x{h.group(1) if h else '-'} against "
                            f"{box.group(1)}x{box.group(2)}); every coordinate below would be "
                            f"measured against the wrong canvas")

        # 6. palette
        for literal in sorted(set(COLOUR_RE.findall(text))):
            counted["colours"] += 1
            if literal.lower() not in palette:
                problems.append(f"{rel}: colour {literal} is on no token table. Artwork may not "
                                f"introduce a colour; add it to {TOKEN_FILE} or use a token")

        # 7. fragment references
        defined = set(ID_RE.findall(text))
        for frag in sorted(set(URL_RE.findall(text))):
            if frag not in defined:
                problems.append(f"{rel}: references url(#{frag}), which no id in this file defines")

        # 8 + 9. text runs
        by_baseline: dict[float, list[tuple[float, float, str]]] = {}
        for (y, left, right), body in runs(text):
            counted["runs"] += 1
            if right > CONTENT_RIGHT:
                problems.append(f"{rel}: the run {body[:40]!r} ends at x={right:.1f}, past the "
                                f"content edge {CONTENT_RIGHT}"
                                + (f" AND past the {CANVAS_W} canvas" if right > CANVAS_W else ""))
            by_baseline.setdefault(y, []).append((left, right, body))
        for y, boxes in sorted(by_baseline.items()):
            boxes.sort()
            for (l1, r1, b1), (l2, r2, b2) in zip(boxes, boxes[1:]):
                if l2 < r1:
                    problems.append(f"{rel}: on baseline y={y:g} the runs {b1[:28]!r} and "
                                    f"{b2[:28]!r} overlap by {r1 - l2:.1f} px")

        # 11. orphans
        if readme and path.name not in readme:
            problems.append(f"{rel}: no README.md reference. A sheet nobody shows is either an "
                            f"orphan or a figure that was meant to be wired in")

    # 3 + 4 + 5. the pairs
    for name in sorted(texts):
        if not name.endswith("-light.svg"):
            continue
        twin = name.replace("-light.svg", "-dark.svg")
        if twin not in texts:
            problems.append(f"{SHEET_DIR}/{name}: has no {twin}. The README serves the dark sheet "
                            f"through prefers-color-scheme, so one theme would show nothing")
            continue
        counted["pairs"] += 1
        light, dark = texts[name], texts[twin]
        if masked(light) != masked(dark):
            problems.append(f"{SHEET_DIR}/{name} and {twin} differ in more than colour literals and "
                            f"the <desc> line, so the dark sheet is a second drawing rather than a "
                            f"translation of the light one")
            continue
        # The <desc> line is ALLOWED to differ, and both sheets name their ground in it, so a
        # literal inside it must not feed the pairing: a desc reworded in one theme would
        # otherwise shift every pair after it and report drift that is not there.
        used = set(zip(COLOUR_RE.findall(DESC_RE.sub("", light.lower())),
                       COLOUR_RE.findall(DESC_RE.sub("", dark.lower()))))
        for a, b in sorted(used - set(pairs)):
            problems.append(f"{SHEET_DIR}/{name}: {a} -> {b} is not a declared light/dark pair. "
                            f"Every other pair in these sheets is one token's two values; a pair "
                            f"that is not says the two themes mean different things by one element")
    return problems, counted


def main(root: pathlib.Path | None = None) -> int:
    root = pathlib.Path(root) if root else ROOT
    problems, counted = check(root)
    if problems:
        print("RED: the README's artwork makes a geometric or palette claim that is not true\n")
        for p in problems:
            print(f"  - {p}")
        print("\nA picture on the front page is a claim like any other. These are all measurable, "
              "so none of them has to be found by looking.")
        return 1
    print(f"GREEN: artwork geometry checks out; {counted['sheets']} sheets in {counted['pairs']} "
          f"light/dark pairs; {counted['runs']} text runs inside x={CONTENT_RIGHT} and none "
          f"overlapping; {counted['colours']} colour uses all on the token table")
    return 0


if __name__ == "__main__":
    sys.exit(main(pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None))
