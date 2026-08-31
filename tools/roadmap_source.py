"""The roadmap is one document stored in twelve files.

`MASTER_EXECUTION_ROADMAP.md` carries §A–§I (the conventions every phase inherits), the
status board, and the appendices. Each phase body lives in `docs/roadmap/phase-N.md`.
`roadmap_text()` assembles them back into exactly the document the gates used to read, so
`check_coordination.py` and `check_roadmap_order.py` see no difference.

**Why split it at all.** `check_roadmap_order.py` already forbids a session from working
any phase but the first one that is not done. So every session was carrying eleven phases
into its context to be allowed to touch one — 134 KB, about a third of everything injected
at session start. The conventions are shared and belong in one place; a phase body is read
by the one session working that phase.

**Why assemble rather than teach each gate about the split.** Two gates parse
`^## Phase (\\d+) —` out of a single string, and `check_coordination` additionally uses
`^# Appendix` as the hard end of the phase region. Reproducing that ordering in two
places is how the two would drift apart. One assembler, one ordering, both gates call it.

The `<!-- PHASES -->` marker is where the phase files are spliced in. It sits between the
`# Phases` heading and `# Appendix`, so the assembled text has the same section order as
the original — which is what makes the appendix end-marker keep working.

`tools/test_roadmap_split.py` proves the assembly is byte-identical to the document before
the split, phase by phase and section by section. A split that loses a Definition-of-Done
box would be invisible for weeks otherwise.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROADMAP_REL = "MASTER_EXECUTION_ROADMAP.md"
PHASE_DIR_REL = "docs/roadmap"
MARKER = "<!-- PHASES -->"


def phase_files(root: pathlib.Path = ROOT) -> list[pathlib.Path]:
    """Phase bodies in numeric order. Sorted numerically, not lexically: phase-10 after
    phase-9, which a string sort gets wrong and which would silently reorder the document."""
    d = root / PHASE_DIR_REL
    if not d.is_dir():
        return []
    found: list[tuple[int, pathlib.Path]] = []
    for p in d.glob("phase-*.md"):
        m = re.fullmatch(r"phase-(\d+)", p.stem)
        if m:
            found.append((int(m.group(1)), p))
    return [p for _, p in sorted(found)]


def roadmap_text(root: pathlib.Path = ROOT) -> str:
    """The whole roadmap as one string, exactly as it read before the split."""
    main = (root / ROADMAP_REL).read_text(encoding="utf-8")
    if MARKER not in main:
        return main  # not split (or a checkout from before it) — read as-is
    # Each body is stored without its trailing blank line and rejoined with one, which is
    # what the single file had between phases. Proven byte-identical by
    # tools/test_roadmap_split.py against the pre-split document.
    bodies = "\n\n".join(p.read_text(encoding="utf-8").rstrip("\n") for p in phase_files(root))
    return main.replace(MARKER, bodies)
