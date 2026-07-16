import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from bro_bind_workspace import build_binding


class HookSubprocessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Every local action now requires a workspace binding, so the hook needs
        one issued against this checkout. It is written to a temporary directory
        because the issuer refuses to place a binding inside the tree it authorises."""
        cls.state_dir = pathlib.Path(tempfile.mkdtemp(prefix="bro-hook-"))
        binding_path = cls.state_dir / "binding.json"
        binding = build_binding(ROOT, "bro-test", "test-operator", 3600, int(time.time()))
        binding_path.write_text(json.dumps(binding), encoding="utf-8")
        cls.binding_env = {
            "BRO_WORKSPACE_BINDING": str(binding_path),
            "BRO_SESSION_STATE_DIR": str(cls.state_dir / "sessions"),
        }

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.state_dir, ignore_errors=True)

    def run_hook(self, event, payload, env=None):
        process_env = os.environ.copy()
        process_env.update(self.binding_env)
        process_env.update(env or {})
        return subprocess.run(
            [sys.executable, str(ROOT / "runtime" / "bro_hook.py"), event],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            cwd=ROOT,
            env=process_env,
        )

    def test_pre_tool_denies_without_workspace_binding(self):
        # Session state stays configured so this isolates the workspace gate.
        # Dropping it too would deny at the freeze gate, which cannot tell a
        # clean session from a frozen one without it and so refuses as well.
        process_env = {k: v for k, v in os.environ.items()
                       if k != "BRO_WORKSPACE_BINDING"}
        process_env["BRO_MODE"] = "review"
        process_env["BRO_SESSION_STATE_DIR"] = self.binding_env["BRO_SESSION_STATE_DIR"]
        result = subprocess.run(
            [sys.executable, str(ROOT / "runtime" / "bro_hook.py"), "pre-tool"],
            input=json.dumps({
                "session_id": "hook-nobinding",
                "tool_name": "Read",
                "tool_input": {"file_path": "README.md"},
                "tool_use_id": "toolu_nobinding",
            }),
            text=True, capture_output=True, cwd=ROOT, env=process_env,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('"permissionDecision": "deny"', result.stdout)
        self.assertIn("workspace scope gate RED", result.stdout)

    def test_pre_tool_denies_without_session_state_dir(self):
        # Without a state directory the freeze gate cannot prove the session is
        # not already frozen, so it must refuse rather than assume it is clean.
        process_env = {k: v for k, v in os.environ.items()
                       if k != "BRO_SESSION_STATE_DIR"}
        process_env.update(self.binding_env)
        del process_env["BRO_SESSION_STATE_DIR"]
        process_env["BRO_MODE"] = "review"
        result = subprocess.run(
            [sys.executable, str(ROOT / "runtime" / "bro_hook.py"), "pre-tool"],
            input=json.dumps({
                "session_id": "hook-nostate",
                "tool_name": "Read",
                "tool_input": {"file_path": "README.md"},
                "tool_use_id": "toolu_nostate",
            }),
            text=True, capture_output=True, cwd=ROOT, env=process_env,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('"permissionDecision": "deny"', result.stdout)
        self.assertIn("freeze state gate RED", result.stdout)

    def test_pre_tool_denies_read_outside_workspace(self):
        result = self.run_hook(
            "pre-tool",
            {
                "session_id": "hook-escape",
                "tool_name": "Read",
                "tool_input": {"file_path": str(pathlib.Path.home() / ".ssh" / "id_rsa")},
                "tool_use_id": "toolu_escape",
            },
            {"BRO_MODE": "review"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('"permissionDecision": "deny"', result.stdout)

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
