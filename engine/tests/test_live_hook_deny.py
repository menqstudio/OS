"""Live wiring proof for the enforcement wall (closes the audit's #1 finding).

The other hook tests spawn bro_hook.py via sys.executable, so they stay green even
if .claude/settings.json wires the hook to an interpreter that does not exist. This
test binds to the ACTUAL command in settings.json and fails if its interpreter does
not resolve on PATH -- i.e. it fails closed on dead wiring -- then proves the wired
command really denies an out-of-scope action AND NAMES WHY.

The "and names why" is not decoration. This file's negative used to accept any
`deny`, and O-1 showed the price: once `assert_no_bytecode_shadow` began refusing on
a `__pycache__` under a digest root, a `compileall` run before the live validation
made the wall refuse for the cache rather than for the scope, and this test reported
GREEN on a proof it never took. `engine/ci/live/run_live_turn.sh` states the rule in
`expect_blocked`: a refusal must name its cause, because a negative that passes on
any refusal certifies nothing about the check it names.
"""
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _path in (ROOT / "runtime", pathlib.Path(__file__).resolve().parent):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from _prerequisites import GIT_WORKTREE, requires  # noqa: E402
from bro_protected import bytecode_shadow_offenders, load_protected_manifest  # noqa: E402

# The refusal this negative exists to demonstrate.
SCOPE_CAUSE = "missing BRO_WORKSPACE_BINDING"
# The refusal that displaces it whenever the tree carries compiled bytecode under a
# digest root -- the state a plain `compileall`, `py_compile`, or any interpreter
# started without -B leaves behind.
SHADOW_CAUSE = "compiled bytecode under a digest root"


def wired_pretool_command() -> str:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    return settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def wired_pretool_argv() -> list[str]:
    """The first `||` alternative of the wired command, resolved to a real argv.

    The whole command, not just its interpreter token: `-B` is part of the wiring
    (O-1), and a probe that dropped it would mint bytecode under a digest root and
    thereby manufacture the shadow whose refusal masks the refusal under test.
    """
    tokens = shlex.split(wired_pretool_command().split("||")[0].strip(), posix=True)
    interpreter = shutil.which(tokens[0])
    return [interpreter] + [t.replace("$CLAUDE_PROJECT_DIR", str(ROOT)) for t in tokens[1:]]


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "runtime"))
from bro_protected import (WRITABLE_CONTROL_PLANE_ACKNOWLEDGEMENT,  # noqa: E402
                           WRITABLE_CONTROL_PLANE_ENV)

class LiveHookWiringTests(unittest.TestCase):
    def test_wired_interpreter_resolves_on_path(self):
        interpreter = wired_pretool_command().split()[0]
        self.assertIsNotNone(
            shutil.which(interpreter),
            f"settings.json wires the PreToolUse hook to '{interpreter}', which does not "
            "resolve on PATH; the live enforcement wall would never execute (dead wiring)",
        )

    def _run_wired_hook_out_of_scope(self) -> dict:
        argv = wired_pretool_argv()
        self.assertIsNotNone(argv[0], "the wired interpreter does not resolve on PATH")
        with tempfile.TemporaryDirectory(prefix="bro-live-wire-") as state_dir:
            env = {k: v for k, v in os.environ.items() if k != "BRO_WORKSPACE_BINDING"}
            env["BRO_MODE"] = "review"
            # The freeze gate is evaluated BEFORE the workspace gate, so stripping the
            # session-state directory too would make EVERY run refuse with
            # "freeze state gate RED: missing BRO_SESSION_STATE_DIR" and this negative
            # would never reach the scope check it is named after. Exactly one thing is
            # missing from this environment: the workspace binding.
            env["BRO_SESSION_STATE_DIR"] = str(pathlib.Path(state_dir).resolve())
            # Same trap, one gate along. A checkout is writable by whoever runs the tests
            # and cannot be otherwise, so the O-1 read-half gate refuses first and this
            # negative would observe "control plane is writable" instead of the scope cause
            # it exists to demonstrate — passing for the wrong reason, which is precisely
            # what this file was rewritten to stop. Acknowledged for this probe only.
            env[WRITABLE_CONTROL_PLANE_ENV] = WRITABLE_CONTROL_PLANE_ACKNOWLEDGEMENT
            result = subprocess.run(
                argv,
                input=json.dumps({
                    "session_id": "live-wire",
                    "tool_name": "Read",
                    "tool_input": {"file_path": "README.md"},
                    "tool_use_id": "toolu_wire",
                }),
                text=True, capture_output=True, cwd=str(ROOT), env=env,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"permissionDecision": "deny"', result.stdout)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        return payload["hookSpecificOutput"]

    @requires(GIT_WORKTREE)
    def test_wired_command_denies_out_of_scope(self):
        """The refusal must NAME the missing binding.

        Prerequisite, stated rather than assumed: the engine tree must sit inside a git
        worktree. The wall reads its tree identity through `git ls-files`, so on a tree
        copied without .git the very first gate raises and `fail_closed` answers "deny:
        hook failed closed: CalledProcessError ... 128". That is a THIRD refusal, ahead
        of both the scope cause and the shadow cause, and it is exactly the trap this
        file is built around -- a laxer negative would have gone green on it. Since no
        fixture can conjure a repository, the test declines to run rather than report on
        a proof it did not take; CI always has one, where `require` fails instead of
        skipping.

        One documented exception, and it is the whole point of this file: when the
        tree carries compiled bytecode under a digest root, `assert_no_bytecode_shadow`
        refuses FIRST, from the same gate, for a different reason. That refusal is
        accepted here only if it is TRUE (the offenders really exist) -- a bare `deny`
        never passes. The live-wiring GATE (tools/bro_live_validate.py) refuses the
        shadowed state outright, which is what stops CI certifying an enforcement
        proof it never took; this test stays runnable on a working tree, where a
        `__pycache__` is normal.
        """
        block = self._run_wired_hook_out_of_scope()
        self.assertEqual(block.get("permissionDecision"), "deny")
        reason = str(block.get("permissionDecisionReason") or "")
        if SHADOW_CAUSE in reason:
            self.assertTrue(
                bytecode_shadow_offenders(ROOT, load_protected_manifest(ROOT)),
                f"the wall refused for a bytecode shadow that does not exist: {reason}")
        else:
            self.assertIn(
                SCOPE_CAUSE, reason,
                "the wired hook refused, but not for the reason this negative exists "
                f"to prove (wanted '{SCOPE_CAUSE}'): {reason}")


if __name__ == "__main__":
    unittest.main()
