"""The enforcement wall: where it is wired (HookWiringTests) and what it actually
does when run (HookSubprocessTests).

WHAT THESE TESTS DO NOT PROVE
-----------------------------
HookSubprocessTests runs against a fixture checkout built by `_engine_git_root`,
and hands the hook `BRO_CONTROL_PLANE_WRITABLE_ACKNOWLEDGED`. That is a real
security acknowledgement, not a test knob: it waives O-1, the gate that refuses to
trust a control plane the running account can still write into. A temporary
checkout is writable by definition, so without the acknowledgement the O-1 refusal
arrives first and displaces every refusal asserted below -- each negative would
then be observing a gate it is not named after.

So the trade is explicit: with it set, everything below is evidence about the OTHER
gates and NO evidence whatsoever about O-1. Nothing here may be cited as showing
the control plane is unwritable or unshadowed; `tests/test_control_plane_writable.py`
owns that property and pops this variable so nothing can waive it there. Any test
added here that comes to claim something about control-plane writability or
bytecode shadowing must be run WITHOUT `hook_env()` -- it would otherwise waive the
very thing it claims. As of today no test in this module makes such a claim
(`test_review_shell_deny_is_not_shadowable` is about shadow ENFORCEMENT MODE, not
about a bytecode shadow).
"""
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
for _path in (ROOT / "tools", pathlib.Path(__file__).resolve().parent):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from _engine_git_root import engine_git_root, fixture_environment
from bro_bind_workspace import build_binding, sign_binding
from broctl import build_registry, generate_key


ENFORCEMENT_EVENTS = (
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "PostToolUseFailure", "SubagentStart", "SubagentStop", "Stop",
)


