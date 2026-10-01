import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_secrets import contains_secret, redact, redact_mapping, scan


class DetectionTests(unittest.TestCase):
    def test_detects_known_secret_formats(self):
        samples = [
            "AKIAIOSFODNN7EXAMPLE",
            "sk-ant-api03-abcdefghijklmnopqrstuvwxyz",
            "ghp_1234567890abcdefghij1234ABCD",
            "-----BEGIN RSA PRIVATE KEY-----",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5Nqabc",
            "Bearer abcdefghijklmnopqrstuvwxyz0123",
        ]
        for s in samples:
            self.assertTrue(contains_secret(s), s)

    def test_keyed_secret_is_detected(self):
        self.assertTrue(contains_secret("password: hunter2secretvalue"))
        self.assertTrue(contains_secret("api_key=ABCDEF123456ghijkl"))


class RedactionTests(unittest.TestCase):
    def test_redacts_and_types_the_marker(self):
        out = redact("leaked sk-ant-api03-abcdefghijklmnopqrstuvwxyz here")
        self.assertIn("[REDACTED:anthropic-key]", out)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", out)

    def test_keyed_secret_keeps_key_hides_value(self):
        out = redact("password: hunter2secretvalue")
        self.assertIn("password", out)
        self.assertIn("[REDACTED:keyed-secret]", out)
        self.assertNotIn("hunter2secretvalue", out)

    def test_keyed_secret_with_unclosed_quote_is_redacted(self):
        # A truncated log/stderr tail can open a quote it never closes; the value must
        # still be hidden (the old backreference-closed pattern leaked it verbatim).
        text = 'password="hunter2sekretvalue'
        self.assertTrue(contains_secret(text))
        out = redact(text)
        self.assertNotIn("hunter2sekretvalue", out)
        self.assertIn("[REDACTED:keyed-secret]", out)

    def test_keyed_secret_under_a_quoted_or_prefixed_key_is_redacted(self):
        # The two commonest shapes in a stderr tail: a serialised JSON object, whose key
        # carries a closing quote between the name and the colon, and a prefixed
        # environment variable, whose name has no word boundary before `PASSWORD`. The
        # old pattern needed `\b<name>` directly followed by `[=:]` and left all of
        # these verbatim.
        for text, value in (
            ('{"password": "hunter2sekret"}', "hunter2sekret"),
            ("{'api_key': 'ABCDEF123456ghijkl'}", "ABCDEF123456ghijkl"),
            ("DB_PASSWORD=hunter2sekret", "hunter2sekret"),
            ("export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIK7MDENGbPxRfiCY", "wJalrXUtnFEMIK7MDENGbPxRfiCY"),
            ("GITHUB_TOKEN: abcdef0123456789", "abcdef0123456789"),
            # JSON re-serialised inside a JSON string: the quotes arrive escaped.
            ('{\\"client_secret\\": \\"hunter2sekret\\"}', "hunter2sekret"),
        ):
            self.assertTrue(contains_secret(text), text)
            out = redact(text)
            self.assertNotIn(value, out, text)
            self.assertIn("[REDACTED:keyed-secret]", out, text)

    def test_a_key_name_inside_a_longer_word_is_not_a_keyed_secret(self):
        # The name must END the identifier: `tokens`, `password_file` and `key_id` are
        # counts, paths and identifiers, and this repository's evidence is full of them.
        for text in ("max_tokens=1000000", "password_file: /etc/app/pwfile",
                     "key_id: operator-key-01", "secrets_scanned=1234567"):
            self.assertEqual(redact(text), text)

    def test_keyed_scan_is_linear_on_a_long_identifier_run(self):
        # No prefix group: a megabyte of identifier characters with no key name in it
        # must not backtrack. A quadratic pattern does not finish this in a test run.
        import time
        blob = "a1B2_" * 200_000
        started = time.monotonic()
        self.assertEqual(redact(blob), blob)
        self.assertLess(time.monotonic() - started, 5.0)

    def test_does_not_redact_sha256_or_git_hashes(self):
        # Precision: ubiquitous, legitimate hashes must survive (no over-redaction).
        digest = "a1b2c3d4" * 8  # 64-hex
        head = "11d7697856a1720b2367074e7d9d515d080504aa"  # 40-hex
        text = f"tree_identity: {digest} commit {head}"
        self.assertEqual(redact(text), text)
        self.assertFalse(contains_secret(text))

    def test_redact_mapping_is_recursive(self):
        payload = {"error": "token=ghp_1234567890abcdefghij1234ABCD", "nested": ["ok", "AKIAIOSFODNN7EXAMPLE"]}
        red = redact_mapping(payload)
        self.assertIn("REDACTED", red["error"])
        self.assertIn("REDACTED", red["nested"][1])
        self.assertEqual(red["nested"][0], "ok")

    def test_clean_text_is_unchanged(self):
        text = "mutation requires recovery: RECOVERY_REQUIRED"
        self.assertEqual(redact(text), text)


