#!/usr/bin/env python3
"""No raw C0 control byte in a tracked text file. Because two of them cost real controls.

This is not a style rule. Both harms below were MEASURED in this repository, on 2026-09-20:

  1. 0x08 KILLED TEN ASSERTIONS. `Knowledge.honesty.test.tsx` and `Memory.honesty.test.tsx` each loop a
     nine-entry `FORBIDDEN` list through `expect(text).not.toMatch(forbidden)`, guarding the product's
     central UI honesty rule: a local, unsigned write record must never borrow the receipt vocabulary.
     Five entries per file read `/<0x08>verified<0x08>/i` where `/\\bverified\\b/i` was written — a shell
     ate the backslash and left the character its name refers to. A regex for a literal backspace matches
     no rendered text, so five `not.toMatch` assertions per file were satisfied by every possible input.
     Proved by injecting the word `custody` into the rendered fixture: before the repair both blocks
     PASSED, after it both FAILED naming the word. The words `verified`, `trusted`, `receipt` and
     `custody` were forbidden NOWHERE in those tests. And the same file spells `/\\bsigned\\b/i`
     correctly 74 lines earlier, which is the file's own proof that the other spelling is damage.

  2. 0x00 BLINDED THE SEARCH. `writeRecord.tsx` carried a NUL at offset 7,871 — inside the 8,000-byte
     window ripgrep reads before calling a file binary. `rg -n UNRECOGNISED_REPLY src/features/` returned
     four hits in the TEST file and zero in the file where the symbol is DEFINED. Every grep-based
     review of that source was silently incomplete. `Activity.tsx` carried one at offset 8,439, just
     outside the window, so tools still read it — a few bytes added above would have slid it in.

Neither byte renders in a diff, a terminal or a review. There is no position from which a person catches
this, which is why it is a gate and not a fix.

WHAT IS ALLOWED. Tab, LF and CR, because a rule that called them control characters would go red on
every indented file and be switched off within a day. And exactly the sites in `DECLARED`, each with a
written reason — a deliberate fixture is a real thing, and the way to have one is to say so in a diff.

Usage:  python tools/check_source_control_bytes.py [repo-root]
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else pathlib.Path(
    __file__).resolve().parents[1]

#: Text this reads. A binary is not where a control byte gets pasted by accident.
SWEPT_EXT = {
    ".rs", ".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".json", ".md", ".yml", ".yaml",
    ".toml", ".sql", ".sh", ".ps1", ".txt", ".css", ".html", ".cfg", ".ini",
}

#: Tab, LF, CR are text. Everything else below 0x20 is not, and neither is DEL.
ALLOWED = {0x09, 0x0A, 0x0D}

#: (path, byte) -> why this one is deliberate. An entry here must name a FIXTURE — something whose
#: point is to carry the byte — never a file that merely happens to have one.
DECLARED: dict[tuple[str, int], str] = {
    ("engine/tests/test_one_standard_pins.py", 0x01):
        "A fixture that exists to exercise control characters: the row "
        "`{\"terminators\": ..., \"quote\": '\"', \"back\": \"\\\\\", \"ctl\": <0x01>}` pins how one "
        "standard handles a terminator, a quote, a backslash and a control byte. Escaping this one "
        "would remove the only case in the tree that measures the last of those.",
}

MIN_REASON = 80


def tracked(root: pathlib.Path) -> list[str] | str:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
    except (subprocess.SubprocessError, OSError) as exc:
        return f"git ls-files failed ({exc}); a sweep that cannot list the tree proves nothing"
    names = [n for n in out.stdout.decode("utf-8", "replace").split("\0") if n]
    return names or "git ls-files returned nothing; a sweep over no files proves nothing"


def render(line: bytes) -> str:
    """The line with every control byte made visible, so the report can be read."""
    out = []
    for ch in line:
        out.append(f"<0x{ch:02x}>" if ch < 0x20 and ch not in ALLOWED else chr(ch) if ch < 0x80 else ".")
    return "".join(out)


def main() -> int:
    problems: list[str] = []

    for (rel, byte), reason in sorted(DECLARED.items()):
        if not (ROOT / rel).is_file():
            problems.append(
                f"DECLARED names {rel} (0x{byte:02x}), which is not a file. A declaration pointing at "
                f"deleted code reads as a checked exception and is none")
        elif len(reason.strip()) < MIN_REASON:
            problems.append(
                f"DECLARED {rel} (0x{byte:02x}): the reason is {len(reason.strip())} characters; a "
                f"placeholder is not a reason")

    names = tracked(ROOT)
    if isinstance(names, str):
        print("RED: control-byte sweep could not run\n")
        print(f"  - {names}")
        return 1

    swept = declared_seen = found = 0
    for rel in names:
        path = ROOT / rel
        if path.suffix.lower() not in SWEPT_EXT or not path.is_file():
            continue
        try:
            raw = path.read_bytes()
        except OSError as exc:
            problems.append(f"{rel}: unreadable ({exc}) — a file this gate cannot read is not a file it checked")
            continue
        swept += 1
        line_no = 1
        line_start = 0
        for i, ch in enumerate(raw):
            if ch == 0x0A:
                line_no += 1
                line_start = i + 1
                continue
            if ch in ALLOWED or (0x20 <= ch != 0x7F):
                continue
            if (rel, ch) in DECLARED:
                declared_seen += 1
                continue
            found += 1
            end = raw.find(b"\n", i)
            text = raw[line_start:end if end > 0 else len(raw)]
            problems.append(
                f"{rel}:{line_no} carries a raw 0x{ch:02x} at byte {i}. Neither a diff, a terminal nor "
                f"a review renders it. Write it as an escape with the same meaning "
                f"(`\\b`, `\\u0000`) or declare the site.\n      {render(text)[:150]}")

    undeclared_declarations = [
        f"DECLARED {rel} (0x{byte:02x}) matched nothing — the byte it excuses is gone, so the "
        f"exception outlives the thing it was for"
        for (rel, byte) in sorted(DECLARED)
        if (ROOT / rel).is_file() and bytes([byte]) not in (ROOT / rel).read_bytes()
    ]
    problems.extend(undeclared_declarations)

    if problems:
        print("RED: raw control bytes in tracked text\n")
        for p in problems:
            print(f"  - {p}")
        print(f"\n{len(problems)} problem(s) over {swept:,} text files.")
        return 1

    print(f"GREEN: {swept:,} tracked text files carry no raw control byte beyond tab/LF/CR — "
          f"{found} undeclared found, {declared_seen} occurrence(s) of {len(DECLARED)} declared "
          f"fixture(s). Measured, so zero is a measurement and not a silence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
