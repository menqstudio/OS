#!/usr/bin/env python3
"""Will CI refuse this push for something a local run shows in seconds?

    python3 tools/check_push_ready.py

Exit 0 GREEN, 1 RED.

WHY IT EXISTS
-------------
Pull request #317 was pushed and CI's bundle-size job went RED on it. The session had run
"every gate" first -- the argument-free loop, `for g in tools/check_*.py` -- and that loop
cannot run `tools/check_bundle_budget.py` to a verdict, because the gate needs a fresh
`apps/desktop/dist/` and says only `the build is stale` until somebody builds. So it was
read as noise, the build was never made, and a number a two-second local run prints was
found out from CI instead. `.claude/hooks/canonical_law_gate.py` now runs this before every
`git push` that is not a delete, and refuses the push unless it is GREEN.

WHAT IT RUNS -- the local gates CI runs that the argument-free loop skips, and only those
  * `tools/check_bundle_budget.py`, when the branch changes what the bundle is built from:
    anything under `apps/desktop/src/`, or `apps/desktop/package.json`,
    `package-lock.json`, `vite.config.ts`, `perf-budget.json`, `index.html`. "The branch
    changes" means the committed range since the merge base with `origin/main`, plus
    anything staged. That gate already refuses a `dist/` older than the tree; its verdict
    is passed through untouched, and when it is RED for a stale or missing build the
    command is named: `cd apps/desktop && npm run build`.
    When the merge base cannot be found the gate is RUN, not skipped: not knowing what
    changed is not knowing that nothing did.
  * `tools/check_runbook_snippets.py`, always -- when `cryptography` imports. When it does
    not, the gate is named as NOT RUN. It is never counted as passed.

WHAT IT DOES NOT RUN, and says so by name on every run
  Every other `tools/check_*.py`. The list is derived from the directory, never typed, so a
  gate added tomorrow is named here tomorrow. Three need arguments, one needs an artifact
  only a build and a run produce, and the rest are the argument-free loop -- a separate,
  slower thing this gate deliberately does not repeat. "Every gate" is never claimed.

WHAT THIS DOES NOT COVER -- listed, not implied
  * `git push` run from inside a script file rather than typed as the command. The hook
    reads the command line, not the files the command line runs;
  * a session opened outside this checkout. The hook loads from the SESSION's project
    root, and a session opened elsewhere gets no hooks at all;
  * a person pushing from their own terminal, or merging in the GitHub web UI;
  * the heavy `tools/check_produced_artifact.py`, and the three suites (engine, Rust,
    frontend). CI runs them; this does not;
  * a working-tree edit that is neither committed nor staged. It is not in the push.

Every input comes through `Inputs`, so the tests need no repository, no build and no
`cryptography`. A gate that crashes or times out is RED with that fact.

Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

BUNDLE = "check_bundle_budget.py"
SNIPPETS = "check_runbook_snippets.py"
SELF = "check_push_ready.py"
BUILD_COMMAND = "cd apps/desktop && npm run build"

#: What the bundle is built from, as the branch's diff names it.
FRONTEND_PREFIX = "apps/desktop/src/"
FRONTEND_FILES = frozenset({
    "apps/desktop/package.json",
    "apps/desktop/package-lock.json",
    "apps/desktop/vite.config.ts",
    "apps/desktop/perf-budget.json",
    "apps/desktop/index.html",
})

#: The two ways `check_bundle_budget.py` says "there is no build to measure".
NO_BUILD = ("the build is stale", "no Vite build manifest found")

#: Gates that print usage, not a verdict, when run bare.
NEEDS_ARGUMENTS = {
    "check_canonical_sync.py": "needs --staged or --base <ref>",
    "check_merge_ready.py": "needs --pr N; it asks GitHub about a pull request, not this tree",
    "check_prior_art.py": "needs --declare <path> or --session <id>",
    "check_read_receipt.py": "needs --session <id>",
}
#: Gates whose input is something only a build AND a run produce.
NEEDS_ARTIFACT = {
    "check_produced_artifact.py": "needs the evidence its `producer_command` writes "
                                  "(a cargo build and a run); CI's Production-half job runs it",
}


class GateError(Exception):
    """An input could not be read, or a gate could not be run. The message is the reason."""


def is_frontend(path: str) -> bool:
    path = path.replace("\\", "/")
    return path.startswith(FRONTEND_PREFIX) or path in FRONTEND_FILES


class Inputs:
    """Every fact this gate reads, behind a method a test can replace."""

    def __init__(self, root: pathlib.Path = ROOT) -> None:
        self.root = root

    def _git(self, *args: str) -> str:
        try:
            done = subprocess.run(["git", "-C", str(self.root), *args],
                                  capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            raise GateError(f"git {args[0]} could not be run: {exc}") from None
        if done.returncode != 0:
            err = (done.stderr or b"").decode("utf-8", errors="replace").strip()
            raise GateError(f"git {' '.join(args[:3])} exited {done.returncode}: "
                            f"{(err.splitlines() or ['no output'])[0][:200]}")
        return (done.stdout or b"").decode("utf-8", errors="replace")

    def changed(self) -> tuple[str, list[str]]:
        """`(merge base, paths)`: the committed range since the base, plus anything staged."""
        base = ""
        for ref in ("origin/main", "main"):
            try:
                base = self._git("merge-base", "HEAD", ref).strip()
            except GateError:
                continue
            if base:
                break
        if not base:
            raise GateError("no merge base with origin/main or main could be found")
        paths = set(self._git("diff", "--name-only", base, "HEAD").splitlines())
        paths |= set(self._git("diff", "--name-only", "--cached").splitlines())
        return base, sorted(p.strip() for p in paths if p.strip())

    def run_gate(self, name: str, args: list[str]) -> tuple[int, str]:
        """Run one gate OF THE TREE BEING PUSHED and return `(exit code, what it printed)`."""
        script = self.root / "tools" / name
        try:
            done = subprocess.run([sys.executable, "-B", str(script), *args], cwd=str(self.root),
                                  capture_output=True, timeout=40)
        except subprocess.TimeoutExpired:
            raise GateError(f"tools/{name} did not finish within 40s") from None
        except OSError as exc:
            raise GateError(f"tools/{name} could not be started: {exc}") from None
        text = ((done.stdout or b"") + (done.stderr or b"")).decode("utf-8", errors="replace")
        return done.returncode, text.strip()

    def snippets_blocker(self) -> str | None:
        """Why `check_runbook_snippets.py` cannot run here, or None when it can."""
        try:
            found = importlib.util.find_spec("cryptography")
        except (ImportError, ValueError):
            found = None
        if found is None:
            return ("`cryptography` does not import here, and the gate imports the engine "
                    "modules that need it")
        return None

    def gates(self) -> list[str]:
        return sorted(p.name for p in (self.root / "tools").glob("check_*.py"))


def _indent(text: str, by: str = "      ") -> str:
    return "\n".join(by + line for line in (text or "(it printed nothing)").splitlines())


def _run(inputs: Inputs, name: str, args: list[str], why: str,
         problems: list[str], ran: list[str]) -> None:
    """Run one gate; a crash or a timeout is a problem, exactly as a RED verdict is."""
    try:
        code, output = inputs.run_gate(name, args)
    except GateError as exc:
        problems.append(f"tools/{name} could not be run to a verdict: {exc}")
        print(f"  RED   tools/{name}  ({why})\n      it could not be run to a verdict: {exc}")
        return
    ran.append(name)
    if code == 0:
        print(f"  GREEN tools/{name}  ({why})")
        return
    print(f"  RED   tools/{name}  ({why})\n{_indent(output)}")
    problems.append(f"tools/{name} is RED")
    if name == BUNDLE and any(marker in output for marker in NO_BUILD):
        problems.append(f"there is no fresh build for it to measure -- run: {BUILD_COMMAND}")


def not_run_report(inputs: Inputs, ran: list[str], conditional: dict[str, str]) -> list[str]:
    """One line per gate this run did NOT run, by name, with the reason."""
    lines: list[str] = []
    loop: list[str] = []
    for name in inputs.gates():
        if name in ran or name == SELF:
            continue
        if name in conditional:
            lines.append(f"  tools/{name} -- {conditional[name]}")
        elif name in NEEDS_ARGUMENTS:
            lines.append(f"  tools/{name} -- {NEEDS_ARGUMENTS[name]}")
        elif name in NEEDS_ARTIFACT:
            lines.append(f"  tools/{name} -- {NEEDS_ARTIFACT[name]}")
        else:
            loop.append(name)
    if loop:
        lines.append(f"  {len(loop)} argument-free gate(s) -- the separate loop "
                     f"`for g in tools/check_*.py; do python3 \"$g\"; done`, not run here:")
        lines.append("    " + ", ".join(loop))
    return lines


def verdict(inputs: Inputs) -> int:
    problems: list[str] = []
    ran: list[str] = []
    conditional: dict[str, str] = {}

    try:
        base, changed = inputs.changed()
    except GateError as exc:
        print(f"push-ready: what this branch changes could NOT be established ({exc}).\n")
        bundle_why = "what changed is unknown, so it is not assumed to be nothing"
        run_bundle = True
    else:
        frontend = [p for p in changed if is_frontend(p)]
        print(f"push-ready: {len(changed)} path(s) changed since the merge base {base[:12]} "
              f"with main, staged included; {len(frontend)} of them bundled frontend source.\n")
        run_bundle = bool(frontend)
        bundle_why = ("frontend changed: " + ", ".join(frontend[:2])
                      + (f" +{len(frontend) - 2} more" if len(frontend) > 2 else ""))

    if run_bundle:
        _run(inputs, BUNDLE, ["--root", str(inputs.root)], bundle_why, problems, ran)
    else:
        conditional[BUNDLE] = ("no bundled frontend path changed on this branch; it would "
                               "measure the same bundle `main` has")
    blocker = inputs.snippets_blocker()
    if blocker is None:
        _run(inputs, SNIPPETS, [], "always", problems, ran)
    else:
        conditional[SNIPPETS] = f"COULD NOT RUN: {blocker}. CI will run it; this did not"
    report = not_run_report(inputs, ran, conditional)

    if report:
        print("\nNOT RUN by this gate, and so NOT claimed:")
        print("\n".join(report))

    if problems:
        print("\nRED: do NOT push -- CI will refuse this, and it can be seen from here:")
        for i, problem in enumerate(problems, 1):
            print(f"  {i}. {problem}")
        return 1
    skipped = len([g for g in inputs.gates() if g not in ran and g != SELF])
    print(f"\nGREEN: {len(ran)} gate(s) ran and passed ({', '.join(ran) or 'none'}); "
          f"{skipped} named above were not run. This is not every gate.")
    return 0


def main(argv: list[str] | None = None, inputs: Inputs | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT), help="the checkout being pushed")
    args = ap.parse_args(argv)
    inputs = inputs or Inputs(pathlib.Path(args.root).resolve())
    try:
        return verdict(inputs)
    except Exception as exc:  # noqa: BLE001 - a gate that crashed has not said yes
        print(f"\nRED: do NOT push -- the gate itself failed: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
