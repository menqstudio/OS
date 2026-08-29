"""The canon has to stay readable — the reverse of `check_read_receipt.py`.

`check_read_receipt.py` asks *did this session read every canonical file?* That is the
forward direction, and this repository has enforced it for weeks. Nothing asked the
reverse: **is the canon still small enough that reading it is possible?**

It is not, and the shape of the failure is worth stating exactly, because it is not
untidiness:

* `config/canonical-read-manifest.json` names 16 paths totalling **1 917 KB — about
  386 000 tokens.** No session can hold that and still have room to work.
* `.claude/hooks/canonical_law_gate.py` believes the set is "~810 KB (~200k tokens)"
  (`:68`) and pastes up to `MAX_INJECT_BYTES` of it, so a session is handed roughly a
  quarter of the canon and a list of what it did not get — and the read receipt is
  recorded either way.
* `NEXT_CHAT.md` and `PROJECT_STATE.md` are the same document: **3 037 consecutive
  identical lines from line 2**, differing only in their titles. `TASKS.md` is 92%
  contained in `NEXT_CHAT.md`. Across the three, 59% of the text is a duplicate.

Every gate in `tools/` so far can only be satisfied by ADDING — a check to write, a
document to update, a row to append. That is why the canon only ever grew: a session
that appends is compliant, and a session that deletes is not rewarded. `NEXT_CHAT.md`
reached 4 034 lines one honest paragraph at a time.

So this gate can only be satisfied by REMOVING. It is the same trick
`check_dead_tokens.py` plays on `check_c1_tokens.py`: assert the direction with no
visible symptom, because that is the direction residue collects in.

Three refusals, each naming what to do about it:

1. **Per-file ceiling.** Every canonical path has a byte budget in
   `config/canon-budget.json`. Over it, the gate names the file and the overage. The
   remedy is never "raise the number" — it is to move the history to `docs/archive/`
   and leave the live statement behind.
2. **Total ceiling.** The manifest's own sum must fit one context. A canon that cannot
   be delivered is not a canon, it is a bibliography.
3. **Duplication ceiling.** No two canonical files may share more than a set fraction
   of the smaller one's substantive lines. Three files carrying one document is how
   1 917 KB happened, and no per-file ceiling alone would have caught it: each of the
   three was individually "just a long document".

And both directions of the budget itself: every manifest path must carry a budget, and
every budget must name a manifest path. An entry for a file nobody reads, or a
canonical file with no ceiling, is the hole this gate would otherwise grow.

Stdlib only, offline, fail-closed. Exit 0 GREEN, 1 RED.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST_REL = "config/canonical-read-manifest.json"
BUDGET_REL = "config/canon-budget.json"

# A line has to carry some content before "these two files are the same" means
# anything. Blank lines, `---`, table rules and bare fence markers are identical
# everywhere and would put a floor under every comparison.
MIN_SUBSTANTIVE = 40


def fail(problems: list[str]) -> int:
    print("RED: canonical read set is over budget\n")
    for p in problems:
        print(f"  - {p}")
    print(
        "\nThe remedy is never a bigger number. Move the history to docs/archive/ and\n"
        "leave the live statement in the canonical file. A budget raised to fit the\n"
        "text is the same as no budget, and this gate exists because that is what\n"
        "happened to the read manifest."
    )
    return 1


def load_json(root: pathlib.Path, rel: str) -> dict:
    path = root / rel
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"RED: {rel} is missing")
        raise SystemExit(1)
    except json.JSONDecodeError as exc:
        print(f"RED: {rel} is not valid JSON: {exc}")
        raise SystemExit(1)


def substantive_lines(path: pathlib.Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    return {ln.strip() for ln in text.splitlines() if len(ln.strip()) >= MIN_SUBSTANTIVE}


def main(root: pathlib.Path = ROOT) -> int:
    manifest = load_json(root, MANIFEST_REL)
    budget = load_json(root, BUDGET_REL)

    paths = manifest.get("paths")
    if not isinstance(paths, list) or not paths:
        print("RED: the read manifest declares no paths")
        return 1

    ceilings = budget.get("per_file_bytes")
    total_max = budget.get("total_bytes_max")
    overlap_max = budget.get("max_shared_fraction")
    if not isinstance(ceilings, dict) or not isinstance(total_max, int) or not isinstance(
        overlap_max, (int, float)
    ):
        print(
            "RED: config/canon-budget.json must carry per_file_bytes (object), "
            "total_bytes_max (int) and max_shared_fraction (number)"
        )
        return 1

    problems: list[str] = []

    # Both directions of the budget map itself.
    for rel in paths:
        if rel not in ceilings:
            problems.append(
                f"{rel} is canonical and has no budget — every path in the read "
                f"manifest needs a ceiling in config/canon-budget.json"
            )
    for rel in ceilings:
        if rel not in paths:
            problems.append(
                f"{rel} has a budget but is not in the read manifest — an unread file "
                f"with a ceiling is a ceiling nothing enforces"
            )

    # 1 — per-file ceilings, and 2 — the total.
    total = 0
    for rel in paths:
        path = root / rel
        try:
            size = path.stat().st_size
        except OSError:
            problems.append(f"{rel} is in the read manifest and not on disk")
            continue
        total += size
        cap = ceilings.get(rel)
        if isinstance(cap, int) and size > cap:
            problems.append(
                f"{rel} is {size:,} bytes against a ceiling of {cap:,} "
                f"(over by {size - cap:,} — {100 * size // cap}% of budget)"
            )

    if total > total_max:
        problems.append(
            f"the canonical set totals {total:,} bytes against a ceiling of "
            f"{total_max:,}. A session is handed the canon at SessionStart; a set "
            f"this size is truncated, and a read that silently did not happen is "
            f"worse than one that was never claimed"
        )

    # 3 — duplication between canonical files.
    lines = {rel: substantive_lines(root / rel) for rel in paths}
    for i, a in enumerate(paths):
        for b in paths[i + 1:]:
            la, lb = lines[a], lines[b]
            smaller = min(len(la), len(lb))
            if smaller == 0:
                continue
            shared = len(la & lb)
            fraction = shared / smaller
            if fraction > overlap_max:
                problems.append(
                    f"{a} and {b} share {shared:,} substantive lines — "
                    f"{fraction:.0%} of the smaller file, against a ceiling of "
                    f"{overlap_max:.0%}. Two canonical files carrying one document "
                    f"means every session reads it twice"
                )

    if problems:
        return fail(problems)

    print(
        f"GREEN: canonical read set within budget; files={len(paths)}; "
        f"total={total:,}B of {total_max:,}B "
        f"({100 * total // total_max}%); max_shared_fraction={overlap_max:.0%}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
