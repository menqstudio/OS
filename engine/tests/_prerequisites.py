"""Test helper: environment prerequisites that live OUTSIDE the engine tree.

A handful of tests assert things about the *source repository* rather than about the
running engine: that the wired enforcement wall refuses for a named cause (which
needs a git worktree, because the wall computes its tree identity from `git
ls-files`), that the live-kit pin manifest covers the artifact list the Rust TCB
defines (which needs `apps/`), that the governance reply survives the sidecar
crossing (which needs `bridge/`). Step 6 of the Debian deployment copies `engine/`
and nothing else, and it copies it without `.git`. Run there, those tests used to
ERROR — fourteen red lines on a correctly deployed box, none of them a defect, which
is the state that teaches an operator to skim past red.

The rule this module enforces is: a test gives the SAME verdict in CI and on a
deployed box, or it SKIPS with a reason that names the missing prerequisite exactly.
Never an error, and never a pass for a reason other than the one it exists to prove
(`test_live_hook_deny` is the worked example: on a tree without `.git` the wall still
said "deny", so a laxer negative would have gone green on a refusal it never earned).

A skip is a hole unless someone counts them. CI checks out the whole monorepo, so
every prerequisite named here IS present there. If one is missing under a CI runner
that is not an environment quirk to route around -- it means a test quietly stopped
covering anything -- so `require()` FAILS instead of skipping whenever
`GITHUB_ACTIONS`/`CI` is set. That is the counter: the skips can only appear off the
runner, where they are the honest answer.

Not a test module (no ``test_`` prefix), so unittest discovery ignores it.
"""
from __future__ import annotations

import functools
import os
import pathlib
import subprocess
import unittest

ENGINE_ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parent


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def running_under_ci() -> bool:
    """True on a CI runner, where every prerequisite below must be present.

    Read from the runner's own signals (GitHub Actions sets both) rather than from a
    repository-specific flag, so no workflow edit is needed for the guard to bite and
    no human on a deployed box can trip it by exporting ``BRO_ENV=ci`` -- which the
    deployment runbook tells them to do.
    """
    return _truthy(os.environ.get("GITHUB_ACTIONS")) or _truthy(os.environ.get("CI"))


class Prerequisite:
    """Something outside the engine tree that a test cannot manufacture for itself."""

    def __init__(self, name: str, probe, reason: str):
        self.name = name
        self._probe = probe
        self._reason = reason

    def present(self) -> bool:
        return bool(self._probe())

    @property
    def reason(self) -> str:
        return f"{self.name} unavailable: {self._reason}"

    @property
    def ci_failure(self) -> str:
        return (f"{self.reason}. CI runs on a full checkout where this IS present, so "
                "this is not an environment quirk to skip past: the test would have "
                "stopped covering anything. Fix the checkout, not the assertion.")


@functools.lru_cache(maxsize=1)
def _inside_git_worktree() -> bool:
    """Can the command the engine depends on actually run from the engine tree?

    Asks git, rather than looking for a `.git` entry at or above ENGINE_ROOT. The
    failure this gate exists for is `git ls-files` exiting 128, and the presence of a
    directory named `.git` is only a proxy for that: an empty or corrupt one exits 128
    all the same, a missing git binary fails a third way, and `GIT_DIR` or a worktree
    pointer can make git succeed where a filesystem walk says no. A proxy that
    disagrees with the real thing would either skip a test that could have run or --
    far worse -- let one run into the error this module exists to replace.

    Read-only (`rev-parse` writes nothing) and cached, so it costs one subprocess per
    test process however many tests ask.
    """
    try:
        probe = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(ENGINE_ROOT), capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        # No git binary, or it never answered: either way `git ls-files` cannot work.
        return False
    return probe.returncode == 0 and probe.stdout.strip() == "true"


GIT_WORKTREE = Prerequisite(
    "git worktree",
    _inside_git_worktree,
    "git does not resolve the engine tree to a worktree, so `git ls-files` exits 128 "
    "and every tree-identity read fails closed (a deployed tree is copied without .git)",
)

DESKTOP_TCB_SOURCE = Prerequisite(
    "apps/desktop TCB source",
    lambda: (REPO_ROOT / "apps" / "desktop" / "src-tauri" / "core" / "src"
             / "tcb_integrity.rs").is_file(),
    "apps/desktop/src-tauri/core/src/tcb_integrity.rs is not present beside the "
    "engine tree (deployment Step 6 copies engine/ only)",
)

BRIDGE_SIDECAR = Prerequisite(
    "bridge sidecar",
    lambda: (REPO_ROOT / "bridge" / "engine_sidecar.py").is_file(),
    "bridge/engine_sidecar.py is not present beside the engine tree (deployment "
    "Step 6 copies engine/ only)",
)


def require(*prerequisites: Prerequisite) -> None:
    """Skip -- or, under CI, FAIL -- unless every prerequisite is present."""
    for prerequisite in prerequisites:
        if prerequisite.present():
            continue
        if running_under_ci():
            raise AssertionError(prerequisite.ci_failure)
        raise unittest.SkipTest(prerequisite.reason)


def requires(*prerequisites: Prerequisite):
    """Decorate a TestCase class or a test method with :func:`require`.

    Applied to a class it wraps ``setUp`` rather than replacing the class, so the
    check runs per test and reports through the normal skip/failure channels.
    """

    def decorate(target):
        if isinstance(target, type):
            original = target.setUp

            @functools.wraps(original)
            def setUp(self, *args, **kwargs):  # noqa: N802 - unittest's spelling
                require(*prerequisites)
                original(self, *args, **kwargs)

            target.setUp = setUp
            return target

        @functools.wraps(target)
        def wrapper(self, *args, **kwargs):
            require(*prerequisites)
            return target(self, *args, **kwargs)

        return wrapper

    return decorate