class HookWiringTests(unittest.TestCase):
    """The wall is only a wall where it is wired.

    These assertions read the REAL checkout's settings files and nothing else, so
    they address the module-level ROOT rather than the git-root fixture the
    subprocess drills below run against: the wiring of the tree someone actually
    runs is the subject here, and a fixture copy of it would prove nothing about
    the original. "The enforcement code is fine, nothing invokes it" is precisely
    the failure this class exists to catch.
    """

    def _settings(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def _commands(self, hooks_block):
        for group in hooks_block:
            for entry in group.get("hooks", []):
                yield str(entry.get("command", ""))

    def test_engine_settings_wire_every_enforcement_event(self):
        hooks = self._settings(ROOT / ".claude" / "settings.json")["hooks"]
        for event in ENFORCEMENT_EVENTS:
            self.assertIn(event, hooks, f"{event} is not wired; that gate never runs")
            self.assertTrue(any("bro_hook.py" in c for c in self._commands(hooks[event])),
                            f"{event} is wired to something other than the wall")

    def test_pre_tool_wires_both_the_wall_and_the_identity_hook(self):
        hooks = self._settings(ROOT / ".claude" / "settings.json")["hooks"]
        commands = list(self._commands(hooks["PreToolUse"]))
        self.assertTrue(any("bro_hook.py" in c and "pre-tool" in c for c in commands))
        self.assertTrue(any("bro_identity_hook.py" in c for c in commands))

    def test_hook_settings_wire_success_and_failure_settlement(self):
        hooks = self._settings(ROOT / ".claude" / "settings.json")["hooks"]
        self.assertIn("PostToolUse", hooks)
        self.assertIn("PostToolUseFailure", hooks)
        self.assertIn("post-tool", hooks["PostToolUse"][0]["hooks"][0]["command"])
        self.assertIn("post-tool-failure", hooks["PostToolUseFailure"][0]["hooks"][0]["command"])

    def test_every_hook_command_tries_a_windows_resolvable_interpreter_first(self):
        """H-3: a hook whose interpreter fails to launch is a NON-blocking error,
        so the tool call proceeds. On Windows `python3` is routinely absent, so a
        command that only tries `python3` is a wall that silently is not there."""
        hooks = self._settings(ROOT / ".claude" / "settings.json")["hooks"]
        for event, block in hooks.items():
            for command in self._commands(block):
                self.assertTrue(command.startswith("python "),
                                f"{event} hook does not try `python` first: {command}")
                self.assertIn("python3 ", command, f"{event} hook has no POSIX fallback")
                self.assertIn("py -3 ", command, f"{event} hook has no py-launcher fallback")

    def test_a_repository_root_that_wires_the_wall_must_wire_all_of_it(self):
        """Dormant on purpose, and the dormancy is the open finding.

        The engine hooks resolve their own root from __file__, so wiring them from
        the repository root is a path change and nothing more. What is NOT merely a
        path change is that the wall then runs: it denies every tool call until an
        operator-signed workspace binding exists AND engine/ is a git checkout root
        (bro_workspace.git_config_path raises here today), which the repository's
        CLAUDE.md defers as a standing owner decision. So the repository root
        deliberately does not wire it yet, and this guard only has an opinion once
        someone does — at which point a half-wired wall is worse than none.
        """
        path = ROOT.parent / ".claude" / "settings.json"
        if not path.is_file():
            self.skipTest("no repository-root settings file above engine/")
        hooks = self._settings(path).get("hooks", {})
        wired = {event: block for event, block in hooks.items()
                 if any("bro_hook.py" in c for c in self._commands(block))}
        if not wired:
            self.skipTest("repository root does not wire the enforcement wall (open finding)")
        for event in ENFORCEMENT_EVENTS:
            self.assertIn(event, wired, f"{event} missing from a root-wired wall")


class HookSubprocessTests(unittest.TestCase):
    """The wall, run for real, and asked WHY it refused.

    Addresses `cls.root` rather than the module-level ROOT. These drills spawn the
    real hook against a *repository*: `bro_workspace.git_config_path` reads
    `<root>/.git`, so the engine directory has to be a checkout root. It is not one
    in the OS monorepo, and this class used to answer that with

        @unittest.skipUnless(_ENGINE_IS_GIT_ROOT, "deferred in the OS monorepo")

    which meant every proof below skipped in every CI run. `.git` at the engine root
    is not a prerequisite a test has to be handed, though -- it is one a test can
    build, so `_engine_git_root` builds it (once per class, ~1s) and the drills run
    against that. Where engine/ already IS a checkout root the ambient tree is used
    and nothing is built. Same verdict either way.

    A second, quieter gain: the registry swap below now happens inside the fixture
    copy, so these tests no longer write into the checkout they are run from.
    """

    @classmethod
    def setUpClass(cls):
        """Every local action now requires an OPERATOR-SIGNED workspace binding
        (H-1), so the hook subprocess needs one it can actually verify. The
        subprocess anchors trust in the on-disk registry at
        <fixture root>/config/trusted-keys.json plus the external operator pin, and the
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
        cls.root = engine_git_root()
        # Two environment requirements the fixture tree imposes, each of which
        # otherwise displaces every refusal asserted below; `_engine_git_root`
        # documents what they prevent and, for the O-1 acknowledgement, what
        # accepting it subtracts from these proofs.
        cls.fixture_env = fixture_environment()
        cls.state_dir = pathlib.Path(tempfile.mkdtemp(prefix="bro-hook-"))
        now = int(time.time())
        cls.operator = generate_key("operator-root", "test-operator-root", False)
        registry_path = cls.root / "config" / "trusted-keys.json"
        original_registry = registry_path.read_bytes()
        registry_path.write_text(
            json.dumps(build_registry([cls.operator], now, 100_000),
                       indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        cls.addClassCleanup(registry_path.write_bytes, original_registry)
        binding_path = cls.state_dir / "binding.json"
        binding = build_binding(cls.root, "bro-test", "test-operator", 3600, now)
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

    def hook_argv(self, script, *arguments):
        """`-B`, always: the wired command in .claude/settings.json carries it (O-1),
        and a probe that dropped it would mint bytecode under a digest root and so
        manufacture the very shadow whose refusal masks the refusal under test."""
        return [sys.executable, "-B", str(self.root / "runtime" / script), *arguments]

    def hook_env(self, *, drop=(), **overrides):
        """The ambient environment, plus what the fixture tree requires.

        Every subprocess below goes through here so no drill can forget the fixture
        requirements and land on a displaced refusal instead of its own.

        `drop` is absolute: it removes the name from the ambient environment AND from
        the overrides, so a negative that exists to prove "the wall refuses when X is
        missing" cannot have X handed back to it by the shared binding environment.
        """
        process_env = {k: v for k, v in os.environ.items() if k not in drop}
        # An ambient production file pin would conflict with the test env pin.
        process_env.pop("BRO_OPERATOR_ROOT_PUBKEY_FILE", None)
        process_env.update(self.fixture_env)
        process_env.update({k: v for k, v in overrides.items() if k not in drop})
        return process_env

    def run_hook(self, event, payload, env=None):
        process_env = self.hook_env(**self.binding_env)
        process_env.update(env or {})
        return subprocess.run(
            self.hook_argv("bro_hook.py", event),
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            cwd=self.root,
            env=process_env,
        )

    def test_pre_tool_denies_without_workspace_binding(self):
        # Session state stays configured so this isolates the workspace gate.
        # Dropping it too would deny at the freeze gate, which cannot tell a
        # clean session from a frozen one without it and so refuses as well.
        process_env = self.hook_env(
            drop=("BRO_WORKSPACE_BINDING",), BRO_MODE="review",
            BRO_SESSION_STATE_DIR=self.binding_env["BRO_SESSION_STATE_DIR"])
        result = subprocess.run(
            self.hook_argv("bro_hook.py", "pre-tool"),
            input=json.dumps({
                "session_id": "hook-nobinding",
                "tool_name": "Read",
                "tool_input": {"file_path": "README.md"},
                "tool_use_id": "toolu_nobinding",
            }),
            text=True, capture_output=True, cwd=self.root, env=process_env,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('"permissionDecision": "deny"', result.stdout)
        self.assertIn("workspace scope gate RED", result.stdout)

    def test_pre_tool_denies_without_session_state_dir(self):
        # Without a state directory the freeze gate cannot prove the session is
        # not already frozen, so it must refuse rather than assume it is clean.
        process_env = self.hook_env(drop=("BRO_SESSION_STATE_DIR",),
                                    **{**self.binding_env, "BRO_MODE": "review"})
        result = subprocess.run(
            self.hook_argv("bro_hook.py", "pre-tool"),
            input=json.dumps({
                "session_id": "hook-nostate",
                "tool_name": "Read",
                "tool_input": {"file_path": "README.md"},
                "tool_use_id": "toolu_nostate",
            }),
            text=True, capture_output=True, cwd=self.root, env=process_env,
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
        # WHY, not merely THAT: a hook that refused because the deployment is broken
        # would satisfy a bare `deny` and certify nothing about containment.
        self.assertIn("workspace scope gate RED: path escapes workspace", result.stdout)

    def test_pre_tool_denies_unsigned_binding(self):
        # Unsigned BY DESIGN (H-1): a raw, signature-less binding payload is
        # exactly the file an agent could write itself and point the env var at.
        # The wall must refuse it at the signature gate even though every field
        # is otherwise well-formed and in-date.
        unsigned_path = self.state_dir / "unsigned-binding.json"
        unsigned_path.write_text(
            json.dumps(build_binding(self.root, "bro-unsigned", "test-operator",
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
        # The point is that `-C` did not hide the push from the classifier: the refusal
        # must come from the release-grant gate, i.e. the command WAS seen as a push.
        self.assertIn("Release Grant V3 RED", result.stdout)

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
        # Specifically the identity/authority gate: env vars asserting a role are not
        # an authority, and that is the refusal this test is named for.
        self.assertIn("canonical identity/authority gate RED", result.stdout)

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
        self.assertIn("workspace scope gate RED: path escapes workspace", result.stdout)

    def test_pre_tool_denies_glob_traversal_pattern(self):
        result = self.run_hook(
            "pre-tool",
            {"session_id": "hook-glob-trav", "tool_name": "Glob",
             "tool_input": {"pattern": "../../**"}, "tool_use_id": "toolu_glob_trav"},
            {"BRO_MODE": "review"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('"permissionDecision": "deny"', result.stdout)
        self.assertIn("workspace scope gate RED: path escapes workspace", result.stdout)

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
        # Named, because the named refusal is NOT the one the test title implies: this
        # command never reaches the review-mode rule — `find` with `-delete` is refused
        # earlier, by the capability kernel, as an unknown tool/action. The shadowability
        # property below still holds, and review-mode shell containment itself is covered
        # by test_review_containment.test_reproduced_shell_bypasses_are_denied.
        self.assertIn("tool capability gate RED", result.stdout)
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

    def test_identity_hook_parses_stdin(self):
        result = subprocess.run(
            self.hook_argv("bro_identity_hook.py"),
            input=json.dumps({"tool_name": "Read", "tool_input": {}}),
            text=True,
            capture_output=True,
            cwd=self.root,
            env=self.hook_env(),
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
        env = self.hook_env(BRO_MODE="work", BRO_AGENT_PROFILE=str(profile))
        result = subprocess.run(
            self.hook_argv("bro_identity_hook.py"),
            input=json.dumps({"tool_name": "Write", "tool_input": {"file_path": "x.py"}}),
            text=True, capture_output=True, cwd=self.root, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"permissionDecision": "deny"', result.stdout)
        # A crash-turned-deny and a deliberate deny are indistinguishable without this.
        self.assertIn("agent identity gate RED: agent profile must be a JSON object",
                      result.stdout)


if __name__ == "__main__":
    unittest.main()
