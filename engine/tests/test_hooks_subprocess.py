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

from bro_bind_workspace import build_binding, sign_binding
from broctl import build_registry, generate_key


class HookSubprocessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Every local action now requires an OPERATOR-SIGNED workspace binding
        (H-1), so the hook subprocess needs one it can actually verify. The
        subprocess anchors trust in the on-disk registry at
        ROOT/config/trusted-keys.json plus the external operator pin, and the
        committed dev registry's private key is (correctly) not in the repo —
        so this fixture stands in for the offline operator: it generates a test
        operator-root key, swaps in a registry signed by that key for the
        lifetime of the class (byte-exact restore via addClassCleanup), signs
        the binding with the SAME key, and hands the subprocess the matching
        pin through the CI env anchor (BRO_ENV=ci + BRO_OPERATOR_ROOT_PUBKEY).
        Ed25519 verification in the subprocess runs for real; nothing is
        stubbed. The binding is built AFTER the registry swap so its
        control-plane digest matches the live tree, and it is written to a
        temporary directory because the issuer refuses to place a binding
        inside the tree it authorises."""
        cls.state_dir = pathlib.Path(tempfile.mkdtemp(prefix="bro-hook-"))
        now = int(time.time())
        cls.operator = generate_key("operator-root", "test-operator-root", False)
        registry_path = ROOT / "config" / "trusted-keys.json"
        original_registry = registry_path.read_bytes()
        registry_path.write_text(
            json.dumps(build_registry([cls.operator], now, 100_000),
                       indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        cls.addClassCleanup(registry_path.write_bytes, original_registry)
        binding_path = cls.state_dir / "binding.json"
        binding = build_binding(ROOT, "bro-test", "test-operator", 3600, now)
        binding_path.write_text(json.dumps(sign_binding(binding, cls.operator)),
                                encoding="utf-8")
        cls.binding_env = {
            "BRO_WORKSPACE_BINDING": str(binding_path),
            "BRO_SESSION_STATE_DIR": str(cls.state_dir / "sessions"),
            # The raw env pin is honoured only under the CI flag; the test IS
            # the CI stand-in for the operator who pins the root out of band.
            "BRO_ENV": "ci",
            "BRO_OPERATOR_ROOT_PUBKEY": cls.operator["public_key"],
        }

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.state_dir, ignore_errors=True)

    def run_hook(self, event, payload, env=None):
        process_env = os.environ.copy()
        # An ambient production file pin would conflict with the test env pin.
        process_env.pop("BRO_OPERATOR_ROOT_PUBKEY_FILE", None)
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

    def test_pre_tool_denies_unsigned_binding(self):
        # Unsigned BY DESIGN (H-1): a raw, signature-less binding payload is
        # exactly the file an agent could write itself and point the env var at.
        # The wall must refuse it at the signature gate even though every field
        # is otherwise well-formed and in-date.
        unsigned_path = self.state_dir / "unsigned-binding.json"
        unsigned_path.write_text(
            json.dumps(build_binding(ROOT, "bro-unsigned", "test-operator",
                                     3600, int(time.time()))),
            encoding="utf-8")
        result = self.run_hook(
            "pre-tool",
            {
                "session_id": "hook-unsigned",
                "tool_name": "Read",
                "tool_input": {"file_path": "README.md"},
                "tool_use_id": "toolu_unsigned",
            },
            {"BRO_MODE": "review", "BRO_WORKSPACE_BINDING": str(unsigned_path)},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('"permissionDecision": "deny"', result.stdout)
        self.assertIn("not operator-signed", result.stdout)

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

    def test_pre_tool_denies_glob_absolute_pattern(self):
        # Glob's pattern is a real path target and must be workspace-contained.
        result = self.run_hook(
            "pre-tool",
            {"session_id": "hook-glob-abs", "tool_name": "Glob",
             "tool_input": {"pattern": "/etc/**"}, "tool_use_id": "toolu_glob_abs"},
            {"BRO_MODE": "review"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('"permissionDecision": "deny"', result.stdout)

    def test_pre_tool_denies_glob_traversal_pattern(self):
        result = self.run_hook(
            "pre-tool",
            {"session_id": "hook-glob-trav", "tool_name": "Glob",
             "tool_input": {"pattern": "../../**"}, "tool_use_id": "toolu_glob_trav"},
            {"BRO_MODE": "review"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('"permissionDecision": "deny"', result.stdout)

    def test_review_shell_deny_is_not_shadowable(self):
        # shadow is active (enabled + a usable external ledger), yet a review-mode
        # shell denial must remain a hard deny — shadow may not become a way to run
        # a mutation under a read-only mode.
        ledger = self.state_dir / "shadow-review.jsonl"
        result = self.run_hook(
            "pre-tool",
            {"session_id": "hook-shadow-review", "tool_name": "Bash",
             "tool_input": {"command": "find . -delete"}, "tool_use_id": "toolu_shadow_review"},
            {"BRO_MODE": "review", "BRO_ENFORCEMENT": "shadow", "BRO_SHADOW_LEDGER": str(ledger)},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('"permissionDecision": "deny"', result.stdout)
        self.assertFalse(ledger.exists())  # a hard deny is not recorded as a would-block

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

    def test_identity_hook_fails_closed_on_non_dict_profile(self):
        # A profile that is valid JSON but not an object (a list) parses fine, then
        # validate_agent_profile_identity does profile.get(...) -> AttributeError. The
        # hook must emit a deny and exit 0 (fail closed), never crash with a traceback
        # and a non-deny non-zero exit that lets the mutating tool through.
        import tempfile
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-idhook-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        profile = tmp / "profile.json"
        profile.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
        env = os.environ.copy()
        env.update({"BRO_MODE": "work", "BRO_AGENT_PROFILE": str(profile)})
        result = subprocess.run(
            [sys.executable, str(ROOT / "runtime" / "bro_identity_hook.py")],
            input=json.dumps({"tool_name": "Write", "tool_input": {"file_path": "x.py"}}),
            text=True, capture_output=True, cwd=ROOT, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"permissionDecision": "deny"', result.stdout)


if __name__ == "__main__":
    unittest.main()