class RecoveryWiringTests(unittest.TestCase):
    def test_recovery_redacts_persisted_error(self):
        # The recovery module must persist redacted error text, not raw secrets. Asked of the
        # journal it writes: `bro_recovery.redact` is only the name it imported, and calling that
        # says nothing about whether the one place an error is persisted goes through it.
        import bro_recovery
        from bro_contracts import canonical_json_sha256

        store = tempfile.TemporaryDirectory()
        self.addCleanup(store.cleanup)
        token = "abcdefghijklmnopqrstuvwxyz0123"
        before = {"head": "a" * 40, "tree": "b" * 64, "status_hash": "c" * 64}
        action = {"tool": "Write", "action": "write", "capabilities": ["WRITE_REPOSITORY"],
                  "targets": ["runtime/x.py"]}
        prepared = {
            "schema": 1, "record_id": "recovery-1", "task_id": "task-redact-1",
            "agent_id": "agt-p01-r01", "session_id": "session-1", "tool_use_id": "toolu_1",
            "phase": "PREPARED", "effect_class": "IRREVERSIBLE",
            "action_hash": canonical_json_sha256(action),
            "capabilities": action["capabilities"], "targets": action["targets"],
            "before_head": before["head"], "before_tree": before["tree"],
            "after_head": None, "after_tree": None,
            "before_status_hash": before["status_hash"], "after_status_hash": None,
            "recovery_proof_hash": None, "irreversible_effects": [], "state_version": 0,
            "previous_record_hash": None, "issued_at_epoch": 1000}
        with patch.dict(os.environ, {"BRO_RECOVERY_STORE": store.name}), \
                patch("bro_recovery.snapshot", return_value=before), \
                patch("bro_recovery._signed_record", return_value=prepared):
            bro_recovery.prepare_mutation(
                task={"task_id": "task-redact-1"}, agent_id="agt-p01-r01",
                session_id="session-1", tool_use_id="toolu_1",
                capabilities=("WRITE_REPOSITORY",), targets=("runtime/x.py",),
                tool="Write", action_name="write")
            bro_recovery.settle_mutation(
                "task-redact-1", "toolu_1", success=False,
                error=f"irreversible failed: bearer {token}")
            state = bro_recovery._load_state("task-redact-1")
            on_disk = "".join(
                path.read_text(encoding="utf-8", errors="replace")
                for path in pathlib.Path(store.name).rglob("*") if path.is_file())
        self.assertEqual(state["phase"], "FAILED_WITH_IRREVERSIBLE_EFFECT")
        self.assertEqual(len(state["irreversible_effects"]), 1)
        self.assertIn("REDACTED", state["irreversible_effects"][0])
        self.assertIn("irreversible failed", state["irreversible_effects"][0])
        self.assertNotIn(token, on_disk)


class RedactionCompletenessTests(unittest.TestCase):
    """Security remediation, blocker 5: redaction hid only the PEM header and
    missed modern token formats. No key byte and no whole token may survive."""

    def test_full_pem_leaves_no_key_bytes(self):
        pem = ("-----BEGIN OPENSSH PRIVATE KEY-----\n"
               "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gt\n"
               "ZWQyNTUxOQAAACD\n"
               "-----END OPENSSH PRIVATE KEY-----\n"
               "trailing log line here")
        out = redact(pem)
        self.assertNotIn("b3BlbnNz", out)                 # body gone
        self.assertNotIn("END OPENSSH", out)              # END marker gone
        self.assertIn("REDACTED", out)
        self.assertIn("trailing log line here", out)      # following text preserved

    def test_truncated_pem_body_is_redacted(self):
        out = redact("-----BEGIN RSA PRIVATE KEY-----\n"
                     "MIIEabcdEFGH1234567890abcdEFGH1234567890abcd\nmorebase64AAAABBBBCCCCDDDD1234")
        self.assertNotIn("MIIEabcd", out)

    def test_truncated_pem_short_body_and_tail_are_redacted(self):
        # a truncated key with short body lines and no END: everything from the
        # BEGIN header to end of input is key material and must be redacted
        out = redact("-----BEGIN PRIVATE KEY-----\nABCD1234\nEFGH5678\n")
        self.assertNotIn("ABCD1234", out)
        self.assertNotIn("EFGH5678", out)
        self.assertIn("REDACTED", out)

    def test_complete_pem_preserves_following_text(self):
        # a COMPLETE block must not consume text after END
        out = redact("-----BEGIN PRIVATE KEY-----\nABCD1234\n-----END PRIVATE KEY-----\nkeep me")
        self.assertNotIn("ABCD1234", out)
        self.assertIn("keep me", out)

    def test_modern_token_formats_are_redacted(self):
        for token in ("sk-proj-abcdEFGH1234567890ijklMNOP",
                      "github_pat_11ABCDEFG0abcdef1234567890ABCDEF"):
            out = redact(f"leaked {token} here")
            self.assertNotIn(token, out)
            self.assertIn("REDACTED", out)

    def test_no_over_redaction_of_ordinary_text(self):
        text = "normal log line, sha 3f2a1b9c, path /runtime/x.py, count=42"
        self.assertEqual(redact(text), text)


if __name__ == "__main__":
    unittest.main()
