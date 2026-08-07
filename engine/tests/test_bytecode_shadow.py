"""O-1 — the bytecode-shadow gate, and proof that it is actually wired.

Background. `is_digest_member` deliberately excludes `__pycache__`, `.pyc` and
`.pyo` from the control-plane digest (a cold-cache checkout would otherwise flip
bound != current and RED-deny an authorized action). The price of that exclusion is
that a forged `.pyc` under a digest root is invisible to
`verify_control_plane_digest` while CPython will happily import it in place of the
`.py` source the digest verified. `assert_no_bytecode_shadow` is the compensating
control; until this file existed it had **zero callers and zero tests**, so the
compensating control compensated for nothing.

These tests are written so that each one dies if its specific check is removed:

  * `ThreatModelTests`            — the attack is real: a forged `.pyc` executes and
                                    the digest does not move. (No check of ours; this
                                    is the premise the rest of the file defends.)
  * `DigestChokepointTests`       — kills `assert_no_bytecode_shadow` inside
                                    `verify_control_plane_digest`.
  * `WallEntryPathTests`          — kills the call in `_bind_workspace`.
  * `SettlementPathTests`         — kills the call in `_settle_execution_tool`.
  * `HookInterpreterFlagTests`    — kills `-B` in `.claude/settings.json`.
  * `ImportOrderingTests`         — records exactly which half of the hole `-B`
                                    closes and which half stays open.
"""
from __future__ import annotations

import importlib.util  # noqa: F401  (MAGIC_NUMBER)
import json
import marshal
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import bro_control_plane
from bro_policy import State
from bro_protected import (
    ProtectedManifest,
    ProtectedScopeError,
    assert_no_bytecode_shadow,
    bytecode_shadow_offenders,
    compute_control_plane_digest,
    is_digest_member,
    verify_control_plane_digest,
)

MANIFEST = ProtectedManifest(
    protected_roots=("runtime/**", "config/**", "tools/**"),
    digest_roots=("runtime/**", "config/**", "tools/**"),
    unprotected_exceptions=(),
)

MANIFEST_JSON = {
    "schema": 1,
    "protected_roots": ["runtime/**", "config/**", "tools/**"],
    "digest_roots": ["runtime/**", "config/**", "tools/**"],
    "unprotected_exceptions": [],
}

SHADOW_MARKER = "compiled bytecode under a digest root"


class ShadowRootFixture(unittest.TestCase):
    """A miniature control plane on disk, so the gates run against real files."""

    def setUp(self):
        self.root = pathlib.Path(
            os.path.realpath(tempfile.mkdtemp(prefix="bro-shadow-o1-")))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.write("runtime/bro_policy.py", "POLICY = 1\n")
        self.write("runtime/bro_hook.py", "HOOK = 1\n")
        self.write("config/protected-control-plane.json",
                   json.dumps(MANIFEST_JSON, indent=2))
        self.write("docs/notes.md", "not a digest member\n")

    def write(self, relative: str, content: str) -> pathlib.Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def plant_cache_dir(self, relative: str = "runtime/__pycache__/bro_policy.pyc"):
        """The cheapest shadow: a bytecode file under a digest root."""
        return self.write(relative, "not really bytecode, but the gate cannot know")


def forge_pyc(source: pathlib.Path, forged_source: str) -> pathlib.Path:
    """Write a timestamp-valid `.pyc` for `source` whose CODE is `forged_source`.

    The header carries the real source's mtime and size, which is the whole trick:
    CPython validates the cache against those two numbers only, so the forged code
    object is accepted as an up-to-date compilation of a source it never came from.
    """
    stat = source.stat()
    code = compile(forged_source, str(source), "exec")
    # Built by hand rather than via importlib.util.cache_from_source: that helper
    # honours sys.pycache_prefix, which the test runner may have set, and would then
    # place the forgery somewhere the importing subprocess never looks.
    cache = (source.parent / "__pycache__"
             / f"{source.stem}.{sys.implementation.cache_tag}.pyc")
    cache.parent.mkdir(parents=True, exist_ok=True)
    header = (importlib.util.MAGIC_NUMBER
              + struct.pack("<I", 0)  # flags: 0 = timestamp-validated
              + struct.pack("<I", int(stat.st_mtime) & 0xFFFFFFFF)
              + struct.pack("<I", stat.st_size & 0xFFFFFFFF))
    cache.write_bytes(header + marshal.dumps(code))
    return cache


