import json
import os
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class HookSubprocessTests(unittest.TestCase):
    def run_hook(self, event, payload, env=None):
        process_env = os.environ.copy()
        process_env.update(env or {})
        return subprocess.run(
            [sys.executable, str(ROOT / "runtime" / "bro_hook.py"), event],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            cwd=ROOT,
            env=process_env,
        )

    def test_pre_tool_allowed_read_contract(self):
        result = self.run_hook(
            "pre-tool",
            {
                "session_id": "hook-read",
                "tool_name": "Read",
                "tool_input": {"file_path": "README.md"},
                "tool_use_id": "toolu_read",
            },
            {"BRO_MODE": "review"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('"permissionDecision": "deny"', result.stdout)

    def test_pre_tool_denies_git_global_option_push(self):
        result = self.run_hook(
            "pre-tool",
            {
                "session_id": "hook-push",
                "tool_name": "Bash",
                "tool_input": {"command": "git -C . push origin main"},
                "tool_use_id": "toolu_push",
            },
            {"BRO_MODE": "review"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('"permissionDecision": "deny"', result.stdout)

    def test_pre_tool_denies_unsigned_work_mode(self):
        result = self.run_hook(
            "pre-tool",
            {
                "session_id": "hook-work",
                "tool_name": "Write",
                "tool_input": {"file_path": "README.md"},
                "tool_use_id": "toolu_work",
            },
            {
                "BRO_MODE": "work",
                "BRO_ROLE": "specialist",
                "BRO_AGENT_ID": "agt-p01-r01",
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('"permissionDecision": "deny"', result.stdout)

    def test_post_tool_non_push_is_noop(self):
        result = self.run_hook(
            "post-tool",
            {
                "session_id": "hook-post",
                "tool_name": "Bash",
                "tool_input": {"command": "git status"},
                "tool_use_id": "toolu_status",
                "tool_response": {"stdout": "", "stderr": "", "interrupted": False},
            },
            {"BRO_MODE": "review"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_hook_settings_wire_success_and_failure_settlement(self):
        settings = json.loads(
            (ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        hooks = settings["hooks"]
        self.assertIn("PostToolUse", hooks)
        self.assertIn("PostToolUseFailure", hooks)
        self.assertIn(
            "post-tool",
            hooks["PostToolUse"][0]["hooks"][0]["command"],
        )
        self.assertIn(
            "post-tool-failure",
            hooks["PostToolUseFailure"][0]["hooks"][0]["command"],
        )

    def test_identity_hook_parses_stdin(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "runtime" / "bro_identity_hook.py")],
            input=json.dumps({"tool_name": "Read", "tool_input": {}}),
            text=True,
            capture_output=True,
            cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
