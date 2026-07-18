import hashlib
import hmac
import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_contracts import validate_registered_schemas
from bro_security import (
    SecurityError,
    analyze_command,
    canonical_bytes,
    consume_nonce,
    enforce_scope,
    finalize_nonce,
    quarantine_nonce,
    release_nonce_reservation,
    reserve_nonce,
    validate_exact_push,
    verify_signed_document,
)


class SecurityV2Tests(unittest.TestCase):
    def test_git_global_option_bypasses_are_detected(self):
        cases = [
            "git -C /repo push origin main",
            "git -C . commit -m x",
            "git -c http.extraheader=x push origin main",
            "git -c credential.helper=x push origin main",
            "git --git-dir=.git push origin main",
            "git --work-tree=. commit -am x",
            "git -C . -c user.name=x commit -m x",
            "git -c core.sshCommand=evil push",
            "git -c alias.x=push x origin main",
            "git update-ref refs/heads/x HEAD",
            "git stash",
            "git worktree add ../x",
            "git config user.name x",
            "git remote set-url origin evil",
        ]
        for command in cases:
            info = analyze_command(command)[0]
            self.assertTrue(info.mutating, command)
        self.assertTrue(
            analyze_command("git -c alias.x=push x origin main")[0].dangerous_config
        )

    def test_segments_quotes_windows_and_mixed_case(self):
        infos = analyze_command(
            'git status && C:\\Git\\bin\\GIT.EXE -C . commit -m "x y"; '
            "git log | git show"
        )
        self.assertTrue(any(info.mutating for info in infos))
        self.assertEqual(sum(info.executable == "git" for info in infos), 4)

    def test_wrappers_are_fail_closed(self):
        cases = [
            'powershell -Command "Set-Content secret.txt hacked"',
            'pwsh -c "Remove-Item x"',
            "cmd /c del x",
            'bash -c "git push origin main"',
            'sh -c "rm x"',
            'python -c "open(\\"x\\",\\"w\\").write(\\"bad\\")"',
        ]
        for command in cases:
            self.assertTrue(analyze_command(command)[0].mutating, command)

    def test_redirection_and_substitution_are_denied(self):
        for command in (
            "echo hacked > file.txt",
            "cat x < y",
            "echo `whoami`",
            "cat $(rm -rf x)",          # unquoted command substitution
            'cat "$(rm -rf x)"',        # substitution inside double quotes still runs
            'echo "`whoami`"',          # backtick inside double quotes still runs
            "echo $((1+1))",            # arithmetic expansion shares the $( opener
        ):
            with self.assertRaises(SecurityError, msg=command):
                analyze_command(command)

    def test_single_quoted_substitution_is_literal(self):
        # Single quotes suppress substitution in the shell, so '$(...)' and
        # backticks are literal text, not a bypass, and must not be rejected.
        infos = analyze_command("echo '$(rm -rf x)'")
        self.assertEqual(infos[0].executable, "echo")

    def test_unknown_executable_is_not_read_only(self):
        info = analyze_command("custom-tool --do-anything")[0]
        self.assertTrue(info.mutating)
        self.assertFalse(info.recognized_read_only)

    def test_exact_push_shape(self):
        validate_exact_push(
            "git push origin HEAD:bro-agent-os-v1", "bro-agent-os-v1"
        )
        blocked = [
            "git push origin bro-agent-os-v1",
            "git push upstream HEAD:bro-agent-os-v1",
            "git push --force origin HEAD:bro-agent-os-v1",
            "git -C . push origin HEAD:bro-agent-os-v1",
            "git push origin HEAD:other",
            "git status && git push origin HEAD:bro-agent-os-v1",
        ]
        for command in blocked:
            with self.assertRaises(SecurityError, msg=command):
                validate_exact_push(command, "bro-agent-os-v1")

    def test_scope_enforcement(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            (root / "ok").mkdir()
            enforce_scope(root, ["ok/a.txt"], ["ok"], ["ok/no"])
            for bad in ("../x", "/tmp/x", "C:/Windows/x"):
                with self.assertRaises(SecurityError):
                    enforce_scope(root, [bad], ["ok"], [])
            with self.assertRaises(SecurityError):
                enforce_scope(root, ["ok/no/x"], ["ok"], ["ok/no"])

    def test_signature_and_tamper(self):
        key = "k" * 32
        os.environ["TEST_KEY"] = key
        payload = {"a": 1}
        signature = hmac.new(
            key.encode(), canonical_bytes(payload), hashlib.sha256
        ).hexdigest()
        document = {"payload": payload, "signature": signature}
        self.assertEqual(verify_signed_document(document, "TEST_KEY"), payload)
        document["payload"]["a"] = 2
        with self.assertRaises(SecurityError):
            verify_signed_document(document, "TEST_KEY")

    def test_atomic_nonce_replay_legacy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = {"nonce": "abcdefghijklmnop"}
            consume_nonce(payload, pathlib.Path(temp_dir))
            with self.assertRaises(SecurityError):
                consume_nonce(payload, pathlib.Path(temp_dir))

    def test_nonce_reserve_then_finalize(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = pathlib.Path(temp_dir)
            payload = {
                "nonce": "abcdefghijklmnop",
                "expected_head_sha": "a" * 40,
                "branch": "main",
            }
            command = "git push origin HEAD:main"
            reserve_nonce(payload, ledger, "toolu_1", command)
            self.assertEqual(len(list(ledger.glob("*.reserved"))), 1)
            finalize_nonce(payload, ledger, "toolu_1", command)
            self.assertEqual(len(list(ledger.glob("*.reserved"))), 0)
            self.assertEqual(len(list(ledger.glob("*.used"))), 1)
            with self.assertRaises(SecurityError):
                reserve_nonce(payload, ledger, "toolu_2", command)

    def test_failed_push_can_release_only_matching_reservation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = pathlib.Path(temp_dir)
            payload = {
                "nonce": "abcdefghijklmnop",
                "expected_head_sha": "a" * 40,
                "branch": "main",
            }
            command = "git push origin HEAD:main"
            reserve_nonce(payload, ledger, "toolu_1", command)
            with self.assertRaises(SecurityError):
                release_nonce_reservation(payload, ledger, "toolu_wrong", command)
            release_nonce_reservation(payload, ledger, "toolu_1", command)
            self.assertEqual(list(ledger.glob("*.reserved")), [])
            reserve_nonce(payload, ledger, "toolu_2", command)

    def test_ambiguous_push_quarantines_nonce(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = pathlib.Path(temp_dir)
            payload = {
                "nonce": "abcdefghijklmnop",
                "expected_head_sha": "a" * 40,
                "branch": "main",
            }
            command = "git push origin HEAD:main"
            reserve_nonce(payload, ledger, "toolu_1", command)
            quarantine_nonce(payload, ledger, "toolu_1", command, "network unknown")
            self.assertEqual(len(list(ledger.glob("*.ambiguous"))), 1)
            with self.assertRaises(SecurityError):
                reserve_nonce(payload, ledger, "toolu_2", command)

    def test_registered_schemas_compile(self):
        self.assertGreaterEqual(validate_registered_schemas(ROOT), 10)


if __name__ == "__main__":
    unittest.main()