def clean_env(**overrides) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE")}
    env.update(overrides)
    return env


# --------------------------------------------------------------------------- #
# 1. The premise: the attack works and the digest cannot see it.
# --------------------------------------------------------------------------- #
class ThreatModelTests(ShadowRootFixture):
    def test_a_forged_pyc_executes_instead_of_the_source(self):
        source = self.write("runtime/probe_target.py", 'VALUE = "genuine"\n')
        forge_pyc(source, 'VALUE = "forged"\n')
        # -B is passed ON PURPOSE: it disables WRITING bytecode and does nothing
        # about READING it. If -B alone were the fix for O-1, this would print
        # "genuine".
        result = subprocess.run(
            [sys.executable, "-B", "-c",
             "import probe_target; print(probe_target.VALUE)"],
            cwd=str(self.root / "runtime"), capture_output=True, text=True,
            env=clean_env())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "forged",
                         "CPython did not import the planted cache; the rest of "
                         "this file's threat model would need revisiting")

    def test_the_forgery_does_not_move_the_control_plane_digest(self):
        source = self.write("runtime/probe_target.py", 'VALUE = "genuine"\n')
        before = compute_control_plane_digest(self.root, MANIFEST)
        forge_pyc(source, 'VALUE = "forged"\n')
        self.assertEqual(compute_control_plane_digest(self.root, MANIFEST), before,
                         "the digest moved; is_digest_member no longer excludes "
                         "bytecode and O-1's premise has changed")

    def test_bytecode_is_excluded_from_the_digest_but_seen_by_the_shadow_scan(self):
        self.assertFalse(is_digest_member(MANIFEST, "runtime/__pycache__/x.pyc"))
        self.assertFalse(is_digest_member(MANIFEST, "runtime/x.pyc"))
        self.plant_cache_dir()
        self.assertIn("runtime/__pycache__",
                      bytecode_shadow_offenders(self.root, MANIFEST))


class DetectionTests(ShadowRootFixture):
    def test_clean_tree_passes(self):
        assert_no_bytecode_shadow(self.root, MANIFEST)
        self.assertEqual(bytecode_shadow_offenders(self.root, MANIFEST), [])

    def test_pycache_directory_under_a_digest_root_is_an_offender(self):
        self.plant_cache_dir("tools/__pycache__/broctl.pyc")
        with self.assertRaises(ProtectedScopeError) as ctx:
            assert_no_bytecode_shadow(self.root, MANIFEST)
        self.assertIn(SHADOW_MARKER, str(ctx.exception))
        self.assertIn("tools/__pycache__", str(ctx.exception))

    def test_loose_pyc_and_pyo_beside_the_source_are_offenders(self):
        self.write("runtime/bro_policy.pyc", "x")
        self.write("runtime/bro_policy.pyo", "x")
        self.assertEqual(bytecode_shadow_offenders(self.root, MANIFEST),
                         ["runtime/bro_policy.pyc", "runtime/bro_policy.pyo"])

    def test_bytecode_outside_every_digest_root_is_not_an_offender(self):
        self.write("docs/__pycache__/whatever.pyc", "x")
        self.write("docs/loose.pyc", "x")
        assert_no_bytecode_shadow(self.root, MANIFEST)


# --------------------------------------------------------------------------- #
# 2. The chokepoint: nothing may trust a digest without the shadow check.
# --------------------------------------------------------------------------- #
class DigestChokepointTests(ShadowRootFixture):
    def test_matching_digest_is_still_refused_when_bytecode_is_present(self):
        """Delete `assert_no_bytecode_shadow` from `verify_control_plane_digest`
        and this goes red: the digest matches, so the function would return."""
        bound = compute_control_plane_digest(self.root, MANIFEST)
        self.assertEqual(
            verify_control_plane_digest(self.root, MANIFEST, bound), bound)
        self.plant_cache_dir()
        with self.assertRaises(ProtectedScopeError) as ctx:
            verify_control_plane_digest(self.root, MANIFEST, bound)
        self.assertIn(SHADOW_MARKER, str(ctx.exception))

    def test_the_shadow_check_precedes_the_bound_digest_shape_check(self):
        """A shadow must not be reportable-around by handing in a junk digest:
        whichever failure the caller induces, the tree is still refused."""
        self.plant_cache_dir()
        with self.assertRaises(ProtectedScopeError) as ctx:
            verify_control_plane_digest(self.root, MANIFEST, "not-a-digest")
        self.assertIn(SHADOW_MARKER, str(ctx.exception))


