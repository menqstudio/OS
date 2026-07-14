import os
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_policy import State, authorize_tool, settle_release_tool


def bundle(agent_id="agent-1", role="specialist"):
    return SimpleNamespace(
        agent={"agent_id": agent_id},
        task={
            "scope": ["."],
            "prohibited_scope": [],
            "repository": {
                "full_name": "menqstudio/Bro",
                "branch": "bro-agent-os-v1",
            },
        },
        task_sha256="0" * 64,
    )


def release_payload():
    return {
        "schema": 2,
        "nonce": "abcdefghijklmnop",
        "repository": "menqstudio/Bro",
        "branch": "bro-agent-os-v1",
        "remote": "https://github.com/menqstudio/Bro.git",
        "expected_head_sha": "a" * 40,
    }


class PolicyTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("BRO_EXTERNAL_RELEASE_BOUNDARY", None)

    def test_review_denies_write(self):
        self.assertFalse(
            authorize_tool(
                State("review", "bro", "s"), "Write", {"file_path": "x"}
            )[0]
        )

    def test_review_allows_read(self):
        self.assertTrue(
            authorize_tool(
                State("review", "bro", "s"), "Read", {"file_path": "x"}
            )[0]
        )

    def test_review_git_allowlist_and_bypasses(self):
        self.assertTrue(
            authorize_tool(
                State("review", "bro", "s"),
                "Bash",
                {"command": "git status"},
            )[0]
        )
        blocked = (
            "git -C /repo push origin main",
            "git -C . commit -m x",
            "git -c http.extraheader=x push origin main",
            "git --git-dir=.git push origin main",
            "git -c alias.x=push x origin main",
            "git update-ref refs/heads/x HEAD",
            'powershell -Command "Set-Content x y"',
            "cmd /c del x",
            'bash -c "git push origin main"',
            'python -c "open(\\"x\\",\\"w\\").write(\\"bad\\")"',
            "echo hacked > x",
        )
        for command in blocked:
            self.assertFalse(
                authorize_tool(
                    State("review", "bro", "s"),
                    "Bash",
                    {"command": command},
                )[0],
                command,
            )

    def test_bro_cannot_mutate(self):
        ok, reason = authorize_tool(
            State("work", "bro", "s"), "Write", {"file_path": "x"}
        )
        self.assertFalse(ok)
        self.assertIn("delegate", reason)

    @patch("bro_policy._grant_bindings_ok", return_value=(True, "bound"))
    @patch("bro_policy.enforce_scope")
    @patch("bro_policy.load_mode_grant_from_env")
    @patch("bro_policy.load_contract_bundle_from_env")
    def test_specialist_mutation_requires_bundle_grant_scope_and_binding(
        self, load_bundle, load_mode, enforce, binding
    ):
        load_bundle.return_value = bundle()
        load_mode.return_value = {"mode": "work"}
        ok, _reason = authorize_tool(
            State("work", "specialist", "s", "agent-1"),
            "Write",
            {"file_path": "x"},
        )
        self.assertTrue(ok)
        enforce.assert_called_once()
        binding.assert_called_once()

    def test_work_denies_push_without_valid_gates(self):
        self.assertFalse(
            authorize_tool(
                State("work", "specialist", "s"),
                "Bash",
                {"command": "git push origin HEAD:bro-agent-os-v1"},
                "toolu_1",
            )[0]
        )

    @patch("bro_policy.load_contract_bundle_from_env")
    def test_release_denies_wrong_role(self, load_bundle):
        load_bundle.return_value = bundle()
        self.assertFalse(
            authorize_tool(
                State("release", "release-verifier", "s", "agent-1"),
                "Bash",
                {"command": "git push origin HEAD:bro-agent-os-v1"},
                "toolu_1",
            )[0]
        )

    @patch("bro_policy.reserve_nonce")
    @patch("bro_policy._release_ledger_dir", return_value=pathlib.Path("/external/ledger"))
    @patch("bro_policy.git", return_value="https://github.com/menqstudio/Bro.git")
    @patch("bro_policy._signed_release_payload")
    @patch("bro_policy._grant_bindings_ok", return_value=(True, "bound"))
    @patch("bro_policy.load_mode_grant_from_env")
    @patch("bro_policy.load_contract_bundle_from_env")
    def test_release_push_reserves_nonce_before_execution(
        self,
        load_bundle,
        load_mode,
        binding,
        load_release,
        git,
        ledger,
        reserve,
    ):
        load_bundle.return_value = bundle("push-1", "push-executor")
        load_mode.return_value = {"mode": "release"}
        load_release.return_value = release_payload()
        os.environ["BRO_EXTERNAL_RELEASE_BOUNDARY"] = "confirmed"
        command = "git push origin HEAD:bro-agent-os-v1"
        ok, reason = authorize_tool(
            State("release", "push-executor", "s", "push-1"),
            "Bash",
            {"command": command},
            "toolu_1",
        )
        self.assertTrue(ok, reason)
        reserve.assert_called_once_with(
            load_release.return_value,
            pathlib.Path("/external/ledger"),
            "toolu_1",
            command,
        )

    @patch("bro_policy.reserve_nonce")
    @patch("bro_policy._release_ledger_dir", return_value=pathlib.Path("/external/ledger"))
    @patch("bro_policy.git", return_value="https://github.com/menqstudio/Bro.git")
    @patch("bro_policy._signed_release_payload")
    @patch("bro_policy._grant_bindings_ok", return_value=(True, "bound"))
    @patch("bro_policy.load_mode_grant_from_env")
    @patch("bro_policy.load_contract_bundle_from_env")
    def test_release_push_requires_exact_refspec(
        self,
        load_bundle,
        load_mode,
        binding,
        load_release,
        git,
        ledger,
        reserve,
    ):
        load_bundle.return_value = bundle("push-1", "push-executor")
        load_mode.return_value = {"mode": "release"}
        load_release.return_value = release_payload()
        os.environ["BRO_EXTERNAL_RELEASE_BOUNDARY"] = "confirmed"
        ok, reason = authorize_tool(
            State("release", "push-executor", "s", "push-1"),
            "Bash",
            {"command": "git push origin bro-agent-os-v1"},
            "toolu_1",
        )
        self.assertFalse(ok)
        self.assertIn("binding mismatch", reason)
        reserve.assert_not_called()

    @patch("bro_policy.finalize_nonce")
    @patch("bro_policy._release_ledger_dir", return_value=pathlib.Path("/external/ledger"))
    @patch("bro_policy.git", return_value="https://github.com/menqstudio/Bro.git")
    @patch("bro_policy._signed_release_payload")
    @patch("bro_policy._grant_bindings_ok", return_value=(True, "bound"))
    @patch("bro_policy.load_contract_bundle_from_env")
    def test_post_success_finalizes_nonce(
        self, load_bundle, binding, load_release, git, ledger, finalize
    ):
        load_bundle.return_value = bundle("push-1", "push-executor")
        load_release.return_value = release_payload()
        command = "git push origin HEAD:bro-agent-os-v1"
        handled, green, message = settle_release_tool(
            State("release", "push-executor", "s", "push-1"),
            "Bash",
            {"command": command},
            "toolu_1",
            success=True,
        )
        self.assertTrue(handled)
        self.assertTrue(green, message)
        finalize.assert_called_once()

    @patch("bro_policy.release_nonce_reservation")
    @patch("bro_policy._remote_branch_head", return_value="b" * 40)
    @patch("bro_policy._release_ledger_dir", return_value=pathlib.Path("/external/ledger"))
    @patch("bro_policy.git", return_value="https://github.com/menqstudio/Bro.git")
    @patch("bro_policy._signed_release_payload")
    @patch("bro_policy._grant_bindings_ok", return_value=(True, "bound"))
    @patch("bro_policy.load_contract_bundle_from_env")
    def test_post_failure_releases_only_after_remote_proves_absence(
        self,
        load_bundle,
        binding,
        load_release,
        git,
        ledger,
        remote_head,
        release,
    ):
        load_bundle.return_value = bundle("push-1", "push-executor")
        load_release.return_value = release_payload()
        handled, green, message = settle_release_tool(
            State("release", "push-executor", "s", "push-1"),
            "Bash",
            {"command": "git push origin HEAD:bro-agent-os-v1"},
            "toolu_1",
            success=False,
            error="network error",
        )
        self.assertTrue(handled)
        self.assertTrue(green, message)
        release.assert_called_once()

    @patch("bro_policy.quarantine_nonce")
    @patch("bro_policy._remote_branch_head", side_effect=RuntimeError("offline"))
    @patch("bro_policy._release_ledger_dir", return_value=pathlib.Path("/external/ledger"))
    @patch("bro_policy.git", return_value="https://github.com/menqstudio/Bro.git")
    @patch("bro_policy._signed_release_payload")
    @patch("bro_policy._grant_bindings_ok", return_value=(True, "bound"))
    @patch("bro_policy.load_contract_bundle_from_env")
    def test_post_failure_quarantines_when_remote_is_unknown(
        self,
        load_bundle,
        binding,
        load_release,
        git,
        ledger,
        remote_head,
        quarantine,
    ):
        load_bundle.return_value = bundle("push-1", "push-executor")
        load_release.return_value = release_payload()
        handled, green, message = settle_release_tool(
            State("release", "push-executor", "s", "push-1"),
            "Bash",
            {"command": "git push origin HEAD:bro-agent-os-v1"},
            "toolu_1",
            success=False,
            error="network error",
        )
        self.assertTrue(handled)
        self.assertFalse(green)
        self.assertIn("quarantined", message)
        quarantine.assert_called_once()


if __name__ == "__main__":
    unittest.main()
