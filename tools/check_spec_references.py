#!/usr/bin/env python3
"""Every `§x.y` in the source must say, truthfully, whether it is implemented.

**Why this gate exists.** Three independent audits ran against this repository. The first two
measured the code against `apps/desktop/AUDIT/AUDIT_LEDGER.md` — a file the implementer writes —
and both returned RED on rows the implementer had marked closed. The third changed lens and
measured the code against the DESIGN SPEC instead, and immediately found eight numbered sections
cited in code as though they were satisfied while nothing implemented them: §7 deep verification,
the §4.3 signed lease, the §4.7 execution receipt, §1.5 step 4, §7.1 freshness, the §0.1 platform
gate, §2.3 store ACLs.

That is not eight bugs. It is one mechanism, and it is the mechanism by which the P0s in rounds
one and two passed review in the first place: a reviewer who sees `// §7.1(d)` beside a line
reasonably assumes §7.1(d) holds. In this repository that assumption was often wrong, and nothing
could tell the reviewer which times.

So a `§` reference is now a CLAIM the build checks:

  * every distinct reference in the source must be declared in `config/spec-conformance.json`;
  * one declared `implemented` must name a test, and that test must exist;
  * one declared `not_implemented` or `partial` must carry the words NOT IMPLEMENTED (or
    PARTIAL) at every site that cites it, so the comment cannot read as a statement of fact;
  * an UNDECLARED reference fails the build.

The last rule is the load-bearing one. Existing references start as `unreviewed`, which is
honest — nobody has checked them — and the gate refuses anything NEW that is not declared. The
debt is frozen where the audits found it and cannot grow silently while it is paid down.

stdlib only, no network. Run: `python tools/check_spec_references.py`
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DECLARATION = ROOT / "config" / "spec-conformance.json"
SCAN_DIRS = ("apps", "engine", "tools", "bridge")
SCAN_SUFFIXES = (".rs", ".py", ".ts", ".tsx", ".sh")
SKIP_PARTS = {"node_modules", "target", ".git", "__pycache__", "dist", "AUDIT"}
#: This file and the declaration explain the sections; they are not claims ABOUT them.
SKIP_FILES = {"tools/check_spec_references.py", "tools/test_check_spec_references.py"}

REFERENCE = re.compile(r"§[0-9]+(?:\.[0-9]+)*(?:\([a-z]\))?")

#: How close to the citation the honesty marker has to be. A marker paragraphs away from the
#: reference does not reach a reader skimming the line the reference is on, which is the whole
#: failure mode.
MARKER_WINDOW = 400

VALID_STATUSES = {"implemented", "partial", "not_implemented", "unreviewed"}

#: `not_implemented` means NOTHING about the section is true, so every citation of it must carry
#: the marker. `partial` is different and the difference matters: a partially-implemented section
#: has sites that legitimately describe the part that DOES exist, and forcing a warning onto those
#: would be a false claim in the other direction. What a partial section must not do is leave the
#: gap discoverable only from a JSON file, so at least one citation has to name it in the code.
STRICT_MARKERS = ("NOT IMPLEMENTED", "UNIMPLEMENTED")
PARTIAL_MARKERS = ("NOT IMPLEMENTED", "UNIMPLEMENTED", "PARTIAL", "MISSING")


def source_files() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for top in SCAN_DIRS:
        base = ROOT / top
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix not in SCAN_SUFFIXES:
                continue
            if SKIP_PARTS & set(path.parts):
                continue
            if path.relative_to(ROOT).as_posix() in SKIP_FILES:
                continue
            out.append(path)
    return sorted(out)


def citations(files: list[pathlib.Path]) -> dict[str, list[tuple[pathlib.Path, int, str]]]:
    """section -> [(file, line number, the surrounding text)]."""
    found: dict[str, list[tuple[pathlib.Path, int, str]]] = {}
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "§" not in text:
            continue
        lines = text.splitlines()
        offsets, running = [], 0
        for line in lines:
            offsets.append(running)
            running += len(line) + 1
        for match in REFERENCE.finditer(text):
            start = match.start()
            number = next((i for i, o in enumerate(offsets) if o > start), len(lines)) - 1
            window = text[max(0, start - MARKER_WINDOW): start + MARKER_WINDOW]
            found.setdefault(match.group(0), []).append((path, number + 1, window))
    return found


def load_declaration() -> dict:
    try:
        return json.loads(DECLARATION.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"RED: {DECLARATION.relative_to(ROOT)} is missing", file=sys.stderr)
        raise SystemExit(1)
    except ValueError as exc:
        print(f"RED: {DECLARATION.relative_to(ROOT)} is malformed: {exc}", file=sys.stderr)
        raise SystemExit(1)


def check() -> list[str]:
    declared = load_declaration().get("sections", {})
    problems: list[str] = []

    for section, status in sorted(declared.items()):
        if not isinstance(status, dict) or status.get("status") not in VALID_STATUSES:
            problems.append(f"{section}: status must be one of {sorted(VALID_STATUSES)}")

    cited = citations(source_files())

    for section in sorted(cited):
        entry = declared.get(section)
        if entry is None:
            sites = ", ".join(
                f"{p.relative_to(ROOT).as_posix()}:{n}" for p, n, _ in cited[section][:3]
            )
            problems.append(
                f"{section} is cited in the source but not declared in "
                f"{DECLARATION.relative_to(ROOT).as_posix()} ({sites}). A § reference is a claim; "
                "declare whether it is implemented, partial, not implemented, or unreviewed."
            )
            continue

        state = entry.get("status")

        if state == "implemented":
            if not entry.get("tests"):
                problems.append(
                    f"{section} is declared implemented but names no test. An implementation "
                    "nothing exercises is the shape every closed-then-reopened finding had."
                )

        # A named test is checked whatever the status naming it. This used to run only under
        # `implemented`, and the hole was live: a `partial` entry was accepted here naming two
        # tests that had not been written yet. A declaration pointing at a test that does not
        # exist is worse than one pointing at nothing, because it reads as evidence.
        for test in entry.get("tests") or []:
            if not any(test in f.read_text(encoding="utf-8", errors="ignore")
                       for f in source_files()):
                problems.append(
                    f"{section} names test {test!r}, which does not exist in the source"
                )

        if state == "not_implemented":
            for path, line, window in cited[section]:
                if not any(m in window.upper() for m in STRICT_MARKERS):
                    problems.append(
                        f"{section} is declared not_implemented but "
                        f"{path.relative_to(ROOT).as_posix()}:{line} cites it with no "
                        "'NOT IMPLEMENTED' nearby — a reader sees the reference and assumes the "
                        "section holds."
                    )

        if state == "partial":
            if not entry.get("missing"):
                problems.append(
                    f"{section} is declared partial but does not say WHICH part is missing. "
                    "'Partial' without that is the same unfalsifiable claim as a bare reference."
                )
            marked = any(
                any(m in window.upper() for m in PARTIAL_MARKERS)
                for _, _, window in cited[section]
            )
            if not marked:
                problems.append(
                    f"{section} is declared partial and no citation of it names the gap. The "
                    "missing part must be discoverable from the code, not only from this JSON."
                )

    return problems


def main() -> int:
    problems = check()
    if problems:
        print("RED: spec references do not match their declared status —")
        for problem in problems:
            print(f"  - {problem}")
        print(f"\n{len(problems)} problem(s).")
        return 1
    declared = load_declaration().get("sections", {})
    counts: dict[str, int] = {}
    for entry in declared.values():
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
    print(f"GREEN: every § reference in the source is declared ({summary}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
