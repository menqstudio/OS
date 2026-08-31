#!/usr/bin/env python3
"""Prior art -- "does this already exist?" recorded as evidence, not remembered.

THE DEFECT THIS BINDS
  In two days, in this repository: the audit-anchor custody machinery was nearly
  written from scratch three times before somebody noticed
  `win-live/src/provision_custody.rs` already did it; a second copy of the
  writability logic was almost added instead of calling `bro_custody`. Going the
  other way, 262 agent definitions the app could not reach, five engine security
  functions with no caller, two backend commands with no frontend wrapper. Same
  defect from two sides: nobody looked first, and nothing joined up after.

  "I looked" is not evidence, for the same reason "I read it" is not.

WHAT IS ACTUALLY CHECKABLE -- and what is not
  "Is this a duplicate?" is a judgement. A gate that claims to answer it would
  manufacture false confidence, which is worse than the silence it replaces. So
  this gate does NOT decide. It checks the four things a machine can:

    1. A session that declares NOTHING before creating a new file. Refused.
    2. A declaration that does not name what was searched, or does not state a
       decision (extend X / new because Y). Refused as empty ceremony.
    3. A new file whose stem COLLIDES with an existing file elsewhere in the
       tree, where the declaration never mentions the colliding file. Refused --
       this is the `provision_custody` case reduced to something mechanical.
    4. A new gate under tools/ whose declared INPUTS (the repo-relative paths it
       reads) overlap an existing gate's inputs, unmentioned. Refused -- two
       gates reading the same inputs is the shape of a duplicated check.

  The judgement half is not decided, it is RECORDED: the session writes what it
  searched, what it found and why it is building anyway, into the session receipt,
  where a reviewer can disagree with it. Visible and wrong beats silent.

  Reachability -- the other half of the Owner's rule, "do not leave what you built
  unreachable" -- is deliberately NOT reimplemented here. tools/check_reachability.py
  already owns that question for Tauri commands and named engine symbols, with a
  declarations file and reason-quality rules. It was WIDENED rather than copied
  (see its `tools_gates` section): writing a third implementation would be this
  very rule broken while implementing it.

Usage:
  python tools/check_prior_art.py --declare tools/new_gate.py \
      --searched "grep check_*, tools/ listing, docs/ARCHITECTURE" \
      --found "tools/check_coordination.py (docs consistency, different inputs)" \
      --decision "new: no existing gate reads the canonical read manifest at all"
  python tools/check_prior_art.py --verify tools/new_gate.py
  python tools/check_prior_art.py --collisions tools/new_gate.py
Exit 0 + "GREEN: ..." / exit 1 + the reason.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import time

import check_read_receipt as receipt_store

MIN_SEARCHED_CHARS = 30
MIN_DECISION_CHARS = 40
SKIP_PARTS = {"node_modules", "target", ".git", "__pycache__", "dist", ".venv", "build"}
GATE_DIR = "tools"
# Repo-relative path literals a gate reads, as they appear in its source.
_PATH_LITERAL_RE = re.compile(
    r"""["'"']((?:apps|engine|bridge|config|contracts|docs|tools|\.github)/[A-Za-z0-9_./*-]+)["'"']""")
_DECISION_RE = re.compile(r"^(extend|new)\s*:\s*(.+)$", re.IGNORECASE | re.DOTALL)


def repo_files(root: pathlib.Path) -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if SKIP_PARTS.intersection(path.relative_to(root).parts):
            continue
        out.append(path)
    return out


def stem_collisions(root: pathlib.Path, rel_path: str) -> list[str]:
    """Existing files whose stem equals the new file's stem. The cheap, reliable
    half of "does this already exist" -- it never proves a duplicate, but a hit is
    always worth a sentence before a second copy is created."""
    target = pathlib.PurePosixPath(str(rel_path).replace("\\", "/"))
    stem = target.stem
    if not stem:
        return []
    hits = []
    for path in repo_files(root):
        rel = path.relative_to(root).as_posix()
        if rel == target.as_posix():
            continue
        if path.stem == stem:
            hits.append(rel)
    return sorted(hits)