# --------------------------------------------------------------------------- #
# 3. The wall's own entry paths.
# --------------------------------------------------------------------------- #
class WallEntryPathTests(ShadowRootFixture):
    """`_bind_workspace` must refuse on its own authority, BEFORE it loads a
    binding — so the check cannot be skipped by an input that fails earlier.

    Delete the call from `_bind_workspace` and every test here goes red: with no
    `BRO_WORKSPACE_BINDING` in the environment, `load_workspace` raises
    `WorkspaceError` about a missing binding and `verify_control_plane_digest` is
    never reached, so the shadow is never reported.
    """

    def setUp(self):
        super().setUp()
        self.plant_cache_dir()
        self.classification = bro_control_plane.classify_request(
            "Write", {"file_path": "docs/notes.md"})

    def test_bind_workspace_refuses_before_any_binding_is_loaded(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("BRO_WORKSPACE_BINDING", "BRO_SESSION_STATE_DIR")}
        with patch.object(bro_control_plane, "ROOT", self.root), \
                patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ProtectedScopeError) as ctx:
                bro_control_plane._bind_workspace(self.classification)
        self.assertIn(SHADOW_MARKER, str(ctx.exception))

    def test_authorize_tool_denies_end_to_end(self):
        state = State(mode="work", role="specialist", session_id="sess-o1",
                      agent_id="agt-p01-r02")
        state_dir = self.root.parent / f"{self.root.name}-state"
        state_dir.mkdir(exist_ok=True)
        self.addCleanup(shutil.rmtree, state_dir, ignore_errors=True)
        env = {k: v for k, v in os.environ.items()
               if k not in ("BRO_WORKSPACE_BINDING", "BRO_AUDIT_LEDGER")}
        env["BRO_SESSION_STATE_DIR"] = str(state_dir)
        with patch.object(bro_control_plane, "ROOT", self.root), \
                patch.dict(os.environ, env, clear=True):
            allowed, reason = bro_control_plane.authorize_tool(
                state, "Write", {"file_path": "docs/notes.md"}, "toolu_o1")
        self.assertFalse(allowed)
        self.assertIn(SHADOW_MARKER, reason)


class SettlementPathTests(ShadowRootFixture):
    """PostToolUse settlement never reaches `_bind_workspace` and passes
    `control_plane_digest=None` to the lease, so it inherits no bytecode check from
    either. Delete the call from `_settle_execution_tool` and this goes red: the
    call still returns `(True, False, ...)`, but the message becomes
    `execution/recovery settlement RED: missing BRO_TASK_CONTRACT` — which is why
    the assertion below is on the message, not on the verdict tuple.
    """

    def test_settlement_of_a_governed_mutation_is_red_under_a_shadow(self):
        self.plant_cache_dir()
        state = State(mode="work", role="specialist", session_id="sess-o1",
                      agent_id="agt-p01-r02")
        env = {k: v for k, v in os.environ.items() if k != "BRO_AUDIT_LEDGER"}
        with patch.object(bro_control_plane, "ROOT", self.root), \
                patch.dict(os.environ, env, clear=True):
            settled, green, message = bro_control_plane.settle_execution_tool(
                state, "Write", {"file_path": "docs/notes.md"}, "toolu_o1",
                success=True)
        self.assertTrue(settled)
        self.assertFalse(green)
        self.assertIn(SHADOW_MARKER, message)

    def test_a_clean_tree_gets_past_the_shadow_gate(self):
        """Proves the gate above is discriminating, not a blanket RED."""
        state = State(mode="work", role="specialist", session_id="sess-o1",
                      agent_id="agt-p01-r02")
        env = {k: v for k, v in os.environ.items() if k != "BRO_AUDIT_LEDGER"}
        with patch.object(bro_control_plane, "ROOT", self.root), \
                patch.dict(os.environ, env, clear=True):
            settled, green, message = bro_control_plane.settle_execution_tool(
                state, "Write", {"file_path": "docs/notes.md"}, "toolu_o1",
                success=True)
        self.assertTrue(settled)
        self.assertFalse(green)
        self.assertNotIn(SHADOW_MARKER, message)


