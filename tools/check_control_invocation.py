#!/usr/bin/env python3
"""T-056: every fail-closed control must name what its failure PREVENTS.

A check that nothing invokes is a suggestion. `engine/tools/bro_deploy_preflight.py`
calls itself a fail-closed deployment preflight and is named three times in
`engine/docs/OPERATOR_RUNBOOK.md` — and has zero non-test callers, so its failure
prevents nothing. Being named in a runbook is a request that somebody run it.

This gate holds `config/control-invocation.json` to one question per control:
**what does its failure stop?** `merge`, `session`, `deploy`, `release`, or
`nothing`.

THE POPULATION IS DERIVED FROM THE FILESYSTEM — `tools/check_*.py` plus
`engine/tools/*.py` — and never from a list. A gate holding a list can omit
itself; a gate globbing its own directory physically cannot, and this file
appears in its own population by construction.

WHAT IS DERIVED VERSUS WHAT IS DECLARED, because the difference is the whole
point:

  DERIVED here, and the registry may not disagree with it:
    * which workflow jobs reference the file, directly or through a shell script
      those jobs run, or through another population file that references it;
    * whether any of those job names is in `config/required-checks.json` —
      running in CI is NOT the same as blocking a merge, and two controls in this
      tree run in CI under contexts nobody requires;
    * whether `.claude/hooks/` or `.claude/settings.json` names the file.

  DECLARED, because no derivation can answer it:
    * `kind`: `check` (it produces a verdict) or `tool` (it does something).
      `broctl.py` is a tool. A tool may block nothing without argument.
    * `unenforced_reason` + `tracked_by` for a CHECK that blocks nothing. That
      pair is the freeze: the debt is written down where a reader meets it, and
      a NEW one cannot appear without somebody writing the sentence.

Exit 0 GREEN, 1 RED.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTRY_REL = "config/control-invocation.json"
REQUIRED_REL = "config/required-checks.json"

BLOCKS = ("merge", "session", "deploy", "release", "nothing")
KINDS = ("check", "tool")

#: A file whose own text says this is claiming to be fail-closed. The claim is
#: what makes `blocks: nothing` a contradiction rather than a fact.
FAIL_CLOSED = re.compile(r"fail[- ]clos", re.I)


def population(root: pathlib.Path) -> list[str]:
    """Derived, never listed. This file is in it."""
    found = sorted(p.relative_to(root).as_posix() for p in (root / "tools").glob("check_*.py"))
    found += sorted(
        p.relative_to(root).as_posix() for p in (root / "engine" / "tools").glob("*.py")
    )
    return found


def _yaml_jobs(root: pathlib.Path) -> list[tuple[str, str]]:
    """(job display name, the job's serialised body) for every root workflow."""
    try:
        import yaml  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return []
    out: list[tuple[str, str]] = []
    for wf in sorted((root / ".github" / "workflows").glob("*.yml")):
        try:
            doc = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            continue
        for job, spec in (doc.get("jobs") or {}).items():
            out.append((spec.get("name") or job, json.dumps(spec)))
    return out


def _uncommented(text: str) -> str:
    """Comment lines removed. A control named in a comment is described, not run."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def derive(root: pathlib.Path) -> dict[str, dict]:
    """What actually invokes each control, read from the tree."""
    pop = population(root)
    required = set(json.loads((root / REQUIRED_REL).read_text(encoding="utf-8"))["contexts"])
    jobs = _yaml_jobs(root)

    scripts = {}
    for p in root.rglob("*.sh"):
        rel = p.relative_to(root).as_posix()
        if rel.startswith(".git/") or "node_modules" in rel:
            continue
        scripts[rel] = p.read_text(encoding="utf-8", errors="replace")

    hooks = ""
    for p in list((root / ".claude" / "hooks").glob("*")) + [root / ".claude" / "settings.json"]:
        if p.is_file():
            hooks += p.read_text(encoding="utf-8", errors="replace")

    texts = {f: (root / f).read_text(encoding="utf-8", errors="replace") for f in pop}

    out: dict[str, dict] = {}
    for f in pop:
        name = pathlib.Path(f).name
        stem = name[:-3]
        hit: set[str] = set()
        for jobname, blob in jobs:
            if name in blob:
                hit.add(jobname)
                continue
            # a job that runs a shell script which runs the control
            for srel, stext in scripts.items():
                if (srel in blob or pathlib.Path(srel).name in blob) and name in stext:
                    hit.add(jobname)
                    break
        # Transitive, and deliberately narrow: a control INVOKED by another
        # population file inherits that file's jobs. A mention is not a call —
        # the reachability gate learned this the expensive way — so this
        # requires an import or the filename in an argv-shaped position, with
        # comment lines stripped first.
        for other in pop:
            if other == f:
                continue
            body = _uncommented(texts[other])
            invoked = (
                re.search(rf"^\s*import\s+{re.escape(stem)}\b", body, re.M)
                or re.search(rf"^\s*from\s+{re.escape(stem)}\s+import\b", body, re.M)
                or re.search(rf"[\"'][^\"']*{re.escape(name)}[\"']", body)
            )
            if not invoked:
                continue
            for jobname, blob in jobs:
                if pathlib.Path(other).name in blob:
                    hit.add(jobname)
        out[f] = {
            "jobs": sorted(hit),
            "required_jobs": sorted(j for j in hit if j in required),
            "in_hook": name in hooks or stem in hooks,
            "says_fail_closed": bool(FAIL_CLOSED.search(texts[f])),
        }
    return out


def main(root: pathlib.Path = ROOT) -> int:
    problems: list[str] = []
    reg_path = root / REGISTRY_REL
    if not reg_path.exists():
        print(f"RED: {REGISTRY_REL} does not exist; every derived control needs an entry")
        return 1
    registry = json.loads(reg_path.read_text(encoding="utf-8")).get("controls", {})
    facts = derive(root)
    pop = list(facts)

    # 1 — the derived population and the registry are the same set, both ways.
    missing = [f for f in pop if f not in registry]
    extra = [f for f in registry if f not in facts]
    for f in missing:
        problems.append(
            f"{f}: exists on disk and has no entry in {REGISTRY_REL}. The population is "
            f"DERIVED, so a new control cannot be added without saying what its failure prevents"
        )
    for f in extra:
        problems.append(f"{f}: declared in {REGISTRY_REL} and not on disk — the entry outlived its file")

    for f in sorted(set(pop) & set(registry)):
        e = registry[f]
        d = facts[f]
        kind = e.get("kind")
        blocks = e.get("blocks")
        if kind not in KINDS:
            problems.append(f"{f}: `kind` must be one of {KINDS}, got {kind!r}")
            continue
        if blocks not in BLOCKS:
            problems.append(f"{f}: `blocks` must be one of {BLOCKS}, got {blocks!r}")
            continue

        # 2 — a declared consequence must be one the tree actually delivers.
        if blocks == "merge" and not d["required_jobs"]:
            ran = f"; it runs in {d['jobs']}" if d["jobs"] else "; no workflow job names it"
            problems.append(
                f"{f}: declares `blocks: merge` and NO job that names it is a required context in "
                f"{REQUIRED_REL}{ran}. Running in CI is not blocking a merge"
            )
        if blocks == "session" and not d["in_hook"]:
            problems.append(
                f"{f}: declares `blocks: session` and nothing in .claude/hooks or "
                f".claude/settings.json names it"
            )

        # 3 — and a consequence the tree DOES deliver may not be understated.
        if blocks == "nothing" and d["required_jobs"]:
            problems.append(
                f"{f}: declares `blocks: nothing` but {d['required_jobs']} is a required context. "
                f"Understating a consequence is the same defect as overstating one"
            )

        # 4 — the claim a file makes about itself must match what it can do.
        if blocks == "nothing":
            if kind == "check" and d["says_fail_closed"]:
                if not (e.get("unenforced_reason") and e.get("tracked_by")):
                    problems.append(
                        f"{f}: its own text says fail-closed, it is a `check`, and its failure "
                        f"prevents NOTHING. That is permitted only with `unenforced_reason` and "
                        f"`tracked_by` — write the sentence, so the debt is where a reader meets it"
                    )
            if not e.get("why"):
                problems.append(f"{f}: `blocks: nothing` needs a `why`")
        for field in ("unenforced_reason", "why"):
            v = e.get(field)
            if v is not None and len(v) < 40:
                problems.append(f"{f}: `{field}` is {len(v)} chars; a placeholder is not a reason")
        tracked = e.get("tracked_by")
        if tracked and not (root / tracked).exists():
            problems.append(f"{f}: `tracked_by` names {tracked}, which does not exist")

    if problems:
        print("RED: controls do not name what their failure prevents —\n")
        for p in problems:
            print(f"  - {p}")
        print(f"\n{len(problems)} problem(s).")
        return 1

    by = {}
    for f in pop:
        by[registry[f]["blocks"]] = by.get(registry[f]["blocks"], 0) + 1
    checks = sum(1 for f in pop if registry[f]["kind"] == "check")
    debt = [f for f in pop if registry[f].get("unenforced_reason")]
    print(
        f"GREEN: {len(pop)} controls derived from the filesystem ({checks} checks, "
        f"{len(pop) - checks} tools); every declared consequence matches what the tree delivers. "
        f"blocks: " + ", ".join(f"{k}={v}" for k, v in sorted(by.items()))
        + (f"; {len(debt)} fail-closed check(s) declared unenforced with a written reason: "
           + ", ".join(sorted(pathlib.Path(f).name for f in debt)) if debt else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
