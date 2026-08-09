#!/usr/bin/env python3
"""The update law -- code and canon move together, or the change is refused.

THE RULE
  "Update every canonical file whenever anything changes." Standing Owner rule,
  broken repeatedly: config/current_state.json spent sixteen merged PRs naming a
  branch that no longer existed, while the human docs restated it.

WHAT ALREADY EXISTED -- read this before assuming this file is new work
  * `.claude/hooks/coordination_stop_guard.py` blocks the END of a turn when code
    changed and no coordination doc did. It is FAIL-OPEN by design and carries two
    bypasses (`BRO_SKIP_DOC_SYNC=1`, a `[no-doc-sync]` commit tag). It is a
    reminder, and it was used as one.
  * `tools/check_coordination.py` §`_check_state_sync` enforces the same idea at
    PR level in CI, but only when a diff base exists (`GITHUB_BASE_REF`), and it
    is satisfied by touching ANY ONE state file.

  The gap this closes: per-COMMIT enforcement, locally, with no environment
  bypass, requiring ALL the required documents rather than any one of them. It is
  the same law at a third point on the timeline, not a second implementation of
  the same point -- the check_coordination PR rule stays authoritative for a PR.

WHY BOTH LOCAL AND CI
  A check that only runs in CI lets the mistake reach GitHub: the bad commit is in
  the history, the PR is red, and the fix is a second commit apologising for the
  first. A check that only runs locally does not survive a fresh clone --
  `.git/hooks` is not tracked, so a new machine has no gate at all, and
  `git commit --no-verify` removes it on the machine that does. So: the local
  pre-commit hook (tools/githooks/pre-commit) gives the fast, same-second refusal,
  and the CI job is the one that cannot be skipped. Neither alone is the law.

  This module deliberately takes the changed-file list as DATA. It needs no git to
  be tested, and the same function serves the pre-commit hook (staged files), CI
  (a PR diff) and a unit test (a literal list).

Usage:
  python tools/check_canonical_sync.py --staged
  python tools/check_canonical_sync.py --base origin/main
  python tools/check_canonical_sync.py --changed-files -    # newline list on stdin
Exit 0 + "GREEN: ..." / exit 1 + what is missing.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import pathlib
import subprocess
import sys

LAW = "config/canonical-update-law.json"


def load_law(root: pathlib.Path) -> dict:
    document = json.loads((root / LAW).read_text(encoding="utf-8"))
    for key in ("substantive_globs", "required_docs", "exempt_globs"):
        value = document.get(key)
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError(f"{LAW}: {key!r} must be a list of strings")
    if not document["required_docs"]:
        # An empty required list would make the law vacuously satisfied, which is
        # indistinguishable from deleting the gate while it still reports GREEN.
        raise ValueError(f"{LAW}: required_docs is empty -- the law would always pass")
    return document


def _hit(path: str, globs: list[str]) -> bool:
    # fnmatch '*' spans '/', so these globs match at any depth (same convention as
    # tools/check_coordination.py's SUBSTANTIVE_GLOBS).
    return any(fnmatch.fnmatch(path, glob) for glob in globs)


def normalise(paths) -> list[str]:
    return sorted({str(p).strip().replace("\\", "/") for p in paths if str(p).strip()})


def check(root: pathlib.Path, changed) -> list[str]:
    """Return problems (empty == lawful). `changed` is a list of repo-relative paths."""
    law = load_law(root)
    files = normalise(changed)
    if not files:
        return []
    substantive = [f for f in files
                   if _hit(f, law["substantive_globs"]) and not _hit(f, law["exempt_globs"])]
    if not substantive:
        return []
    missing = [doc for doc in law["required_docs"] if doc not in files]
    if not missing:
        return []
    sample = ", ".join(substantive[:5]) + (", ..." if len(substantive) > 5 else "")
    return [
        f"this change touches {len(substantive)} substantive file(s) ({sample}) but does not "
        f"update {missing} in the same commit. The canon and the code move together: state what "
        f"changed in each of {law['required_docs']}, then commit again. There is no environment "
        "bypass for this gate -- the bypasses on the older Stop-hook are why the rule was broken."
    ]


def _git(root: pathlib.Path, args: list[str]) -> list[str] | None:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                             timeout=30, check=True).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    return [line.strip() for line in out.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[1]))
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--staged", action="store_true", help="git diff --cached --name-only")
    source.add_argument("--base", default=None, help="git diff --name-only <base>...HEAD")
    source.add_argument("--changed-files", default=None,
                        help="file with one path per line, or '-' for stdin")
    args = parser.parse_args(argv)
    root = pathlib.Path(args.root).resolve()

    if args.staged:
        changed = _git(root, ["diff", "--cached", "--name-only"])
    elif args.base:
        changed = (_git(root, ["diff", "--name-only", f"origin/{args.base}...HEAD"])
                   or _git(root, ["diff", "--name-only", f"{args.base}...HEAD"]))
    elif args.changed_files == "-":
        changed = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
    else:
        changed = [line.strip() for line in
                   pathlib.Path(args.changed_files).read_text(encoding="utf-8").splitlines()
                   if line.strip()]
    if changed is None:
        # Fail closed on the git paths: "I could not find out what changed" must not
        # read as "nothing substantive changed".
        print("RED: could not determine the changed files from git; refusing to pass by default")
        return 1
    try:
        problems = check(root, changed)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"RED: {LAW} is unusable: {exc}")
        return 1
    if problems:
        print("RED: canonical update law:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"GREEN: canonical update law satisfied over {len(normalise(changed))} changed file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