# --------------------------------------------------------------------------- #
# 4. The wired interpreters.
# --------------------------------------------------------------------------- #
def hook_commands() -> list[tuple[str, str]]:
    settings = json.loads(
        (ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    out = []
    for event, block in settings["hooks"].items():
        for group in block:
            for entry in group.get("hooks", []):
                out.append((event, str(entry.get("command", ""))))
    return out


class HookInterpreterFlagTests(unittest.TestCase):
    def test_every_wired_interpreter_alternative_passes_dash_B(self):
        """Every `||` alternative is a separate interpreter launch; one without -B
        is a session that mints bytecode under a digest root and then denies itself
        (or, worse, mints the shadow it is supposed to police)."""
        commands = hook_commands()
        self.assertTrue(commands, "no hook commands are wired at all")
        allowed = ("python -B ", "python3 -B ", "py -3 -B ")
        for event, command in commands:
            for alternative in command.split("||"):
                alternative = alternative.strip()
                self.assertTrue(
                    alternative.startswith(allowed),
                    f"{event}: hook interpreter runs without -B: {alternative!r}")

    def test_the_wired_interpreter_really_disables_bytecode_writing(self):
        """Live proof, not a string match: launch the actual wired token with the
        actual wired flags and ask the interpreter what it thinks."""
        for event, command in hook_commands():
            first = command.split("||")[0].strip().split()
            interpreter = shutil.which(first[0])
            self.assertIsNotNone(
                interpreter,
                f"{event}: settings.json wires '{first[0]}', which is not on PATH")
            flags = [token for token in first[1:] if token.startswith("-")]
            result = subprocess.run(
                [interpreter, *flags, "-c",
                 "import sys; print(sys.dont_write_bytecode)"],
                capture_output=True, text=True, env=clean_env())
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(), "True",
                f"{event}: the wired interpreter starts with bytecode writing "
                "ENABLED; every hook launch can mint a cache under a digest root")


class ImportOrderingTests(unittest.TestCase):
    """The honest record of what `-B` does and does not close.

    `bro_protected` sets `sys.dont_write_bytecode = True` at import. These two tests
    pin down that this happens far too late to be the control, and that only the
    interpreter flag closes the WRITE half. Neither closes the READ half — see
    `ThreatModelTests.test_a_forged_pyc_executes_instead_of_the_source`, which is
    run with `-B` precisely to demonstrate that.
    """

    def _import_the_wall(self, *flags) -> set[str]:
        prefix = pathlib.Path(tempfile.mkdtemp(prefix="bro-pycprefix-"))
        self.addCleanup(shutil.rmtree, prefix, ignore_errors=True)
        result = subprocess.run(
            [sys.executable, *flags, "-c",
             "import sys; sys.path.insert(0, 'runtime'); import bro_hook"],
            cwd=str(ROOT), capture_output=True, text=True,
            env=clean_env(PYTHONPYCACHEPREFIX=str(prefix)))
        self.assertEqual(result.returncode, 0, result.stderr)
        return {p.name.split(".")[0] for p in prefix.rglob("bro_*.pyc")}

    def test_without_dash_B_the_wall_mints_bytecode_for_its_own_modules(self):
        minted = self._import_the_wall()
        # Not an aspiration: this is what the interpreter actually does today.
        self.assertIn("bro_protected", minted,
                      "bro_protected's own cache is written by the loader BEFORE "
                      "the module body sets sys.dont_write_bytecode")
        for module in ("bro_audit_log", "bro_policy", "bro_control_plane"):
            self.assertIn(module, minted, f"{module} cached before the flag ran")

    def test_with_the_wired_dash_B_nothing_is_minted(self):
        self.assertEqual(self._import_the_wall("-B"), set())


if __name__ == "__main__":
    unittest.main()
