import pathlib
import sys
import unittest

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
        # The recovery module must persist redacted error text, not raw secrets.
        import bro_recovery
        redacted = bro_recovery.redact("irreversible failed: bearer abcdefghijklmnopqrstuvwxyz0123")
        self.assertIn("REDACTED", redacted)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz0123", redacted)


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
