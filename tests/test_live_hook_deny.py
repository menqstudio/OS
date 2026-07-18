"""Live wiring proof for the enforcement wall (closes the audit's #1 finding).

The other hook tests spawn bro_hook.py via sys.executable, so they stay green even
if .claude/settings.json wires the hook to an interpreter that does not exist. This
test binds to the ACTUAL interpreter token in settings.json and fails if it does not
resolve on PATH -- i.e. it fails closed on dead wiring -- then proves the wired
command really denies an out-of-scope action.
"""
import json
import os
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def wired_pretool_command() -> str:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    return settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


class LiveHookWiringTests(unittest.TestCase):
    def test_wired_interpreter_resolves_on_path(self):
        interpreter = wired_pretool_command().split()[0]
        self.assertIsNotNone(
            shutil.which(interpreter),
            f"settings.json wires the PreToolUse hook to '{interpreter}', which does not "
            "resolve on PATH; the live enforcement wall would never execute (dead wiring)",
        )

    def test_wired_command_denies_out_of_scope(self):
        interpreter = shutil.which(wired_pretool_command().split()[0])
        self.assertIsNotNone(interpreter)
        env = {k: v for k, v in os.environ.items()
               if k not in ("BRO_SESSION_STATE_DIR", "BRO_WORKSPACE_BINDING")}
        env["BRO_MODE"] = "review"
        result = subprocess.run(
            [interpreter, str(ROOT / "runtime" / "bro_hook.py"), "pre-tool"],
            input=json.dumps({
                "session_id": "live-wire",
                "tool_name": "Read",
                "tool_input": {"file_path": "README.md"},
                "tool_use_id": "toolu_wire",
            }),
            text=True, capture_output=True, cwd=str(ROOT), env=env,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('"permissionDecision": "deny"', result.stdout)


if __name__ == "__main__":
    unittest.main()