def gate_inputs(path: pathlib.Path) -> set[str]:
    """Repo-relative paths a gate module names in its source -- its inputs."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return {match.group(1) for match in _PATH_LITERAL_RE.finditer(text)}


def gate_overlaps(root: pathlib.Path, rel_path: str) -> dict[str, list[str]]:
    """{existing gate: shared inputs} for a new tools/check_*.py."""
    rel = str(rel_path).replace("\\", "/")
    if not (rel.startswith(f"{GATE_DIR}/check_") and rel.endswith(".py")):
        return {}
    new_inputs = gate_inputs(root / rel)
    if not new_inputs:
        return {}
    overlaps: dict[str, list[str]] = {}
    for existing in sorted((root / GATE_DIR).glob("check_*.py")):
        existing_rel = existing.relative_to(root).as_posix()
        if existing_rel == rel:
            continue
        shared = sorted(new_inputs & gate_inputs(existing))
        if shared:
            overlaps[existing_rel] = shared
    return overlaps


def declarations(root: pathlib.Path, sid: str) -> list[dict]:
    document = receipt_store.load(root, sid) or {}
    entries = document.get("prior_art")
    return entries if isinstance(entries, list) else []


def declaration_for(root: pathlib.Path, sid: str, rel_path: str) -> dict | None:
    """The LATEST declaration for a path, not the first.

    Measured 2026-08-31 before changing anything: today this cannot differ,
    because `declare` filters out any existing entry for the same target before
    appending, so a target never has two records. Declaring twice stores one
    entry -- the second -- and this function already returned it. The gate's own
    "then re-declare" remedy is reachable, contrary to what a note of mine said.

    It returns the last anyway, and the reason is not a live bug. As written,
    this function's correctness DEPENDED on a dedup happening somewhere else,
    silently: any future writer that appends without filtering would make the
    gate read a stale record and nothing would say so. Reading the last is
    correct whether or not that dedup exists, which removes the coupling.
    """
    rel = str(rel_path).replace("\\", "/")
    latest = None
    for entry in declarations(root, sid):
        if str(entry.get("target", "")).replace("\\", "/") == rel:
            latest = entry
    return latest


def declare(root: pathlib.Path, sid: str, rel_path: str, searched: str,
            found: str, decision: str) -> tuple[bool, str]:
    ok, why = receipt_store.verify(root, sid)
    if not ok:
        return False, f"cannot record prior art: {why}"
    if len(searched.strip()) < MIN_SEARCHED_CHARS:
        return False, (f"--searched must name what was actually searched -- the greps, the "
                       f"directories, the docs (at least {MIN_SEARCHED_CHARS} characters)")
    match = _DECISION_RE.match(decision.strip())
    if not match:
        return False, ("--decision must start with 'extend:' or 'new:' -- either you are "
                       "continuing something that exists, or you are saying why nothing does")
    if len(match.group(2).strip()) < MIN_DECISION_CHARS:
        return False, (f"--decision needs a real justification after '{match.group(1)}:' "
                       f"(at least {MIN_DECISION_CHARS} characters)")
    document = receipt_store.load(root, sid) or {}
    entries = [e for e in declarations(root, sid)
               if str(e.get("target", "")).replace("\\", "/") != str(rel_path).replace("\\", "/")]
    entries.append({
        "target": str(rel_path).replace("\\", "/"),
        "searched": searched.strip(),
        "found": found.strip(),
        "decision": decision.strip(),
        "at_epoch": int(time.time()),
    })
    document["prior_art"] = entries
    receipt_store.write_receipt(root, sid, document)
    return True, f"prior art recorded for {rel_path}"


def verify(root: pathlib.Path, sid: str, rel_path: str) -> tuple[bool, str]:
    """(ok, reason) -- may this session create `rel_path`?"""
    rel = str(rel_path).replace("\\", "/")
    entry = declaration_for(root, sid, rel)
    if entry is None:
        return False, (
            f"REFUSED: {rel} does not exist yet and this session has recorded no prior-art search "
            f"for it. Before building, establish that it does not already exist -- then record it: "
            f"python tools/check_prior_art.py --declare {rel} --searched \"<what you searched>\" "
            f"--found \"<what exists, or 'nothing')>\" --decision \"extend:<path>|new:<why>\"")
    text = (str(entry.get("found", "")) + " " + str(entry.get("decision", ""))).lower()
    unmentioned = [hit for hit in stem_collisions(root, rel) if hit.lower() not in text]
    if unmentioned:
        return False, (
            f"REFUSED: {rel} collides by name with existing file(s) {unmentioned[:5]} that your "
            "prior-art record never mentions. Say which one you looked at and why this is not a "
            "second copy of it, then re-declare.")
    overlaps = {gate: shared for gate, shared in gate_overlaps(root, rel).items()
                if gate.lower() not in text}
    if overlaps:
        first = sorted(overlaps)[0]
        return False, (
            f"REFUSED: {rel} reads the same inputs as the existing gate {first} "
            f"({overlaps[first][:4]}) and your prior-art record never mentions it. Two gates over "
            "the same inputs is the shape of a duplicated check -- extend it, or say why not.")
    return True, (f"prior art recorded for {rel}: {str(entry.get('decision'))[:80]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[1]))
    parser.add_argument("--session", default=None)
    parser.add_argument("--declare", default=None, metavar="PATH")
    parser.add_argument("--searched", default="")
    parser.add_argument("--found", default="")
    parser.add_argument("--decision", default="")
    parser.add_argument("--verify", default=None, metavar="PATH")
    parser.add_argument("--collisions", default=None, metavar="PATH")
    args = parser.parse_args(argv)
    root = pathlib.Path(args.root).resolve()
    sid = receipt_store.session_id(args.session)
    if args.collisions:
        hits = stem_collisions(root, args.collisions)
        overlaps = gate_overlaps(root, args.collisions)
        print(f"name collisions: {hits or 'none'}")
        print(f"gate input overlaps: {overlaps or 'none'}")
        return 0
    if args.declare:
        ok, why = declare(root, sid, args.declare, args.searched, args.found, args.decision)
    elif args.verify:
        ok, why = verify(root, sid, args.verify)
    else:
        parser.error("one of --declare / --verify / --collisions is required")
    print(("GREEN: " if ok else "RED: ") + why)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
