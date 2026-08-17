#!/usr/bin/env python3
"""The audit trail has to be openable — sixth independent audit, `A-06`.

The finding: **the fifth round's report was never written to the repository.** `AUDIT_LEDGER.md`
went on naming the FOURTH audit as "Authoritative current assessment" while
`docs/OWNER_ACTION_REQUIRED.md` opened with the FIFTH's verdict, its 11 findings and its 15
promotions to ✅ — and every `(A-01, fifth audit)` citation the round had embedded in source
comments pointed at a document nobody could open.

That is not a documentation slip. The ledger's own legend defines ✅ as *"independently confirmed"*,
and a confirmation whose evidence cannot be read is a claim. Two RED verdicts in this project's
history came from rows marked ✅ by the session that wrote the fix; the ledger exists so that cannot
happen quietly, and for one whole round it could not do its job.

**Why this is a gate and not a habit.** The auditor named the mechanism exactly: the brief that
produces a report says *"as text in your reply — do not create the file"*, because an auditor that
writes to the tree is no longer provably read-only. That constraint is right and is not being
relaxed. It just means **filing the report is the Builder's step**, and an unwritten Builder step is
one nobody notices — which is what happened. So the obligation moves into CI, where a missing report
is red rather than invisible.

WHAT IT CHECKS

  1. Every relative link **into** `apps/desktop/AUDIT/` from the ledger or the OWNER page resolves
     to a file that exists. A citation nobody can open is the whole finding.
  2. The ledger's "Authoritative current assessment" points at the **newest** report in that
     directory. Filing a report and forgetting to repoint the ledger is half of `A-06`; repointing
     the ledger at a file that was never filed is the other half, and (1) catches that one.
  3. The OWNER page's banner and the ledger agree on **which round is current**. The exact symptom
     of `A-06` was these two disagreeing — the OWNER page on the fifth, the ledger on the fourth —
     for long enough that a reader following one to the other got a contradiction.

WHAT IT DOES NOT CHECK. Not whether the report says anything true, not whether its findings were
addressed, and not whether a round happened at all — nothing in a repository can know that a
conversation took place. It checks that what the repository CLAIMS about its own audit trail is
openable and self-consistent, which is exactly the property `A-06` found missing.

Run:  python tools/check_audit_reports.py
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

AUDIT_DIR = "apps/desktop/AUDIT"
LEDGER = f"{AUDIT_DIR}/AUDIT_LEDGER.md"
OWNER = "docs/OWNER_ACTION_REQUIRED.md"
STATE = "config/current_state.json"

#: A report shorter than this is a placeholder. A-06's gate implemented "openable" as
#: .exists(), and the seventh audit passed it with a zero-byte file cited by all three
#: documents. Deliberately generous: the shortest real report in this directory is far above it.
MIN_REPORT_BYTES = 2048

#: The ordinals a round is written with, in order. Matching on words rather than digits because
#: that is how both documents are written ("the FOURTH independent audit", "FIFTH AUDIT").
ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth",
            "ninth", "tenth"]


def relative_links(text: str) -> list[str]:
    """Markdown link targets that are relative paths — pure/testable.

    Anchors (`#…`) and absolute URLs are not files and are not this gate's business.
    """
    out = []
    for m in re.finditer(r"\]\(([^)\s]+)\)", text):
        target = m.group(1).split("#", 1)[0]
        if not target or "://" in target or target.startswith("#"):
            continue
        out.append(target)
    return out


def audit_links(text: str, from_dir: pathlib.PurePosixPath) -> list[str]:
    """Link targets that resolve INTO the audit directory, as repo-relative paths."""
    out = []
    for target in relative_links(text):
        resolved = (from_dir / target) if not target.startswith("/") else pathlib.PurePosixPath(target.lstrip("/"))
        normalised = pathlib.PurePosixPath(*_normalise(resolved.parts))
        if str(normalised).startswith(AUDIT_DIR):
            out.append(str(normalised))
    return out


def _normalise(parts: tuple[str, ...]) -> list[str]:
    """Resolve `.`/`..` without touching the filesystem, so this stays pure."""
    stack: list[str] = []
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            if stack:
                stack.pop()
            continue
        stack.append(part)
    return stack


def newest_report(names: list[str]) -> str | None:
    """The newest report filename by its `YYYY-MM-DD` prefix — pure/testable.

    Ties break on the rest of the name, which is stable but arbitrary; two reports filed on one day
    is not a case this project has had, and if it arrives the tie deserves a human decision rather
    than a sort order.
    """
    dated = [n for n in names if re.match(r"^\d{4}-\d{2}-\d{2}-", n) and n.endswith(".md")]
    return max(dated) if dated else None


def authoritative_link(ledger_text: str) -> str | None:
    """The file the ledger calls current — pure/testable."""
    m = re.search(r"\*\*Authoritative current assessment:\*\*\s*\[[^\]]*\]\(([^)\s]+)\)", ledger_text)
    return m.group(1).split("#", 1)[0].lstrip("./") if m else None


def ordinal_of(text: str) -> str | None:
    """The round ordinal a document announces — pure/testable.

    Reads the FIRST occurrence, because both documents lead with the current round and go on to
    describe older ones. A gate that read the last one would pass whenever the history was longest.
    """
    m = re.search(r"\*\*(%s)\*\*\s+(?:independent\s+)?audit|\*\*(%s)\s+AUDIT"
                  % ("|".join(ORDINALS), "|".join(o.upper() for o in ORDINALS)),
                  text, re.I)
    if not m:
        return None
    return (m.group(1) or m.group(2)).lower()


def state_audit_pointer(text: str) -> str | None:
    """The report `config/current_state.json` calls the last independent audit — pure/testable.

    Added on the same day the gate was written, because the machine-readable file turned out to be
    carrying the prose file's defect and carrying it worse. Its `AUDIT POSITION:` sentence named the
    `2026-08-06` remediation audit and asserted *"no independent audit has been run on any later
    head"* — after the third, fourth, fifth and sixth had run. **Five rounds stale**, in the file
    `check_coordination.py` treats as the anchor the human documents must agree with.

    That is `A-06` one layer down: the OWNER page and the ledger disagreed with each other, and this
    file disagreed with both while being the one a tool would read.
    """
    m = re.search(r"the last INDEPENDENT audit\s*--\s*(%s/[^\s,]+\.md)" % re.escape(AUDIT_DIR), text)
    return m.group(1) if m else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root)

    failures: list[str] = []
    ledger_path = root / LEDGER
    owner_path = root / OWNER
    audit_dir = root / AUDIT_DIR

    if not ledger_path.exists():
        print(f"RED: {LEDGER} does not exist — the index of record is the record.", file=sys.stderr)
        return 1

    ledger_text = ledger_path.read_text(encoding="utf-8")
    owner_text = owner_path.read_text(encoding="utf-8") if owner_path.exists() else ""

    # 1. every cited report opens
    checked = 0
    for label, text, from_dir in (
        (LEDGER, ledger_text, pathlib.PurePosixPath(AUDIT_DIR)),
        (OWNER, owner_text, pathlib.PurePosixPath("docs")),
    ):
        for target in audit_links(text, from_dir):
            checked += 1
            if not (root / target).exists():
                failures.append(
                    f"{label} links to `{target}`, which does not exist. A-06 is exactly this: a "
                    f"citation nobody can open, in the file whose legend defines ✅ as "
                    f"'independently confirmed'.")

    # 2. the ledger points at the newest report on disk
    reports = sorted(p.name for p in audit_dir.glob("*.md") if p.name != "AUDIT_LEDGER.md")
    newest = newest_report(reports)
    current = authoritative_link(ledger_text)
    if current is None:
        failures.append(f"{LEDGER} has no '**Authoritative current assessment:**' link. Without it "
                        f"nothing says which round is in force.")
    elif newest and current != newest:
        failures.append(
            f"{LEDGER} calls `{current}` authoritative, but the newest report filed is `{newest}`. "
            f"Either the ledger was not repointed after a round, or a report was filed that nobody "
            f"treats as current — both are how the fifth round's verdict went missing.")

    # 3. the two documents agree on which round is current
    led = ordinal_of(ledger_text)
    if owner_text:
        own = ordinal_of(owner_text)
        if led and own and led != own:
            failures.append(
                f"{LEDGER} leads with the {led.upper()} round and {OWNER} leads with the "
                f"{own.upper()}. A reader following one to the other gets a contradiction — the "
                f"literal symptom of A-06.")

    # 3b. THE ROUND THE DOCUMENTS ANNOUNCE HAS A REPORT — seventh independent audit, `G-03`.
    #
    # Checks 1-3 above compare the ledger, the OWNER page and the directory TO EACH OTHER. None
    # compares any of them to the round the documents announce, so the gate written to close A-06
    # did not detect A-06: the auditor set both banners to SEVENTH with no seventh report filed and
    # got GREEN. `newest_report()` returns the newest file on disk and `authoritative_link()`
    # returns what the ledger points at; agreeing with each other is not the same as being current.
    #
    # This binds the announcement to the evidence. The filename convention is now load-bearing —
    # a report must carry its ordinal — and that is stated in the failure message, because a gate
    # whose naming rule is undocumented is a gate that goes red on a correctly-filed report.
    if led:
        matching = [n for n in reports if f"-{led}-" in n]
        if not matching:
            failures.append(
                f"{LEDGER} announces the {led.upper()} round and no report in {AUDIT_DIR} names it "
                f"(expected a filename containing `-{led}-`). This is A-06 exactly: a round "
                f"announced whose evidence is not in the repository. File the report, or correct "
                f"the banner.")
        elif newest and max(matching) != newest:
            failures.append(
                f"{LEDGER} announces the {led.upper()} round, whose newest report is "
                f"`{max(matching)}`, but `{newest}` is newer and is filed. Either a round happened "
                f"and the banners were not moved, or a report was filed under the wrong ordinal.")

    # 3c. A report has to have something in it. `A-06`'s gate implemented "openable" as `.exists()`,
    # and the auditor passed it with a zero-byte file cited by all three documents. A smoke check,
    # not a guarantee — it is trivially satisfiable by padding, and it is written down as the lesser
    # thing it is rather than defended as the greater one.
    for name in reports:
        size = (audit_dir / name).stat().st_size
        if size < MIN_REPORT_BYTES:
            failures.append(
                f"{AUDIT_DIR}/{name} is {size} bytes. A report that small is a placeholder; "
                f"`exists()` is not the same as `is a report`. (Smoke check only — padding "
                f"satisfies it, and it is not claimed to do more.)")

    # 4. the machine-readable anchor names the same round the humans do
    state_path = root / STATE
    if state_path.exists():
        pointer = state_audit_pointer(state_path.read_text(encoding="utf-8"))
        if pointer is None:
            failures.append(
                f"{STATE} does not name a last-independent-audit report. Every human document has "
                f"an audit position; the file a tool reads must have one too.")
        else:
            checked += 1
            if not (root / pointer).exists():
                failures.append(f"{STATE} names `{pointer}`, which does not exist.")
            elif newest and pathlib.PurePosixPath(pointer).name != newest:
                failures.append(
                    f"{STATE} calls `{pathlib.PurePosixPath(pointer).name}` the last independent "
                    f"audit; the newest report filed is `{newest}`. This field was FIVE ROUNDS "
                    f"stale until 2026-08-17 — A-06 in the machine-readable anchor, where it is "
                    f"worse, because check_coordination.py makes the human docs agree with it.")

    if failures:
        print("RED: the audit trail does not open —", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print(f"\n{len(failures)} problem(s).", file=sys.stderr)
        return 1
    print(f"GREEN: {checked} audit citation(s) resolve; the ledger and the OWNER page both lead "
          f"with `{newest}`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
