"""Test helper: an engine tree that IS its own git worktree root.

The two most load-bearing modules in this suite address a *repository*, not merely a
directory: `test_hooks_subprocess` drives the real enforcement wall as a subprocess
and asserts WHY it refuses, and `test_full_execution_transaction_e2e` drives the
mutation gate end to end. Both reach `bro_workspace.git_config_path(root)`, which
reads `<root>/.git` directly (parsed, not shelled out to) and raises "is not a git
checkout" when it is absent. In the OS monorepo the git top-level is OS/ and
`engine/` is a subdirectory, so `engine/.git` does not exist.

For that reason both modules carried::

    _ENGINE_IS_GIT_ROOT = (ENGINE_ROOT / ".git").exists()

    @unittest.skipUnless(_ENGINE_IS_GIT_ROOT, "deferred in the OS monorepo")

which skipped 22 tests in every CI run -- including every live subprocess proof the
wall has. A skip is a hole unless someone counts them (`_prerequisites`), and this
one had been counted as "cannot be run here". It could be: unlike `apps/` or
`bridge/`, `.git` at the engine root is not something outside the engine tree that a
test has to be handed. It is a property a test can MANUFACTURE -- copy the tree,
`git init` it, commit it, give it a remote -- and a test that can manufacture its
precondition has no business skipping on it.

So this module builds that tree once per process and hands back its root. When
`engine/` already IS a checkout root (a standalone engine checkout) nothing is built
and the ambient tree is used unchanged. Same verdict either way, which is the rule
`_prerequisites` states; the difference is only whether the fixture had to make the
repository or found one.

TWO THINGS THE FIXTURE MUST HAND THE TESTS, AND WHY
---------------------------------------------------
Both are about DISPLACED REFUSALS, which is the failure mode this repository has
spent its life removing: a negative test asks the wall to refuse for cause X, some
earlier gate refuses for unrelated cause Y, and a test that only asserted "deny"
goes green having proven nothing. The tests here assert the cause by name, so a
displaced refusal shows up as "expected reason not found" rather than as a false
green -- but it still costs the proof. The fixture therefore removes both known
displacers from the environment it hands out, rather than letting each test
rediscover them:

* ``PYTHONDONTWRITEBYTECODE`` (with ``-B`` on the argv, belt and braces). Without
  it the first hook subprocess writes `__pycache__` into the fixture, and every
  subsequent run refuses at `assert_no_bytecode_shadow` -- "compiled bytecode under
  a digest root" -- ahead of the gate under test. Observed: it displaces EVERY
  negative in `test_hooks_subprocess`.
* ``BRO_CONTROL_PLANE_WRITABLE_ACKNOWLEDGED`` -- see :data:`O1_ACKNOWLEDGEMENT`
  below, which is not a test knob and is documented as what it is.

Not a test module (no ``test_`` prefix), so unittest discovery ignores it.
"""
from __future__ import annotations

import atexit
import functools
import contextlib
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

for _path in (pathlib.Path(__file__).resolve().parents[1] / "runtime",
              pathlib.Path(__file__).resolve().parent):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from _prerequisites import Prerequisite, require  # noqa: E402
from bro_protected import (WRITABLE_CONTROL_PLANE_ACKNOWLEDGEMENT,  # noqa: E402
                           WRITABLE_CONTROL_PLANE_ENV)

ENGINE_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Remote for the fixture repository when the tree above it does not name one.
#: `verify_repository_binding` compares the binding's remote against `.git/config`,
#: and the binding is built FROM that config, so any URL is self-consistent -- but
#: inheriting the real one keeps the fixture a faithful copy rather than a lookalike.
FALLBACK_REMOTE = "https://github.com/menqstudio/OS.git"


def _git_available() -> bool:
    try:
        probe = subprocess.run(["git", "--version"], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


GIT_BINARY = Prerequisite(
    "git binary",
    _git_available,
    "`git` does not run here, so the fixture cannot build the checkout root the "
    "enforcement wall reads its repository binding from (engine/ is a subdirectory "
    "in the monorepo, so there is no ambient one to use instead)",
)


def _inherited_remote() -> str:
    """The remote URL of whatever checkout contains the engine tree, if any.

    Read straight out of `.git/config` rather than asked of `git`, because the engine
    tree is routinely shared with other work and this helper must not run a git
    command against it -- reading a file cannot disturb an index or a worktree.
    """
    for candidate in (ENGINE_ROOT, *ENGINE_ROOT.parents):
        config = candidate / ".git" / "config"
        if not config.is_file():
            continue
        try:
            text = config.read_text(encoding="utf-8")
        except OSError:
            break
        match = re.search(r"^\s*url\s*=\s*(.+?)\s*$", text, re.MULTILINE)
        if match:
            return match.group(1)
        break
    return FALLBACK_REMOTE


def _git(root: pathlib.Path, *arguments: str) -> None:
    """Run git inside the FIXTURE and refuse to continue if it did not work.

    Checked rather than best-effort on purpose: a fixture that silently failed to
    initialise would hand the tests a directory without `.git`, and they would then
    fail at the workspace gate for a reason that looks like a defect in the wall.
    A build that cannot build says so here, once, in its own words.
    """
    result = subprocess.run(["git", *arguments], cwd=str(root),
                            capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"the engine git-root fixture could not run `git {' '.join(arguments)}` in "
            f"{root} (exit {result.returncode}): {result.stdout}{result.stderr}")


def _discard(workspace: pathlib.Path) -> None:
    """Delete the fixture at exit, including the read-only files git leaves behind.

    Git marks loose objects read-only, which on Windows makes `os.unlink` fail; a plain
    `rmtree(ignore_errors=True)` would leave a copy of the engine tree in the temp
    directory after every suite run. Clear the bit and retry rather than accumulate.
    """
    def _retry(function, path, _excinfo):
        try:
            os.chmod(path, 0o700)
            function(path)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(workspace, onexc=_retry)
    else:
        shutil.rmtree(workspace, onerror=_retry)


def _build_git_root() -> pathlib.Path:
    """Copy the engine tree into a temporary directory and make it a checkout root."""
    require(GIT_BINARY)
    workspace = pathlib.Path(tempfile.mkdtemp(prefix="bro-engine-gitroot-"))
    atexit.register(_discard, workspace)
    root = workspace / "engine"
    # `__pycache__` is excluded, and that exclusion is load-bearing rather than tidy:
    # the control-plane digest deliberately skips `__pycache__/*.pyc`, so
    # `assert_no_bytecode_shadow` refuses outright on any tree that carries them.
    # Copied in, that refusal DISPLACES every negative in both modules -- each test
    # then reports that its expected cause was "not found", and a laxer test that
    # asserted only `deny` would have gone green on a refusal it never earned.
    shutil.copytree(ENGINE_ROOT, root, symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
    _git(root, "init", "-q", ".")
    _git(root, "add", "-A")
    # Identity and signing are supplied per-command: the fixture must build the same
    # way on a runner with no `user.email` configured and on a developer box whose
    # global config signs every commit (a signing prompt would hang the suite).
    _git(root, "-c", "user.email=fixture@bro.invalid", "-c", "user.name=bro-test-fixture",
         "-c", "commit.gpgsign=false", "commit", "-q", "-m", "engine git-root test fixture")
    # Without a remote, `bro_bind_workspace.detect_remote` raises "repository has no
    # remote url" and no binding can be built at all.
    _git(root, "remote", "add", "origin", _inherited_remote())
    return root


@functools.lru_cache(maxsize=1)
def engine_git_root() -> pathlib.Path:
    """The engine tree to address, as a git worktree root. Built at most once.

    Costs about a second, so callers take it in `setUpClass`; the cache makes a second
    caller free, and both modules that use it share one fixture per process.
    """
    if (ENGINE_ROOT / ".git").exists():
        return ENGINE_ROOT          # a standalone engine checkout: build nothing
    return _build_git_root()


#: The O-1 acknowledgement, and what setting it COSTS these tests.
#:
#: Not a test knob. `assert_control_plane_not_writable` refuses to trust a control plane the
#: running account can still write into, because a `.pyc` planted there is imported by CPython
#: before any check in the process exists to notice it; the acknowledgement is the phrase an
#: operator types to record that a deployment has weighed that residual risk and accepted it.
#: A temporary checkout is writable by definition, so without it the O-1 refusal arrives FIRST
#: and displaces every other negative in both modules -- the same false-green shape as the
#: bytecode shadow above, and the same one this repository has been removing.
#:
#: What that costs, stated so no reader of these tests can miss it: with the acknowledgement set,
#: these tests assert that the OTHER gates refuse correctly and say NOTHING WHATSOEVER about O-1.
#: They are not evidence that the control plane is unwritable, and they must never be cited as
#: such. O-1 itself is proven by `tests/test_control_plane_writable.py`, which owns the property,
#: builds trees whose writability it sets itself, and pops this variable in `setUp` so that
#: nothing -- including this fixture -- can waive the gate it exists to exercise. Any test in
#: these two modules that ever comes to assert something about the control plane being unwritable
#: or unshadowed must NOT be handed this environment; it would waive the very thing it claims.
O1_ACKNOWLEDGEMENT = {WRITABLE_CONTROL_PLANE_ENV: WRITABLE_CONTROL_PLANE_ACKNOWLEDGEMENT}


def fixture_environment() -> dict[str, str]:
    """The environment variables the fixture tree requires, and nothing else.

    Handed to a subprocess (or merged into `os.environ` under `patch.dict` for the
    in-process drills) by the caller. Deliberately returned rather than exported: an
    acknowledgement that leaked into the ambient environment would waive the O-1 gate
    for every other test in the process, including the ones that exist to prove it.
    """
    return {
        # Stops the hook subprocess minting `__pycache__` inside the fixture. The first
        # run would succeed and every run after it would refuse at the bytecode-shadow
        # gate instead of the gate under test -- a displaced refusal, i.e. a negative
        # that passes for the wrong reason. Callers also pass `-B` on the argv, which is
        # how the wall itself is wired in `.claude/settings.json`.
        "PYTHONDONTWRITEBYTECODE": "1",
        # A temp checkout is writable by definition, so the O-1 read-half gate refuses
        # before anything else runs. Acknowledged for this fixture only; see
        # O1_ACKNOWLEDGEMENT above for exactly what that subtracts from these proofs.
        **O1_ACKNOWLEDGEMENT,
    }


#: Module attributes that anchor a runtime module to the engine tree it was imported from.
_ANCHOR_ATTRIBUTES = ("ROOT", "_ENGINE_ROOT")


@contextlib.contextmanager
def anchored_to(root: pathlib.Path):
    """Point the already-imported runtime modules at `root` for the duration.

    The subprocess drills get this for free: a child process launched from the fixture
    resolves every `ROOT = pathlib.Path(__file__).resolve().parents[1]` to the fixture
    on its own. The in-process drills cannot -- `bro_control_plane` and friends are
    imported once per process and are shared with every other test module, so
    re-importing them from the fixture would hand the REST of the suite a second copy
    of the runtime. Rebinding the constant for the length of one test is the smaller
    change and the reversible one.

    Swept rather than enumerated, because an enumeration that missed a module would
    leave that module verifying the real engine tree while the rest verified the
    fixture, and integrity proven on one tree while scope is checked on another is the
    exact confusion `_bind_workspace`'s M-7 check exists to refuse.
    """
    anchored = ENGINE_ROOT / "runtime", ENGINE_ROOT / "tools"
    restore: list[tuple[object, str, pathlib.Path]] = []
    for module in list(sys.modules.values()):
        origin = getattr(module, "__file__", None)
        if not origin or pathlib.Path(origin).resolve().parent not in anchored:
            continue
        for attribute in _ANCHOR_ATTRIBUTES:
            value = getattr(module, attribute, None)
            if isinstance(value, pathlib.Path) and value == ENGINE_ROOT:
                restore.append((module, attribute, value))
                setattr(module, attribute, root)
    try:
        yield
    finally:
        for module, attribute, value in restore:
            setattr(module, attribute, value)


def acknowledged_environment() -> dict[str, str]:
    """`fixture_environment` minus the bits only a subprocess can use.

    In-process there is no interpreter to configure: nothing imports from the fixture
    tree inside this process, so no `__pycache__` can appear there. What remains is the
    O-1 acknowledgement, which the in-process gates read from `os.environ` exactly as
    the subprocess ones do.
    """
    return dict(O1_ACKNOWLEDGEMENT)
